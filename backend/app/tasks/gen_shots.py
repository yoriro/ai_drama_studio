from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session_factory
from app.services.asset_files import resolve_data_path
from app.models import (
    Asset,
    Clip,
    ClipRefSlot,
    ClipShot,
    ClipVideo,
    Episode,
    Shot,
    ShotAsset,
)
from app.services.gen_shots import GeneratedShotsResponse, extract_shots
from app.services.vllm import VLLMClient
from app.tasks.queue import ClaimedTask, TaskChange, TaskQueue, WorkerContext


@dataclass(frozen=True, slots=True)
class _MediaMove:
    source: Path
    destination: Path


class _CanceledBeforeCommit(Exception):
    """The task cancellation won the final business commit race."""


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"gen_shots {field} must be a positive integer")
    return value


def _snapshot(task: ClaimedTask) -> dict[str, Any]:
    snapshot = task.payload.get("input_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("gen_shots input_snapshot must be an object")
    return snapshot


def _rows_snapshot(
    replacement: dict[str, Any], field: str
) -> list[dict[str, int]]:
    rows = replacement.get(field)
    if not isinstance(rows, list):
        raise ValueError(f"replacement_snapshot.{field} must be an array")
    parsed: list[dict[str, int]] = []
    previous_id = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "revision"}:
            raise ValueError(f"replacement_snapshot.{field} item is invalid")
        row_id = _positive_int(row["id"], f"replacement_snapshot.{field}.id")
        revision = _positive_int(
            row["revision"], f"replacement_snapshot.{field}.revision"
        )
        if row_id <= previous_id:
            raise ValueError(f"replacement_snapshot.{field} ids must be ascending")
        previous_id = row_id
        parsed.append({"id": row_id, "revision": revision})
    return parsed


def _replacement_media(
    replacement: dict[str, Any],
) -> tuple[list[dict[str, object]], list[int]]:
    media = replacement.get("clip_media")
    video_ids = replacement.get("clip_video_ids")
    if not isinstance(media, list) or not isinstance(video_ids, list):
        raise ValueError("replacement_snapshot media fields are invalid")
    parsed: list[dict[str, object]] = []
    video_media: list[dict[str, object]] = []
    override_media: list[dict[str, object]] = []
    seen: set[tuple[str, int]] = set()
    previous_kind: str | None = None
    previous_id = 0
    for item in media:
        if not isinstance(item, dict) or set(item) != {"kind", "id", "path"}:
            raise ValueError("replacement_snapshot.clip_media item is invalid")
        kind = item["kind"]
        if kind not in {"clip_video", "slot_override"}:
            raise ValueError("replacement_snapshot.clip_media kind is invalid")
        if kind == "clip_video" and previous_kind == "slot_override":
            raise ValueError("replacement_snapshot.clip_media order is invalid")
        item_id = _positive_int(item["id"], "replacement_snapshot.clip_media.id")
        path = item["path"]
        if not isinstance(path, str) or not path or Path(path).is_absolute():
            raise ValueError("replacement_snapshot.clip_media path is invalid")
        if any(part == ".." for part in Path(path).parts):
            raise ValueError("replacement_snapshot.clip_media path is invalid")
        key = (kind, item_id)
        if key in seen:
            raise ValueError("replacement_snapshot.clip_media contains duplicates")
        if kind != previous_kind:
            previous_id = 0
        if item_id <= previous_id:
            raise ValueError("replacement_snapshot.clip_media ids must be ascending")
        previous_id = item_id
        previous_kind = kind
        seen.add(key)
        copied = {"kind": kind, "id": item_id, "path": path}
        parsed.append(copied)
        if kind == "clip_video":
            video_media.append(copied)
        else:
            override_media.append(copied)
    parsed_video_ids = [int(item["id"]) for item in video_media]
    expected_video_ids = [_positive_int(item, "replacement_snapshot.clip_video_ids") for item in video_ids]
    if expected_video_ids != parsed_video_ids:
        raise ValueError(
            "replacement_snapshot.clip_video_ids must match clip_media videos"
        )
    if expected_video_ids != sorted(expected_video_ids):
        raise ValueError("replacement_snapshot.clip_video_ids must be ascending")
    return parsed, parsed_video_ids


async def _read_locked_replacement(
    session: AsyncSession,
    task: ClaimedTask,
) -> tuple[
    Episode,
    list[Shot],
    list[Clip],
    list[dict[str, object]],
    list[int],
]:
    snapshot = _snapshot(task)
    episode_id = _positive_int(snapshot.get("episode_id"), "episode_id")
    if episode_id != task.target_id:
        raise ValueError("gen_shots episode_id does not match task target")
    project_id = _positive_int(snapshot.get("project_id"), "project_id")
    replacement = snapshot.get("replacement_snapshot")
    if not isinstance(replacement, dict) or set(replacement) != {
        "shots",
        "clips",
        "clip_video_ids",
        "clip_media",
    }:
        raise ValueError("replacement_snapshot has invalid fields")
    expected_shots = _rows_snapshot(replacement, "shots")
    expected_clips = _rows_snapshot(replacement, "clips")
    clip_ids = {row["id"] for row in expected_clips}
    media, video_ids = _replacement_media(replacement)

    episode_result = await session.execute(
        select(Episode)
        .where(Episode.id == episode_id, Episode.project_id == project_id)
        .with_for_update()
    )
    episode = episode_result.scalar_one_or_none()
    if episode is None:
        raise ValueError("gen_shots target episode no longer belongs to project")

    shot_result = await session.execute(
        select(Shot)
        .where(Shot.episode_id == episode_id)
        .order_by(Shot.id)
        .with_for_update()
    )
    shots = list(shot_result.scalars().all())
    actual_shots = [{"id": shot.id, "revision": shot.revision} for shot in shots]
    if actual_shots != expected_shots:
        raise ValueError("gen_shots replacement snapshot shots changed")

    clip_result = await session.execute(
        select(Clip)
        .where(Clip.episode_id == episode_id)
        .order_by(Clip.id)
        .with_for_update()
    )
    clips = list(clip_result.scalars().all())
    actual_clips = [{"id": clip.id, "revision": clip.revision} for clip in clips]
    if actual_clips != expected_clips:
        raise ValueError("gen_shots replacement snapshot clips changed")
    actual_clip_ids = {clip.id for clip in clips}
    if actual_clip_ids != clip_ids:
        raise ValueError("gen_shots replacement snapshot clip ownership changed")
    if not clip_ids and media:
        raise ValueError("gen_shots replacement snapshot media has no clip owner")

    if clip_ids:
        video_result = await session.execute(
            select(ClipVideo)
            .where(ClipVideo.clip_id.in_(clip_ids))
            .order_by(ClipVideo.id)
            .with_for_update()
        )
        videos = list(video_result.scalars().all())
        expected_videos = {
            int(item["id"]): item["path"]
            for item in media
            if item["kind"] == "clip_video"
        }
        actual_videos = {video.id: (video.clip_id, video.file_path) for video in videos}
        if set(actual_videos) != set(expected_videos):
            raise ValueError("gen_shots replacement snapshot clip videos changed")
        for video_id, path in expected_videos.items():
            clip_id, current_path = actual_videos[video_id]
            if clip_id not in clip_ids or current_path != path:
                raise ValueError("gen_shots replacement snapshot clip video changed")

        override_result = await session.execute(
            select(ClipRefSlot)
            .where(
                ClipRefSlot.clip_id.in_(clip_ids),
                ClipRefSlot.override_image_path.is_not(None),
            )
            .order_by(ClipRefSlot.id)
            .with_for_update()
        )
        overrides = list(override_result.scalars().all())
        expected_overrides = {
            int(item["id"]): item["path"]
            for item in media
            if item["kind"] == "slot_override"
        }
        actual_overrides = {
            slot.id: (slot.clip_id, slot.override_image_path) for slot in overrides
        }
        if set(actual_overrides) != set(expected_overrides):
            raise ValueError("gen_shots replacement snapshot overrides changed")
        for slot_id, path in expected_overrides.items():
            clip_id, current_path = actual_overrides[slot_id]
            if clip_id not in clip_ids or current_path != path:
                raise ValueError("gen_shots replacement snapshot override changed")

    media_paths: list[dict[str, object]] = []
    trash_root = settings.DATA_DIR.resolve() / "trash"
    for item in media:
        path = str(item["path"])
        source = resolve_data_path(settings.DATA_DIR, path)
        destination = (trash_root / Path(path)).resolve()
        try:
            destination.relative_to(trash_root)
        except ValueError as exc:
            raise ValueError("gen_shots media path is outside trash") from exc
        media_paths.append(
            {"kind": item["kind"], "id": item["id"], "path": path, "source": source, "destination": destination}
        )
    return episode, shots, clips, media_paths, video_ids


async def _validate_final_assets(
    session: AsyncSession,
    task: ClaimedTask,
    result: GeneratedShotsResponse,
) -> None:
    snapshot = _snapshot(task)
    project_id = _positive_int(snapshot.get("project_id"), "project_id")
    referenced_ids = {asset_id for shot in result.shots for asset_id in shot.asset_ids}
    if not referenced_ids:
        return
    asset_result = await session.execute(
        select(Asset)
        .where(Asset.id.in_(referenced_ids))
        .with_for_update()
    )
    assets = list(asset_result.scalars().all())
    if len(assets) != len(referenced_ids) or any(
        asset.project_id != project_id or asset.type not in {"character", "scene"}
        for asset in assets
    ):
        raise ValueError("gen_shots output asset id is no longer valid for the project")


def _move_media(
    media_paths: list[dict[str, object]], moved: list[_MediaMove]
) -> None:
    for item in media_paths:
        source = item["source"]
        destination = item["destination"]
        if not isinstance(source, Path) or not isinstance(destination, Path):
            raise ValueError("gen_shots media paths are invalid")
        if not source.is_file():
            raise FileNotFoundError(str(source))
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)
        moved.append(_MediaMove(source=source, destination=destination))


def _restore_media(moved: list[_MediaMove]) -> None:
    for item in reversed(moved):
        if not item.destination.exists():
            raise FileNotFoundError(str(item.destination))
        item.source.parent.mkdir(parents=True, exist_ok=True)
        item.destination.replace(item.source)


async def _replace_episode(
    session: AsyncSession,
    queue: TaskQueue,
    task: ClaimedTask,
    result: GeneratedShotsResponse,
    moved: list[_MediaMove],
) -> TaskChange:
    episode, old_shots, old_clips, media_paths, video_ids = (
        await _read_locked_replacement(session, task)
    )
    await _validate_final_assets(session, task, result)
    _move_media(media_paths, moved)

    old_clip_ids = [clip.id for clip in old_clips]
    old_shot_ids = [shot.id for shot in old_shots]
    if old_clip_ids:
        await session.execute(delete(ClipShot).where(ClipShot.clip_id.in_(old_clip_ids)))
        await session.execute(delete(ClipRefSlot).where(ClipRefSlot.clip_id.in_(old_clip_ids)))
        await session.execute(delete(ClipVideo).where(ClipVideo.id.in_(video_ids)))
        await session.execute(delete(Clip).where(Clip.id.in_(old_clip_ids)))
    if old_shot_ids:
        await session.execute(delete(ShotAsset).where(ShotAsset.shot_id.in_(old_shot_ids)))
        await session.execute(delete(Shot).where(Shot.id.in_(old_shot_ids)))

    snapshot = _snapshot(task)
    script_revision = _positive_int(snapshot.get("script_revision"), "script_revision")
    for generated in result.shots:
        shot = Shot(
            episode_id=episode.id,
            order_index=generated.order,
            duration_est=generated.duration_est,
            shot_type=generated.shot_type,
            camera=generated.camera,
            description=generated.description,
            dialogue=generated.dialogue,
            status="normal",
            revision=1,
        )
        session.add(shot)
        await session.flush()
        for asset_id in generated.asset_ids:
            session.add(ShotAsset(shot_id=shot.id, asset_id=asset_id))
        await session.flush()
    episode.shots_generated_script_revision = script_revision
    completed = await queue.complete(session, task.id)
    if completed.changed:
        return completed
    current = completed.task
    if current is not None and (
        current.status == "canceled"
        or (current.status == "running" and current.cancel_requested_at is not None)
    ):
        raise _CanceledBeforeCommit
    raise RuntimeError(f"gen_shots task {task.id} did not transition to done")


async def gen_shots_handler(task: ClaimedTask, context: WorkerContext) -> None:
    result = await extract_shots(
        task,
        context,
        VLLMClient(str(settings.VLLM_BASE_URL)),
    )
    if result is None:
        return
    safe_point = await context.cancel_safe_point()
    if safe_point.task is not None and safe_point.task.status == "canceled":
        return

    moved: list[_MediaMove] = []
    committed = False
    canceled_before_commit = False
    try:
        async with async_session_factory() as session:
            async with session.begin():
                completed = await _replace_episode(
                    session,
                    context.queue,
                    task,
                    result,
                    moved,
                )
            committed = True
    except _CanceledBeforeCommit:
        canceled_before_commit = True
    finally:
        if not committed and moved:
            try:
                _restore_media(moved)
            except OSError as restore_error:
                raise RuntimeError(
                    "gen_shots database operation failed and trash restore failed: "
                    f"{restore_error}"
                ) from restore_error
    if canceled_before_commit:
        await context.cancel_safe_point()
        return
    await context.queue.publish_committed(completed)
