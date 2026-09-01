from __future__ import annotations

from collections.abc import Mapping

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.workflow_binding import WorkflowBindingSnapshot
from app.models import Asset, Project, PromptTemplate, Style, Task
from app.services.asset_image_inputs import (
    build_asset_image_identifiers,
    build_asset_image_input_hash,
    build_zimage_response_format,
    render_zimage_prompt,
)
from app.tasks.queue import (
    EnqueueResult,
    TaskRequestConflictError,
    TaskQueue,
    normalize_request_id,
)


_TEMPLATE_KEY = "zimage"
_VISIBLE_ASSET_TYPES = ("character", "scene")


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Asset not found")


def _conflict(message: str) -> HTTPException:
    return HTTPException(status_code=409, detail=message)


def _internal_error(message: str) -> HTTPException:
    return HTTPException(status_code=500, detail=message)


def _request_user_note(task: Task) -> str | None:
    snapshot = task.payload.get("input_snapshot")
    if not isinstance(snapshot, dict) or "user_note" not in snapshot:
        raise RuntimeError(
            f"task {task.id} has no valid gen_asset_image user_note snapshot"
        )
    user_note = snapshot["user_note"]
    if user_note is not None and not isinstance(user_note, str):
        raise RuntimeError(
            f"task {task.id} has an invalid gen_asset_image user_note snapshot"
        )
    return user_note


def _matches_request_identity(
    task: Task, asset_id: int, user_note: str | None
) -> bool:
    if task.type != "gen_asset_image" or task.target_id != asset_id:
        return False
    return _request_user_note(task) == user_note


def _request_conflict(task: Task) -> TaskRequestConflictError:
    return TaskRequestConflictError(
        "request_id is already bound to a different task request",
        existing_task=task,
    )


async def enqueue_generate_asset_image(
    session: AsyncSession,
    queue: TaskQueue,
    asset_id: int,
    *,
    user_note: str | None,
    request_id: str | None,
    workflow_binding: WorkflowBindingSnapshot,
) -> EnqueueResult:
    normalized_request_id = normalize_request_id(request_id)

    async with session.begin():
        if normalized_request_id is not None:
            await queue.acquire_request_id_lock(session, normalized_request_id)
            existing = await queue.find_request(session, normalized_request_id)
            if existing is not None:
                if not _matches_request_identity(existing, asset_id, user_note):
                    raise _request_conflict(existing)
                return EnqueueResult(task=existing, created=False)

        asset = await session.scalar(
            select(Asset)
            .where(
                Asset.id == asset_id,
                Asset.type.in_(_VISIBLE_ASSET_TYPES),
            )
            .with_for_update()
        )
        if asset is None:
            raise _not_found()

        project = await session.scalar(
            select(Project)
            .where(Project.id == asset.project_id)
            .with_for_update()
        )
        if project is None:
            raise _conflict("Asset project does not exist")

        style = await session.scalar(
            select(Style)
            .where(Style.id == project.style_id)
            .with_for_update()
        )
        if style is None:
            raise _conflict("Project style does not exist")

        template = await session.scalar(
            select(PromptTemplate)
            .where(PromptTemplate.key == _TEMPLATE_KEY)
            .with_for_update()
        )
        if template is None:
            raise _conflict("zimage prompt template does not exist")

        asset_snapshot: Mapping[str, object] = {
            "id": asset.id,
            "project_id": asset.project_id,
            "type": asset.type,
            "name": asset.name,
            "description": asset.description,
            "revision": asset.revision,
        }
        try:
            rendered_prompt = render_zimage_prompt(
                template.content,
                asset=asset_snapshot,
                style=style.prompt_fragment,
                user_note=user_note,
            )
        except ValueError as exc:
            raise _conflict(str(exc)) from exc

        input_hash = build_asset_image_input_hash(
            asset_name=asset.name,
            asset_description=asset.description,
            asset_revision=asset.revision,
            style_prompt_fragment=style.prompt_fragment,
            template_content=template.content,
            user_note=user_note,
            model=settings.VLLM_MODEL,
            workflow_hash=workflow_binding.workflow_hash,
        )
        if asset.image_prompt_hash == input_hash:
            if asset.image_prompt_cache is None:
                raise _internal_error(
                    "Asset image prompt cache is inconsistent with its hash"
                )
            cached_prompt = asset.image_prompt_cache
        else:
            cached_prompt = None

        identifiers = build_asset_image_identifiers(normalized_request_id)
        input_snapshot = {
            "asset": dict(asset_snapshot),
            "style": style.prompt_fragment,
            "template_key": _TEMPLATE_KEY,
            "template_content": template.content,
            "user_note": user_note,
            "rendered_prompt": rendered_prompt,
            "model": settings.VLLM_MODEL,
            "temperature": settings.VLLM_TEMPERATURE,
            "guided_json_schema": build_zimage_response_format(),
            "workflow": workflow_binding.workflow_payload(),
            "seed": identifiers.seed,
            "comfy_prompt_id": identifiers.comfy_prompt_id,
            "cached_prompt": cached_prompt,
        }
        payload = {
            "input_snapshot": input_snapshot,
            "input_hash": input_hash,
            "source_revisions": {
                "asset": {
                    "id": asset.id,
                    "revision": asset.revision,
                }
            },
        }
        try:
            return await queue.enqueue(
                session,
                "gen_asset_image",
                asset.id,
                payload,
                request_id=normalized_request_id,
            )
        except TaskRequestConflictError as exc:
            existing = exc.existing_task
            if existing is None and normalized_request_id is not None:
                existing = await queue.find_request(
                    session, normalized_request_id
                )
            if existing is None or not _matches_request_identity(
                existing, asset.id, user_note
            ):
                raise
            return EnqueueResult(task=existing, created=False)
