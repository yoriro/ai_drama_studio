from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Style
from app.schemas.styles import StyleCreate, StylePatch


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Style not found")


async def list_styles(session: AsyncSession) -> list[Style]:
    result = await session.execute(select(Style).order_by(Style.id))
    return list(result.scalars().all())


async def get_style(session: AsyncSession, style_id: int) -> Style:
    style = await session.get(Style, style_id)
    if style is None:
        raise _not_found()
    return style


async def create_style(session: AsyncSession, payload: StyleCreate) -> Style:
    try:
        async with session.begin():
            style = Style(
                name=payload.name,
                prompt_fragment=payload.prompt_fragment,
            )
            session.add(style)
            await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Style name already exists"
        ) from exc
    return style


async def update_style(
    session: AsyncSession, style_id: int, payload: StylePatch
) -> Style:
    try:
        async with session.begin():
            style = await get_style(session, style_id)
            changed = False
            if "name" in payload.model_fields_set and payload.name != style.name:
                style.name = payload.name
                changed = True
            if (
                "prompt_fragment" in payload.model_fields_set
                and payload.prompt_fragment != style.prompt_fragment
            ):
                style.prompt_fragment = payload.prompt_fragment
                changed = True
            if changed:
                style.updated_at = datetime.now(timezone.utc)
            await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Style name already exists"
        ) from exc
    return style


async def delete_style(session: AsyncSession, style_id: int) -> None:
    try:
        async with session.begin():
            style = await get_style(session, style_id)
            await session.delete(style)
            await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Style is referenced by a project"
        ) from exc
