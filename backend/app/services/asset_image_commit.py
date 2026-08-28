from __future__ import annotations

import copy
import sys
from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Asset, AssetImage, Task
from app.services.asset_files import (
    asset_image_path,
    asset_image_relative_path,
    move_asset_image_to_trash,
    resolve_data_path,
    sha256_file,
    temporary_asset_image_path,
)
from app.services.assets import _mark_asset_dependents_changed
from app.tasks.queue import ClaimedTask, TaskChange, TaskQueue


@dataclass(frozen=True, slots=True)
class GeneratedPng:
    """A validated PNG waiting for the final database transaction."""

    temp_path: Path
    sha256: str


class AssetImagePersistenceError(RuntimeError):
    """The generated image operation and its file cleanup cannot be diagnosed separately."""


class _CanceledBeforeCommit(Exception):
    """The task cancellation won the final business commit race."""


def _validate_png(path: Path) -> None:
    try:
        with Image.open(path) as image:
            image_format = image.format
            image.verify()
        with Image.open(path) as image:
            image.load()
    except (OSError, SyntaxError, ValueError) as exc:
        raise ValueError("generated file is not a complete PNG") from exc
    if image_format != "PNG":
        raise ValueError("generated file is not a PNG")


async def write_generated_png(
    chunks: AsyncIterable[bytes], *, data_dir: Path | None = None
) -> GeneratedPng:
    """Stream one Comfy output into DATA_DIR/tmp and validate its raw PNG bytes."""

    root = (data_dir or settings.DATA_DIR).resolve()
    temp_path = temporary_asset_image_path(root)
    keep_temp = False
    try:
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = 0
        with temp_path.open("wb") as file_handle:
            async for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise TypeError("generated image stream must yield bytes")
                bytes_written += len(chunk)
                file_handle.write(chunk)
        if bytes_written == 0:
            raise ValueError("generated image is empty")
        _validate_png(temp_path)
        digest = sha256_file(temp_path)
        keep_temp = True
        return GeneratedPng(temp_path=temp_path, sha256=digest)
    finally:
        if not keep_temp and temp_path.exists():
            temp_path.unlink()


def cleanup_generated_png(
    generated: GeneratedPng, *, data_dir: Path | None = None
) -> None:
    """Remove a generated PNG temp file after the caller abandons it."""

    root = (data_dir or settings.DATA_DIR).resolve()
    temp_path = resolve_data_path(root, generated.temp_path)
    temp_path.unlink(missing_ok=True)


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"gen_asset_image {field} must be a positive integer")
    return value


def _revision(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"gen_asset_image {field} must be a positive integer")
    return value


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"gen_asset_image {field} must be non-blank text")
    return value


def _read_snapshot(task: ClaimedTask) -> tuple[dict[str, Any], int, int, int]:
    snapshot = task.payload.get("input_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("gen_asset_image input_snapshot must be an object")
    asset_snapshot = snapshot.get("asset")
    if not isinstance(asset_snapshot, dict):
        raise ValueError("gen_asset_image input_snapshot.asset must be an object")
    snapshot_asset_id = _positive_int(
        asset_snapshot.get("id"), "input_snapshot.asset.id"
    )
    project_id = _positive_int(
        asset_snapshot.get("project_id"), "input_snapshot.asset.project_id"
    )
    snapshot_revision = _revision(
        asset_snapshot.get("revision"), "input_snapshot.asset.revision"
    )
    source_revisions = task.payload.get("source_revisions")
    if not isinstance(source_revisions, dict):
        raise ValueError("gen_asset_image source_revisions must be an object")
    asset_source = source_revisions.get("asset")
    if not isinstance(asset_source, dict):
        raise ValueError("gen_asset_image source_revisions.asset must be an object")
    source_asset_id = _positive_int(
        asset_source.get("id"), "source_revisions.asset.id"
    )
    source_revision = _revision(
        asset_source.get("revision"), "source_revisions.asset.revision"
    )
    if (
        snapshot_asset_id != task.target_id
        or source_asset_id != task.target_id
        or snapshot_revision != source_revision
    ):
        raise ValueError("gen_asset_image asset snapshot does not match task target")
    return snapshot, snapshot_asset_id, project_id, source_revision


def _read_user_note(snapshot: dict[str, Any]) -> str | None:
    if "user_note" not in snapshot:
        raise ValueError("gen_asset_image input_snapshot.user_note is missing")
    user_note = snapshot["user_note"]
    if user_note is not None and not isinstance(user_note, str):
        raise ValueError("gen_asset_image input_snapshot.user_note is invalid")
    return user_note


def _read_seed(snapshot: dict[str, Any]) -> int:
    seed = snapshot.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**63:
        raise ValueError("gen_asset_image seed must be a 63-bit integer")
    return seed


def _read_input_hash(payload: dict[str, Any]) -> str:
    input_hash = payload.get("input_hash")
    if not isinstance(input_hash, str) or not input_hash:
        raise ValueError("gen_asset_image input_hash must be non-blank text")
    return input_hash


def _read_cached_prompt(snapshot: dict[str, Any]) -> str | None:
    cached_prompt = snapshot.get("cached_prompt")
    if cached_prompt is not None and not isinstance(cached_prompt, str):
        raise ValueError("gen_asset_image cached_prompt must be text or null")
    return cached_prompt


def _read_user_note_and_prompt(
    snapshot: dict[str, Any], built_prompt: str
) -> str | None:
    _read_cached_prompt(snapshot)
    _required_text(built_prompt, "built_prompt")
    return _read_user_note(snapshot)


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
        raise AssetImagePersistenceError(
            f"{primary_error}; {details}"
        ) from primary_error
    raise AssetImagePersistenceError(details)


async def commit_generated_asset_image(
    session: AsyncSession,
    queue: TaskQueue,
    task: ClaimedTask,
    generated: GeneratedPng,
    *,
    built_prompt: str,
    data_dir: Path | None = None,
) -> TaskChange | None:
    """Rename one validated PNG and commit its image/task state atomically."""

    if task.type != "gen_asset_image":
        raise ValueError("commit target task must be gen_asset_image")
    if task.target_id <= 0:
        raise ValueError("gen_asset_image task target must be positive")

    root = (data_dir or settings.DATA_DIR).resolve()
    temp_path = resolve_data_path(root, generated.temp_path)
    formal_path: Path | None = None
    formal_renamed = False
    transaction_committed = False
    completed: TaskChange | None = None
    formal_project_id: int | None = None
    formal_asset_id: int | None = None
    formal_image_id: int | None = None

    try:
        _validate_png(temp_path)
        digest = sha256_file(temp_path)
        async with session.begin():
            stored_result = await session.execute(
                select(Task)
                .where(Task.id == task.id)
                .with_for_update()
            )
            stored_task = stored_result.scalar_one_or_none()
            if stored_task is None:
                raise ValueError("gen_asset_image task no longer exists")
            if (
                stored_task.type != task.type
                or stored_task.target_id != task.target_id
            ):
                raise ValueError("gen_asset_image stored task target changed")
            if stored_task.status == "canceled" or (
                stored_task.status == "running"
                and stored_task.cancel_requested_at is not None
            ):
                return None
            if stored_task.status != "running":
                raise ValueError(
                    f"gen_asset_image task is not running: {stored_task.status}"
                )

            snapshot, asset_id, project_id, source_revision = _read_snapshot(task)
            user_note = _read_user_note_and_prompt(snapshot, built_prompt)
            seed = _read_seed(snapshot)
            input_hash = _read_input_hash(task.payload)
            cached_prompt = _read_cached_prompt(snapshot)

            asset_result = await session.execute(
                select(Asset)
                .where(
                    Asset.id == asset_id,
                    Asset.project_id == project_id,
                    Asset.type.in_(("character", "scene")),
                )
                .with_for_update()
            )
            asset = asset_result.scalar_one_or_none()
            if asset is None:
                raise ValueError("gen_asset_image target asset no longer exists")

            current_result = await session.execute(
                select(AssetImage)
                .where(
                    AssetImage.asset_id == asset.id,
                    AssetImage.is_current.is_(True),
                )
                .order_by(AssetImage.id)
                .with_for_update()
            )
            current_image = current_result.scalar_one_or_none()
            is_current = asset.revision == source_revision and current_image is None

            image = AssetImage(
                asset_id=asset.id,
                file_path="pending",
                sha256=digest,
                seed=seed,
                source="generated",
                is_current=is_current,
                built_prompt=built_prompt,
                input_hash=input_hash,
                input_snapshot=copy.deepcopy(snapshot),
                user_note=user_note,
            )
            session.add(image)
            await session.flush()

            relative_path = asset_image_relative_path(
                asset.project_id, asset.id, image.id, "png"
            )
            formal_path = asset_image_path(
                root, asset.project_id, asset.id, image.id, "png"
            )
            formal_project_id = asset.project_id
            formal_asset_id = asset.id
            formal_image_id = image.id
            formal_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.replace(formal_path)
            formal_renamed = True
            image.file_path = relative_path.as_posix()

            if cached_prompt is None:
                asset.image_prompt_cache = built_prompt
                asset.image_prompt_hash = input_hash
                asset.updated_at = datetime.now(timezone.utc)
            if is_current:
                asset.revision += 1
                asset.updated_at = datetime.now(timezone.utc)
                await _mark_asset_dependents_changed(session, asset.id)
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
                    f"gen_asset_image task {task.id} did not transition to done"
                )
        transaction_committed = True
        return completed
    except _CanceledBeforeCommit:
        return None
    finally:
        primary_error = sys.exc_info()[1]
        cleanup_errors: list[tuple[str, OSError]] = []
        if (
            not transaction_committed
            and formal_renamed
        ):
            if (
                formal_project_id is None
                or formal_asset_id is None
                or formal_image_id is None
            ):
                raise RuntimeError("generated asset image storage state is incomplete")
            try:
                move_asset_image_to_trash(
                    root,
                    formal_project_id,
                    formal_asset_id,
                    formal_image_id,
                    "png",
                )
            except OSError as exc:
                cleanup_errors.append(("trash compensation failed", exc))
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError as exc:
                cleanup_errors.append(("temporary file cleanup failed", exc))
        _combine_cleanup_errors(primary_error, cleanup_errors)
