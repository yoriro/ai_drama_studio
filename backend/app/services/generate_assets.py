import json
import re
from collections.abc import Mapping

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Asset, Episode, Project, PromptTemplate, Style
from app.tasks.queue import EnqueueResult, TaskQueue


_TEMPLATE_KEY = "script2assets"
_PLACEHOLDER_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")
_REQUIRED_PLACEHOLDERS = frozenset({"existing_assets", "style", "script"})


def _conflict(message: str) -> HTTPException:
    return HTTPException(status_code=409, detail=message)


def _render_prompt(
    template_content: str,
    *,
    existing_assets: list[dict[str, object]],
    style: str,
    script: str,
) -> str:
    values: Mapping[str, str] = {
        "existing_assets": json.dumps(
            existing_assets, ensure_ascii=False, separators=(",", ":")
        ),
        "style": style,
        "script": script,
    }
    matches = list(_PLACEHOLDER_PATTERN.finditer(template_content))
    names = [match.group(1) for match in matches]
    if set(names) != _REQUIRED_PLACEHOLDERS:
        raise _conflict(
            "script2assets 模板必须包含且只能使用 "
            "{{existing_assets}}、{{style}}、{{script}} 占位符"
        )
    return _PLACEHOLDER_PATTERN.sub(
        lambda match: values[match.group(1)], template_content
    )


async def enqueue_generate_assets(
    session: AsyncSession,
    queue: TaskQueue,
    episode_id: int,
) -> EnqueueResult:
    async with session.begin():
        episode_result = await session.execute(
            select(Episode)
            .where(Episode.id == episode_id)
            .with_for_update()
        )
        episode = episode_result.scalar_one_or_none()
        if episode is None:
            raise HTTPException(status_code=404, detail="Episode not found")

        project = await session.get(Project, episode.project_id)
        if project is None:
            raise _conflict("项目风格不存在")
        style = await session.get(Style, project.style_id)
        if style is None:
            raise _conflict("项目风格不存在")
        template = await session.scalar(
            select(PromptTemplate).where(PromptTemplate.key == _TEMPLATE_KEY)
        )
        if template is None:
            raise _conflict("script2assets 模板不存在")

        asset_result = await session.execute(
            select(Asset)
            .where(
                Asset.project_id == project.id,
                Asset.type.in_(("character", "scene")),
            )
            .order_by(Asset.id)
        )
        assets = list(asset_result.scalars().all())
        existing_assets = [
            {
                "id": asset.id,
                "type": asset.type,
                "name": asset.name,
                "description": asset.description,
            }
            for asset in assets
        ]
        rendered_prompt = _render_prompt(
            template.content,
            existing_assets=existing_assets,
            style=style.prompt_fragment,
            script=episode.script_text,
        )
        input_snapshot = {
            "episode_id": episode.id,
            "project_id": project.id,
            "script": episode.script_text,
            "script_revision": episode.script_revision,
            "style": style.prompt_fragment,
            "template_key": _TEMPLATE_KEY,
            "template_content": template.content,
            "existing_assets": existing_assets,
            "rendered_prompt": rendered_prompt,
            "model": settings.VLLM_MODEL,
            "temperature": settings.VLLM_TEMPERATURE,
        }
        payload = {
            "input_snapshot": input_snapshot,
            "input_hash": None,
            "source_revisions": {
                "episode": {
                    "id": episode.id,
                    "script_revision": episode.script_revision,
                },
                "assets": [
                    {"id": asset.id, "revision": asset.revision}
                    for asset in assets
                ],
            },
        }
        return await queue.enqueue(
            session,
            "gen_assets",
            episode.id,
            payload,
            request_id=None,
        )
