from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.workflow_binding import MiniMaxWorkflowBindingSnapshot
from app.models import (
    Asset,
    AssetImage,
    Clip,
    ClipRefSlot,
    ClipShot,
    Episode,
    Project,
    PromptTemplate,
    Shot,
    ShotAsset,
    Style,
    Task,
)
from app.services.asset_files import (
    asset_image_relative_path,
    resolve_data_path,
    sha256_file,
)
from app.services.clip_rules import (
    ClipRuleAsset,
    ClipRuleDataError,
    ClipRuleShot,
    evaluate_clip_selection,
)
from app.services.clip_video_inputs import (
    build_clip_video_input_hash,
    build_clip_video_references,
    build_clip_video_shot_snapshots,
    build_clip_video_identifiers,
    build_minimaxh3_response_format,
    render_minimaxh3_prompt,
)
from app.services.clips import _existing_slot_override
from app.tasks.queue import (
    EnqueueResult,
    TaskConflictError,
    TaskQueue,
    TaskRequestConflictError,
    TaskValidationError,
    normalize_request_id,
)


_TEMPLATE_KEY = "minimaxh3"
_VISIBLE_ASSET_TYPES = frozenset({"character", "scene"})
_R5_CODES = frozenset(
    {"shots_not_contiguous", "shot_already_in_clip", "duration_exceeds_max"}
)
_R5A_CODES = frozenset({"shot_has_multiple_scenes", "multiple_scenes"})


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail=message)


def _conflict(message: str) -> HTTPException:
    return HTTPException(status_code=409, detail=message)


def _internal(message: str = "Clip source data is inconsistent") -> HTTPException:
    return HTTPException(status_code=500, detail=message)


def _request_conflict(task: Task) -> TaskRequestConflictError:
    return TaskRequestConflictError(
        "request_id is already bound to a different task request",
        existing_task=task,
    )


def _request_identity(
    *, user_note_provided: bool, user_note: str | None
) -> dict[str, object]:
    return {
        "user_note_provided": user_note_provided,
        "user_note": user_note,
    }


def _matches_request_identity(
    task: Task,
    *,
    clip_id: int,
    user_note_provided: bool,
    user_note: str | None,
) -> bool:
    if task.type != "gen_clip_video" or task.target_id != clip_id:
        return False
    snapshot = task.payload.get("input_snapshot")
    if not isinstance(snapshot, dict):
        raise RuntimeError(f"task {task.id} has an invalid input snapshot")
    identity = snapshot.get("request_identity")
    if not isinstance(identity, dict):
        raise RuntimeError(f"task {task.id} has no request identity snapshot")
    expected_identity = _request_identity(
        user_note_provided=user_note_provided,
        user_note=user_note,
    )
    if identity.get("user_note_provided") != expected_identity[
        "user_note_provided"
    ]:
        return False
    if not user_note_provided:
        return True
    return identity.get("user_note") == expected_identity["user_note"]


async def _load_assets(
    session: AsyncSession, asset_ids: set[int]
) -> dict[int, Asset]:
    if not asset_ids:
        return {}
    result = await session.execute(
        select(Asset).where(Asset.id.in_(sorted(asset_ids))).order_by(Asset.id)
    )
    assets = {int(asset.id): asset for asset in result.scalars().all()}
    if set(assets) != asset_ids:
        raise _internal()
    return assets


async def _load_clip_source(
    session: AsyncSession, clip: Clip, episode: Episode
) -> tuple[
    list[tuple[ClipShot, Shot]],
    dict[int, Asset],
    tuple[dict[str, object], ...],
    tuple[ClipRuleShot, ...],
]:
    shot_result = await session.execute(
        select(ClipShot, Shot)
        .join(Shot, Shot.id == ClipShot.shot_id)
        .where(ClipShot.clip_id == clip.id)
        .order_by(ClipShot.position, ClipShot.shot_id)
    )
    shot_rows = list(shot_result.all())
    if not shot_rows:
        raise _internal()
    positions = [int(clip_shot.position) for clip_shot, _ in shot_rows]
    if positions != list(range(1, len(shot_rows) + 1)):
        raise _internal()
    if any(shot.episode_id != clip.episode_id for _, shot in shot_rows):
        raise _internal()

    shot_ids = [int(shot.id) for _, shot in shot_rows]
    shot_asset_result = await session.execute(
        select(ShotAsset)
        .where(ShotAsset.shot_id.in_(shot_ids))
        .order_by(ShotAsset.shot_id, ShotAsset.asset_id)
    )
    shot_asset_rows = list(shot_asset_result.scalars().all())
    asset_ids = {int(row.asset_id) for row in shot_asset_rows}
    assets = await _load_assets(session, asset_ids)
    if any(asset.project_id != episode.project_id for asset in assets.values()):
        raise _internal()

    asset_ids_by_shot: dict[int, list[int]] = defaultdict(list)
    for row in shot_asset_rows:
        asset_ids_by_shot[int(row.shot_id)].append(int(row.asset_id))

    rule_shots = tuple(
        ClipRuleShot(
            id=int(shot.id),
            order_index=int(shot.order_index),
            duration_est=shot.duration_est,
            assets=tuple(
                ClipRuleAsset(
                    id=asset_id,
                    type=assets[asset_id].type,
                    name=assets[asset_id].name,
                )
                for asset_id in asset_ids_by_shot.get(int(shot.id), ())
                if assets[asset_id].type in _VISIBLE_ASSET_TYPES
            ),
        )
        for _, shot in shot_rows
    )

    raw_shots = [
        {
            "position": int(clip_shot.position),
            "id": int(shot.id),
            "order": int(shot.order_index),
            "duration_est": shot.duration_est,
            "shot_type": shot.shot_type,
            "camera": shot.camera,
            "description": shot.description,
            "dialogue": shot.dialogue,
            "revision": int(shot.revision),
            "asset_ids": sorted(asset_ids_by_shot.get(int(shot.id), ())),
        }
        for clip_shot, shot in shot_rows
    ]
    try:
        shot_snapshots = build_clip_video_shot_snapshots(raw_shots)
    except ValueError as exc:
        raise _internal() from exc

    return shot_rows, assets, shot_snapshots, rule_shots


async def _other_clip_shot_ids(
    session: AsyncSession, clip: Clip, shot_ids: list[int]
) -> set[int]:
    result = await session.execute(
        select(ClipShot.shot_id).where(
            ClipShot.shot_id.in_(shot_ids), ClipShot.clip_id != clip.id
        )
    )
    return {int(shot_id) for shot_id in result.scalars().all()}


async def _discover_and_lock_enabled_assets(
    session: AsyncSession, clip_id: int
) -> None:
    discovery_result = await session.execute(
        select(ClipRefSlot.asset_id)
        .where(
            ClipRefSlot.clip_id == clip_id,
            ClipRefSlot.enabled.is_(True),
            ClipRefSlot.asset_id.is_not(None),
        )
        .order_by(ClipRefSlot.asset_id, ClipRefSlot.id)
    )
    asset_ids = sorted(
        {int(asset_id) for asset_id in discovery_result.scalars().all()}
    )
    if not asset_ids:
        return
    await session.execute(
        select(Asset)
        .where(Asset.id.in_(asset_ids))
        .order_by(Asset.id)
        .with_for_update()
    )


def _rule_failure(
    result_violations: tuple[object, ...],
) -> tuple[str, str] | None:
    for violation in result_violations:
        code = getattr(violation, "code")
        message = getattr(violation, "message")
        if code in _R5_CODES:
            return "R5", str(message)
        if code in _R5A_CODES:
            return "R5a", str(message)
        if code == "no_reference_candidates":
            return "R5", str(message)
    return None


def _current_asset_media_is_valid(asset: Asset, image: AssetImage) -> None:
    try:
        relative_path = Path(image.file_path)
        expected_path = asset_image_relative_path(
            int(asset.project_id),
            int(asset.id),
            int(image.id),
            relative_path.suffix.removeprefix(".").lower(),
        )
        if relative_path.as_posix() != expected_path.as_posix():
            raise ValueError("asset image path is not canonical")
        formal_path = resolve_data_path(settings.DATA_DIR, relative_path)
        if not formal_path.is_file():
            raise OSError("asset image file does not exist")
        if sha256_file(formal_path) != str(image.sha256):
            raise ValueError("asset image hash does not match")
    except (OSError, ValueError) as exc:
        raise exc


async def _build_slot_inputs(
    session: AsyncSession,
    *,
    clip: Clip,
    episode: Episode,
    shot_assets: Mapping[int, Asset],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    slot_result = await session.execute(
        select(ClipRefSlot)
        .where(ClipRefSlot.clip_id == clip.id)
        .order_by(ClipRefSlot.slot_no, ClipRefSlot.id)
    )
    slots = list(slot_result.scalars().all())
    if len({int(slot.slot_no) for slot in slots}) != len(slots):
        raise _internal()
    if any(not 1 <= int(slot.slot_no) <= 9 for slot in slots):
        raise _internal()

    slot_asset_ids = {
        int(slot.asset_id)
        for slot in slots
        if slot.enabled and slot.asset_id is not None
    }
    assets = dict(shot_assets)
    missing_slot_asset_ids = slot_asset_ids - set(assets)
    assets.update(await _load_assets(session, missing_slot_asset_ids))
    if any(asset.project_id != episode.project_id for asset in assets.values()):
        raise _internal()

    image_result = await session.execute(
        select(AssetImage)
        .where(
            AssetImage.asset_id.in_(sorted(slot_asset_ids)),
            AssetImage.is_current.is_(True),
        )
        .order_by(AssetImage.asset_id, AssetImage.id)
    )
    current_images: dict[int, list[AssetImage]] = defaultdict(list)
    for image in image_result.scalars().all():
        current_images[int(image.asset_id)].append(image)
    if any(len(images) > 1 for images in current_images.values()):
        raise _internal()

    slot_inputs: list[dict[str, object]] = []
    enabled_asset_revisions: list[dict[str, object]] = []
    r10_failure: list[str] | None = None
    for slot in slots:
        slot_no = int(slot.slot_no)
        slot_input: dict[str, object] = {
            "slot_no": slot_no,
            "enabled": bool(slot.enabled),
            "asset_id": None if slot.asset_id is None else int(slot.asset_id),
            "asset_name_snapshot": slot.asset_name_snapshot,
            "asset_type_snapshot": slot.asset_type_snapshot,
            "override_image_path": slot.override_image_path,
            "override_sha256": slot.override_sha256,
        }
        if not slot.enabled:
            slot_inputs.append(slot_input)
            continue

        if slot.asset_id is None:
            if slot.override_image_path is None and slot.override_sha256 is None:
                r10_failure = [
                    f"R10 slot {slot_no}: 资产已删无 override"
                ]
                slot_inputs.append(slot_input)
                break
            if (slot.override_image_path is None) != (
                slot.override_sha256 is None
            ):
                r10_failure = [
                    f"R10 slot {slot_no}: 路径、文件或 hash 不可用"
                ]
                slot_inputs.append(slot_input)
                break
            if slot.asset_type_snapshot not in _VISIBLE_ASSET_TYPES:
                raise _internal()
            try:
                existing_override = _existing_slot_override(episode, clip, slot)
            except HTTPException as exc:
                r10_failure = [
                    f"R10 slot {slot_no}: 路径、文件或 hash 不可用 ({exc.detail})"
                ]
                slot_inputs.append(slot_input)
                break
            if existing_override is None:
                r10_failure = [
                    f"R10 slot {slot_no}: 资产已删无 override"
                ]
                slot_inputs.append(slot_input)
                break
            slot_input["override_image_path"] = existing_override[0].as_posix()
            slot_inputs.append(slot_input)
            continue

        asset = assets.get(int(slot.asset_id))
        if asset is None:
            raise _internal()
        if (
            asset.type not in _VISIBLE_ASSET_TYPES
            or asset.type != slot.asset_type_snapshot
        ):
            raise _internal()
        enabled_asset_revisions.append(
            {"id": int(asset.id), "revision": int(asset.revision)}
        )

        if slot.override_image_path is not None or slot.override_sha256 is not None:
            if (slot.override_image_path is None) != (
                slot.override_sha256 is None
            ):
                r10_failure = [
                    f"R10 slot {slot_no}: 路径、文件或 hash 不可用"
                ]
                slot_inputs.append(slot_input)
                break
            try:
                existing_override = _existing_slot_override(episode, clip, slot)
            except HTTPException as exc:
                r10_failure = [
                    f"R10 slot {slot_no}: 路径、文件或 hash 不可用 ({exc.detail})"
                ]
                slot_inputs.append(slot_input)
                break
            if existing_override is None:
                r10_failure = [
                    f"R10 slot {slot_no}: 路径、文件或 hash 不可用"
                ]
                slot_inputs.append(slot_input)
                break
            slot_input["override_image_path"] = existing_override[0].as_posix()
            slot_inputs.append(slot_input | {
                "asset": {
                    "id": int(asset.id),
                    "type": asset.type,
                    "name": asset.name,
                    "description": asset.description,
                    "revision": int(asset.revision),
                }
            })
            continue

        images = current_images.get(int(asset.id), [])
        if not images:
            r10_failure = [f"R10 slot {slot_no}: 活资产无 current 图片"]
            slot_inputs.append(slot_input)
            break
        image = images[0]
        try:
            _current_asset_media_is_valid(asset, image)
        except (OSError, ValueError) as exc:
            r10_failure = [
                f"R10 slot {slot_no}: 路径、文件或 hash 不可用 ({exc})"
            ]
            slot_inputs.append(slot_input)
            break
        slot_inputs.append(slot_input | {
            "asset": {
                "id": int(asset.id),
                "type": asset.type,
                "name": asset.name,
                "description": asset.description,
                "revision": int(asset.revision),
            },
            "current_image": {
                "id": int(image.id),
                "file_path": image.file_path,
                "sha256": image.sha256,
            },
        })

    return slot_inputs, enabled_asset_revisions, r10_failure or []


def _source_revisions(
    clip: Clip,
    shot_rows: list[tuple[ClipShot, Shot]],
    asset_revisions: list[dict[str, object]],
) -> dict[str, object]:
    unique_assets = {
        int(item["id"]): {
            "id": int(item["id"]),
            "revision": int(item["revision"]),
        }
        for item in asset_revisions
    }
    return {
        "clip": {"id": int(clip.id), "revision": int(clip.revision)},
        "shots": [
            {"id": int(shot.id), "revision": int(shot.revision)}
            for _, shot in shot_rows
        ],
        "assets": [unique_assets[asset_id] for asset_id in sorted(unique_assets)],
    }


async def _record_precheck_failure(
    session: AsyncSession,
    queue: TaskQueue,
    *,
    clip: Clip,
    shot_rows: list[tuple[ClipShot, Shot]],
    user_note_provided: bool,
    effective_user_note: str | None,
    requested_duration: int,
    rule: str,
    reason: str,
    asset_revisions: list[dict[str, object]],
    request_id: str | None,
) -> EnqueueResult:
    input_snapshot = {
        "request_identity": _request_identity(
            user_note_provided=user_note_provided,
            user_note=effective_user_note,
        ),
        "clip": {"id": int(clip.id), "revision": int(clip.revision)},
        "user_note": effective_user_note,
        "requested_duration": requested_duration,
        "precheck": {"rule": rule, "reason": reason},
    }
    return await queue.record_failed(
        session,
        "gen_clip_video",
        int(clip.id),
        {
            "input_snapshot": input_snapshot,
            "input_hash": None,
            "source_revisions": _source_revisions(
                clip, shot_rows, asset_revisions
            ),
        },
        f"{rule}: {reason}",
        request_id=request_id,
    )


async def enqueue_generate_clip_video(
    session: AsyncSession,
    queue: TaskQueue,
    clip_id: int,
    *,
    user_note: str | None,
    user_note_provided: bool,
    request_id: str | None,
    workflow_binding: MiniMaxWorkflowBindingSnapshot,
) -> EnqueueResult:
    if isinstance(request_id, str) and "\x00" in request_id:
        raise TaskValidationError("request_id must not contain U+0000")
    normalized_request_id = normalize_request_id(request_id)
    if user_note is not None and "\x00" in user_note:
        raise TaskValidationError("user_note must not contain U+0000")

    async with session.begin():
        if normalized_request_id is not None:
            await queue.acquire_request_id_lock(session, normalized_request_id)
            existing = await queue.find_request(session, normalized_request_id)
            if existing is not None:
                if not _matches_request_identity(
                    existing,
                    clip_id=clip_id,
                    user_note_provided=user_note_provided,
                    user_note=user_note,
                ):
                    raise _request_conflict(existing)
                return EnqueueResult(task=existing, created=False)

        await _discover_and_lock_enabled_assets(session, clip_id)

        clip = await session.scalar(
            select(Clip).where(Clip.id == clip_id).with_for_update()
        )
        if clip is None:
            raise _not_found("Clip not found")
        if clip.id <= 0:
            raise _not_found("Clip not found")

        if user_note_provided and user_note != clip.user_note:
            clip.user_note = user_note
            clip.revision += 1
            clip.freshness = "stale"
            clip.updated_at = datetime.now(timezone.utc)
        effective_user_note = user_note if user_note_provided else clip.user_note

        episode = await session.scalar(
            select(Episode).where(Episode.id == clip.episode_id)
        )
        if episode is None:
            raise _internal()

        (
            shot_rows,
            shot_assets,
            shot_snapshots,
            rule_shots,
        ) = await _load_clip_source(session, clip, episode)
        other_shot_ids = await _other_clip_shot_ids(
            session, clip, [int(shot.id) for _, shot in shot_rows]
        )
        try:
            rule_result = evaluate_clip_selection(
                rule_shots,
                occupied_shot_ids=other_shot_ids,
                clip_min_seconds=settings.CLIP_MIN_SECONDS,
                clip_max_seconds=settings.CLIP_MAX_SECONDS,
                slot_soft_limit=settings.SLOT_SOFT_LIMIT,
                slot_hard_limit=settings.SLOT_HARD_LIMIT,
            )
        except ClipRuleDataError as exc:
            raise _internal() from exc
        rule_failure = _rule_failure(rule_result.violations)
        if rule_failure is not None:
            rule, reason = rule_failure
            return await _record_precheck_failure(
                session,
                queue,
                clip=clip,
                shot_rows=shot_rows,
                user_note_provided=user_note_provided,
                effective_user_note=effective_user_note,
                requested_duration=int(clip.requested_duration),
                rule=rule,
                reason=reason,
                asset_revisions=[
                    {"id": int(asset.id), "revision": int(asset.revision)}
                    for asset in shot_assets.values()
                ],
                request_id=normalized_request_id,
            )

        slot_inputs, enabled_asset_revisions, r10_failure = await _build_slot_inputs(
            session,
            clip=clip,
            episode=episode,
            shot_assets=shot_assets,
        )
        if r10_failure:
            reason = r10_failure[0]
            return await _record_precheck_failure(
                session,
                queue,
                clip=clip,
                shot_rows=shot_rows,
                user_note_provided=user_note_provided,
                effective_user_note=effective_user_note,
                requested_duration=int(clip.requested_duration),
                rule="R10",
                reason=reason,
                asset_revisions=enabled_asset_revisions,
                request_id=normalized_request_id,
            )

        try:
            references_result = build_clip_video_references(slot_inputs)
        except ValueError as exc:
            raise _internal() from exc

        project = await session.scalar(
            select(Project).where(Project.id == episode.project_id).with_for_update()
        )
        if project is None:
            raise _conflict("Clip project does not exist")
        style = await session.scalar(
            select(Style).where(Style.id == project.style_id).with_for_update()
        )
        if style is None:
            raise _conflict("Project style does not exist")
        template = await session.scalar(
            select(PromptTemplate)
            .where(PromptTemplate.key == _TEMPLATE_KEY)
            .with_for_update()
        )
        if template is None:
            raise _conflict("minimaxh3 prompt template does not exist")

        try:
            rendered_prompt = render_minimaxh3_prompt(
                template.content,
                shots=shot_snapshots,
                references=references_result.references,
                style=style.prompt_fragment,
                requested_duration=int(clip.requested_duration),
                user_note=effective_user_note,
            )
        except ValueError as exc:
            raise _conflict(str(exc)) from exc

        input_hash = build_clip_video_input_hash(
            shots=shot_snapshots,
            references=references_result.references,
            style_prompt_fragment=style.prompt_fragment,
            template_content=template.content,
            user_note=effective_user_note,
            requested_duration=int(clip.requested_duration),
            model=settings.VLLM_MODEL,
            workflow_hash=workflow_binding.workflow_hash,
        )
        if clip.prompt_input_hash == input_hash:
            if (
                not isinstance(clip.prompt_cache, str)
                or not clip.prompt_cache.strip()
            ):
                raise _internal(
                    "Clip video prompt cache is inconsistent with its hash"
                )
            cached_prompt: str | None = clip.prompt_cache
        else:
            cached_prompt = None

        identifiers = build_clip_video_identifiers(normalized_request_id)
        input_snapshot: dict[str, object] = {
            "request_identity": _request_identity(
                user_note_provided=user_note_provided,
                user_note=effective_user_note,
            ),
            "clip": {
                "id": int(clip.id),
                "episode_id": int(clip.episode_id),
                "revision": int(clip.revision),
                "generation_mode": clip.generation_mode,
            },
            "user_note": effective_user_note,
            "requested_duration": int(clip.requested_duration),
            "shots": list(shot_snapshots),
            "references": list(references_result.references),
            "reference_media": list(references_result.reference_media),
            "style": style.prompt_fragment,
            "template_key": _TEMPLATE_KEY,
            "template_content": template.content,
            "rendered_prompt": rendered_prompt,
            "model": settings.VLLM_MODEL,
            "temperature": settings.VLLM_TEMPERATURE,
            "guided_json_schema": build_minimaxh3_response_format(),
            "workflow": workflow_binding.workflow_payload(),
            "seed": identifiers.seed,
            "comfy_prompt_id": identifiers.comfy_prompt_id,
            "cached_prompt": cached_prompt,
        }
        payload = {
            "input_snapshot": input_snapshot,
            "input_hash": input_hash,
            "source_revisions": _source_revisions(
                clip,
                shot_rows,
                enabled_asset_revisions,
            ),
        }
        try:
            return await queue.enqueue(
                session,
                "gen_clip_video",
                int(clip.id),
                payload,
                request_id=normalized_request_id,
            )
        except TaskRequestConflictError as exc:
            existing = exc.existing_task
            if existing is None and normalized_request_id is not None:
                existing = await queue.find_request(session, normalized_request_id)
            if existing is None or not _matches_request_identity(
                existing,
                clip_id=clip_id,
                user_note_provided=user_note_provided,
                user_note=user_note,
            ):
                raise
            return EnqueueResult(task=existing, created=False)
