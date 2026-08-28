from __future__ import annotations

from collections.abc import Mapping

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.workflow_binding import WorkflowBindingSnapshot
from app.models import Asset, Project, PromptTemplate, Style
from app.services.asset_image_inputs import (
    build_asset_image_identifiers,
    build_asset_image_input_hash,
    build_zimage_response_format,
    render_zimage_prompt,
)
from app.tasks.queue import (
    EnqueueResult,
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
        return await queue.enqueue(
            session,
            "gen_asset_image",
            asset.id,
            payload,
            request_id=normalized_request_id,
        )
