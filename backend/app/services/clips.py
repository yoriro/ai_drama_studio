from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import fsum, isfinite
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.core.config import settings
from app.models import (
    Asset,
    AssetImage,
    Clip,
    ClipRefSlot,
    ClipShot,
    ClipVideo,
    Episode,
    Shot,
    ShotAsset,
)
from app.services.asset_files import (
    resolve_data_path,
    sha256_file,
    slot_override_relative_path,
    temporary_slot_override_path,
)
from app.services.assets import _validate_decoded_image
from app.schemas.clips import (
    ClipCreateRequest,
    ClipPatchRequest,
    ClipPreviewRequest,
    ClipSlotEnabledPatch,
)
from app.services.clip_rules import (
    ClipRuleAsset,
    ClipRuleDataError,
    ClipRuleShot,
    ClipRuleMessage,
    ClipRuleResult,
    evaluate_clip_selection,
    slot_warnings,
)
from app.services.video_files import (
    clip_video_paths,
    validated_clip_media_move,
)


_VISIBLE_ASSET_TYPES = ("character", "scene")
_POSTGRES_INTEGER_MAX = 2_147_483_647
_SLOT_OVERRIDE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}


def _episode_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Episode not found")


def _selection_validation_error(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _source_data_error() -> HTTPException:
    return HTTPException(status_code=500, detail="Clip source data is inconsistent")


def _slot_override_upload_error(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


async def _prepare_slot_override_upload(
    upload: UploadFile,
) -> tuple[Path, str, str]:
    declared_mime = upload.content_type
    if declared_mime not in _SLOT_OVERRIDE_MIME_TYPES:
        raise _slot_override_upload_error(
            "MIME type must be image/png, image/jpeg, or image/webp"
        )

    temp_path = temporary_slot_override_path(settings.DATA_DIR)
    keep_temp = False
    try:
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = 0
        with temp_path.open("wb") as file_handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > settings.UPLOAD_MAX_MB * 1024 * 1024:
                    raise _slot_override_upload_error(
                        "file exceeds UPLOAD_MAX_MB "
                        f"({settings.UPLOAD_MAX_MB})"
                    )
                file_handle.write(chunk)

        if bytes_written == 0:
            raise _slot_override_upload_error("file must not be empty")
        extension, _ = _validate_decoded_image(temp_path, declared_mime)
        digest = sha256_file(temp_path)
        keep_temp = True
        return temp_path, extension, digest
    finally:
        if not keep_temp and temp_path.exists():
            temp_path.unlink()


def _slot_override_paths(
    episode: Episode,
    clip: Clip,
    slot: ClipRefSlot,
    extension: str,
) -> tuple[Path, Path, Path]:
    relative_path = slot_override_relative_path(
        int(episode.project_id),
        int(episode.id),
        int(clip.id),
        int(slot.id),
        extension,
    )
    formal_path = resolve_data_path(settings.DATA_DIR, relative_path)
    trash_path = resolve_data_path(
        settings.DATA_DIR, Path("trash") / relative_path
    )
    return relative_path, formal_path, trash_path


def _existing_slot_override(
    episode: Episode,
    clip: Clip,
    slot: ClipRefSlot,
) -> tuple[Path, Path, Path, str] | None:
    if slot.override_image_path is None:
        if slot.override_sha256 is not None:
            raise _source_data_error()
        return None
    if not slot.override_sha256:
        raise _source_data_error()

    relative_path = Path(slot.override_image_path)
    extension = relative_path.suffix.removeprefix(".").lower()
    try:
        expected_relative_path, formal_path, trash_path = _slot_override_paths(
            episode, clip, slot, extension
        )
    except ValueError as exc:
        raise _source_data_error() from exc
    if relative_path.as_posix() != expected_relative_path.as_posix():
        raise _source_data_error()
    if not formal_path.is_file():
        raise _source_data_error()
    try:
        stored_digest = sha256_file(formal_path)
    except OSError as exc:
        raise _source_data_error() from exc
    if stored_digest != str(slot.override_sha256):
        raise _source_data_error()
    return relative_path, formal_path, trash_path, extension


def _move_slot_override(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.replace(destination)


def _raise_slot_cleanup_errors(
    primary_error: BaseException | None,
    cleanup_errors: list[tuple[str, OSError]],
) -> None:
    if not cleanup_errors:
        return
    details = "; ".join(
        f"{label}: {error}" for label, error in cleanup_errors
    )
    if primary_error is not None:
        raise RuntimeError(
            f"slot override mutation failed: {primary_error}; {details}"
        ) from primary_error
    raise RuntimeError(f"slot override mutation cleanup failed: {details}")


def _raise_clip_cleanup_errors(
    primary_error: BaseException | None,
    cleanup_errors: list[tuple[str, OSError]],
) -> None:
    if not cleanup_errors:
        return
    details = "; ".join(
        f"{label}: {error}" for label, error in cleanup_errors
    )
    if primary_error is not None:
        raise RuntimeError(
            f"clip deletion failed: {primary_error}; {details}"
        ) from primary_error
    raise RuntimeError(f"clip deletion cleanup failed: {details}")


async def _load_selection(
    session: AsyncSession,
    episode_id: int,
    shot_ids: list[int],
    *,
    lock: bool,
) -> tuple[Episode, tuple[ClipRuleShot, ...], set[int]]:
    episode_statement = select(Episode).where(Episode.id == episode_id)
    if lock:
        episode_statement = episode_statement.with_for_update()
    episode_result = await session.execute(episode_statement)
    episode = episode_result.scalar_one_or_none()
    if episode is None:
        raise _episode_not_found()

    if any(shot_id > _POSTGRES_INTEGER_MAX for shot_id in shot_ids):
        raise _selection_validation_error(
            "shot_ids must reference shots in the episode"
        )

    shot_statement = (
        select(Shot)
        .where(
            Shot.episode_id == episode_id,
            Shot.id.in_(shot_ids),
        )
        .order_by(Shot.order_index, Shot.id)
    )
    if lock:
        shot_statement = shot_statement.with_for_update()
    shot_result = await session.execute(shot_statement)
    shots = list(shot_result.scalars().all())
    if len(shots) != len(shot_ids):
        raise _selection_validation_error(
            "shot_ids must reference existing shots in the episode"
        )

    assets_by_shot: dict[int, list[ClipRuleAsset]] = defaultdict(list)
    asset_statement = (
        select(ShotAsset.shot_id, Asset.id, Asset.project_id, Asset.type, Asset.name)
        .join(Asset, Asset.id == ShotAsset.asset_id)
        .where(
            ShotAsset.shot_id.in_(shot_ids),
        )
        .order_by(ShotAsset.shot_id, Asset.id)
    )
    if lock:
        asset_statement = asset_statement.with_for_update()
    asset_result = await session.execute(asset_statement)
    for shot_id, asset_id, project_id, asset_type, asset_name in asset_result.all():
        if int(project_id) != int(episode.project_id):
            raise _source_data_error()
        if asset_type not in _VISIBLE_ASSET_TYPES:
            continue
        assets_by_shot[int(shot_id)].append(
            ClipRuleAsset(
                id=int(asset_id),
                type=asset_type,
                name=str(asset_name),
            )
        )

    occupied_statement = select(ClipShot).where(ClipShot.shot_id.in_(shot_ids)).order_by(
        ClipShot.shot_id, ClipShot.clip_id
    )
    if lock:
        occupied_statement = occupied_statement.with_for_update()
    occupied_result = await session.execute(occupied_statement)
    occupied_shot_ids = {
        int(row.shot_id) for row in occupied_result.scalars().all()
    }
    rule_shots = tuple(
        ClipRuleShot(
            id=int(shot.id),
            order_index=int(shot.order_index),
            duration_est=shot.duration_est,
            assets=tuple(assets_by_shot.get(shot.id, ())),
        )
        for shot in shots
    )
    return episode, rule_shots, occupied_shot_ids


def _evaluate_selection(
    rule_shots: tuple[ClipRuleShot, ...], occupied_shot_ids: set[int]
) -> ClipRuleResult:
    try:
        result = evaluate_clip_selection(
            rule_shots,
            occupied_shot_ids=occupied_shot_ids,
            clip_min_seconds=settings.CLIP_MIN_SECONDS,
            clip_max_seconds=settings.CLIP_MAX_SECONDS,
            slot_soft_limit=settings.SLOT_SOFT_LIMIT,
            slot_hard_limit=settings.SLOT_HARD_LIMIT,
        )
    except ClipRuleDataError as exc:
        raise _source_data_error() from exc
    return result


def _preview_response(episode_id: int, result: ClipRuleResult) -> dict[str, Any]:
    return {
        "episode_id": episode_id,
        "shot_ids": [shot.id for shot in result.shots],
        "duration_est_total": result.duration_est_total,
        "suggested_requested_duration": result.suggested_requested_duration,
        "reference_candidates": [
            {
                "asset_id": candidate.asset_id,
                "asset_type": candidate.asset_type,
                "asset_name": candidate.asset_name,
                "first_shot_id": candidate.first_shot_id,
                "first_order_index": candidate.first_order_index,
                "selected_by_default": candidate.selected_by_default,
            }
            for candidate in result.reference_candidates
        ],
        "default_reference_asset_ids": list(result.default_reference_asset_ids),
        "violations": [
            {"code": item.code, "message": item.message}
            for item in result.violations
        ],
        "warnings": [
            {"code": item.code, "message": item.message}
            for item in result.warnings
        ],
    }


async def preview_clip(
    session: AsyncSession, episode_id: int, payload: ClipPreviewRequest
) -> dict[str, Any]:
    episode, rule_shots, occupied_shot_ids = await _load_selection(
        session, episode_id, payload.shot_ids, lock=False
    )
    result = _evaluate_selection(rule_shots, occupied_shot_ids)
    return _preview_response(episode.id, result)


def _create_validation_error(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _violation_message(result: ClipRuleResult) -> str:
    return "; ".join(item.message for item in result.violations)


async def create_clip(
    session: AsyncSession, episode_id: int, payload: ClipCreateRequest
) -> dict[str, Any]:
    try:
        async with session.begin():
            episode, rule_shots, occupied_shot_ids = await _load_selection(
                session, episode_id, payload.shot_ids, lock=True
            )
            result = _evaluate_selection(rule_shots, occupied_shot_ids)
            if result.violations:
                raise _create_validation_error(_violation_message(result))

            if len(payload.reference_asset_ids) > settings.SLOT_HARD_LIMIT:
                raise _create_validation_error(
                    "reference_asset_ids must contain no more than "
                    f"{settings.SLOT_HARD_LIMIT} assets"
                )
            candidate_by_id = {
                candidate.asset_id: candidate
                for candidate in result.reference_candidates
            }
            requested_asset_ids = set(payload.reference_asset_ids)
            if not requested_asset_ids.issubset(candidate_by_id):
                raise _create_validation_error(
                    "reference_asset_ids must reference candidate assets"
                )

            if payload.requested_duration is None:
                requested_duration = result.suggested_requested_duration
            else:
                requested_duration = payload.requested_duration
                if not (
                    settings.CLIP_MIN_SECONDS
                    <= requested_duration
                    <= settings.CLIP_MAX_SECONDS
                ):
                    raise _create_validation_error(
                        "requested_duration must be within the configured clip range"
                    )

            ordered_candidates = [
                candidate
                for candidate in result.reference_candidates
                if candidate.asset_id in requested_asset_ids
            ]
            clip = Clip(
                episode_id=episode.id,
                generation_mode="ref2v",
                user_note=payload.user_note,
                requested_duration=requested_duration,
                prompt_cache=None,
                prompt_input_hash=None,
                generation_state="empty",
                freshness="fresh",
                revision=1,
            )
            session.add(clip)
            await session.flush()

            for position, shot in enumerate(result.shots, start=1):
                session.add(
                    ClipShot(
                        clip_id=clip.id,
                        shot_id=shot.id,
                        position=position,
                    )
                )
            for slot_no, candidate in enumerate(ordered_candidates, start=1):
                session.add(
                    ClipRefSlot(
                        clip_id=clip.id,
                        slot_no=slot_no,
                        asset_id=candidate.asset_id,
                        asset_name_snapshot=candidate.asset_name,
                        asset_type_snapshot=candidate.asset_type,
                        enabled=True,
                        override_image_path=None,
                        override_sha256=None,
                    )
                )
            await session.flush()
            return await _clip_response(session, clip)
    except IntegrityError as exc:
        constraint_name = getattr(exc.orig, "constraint_name", None)
        if constraint_name == "uq_clip_shots_shot":
            raise _create_validation_error(
                "Selected shots already belong to a clip."
            ) from exc
        raise


async def _clip_shots(
    session: AsyncSession, clip: Clip
) -> list[tuple[ClipShot, Shot]]:
    result = await session.execute(
        select(ClipShot, Shot)
        .join(Shot, Shot.id == ClipShot.shot_id)
        .where(ClipShot.clip_id == clip.id)
        .order_by(ClipShot.position, ClipShot.shot_id)
    )
    rows = list(result.all())
    if not rows:
        raise _source_data_error()
    positions = [int(clip_shot.position) for clip_shot, _ in rows]
    if positions != list(range(1, len(rows) + 1)):
        raise _source_data_error()
    if any(shot.episode_id != clip.episode_id for _, shot in rows):
        raise _source_data_error()
    return rows


def _clip_warning_values(
    shots: list[tuple[ClipShot, Shot]], enabled_slot_count: int
) -> tuple[ClipRuleMessage, ...]:
    durations: list[float] = []
    for _, shot in shots:
        duration = shot.duration_est
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise _source_data_error()
        duration_value = float(duration)
        if not isfinite(duration_value) or not 1 <= duration_value <= 5:
            raise _source_data_error()
        durations.append(duration_value)
    warnings: list[ClipRuleMessage] = []
    if fsum(durations) < settings.CLIP_MIN_SECONDS:
        warnings.append(
            ClipRuleMessage(
                code="duration_below_min",
                message=(
                    "Estimated duration is below the minimum of "
                    f"{settings.CLIP_MIN_SECONDS} seconds."
                ),
            )
        )
    warnings.extend(
        slot_warnings(
            enabled_slot_count=enabled_slot_count,
            slot_soft_limit=settings.SLOT_SOFT_LIMIT,
        )
    )
    return tuple(warnings)


async def _clip_response(session: AsyncSession, clip: Clip) -> dict[str, Any]:
    shot_rows = await _clip_shots(session, clip)
    slot_count_result = await session.execute(
        select(ClipRefSlot.id)
        .where(
            ClipRefSlot.clip_id == clip.id,
            ClipRefSlot.enabled.is_(True),
        )
    )
    enabled_slot_count = len(slot_count_result.scalars().all())
    warnings = _clip_warning_values(shot_rows, enabled_slot_count)
    return {
        "id": clip.id,
        "episode_id": clip.episode_id,
        "generation_mode": clip.generation_mode,
        "user_note": clip.user_note,
        "requested_duration": clip.requested_duration,
        "generation_state": clip.generation_state,
        "freshness": clip.freshness,
        "revision": clip.revision,
        "shot_ids": [shot.id for _, shot in shot_rows],
        "start_order_index": shot_rows[0][1].order_index,
        "end_order_index": shot_rows[-1][1].order_index,
        "enabled_slot_count": enabled_slot_count,
        "warnings": [
            {"code": item.code, "message": item.message}
            for item in warnings
        ],
        "created_at": clip.created_at,
        "updated_at": clip.updated_at,
    }


async def list_clips(
    session: AsyncSession, episode_id: int
) -> list[dict[str, Any]]:
    if await session.get(Episode, episode_id) is None:
        raise _episode_not_found()
    result = await session.execute(
        select(Clip).where(Clip.episode_id == episode_id).order_by(Clip.id)
    )
    responses = [
        await _clip_response(session, clip) for clip in result.scalars().all()
    ]
    return sorted(
        responses,
        key=lambda response: (response["start_order_index"], response["id"]),
    )


async def get_clip(session: AsyncSession, clip_id: int) -> dict[str, Any]:
    clip = await session.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    return await _clip_response(session, clip)


async def update_clip(
    session: AsyncSession, clip_id: int, payload: ClipPatchRequest
) -> dict[str, Any]:
    async with session.begin():
        result = await session.execute(
            select(Clip).where(Clip.id == clip_id).with_for_update()
        )
        clip = result.scalar_one_or_none()
        if clip is None:
            raise HTTPException(status_code=404, detail="Clip not found")

        changed = False
        if "user_note" in payload.model_fields_set:
            if payload.user_note != clip.user_note:
                clip.user_note = payload.user_note
                changed = True
        if "requested_duration" in payload.model_fields_set:
            requested_duration = payload.requested_duration
            if requested_duration is None:
                raise _create_validation_error(
                    "requested_duration must not be null"
                )
            if not (
                settings.CLIP_MIN_SECONDS
                <= requested_duration
                <= settings.CLIP_MAX_SECONDS
            ):
                raise _create_validation_error(
                    "requested_duration must be within the configured clip range"
                )
            if requested_duration != clip.requested_duration:
                clip.requested_duration = requested_duration
                changed = True

        if changed:
            clip.revision += 1
            clip.freshness = "stale"
            clip.updated_at = datetime.now(timezone.utc)
        await session.flush()
        return await _clip_response(session, clip)


async def list_clip_slots(
    session: AsyncSession, clip_id: int
) -> dict[str, Any]:
    clip = await session.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    episode = await session.get(Episode, clip.episode_id)
    if episode is None:
        raise _source_data_error()

    slot_result = await session.execute(
        select(ClipRefSlot)
        .where(ClipRefSlot.clip_id == clip_id)
        .order_by(ClipRefSlot.slot_no, ClipRefSlot.id)
    )
    slots = list(slot_result.scalars().all())
    if any(slot.slot_no < 1 or slot.slot_no > 9 for slot in slots):
        raise _source_data_error()
    if len({slot.slot_no for slot in slots}) != len(slots):
        raise _source_data_error()

    asset_ids = sorted(
        {int(slot.asset_id) for slot in slots if slot.asset_id is not None}
    )
    assets: dict[int, Asset] = {}
    current_images: dict[int, list[AssetImage]] = defaultdict(list)
    if asset_ids:
        asset_result = await session.execute(
            select(Asset).where(Asset.id.in_(asset_ids)).order_by(Asset.id)
        )
        assets = {int(asset.id): asset for asset in asset_result.scalars().all()}
        if set(assets) != set(asset_ids):
            raise _source_data_error()
        image_result = await session.execute(
            select(AssetImage)
            .where(
                AssetImage.asset_id.in_(asset_ids),
                AssetImage.is_current.is_(True),
            )
            .order_by(AssetImage.asset_id, AssetImage.id)
        )
        for image in image_result.scalars().all():
            current_images[int(image.asset_id)].append(image)

    items: list[dict[str, Any]] = []
    for slot in slots:
        image_source: str | None = None
        image_url: str | None = None
        if slot.override_image_path is not None:
            if not slot.override_image_path:
                raise _source_data_error()
            image_source = "override"
            image_url = f"/media/slot-overrides/{slot.id}"
        elif slot.asset_id is not None:
            asset = assets[int(slot.asset_id)]
            if asset.project_id != episode.project_id:
                raise _source_data_error()
            if asset.type != slot.asset_type_snapshot:
                raise _source_data_error()
            images = current_images.get(int(slot.asset_id), [])
            if len(images) > 1:
                raise _source_data_error()
            if images:
                image_source = "asset_current"
                image_url = f"/media/asset-images/{images[0].id}"
        items.append(
            {
                "id": slot.id,
                "clip_id": slot.clip_id,
                "slot_no": slot.slot_no,
                "asset_id": slot.asset_id,
                "asset_name_snapshot": slot.asset_name_snapshot,
                "asset_type_snapshot": slot.asset_type_snapshot,
                "asset_deleted": slot.asset_id is None,
                "enabled": slot.enabled,
                "image_source": image_source,
                "image_url": image_url,
            }
        )

    warnings = slot_warnings(
        enabled_slot_count=sum(1 for slot in slots if slot.enabled),
        slot_soft_limit=settings.SLOT_SOFT_LIMIT,
    )
    return {
        "clip_id": clip_id,
        "items": items,
        "warnings": [
            {"code": item.code, "message": item.message}
            for item in warnings
        ],
    }


async def update_clip_slot_enabled(
    session: AsyncSession,
    clip_id: int,
    slot_no: int,
    payload: ClipSlotEnabledPatch,
) -> dict[str, Any]:
    async with session.begin():
        clip_result = await session.execute(
            select(Clip).where(Clip.id == clip_id).with_for_update()
        )
        clip = clip_result.scalar_one_or_none()
        if clip is None:
            raise HTTPException(status_code=404, detail="Clip not found")

        slot_result = await session.execute(
            select(ClipRefSlot)
            .where(
                ClipRefSlot.clip_id == clip_id,
                ClipRefSlot.slot_no == slot_no,
            )
            .with_for_update()
        )
        slot = slot_result.scalar_one_or_none()
        if slot is None:
            raise HTTPException(status_code=404, detail="Clip slot not found")

        if slot.enabled != payload.enabled:
            slot.enabled = payload.enabled
            clip.revision += 1
            clip.freshness = "stale"
            clip.updated_at = datetime.now(timezone.utc)

        await session.flush()
        slots = await list_clip_slots(session, clip_id)
        response_slot = next(
            item for item in slots["items"] if item["slot_no"] == slot_no
        )
        return {"slot": response_slot, "warnings": slots["warnings"]}


async def update_clip_slot_override(
    session: AsyncSession,
    clip_id: int,
    slot_no: int,
    *,
    upload: UploadFile | None,
    clear_override: bool,
) -> dict[str, Any]:
    temp_path: Path | None = None
    new_formal_path: Path | None = None
    new_trash_path: Path | None = None
    new_formal_renamed = False
    moved_old: tuple[Path, Path, Path] | None = None
    transaction_committed = False
    try:
        extension: str | None = None
        digest: str | None = None
        if upload is not None:
            temp_path, extension, digest = await _prepare_slot_override_upload(
                upload
            )

        async with session.begin():
            clip_result = await session.execute(
                select(Clip).where(Clip.id == clip_id).with_for_update()
            )
            clip = clip_result.scalar_one_or_none()
            if clip is None:
                raise HTTPException(status_code=404, detail="Clip not found")
            episode = await session.get(Episode, clip.episode_id)
            if episode is None:
                raise _source_data_error()

            slot_result = await session.execute(
                select(ClipRefSlot)
                .where(
                    ClipRefSlot.clip_id == clip_id,
                    ClipRefSlot.slot_no == slot_no,
                )
                .with_for_update()
            )
            slot = slot_result.scalar_one_or_none()
            if slot is None:
                raise HTTPException(status_code=404, detail="Clip slot not found")

            existing = _existing_slot_override(episode, clip, slot)
            if upload is not None:
                if extension is None or digest is None or temp_path is None:
                    raise RuntimeError("slot override upload state is incomplete")
                new_relative_path, new_formal_path, new_trash_path = (
                    _slot_override_paths(episode, clip, slot, extension)
                )
                if (
                    existing is not None
                    and existing[3] == extension
                    and str(slot.override_sha256) == digest
                ):
                    response = await list_clip_slots(session, clip_id)
                else:
                    if new_formal_path.exists() and (
                        existing is None or new_formal_path != existing[1]
                    ):
                        raise _source_data_error()
                    if existing is not None:
                        _move_slot_override(existing[1], existing[2])
                        moved_old = existing[:3]
                    new_formal_path.parent.mkdir(parents=True, exist_ok=True)
                    temp_path.replace(new_formal_path)
                    new_formal_renamed = True
                    slot.override_image_path = new_relative_path.as_posix()
                    slot.override_sha256 = digest
                    clip.revision += 1
                    clip.freshness = "stale"
                    clip.updated_at = datetime.now(timezone.utc)
                    await session.flush()
                    response = await list_clip_slots(session, clip_id)
            elif clear_override:
                if existing is None:
                    response = await list_clip_slots(session, clip_id)
                else:
                    _move_slot_override(existing[1], existing[2])
                    moved_old = existing[:3]
                    slot.override_image_path = None
                    slot.override_sha256 = None
                    clip.revision += 1
                    clip.freshness = "stale"
                    clip.updated_at = datetime.now(timezone.utc)
                    await session.flush()
                    response = await list_clip_slots(session, clip_id)
            else:
                raise RuntimeError("slot override mutation mode is incomplete")

        transaction_committed = True
        response_slot = next(
            item for item in response["items"] if item["slot_no"] == slot_no
        )
        return {"slot": response_slot, "warnings": response["warnings"]}
    finally:
        primary_error = sys.exc_info()[1]
        cleanup_errors: list[tuple[str, OSError]] = []
        if not transaction_committed:
            if new_formal_renamed and new_formal_path is not None:
                if new_formal_path.exists():
                    try:
                        if (
                            moved_old is not None
                            and new_trash_path is not None
                            and new_trash_path == moved_old[2]
                        ):
                            new_formal_path.unlink()
                        elif new_trash_path is None:
                            raise OSError(
                                "slot override new trash path is unavailable"
                            )
                        else:
                            _move_slot_override(
                                new_formal_path, new_trash_path
                            )
                    except OSError as exc:
                        cleanup_errors.append(("new override cleanup failed", exc))
            if moved_old is not None:
                if moved_old[2].exists():
                    try:
                        moved_old[2].replace(moved_old[1])
                    except OSError as exc:
                        cleanup_errors.append(("old override restore failed", exc))
                else:
                    cleanup_errors.append(
                        (
                            "old override restore failed",
                            FileNotFoundError("moved old override is missing"),
                        )
                    )
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError as exc:
                cleanup_errors.append(("temporary override cleanup failed", exc))
        _raise_slot_cleanup_errors(primary_error, cleanup_errors)


def _validated_clip_media_move(
    relative_path_value: str,
    expected_relative_path: Path,
) -> tuple[Path, Path]:
    try:
        return validated_clip_media_move(
            settings.DATA_DIR,
            relative_path_value,
            expected_relative_path,
        )
    except ValueError as exc:
        raise _source_data_error() from exc


async def delete_clip(session: AsyncSession, clip_id: int) -> None:
    moved_media: list[tuple[Path, Path]] = []
    transaction_committed = False
    try:
        async with session.begin():
            clip_result = await session.execute(
                select(Clip).where(Clip.id == clip_id).with_for_update()
            )
            clip = clip_result.scalar_one_or_none()
            if clip is None:
                raise HTTPException(status_code=404, detail="Clip not found")

            episode = await session.get(Episode, clip.episode_id)
            if episode is None:
                raise _source_data_error()

            clip_shot_result = await session.execute(
                select(ClipShot)
                .where(ClipShot.clip_id == clip.id)
                .order_by(ClipShot.position, ClipShot.shot_id)
                .with_for_update()
            )
            clip_shots = list(clip_shot_result.scalars().all())
            if not clip_shots:
                raise _source_data_error()
            positions = [int(clip_shot.position) for clip_shot in clip_shots]
            if positions != list(range(1, len(clip_shots) + 1)):
                raise _source_data_error()
            shot_result = await session.execute(
                select(Shot)
                .where(Shot.id.in_([clip_shot.shot_id for clip_shot in clip_shots]))
                .order_by(Shot.id)
            )
            shots = list(shot_result.scalars().all())
            if len(shots) != len(clip_shots) or any(
                shot.episode_id != clip.episode_id for shot in shots
            ):
                raise _source_data_error()

            slot_result = await session.execute(
                select(ClipRefSlot)
                .where(ClipRefSlot.clip_id == clip.id)
                .order_by(ClipRefSlot.slot_no, ClipRefSlot.id)
                .with_for_update()
            )
            slots = list(slot_result.scalars().all())
            if len({slot.slot_no for slot in slots}) != len(slots):
                raise _source_data_error()

            video_result = await session.execute(
                select(ClipVideo)
                .where(ClipVideo.clip_id == clip.id)
                .order_by(ClipVideo.id)
                .with_for_update()
            )
            videos = list(video_result.scalars().all())

            media_moves: list[tuple[Path, Path]] = []
            media_sources: set[Path] = set()
            for slot in slots:
                if slot.override_image_path is None:
                    if slot.override_sha256 is not None:
                        raise _source_data_error()
                    continue
                existing = _existing_slot_override(episode, clip, slot)
                if existing is None:
                    raise _source_data_error()
                source, destination = _validated_clip_media_move(
                    existing[0].as_posix(),
                    existing[0],
                )
                if source in media_sources:
                    raise _source_data_error()
                media_sources.add(source)
                media_moves.append((source, destination))

            for video in videos:
                try:
                    expected_relative_path, _, _ = clip_video_paths(
                        settings.DATA_DIR,
                        int(episode.project_id),
                        int(episode.id),
                        int(clip.id),
                        int(video.id),
                    )
                except ValueError as exc:
                    raise _source_data_error() from exc
                source, destination = _validated_clip_media_move(
                    video.file_path, expected_relative_path
                )
                if source in media_sources:
                    raise _source_data_error()
                media_sources.add(source)
                media_moves.append((source, destination))

            for source, destination in media_moves:
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.replace(destination)
                moved_media.append((source, destination))

            await session.execute(delete(ClipShot).where(ClipShot.clip_id == clip.id))
            await session.execute(
                delete(ClipRefSlot).where(ClipRefSlot.clip_id == clip.id)
            )
            await session.execute(delete(ClipVideo).where(ClipVideo.clip_id == clip.id))
            await session.execute(delete(Clip).where(Clip.id == clip.id))
            await session.flush()

        transaction_committed = True
    finally:
        primary_error = sys.exc_info()[1]
        cleanup_errors: list[tuple[str, OSError]] = []
        if not transaction_committed:
            for source, destination in reversed(moved_media):
                if not destination.exists():
                    cleanup_errors.append(
                        (
                            "clip media restore failed",
                            FileNotFoundError(str(destination)),
                        )
                    )
                    continue
                if source.exists():
                    cleanup_errors.append(
                        (
                            "clip media restore failed",
                            FileExistsError(str(source)),
                        )
                    )
                    continue
                try:
                    destination.replace(source)
                except OSError as exc:
                    cleanup_errors.append(("clip media restore failed", exc))
        _raise_clip_cleanup_errors(primary_error, cleanup_errors)
