from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Asset, Clip, ClipVideo, Episode, Shot, Task
from app.services.asset_files import resolve_data_path, sha256_file
from app.services.video_files import (
    clip_video_paths,
    probe_clip_video_duration,
)
from app.tasks.gen_clip_video import GeneratedClipVideo
from app.tasks.queue import ClaimedTask, TaskChange, TaskQueue


_SEED_MAX = (1 << 63) - 1


class ClipVideoPersistenceError(RuntimeError):
    """The video commit and one or more file compensations need diagnosis."""


class _CanceledBeforeCommit(Exception):
    """The task cancellation won the final business commit race."""


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"gen_clip_video {field} must be a positive integer")
    return value


def _revision(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"gen_clip_video {field} must be a positive integer")
    return value


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"gen_clip_video {field} must be non-blank text")
    return value


def _read_source_entries(
    source_revisions: object,
) -> tuple[dict[str, int], dict[int, int], dict[int, int]]:
    if not isinstance(source_revisions, dict):
        raise ValueError("gen_clip_video source_revisions must be an object")

    clip_source = source_revisions.get("clip")
    if not isinstance(clip_source, dict):
        raise ValueError("gen_clip_video source_revisions.clip must be an object")
    clip_id = _positive_int(clip_source.get("id"), "source_revisions.clip.id")
    clip_revision = _revision(
        clip_source.get("revision"), "source_revisions.clip.revision"
    )

    def read_list(field: str) -> dict[int, int]:
        entries = source_revisions.get(field)
        if not isinstance(entries, list):
            raise ValueError(f"gen_clip_video source_revisions.{field} must be an array")
        result: dict[int, int] = {}
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"gen_clip_video source_revisions.{field}[{index}] must be an object"
                )
            entry_id = _positive_int(
                entry.get("id"), f"source_revisions.{field}[{index}].id"
            )
            entry_revision = _revision(
                entry.get("revision"),
                f"source_revisions.{field}[{index}].revision",
            )
            if entry_id in result:
                raise ValueError(
                    f"gen_clip_video source_revisions.{field} contains duplicate id"
                )
            result[entry_id] = entry_revision
        return result

    return (
        {"id": clip_id, "revision": clip_revision},
        read_list("shots"),
        read_list("assets"),
    )


def _read_snapshot(
    task: ClaimedTask,
) -> tuple[dict[str, Any], dict[str, int], dict[int, int], dict[int, int], int, int, str | None]:
    snapshot = task.payload.get("input_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("gen_clip_video input_snapshot must be an object")
    snapshot_clip = snapshot.get("clip")
    if not isinstance(snapshot_clip, dict):
        raise ValueError("gen_clip_video input_snapshot.clip must be an object")
    snapshot_clip_id = _positive_int(
        snapshot_clip.get("id"), "input_snapshot.clip.id"
    )
    episode_id = _positive_int(
        snapshot_clip.get("episode_id"), "input_snapshot.clip.episode_id"
    )
    snapshot_clip_revision = _revision(
        snapshot_clip.get("revision"), "input_snapshot.clip.revision"
    )
    source_clip, source_shots, source_assets = _read_source_entries(
        task.payload.get("source_revisions")
    )
    if snapshot_clip_id != task.target_id or source_clip["id"] != task.target_id:
        raise ValueError("gen_clip_video snapshot does not match task target")
    if snapshot_clip_revision != source_clip["revision"]:
        raise ValueError("gen_clip_video snapshot source revision does not match")

    requested_duration = _positive_int(
        snapshot.get("requested_duration"), "requested_duration"
    )
    seed = snapshot.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= _SEED_MAX:
        raise ValueError("gen_clip_video seed must be a 63-bit integer")
    cached_prompt = snapshot.get("cached_prompt")
    if cached_prompt is not None and not isinstance(cached_prompt, str):
        raise ValueError("gen_clip_video cached_prompt must be text or null")
    return (
        snapshot,
        source_clip,
        source_shots,
        source_assets,
        episode_id,
        seed,
        cached_prompt,
    )


def _read_input_hash(task: ClaimedTask) -> str:
    return _required_text(task.payload.get("input_hash"), "input_hash")


def _move_formal_to_trash(formal_path: Path, trash_path: Path) -> None:
    trash_path.parent.mkdir(parents=True, exist_ok=True)
    formal_path.replace(trash_path)


def _combine_cleanup_errors(
    primary_error: BaseException | None,
    cleanup_errors: list[tuple[str, OSError]],
) -> None:
    if not cleanup_errors:
        return
    details = "; ".join(
        f"{label}: {error}" for label, error in cleanup_errors
    )
    if primary_error is not None:
        raise ClipVideoPersistenceError(
            f"{primary_error}; {details}"
        ) from primary_error
    raise ClipVideoPersistenceError(details)


async def _locked_source_rows(
    session: AsyncSession,
    model: type[Shot] | type[Asset],
    identifiers: set[int],
) -> dict[int, Shot | Asset]:
    if not identifiers:
        return {}
    result = await session.execute(
        select(model)
        .where(model.id.in_(sorted(identifiers)))
        .order_by(model.id)
        .with_for_update()
    )
    return {int(row.id): row for row in result.scalars().all()}


async def commit_generated_clip_video(
    session: AsyncSession,
    queue: TaskQueue,
    task: ClaimedTask,
    generated: GeneratedClipVideo,
    *,
    data_dir: Path | None = None,
) -> TaskChange | None:
    """Atomically persist one generated MP4, its source projection, and done."""

    if task.type != "gen_clip_video":
        raise ValueError("commit target task must be gen_clip_video")
    if task.id <= 0 or task.target_id <= 0:
        raise ValueError("gen_clip_video task identifiers must be positive")
    built_prompt = _required_text(generated.built_prompt, "built_prompt")
    input_hash = _read_input_hash(task)

    root = (data_dir or settings.DATA_DIR).resolve()
    temp_path = resolve_data_path(root, generated.temp_path)
    formal_path: Path | None = None
    trash_path: Path | None = None
    formal_renamed = False
    transaction_committed = False
    completed: TaskChange | None = None

    try:
        actual_duration = probe_clip_video_duration(temp_path)
        digest = sha256_file(temp_path)

        async with session.begin():
            stored_task = await session.scalar(
                select(Task)
                .where(Task.id == task.id)
                .with_for_update()
            )
            if stored_task is None:
                raise ValueError("gen_clip_video task no longer exists")
            if (
                stored_task.type != task.type
                or stored_task.target_id != task.target_id
            ):
                raise ValueError("gen_clip_video stored task target changed")
            if stored_task.status == "canceled" or (
                stored_task.status == "running"
                and stored_task.cancel_requested_at is not None
            ):
                return None
            if stored_task.status != "running":
                raise ValueError(
                    f"gen_clip_video task is not running: {stored_task.status}"
                )

            (
                snapshot,
                source_clip,
                source_shots,
                source_assets,
                snapshot_episode_id,
                seed,
                cached_prompt,
            ) = _read_snapshot(task)
            source_clip_id = source_clip["id"]
            clip = await session.scalar(
                select(Clip)
                .where(Clip.id == task.target_id)
                .with_for_update()
            )
            if clip is None:
                raise ValueError("gen_clip_video clip no longer exists")
            if clip.id != source_clip_id or clip.episode_id != snapshot_episode_id:
                raise ValueError("gen_clip_video clip snapshot target changed")

            episode = await session.scalar(
                select(Episode).where(Episode.id == clip.episode_id)
            )
            if episode is None:
                raise ValueError("gen_clip_video episode no longer exists")

            shot_rows = await _locked_source_rows(
                session, Shot, set(source_shots)
            )
            asset_rows = await _locked_source_rows(
                session, Asset, set(source_assets)
            )
            current_result = await session.execute(
                select(ClipVideo)
                .where(ClipVideo.clip_id == clip.id)
                .order_by(ClipVideo.id)
                .with_for_update()
            )
            current_rows = list(current_result.scalars().all())
            source_matches = (
                clip.revision == source_clip["revision"]
                and set(shot_rows) == set(source_shots)
                and set(asset_rows) == set(source_assets)
            )
            if source_matches:
                source_matches = all(
                    shot.episode_id == clip.episode_id
                    and shot.revision == source_shots[shot_id]
                    for shot_id, shot in shot_rows.items()
                )
                source_matches = source_matches and all(
                    asset.project_id == episode.project_id
                    and asset.revision == source_assets[asset_id]
                    for asset_id, asset in asset_rows.items()
                )

            video = ClipVideo(
                clip_id=clip.id,
                file_path="pending",
                sha256=digest,
                seed=seed,
                requested_duration=snapshot["requested_duration"],
                actual_duration=actual_duration,
                is_current=not any(video.is_current for video in current_rows),
                built_prompt=built_prompt,
                input_hash=input_hash,
                input_snapshot=copy.deepcopy(snapshot),
            )
            session.add(video)
            await session.flush()

            (
                relative_path,
                formal_path,
                trash_path,
            ) = clip_video_paths(
                root,
                int(episode.project_id),
                int(episode.id),
                int(clip.id),
                int(video.id),
            )
            formal_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.replace(formal_path)
            formal_renamed = True
            video.file_path = relative_path.as_posix()

            if cached_prompt is None:
                clip.prompt_cache = built_prompt
                clip.prompt_input_hash = input_hash
                clip.updated_at = datetime.now(timezone.utc)
            if source_matches:
                if clip.freshness != "fresh":
                    clip.freshness = "fresh"
                    clip.updated_at = datetime.now(timezone.utc)
                for shot in shot_rows.values():
                    if shot.status != "normal":
                        shot.status = "normal"
                        shot.updated_at = datetime.now(timezone.utc)
            await session.flush()

            completed = await queue.complete(session, task.id)
            if not completed.changed:
                current_task = completed.task
                if current_task is not None and (
                    current_task.status == "canceled"
                    or (
                        current_task.status == "running"
                        and current_task.cancel_requested_at is not None
                    )
                ):
                    raise _CanceledBeforeCommit
                raise RuntimeError(
                    f"gen_clip_video task {task.id} did not transition to done"
                )
        transaction_committed = True
        return completed
    except _CanceledBeforeCommit:
        return None
    finally:
        primary_error = sys.exc_info()[1]
        cleanup_errors: list[tuple[str, OSError]] = []
        if not transaction_committed and formal_renamed:
            if formal_path is None or trash_path is None:
                raise RuntimeError("generated clip video storage state is incomplete")
            try:
                _move_formal_to_trash(formal_path, trash_path)
            except OSError as exc:
                cleanup_errors.append(("trash compensation failed", exc))
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError as exc:
                cleanup_errors.append(("temporary file cleanup failed", exc))
        _combine_cleanup_errors(primary_error, cleanup_errors)
