from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PromptTemplate
from app.schemas.prompt_templates import PromptTemplatePatch


TEMPLATE_KEYS = ("script2assets", "script2shots", "zimage", "minimaxh3")


def _template_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Prompt template not found")


async def list_prompt_templates(
    session: AsyncSession,
) -> list[PromptTemplate]:
    result = await session.execute(
        select(PromptTemplate).where(PromptTemplate.key.in_(TEMPLATE_KEYS))
    )
    templates = {template.key: template for template in result.scalars().all()}
    if set(templates) != set(TEMPLATE_KEYS):
        raise RuntimeError("C002 prompt templates are not initialized")
    return [templates[key] for key in TEMPLATE_KEYS]


async def update_prompt_template(
    session: AsyncSession, key: str, payload: PromptTemplatePatch
) -> PromptTemplate:
    if key not in TEMPLATE_KEYS:
        raise _template_not_found()
    async with session.begin():
        template = await session.scalar(
            select(PromptTemplate).where(PromptTemplate.key == key)
        )
        if template is None:
            raise _template_not_found()
        if payload.content != template.content:
            template.content = payload.content
            template.updated_at = datetime.now(timezone.utc)
        await session.flush()
    return template
