from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.prompt_templates import (
    PromptTemplatePatch,
    PromptTemplateResponse,
)
from app.services.prompt_templates import (
    list_prompt_templates,
    update_prompt_template,
)


router = APIRouter(prefix="/prompt-templates", tags=["prompt-templates"])


@router.get("", response_model=list[PromptTemplateResponse])
async def read_prompt_templates(
    session: AsyncSession = Depends(get_session),
) -> list[PromptTemplateResponse]:
    return await list_prompt_templates(session)


@router.patch("/{key}", response_model=PromptTemplateResponse)
async def update_prompt_template_route(
    key: str,
    payload: PromptTemplatePatch,
    session: AsyncSession = Depends(get_session),
) -> PromptTemplateResponse:
    return await update_prompt_template(session, key, payload)
