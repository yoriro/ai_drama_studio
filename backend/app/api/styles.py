from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.styles import StyleCreate, StylePatch, StyleResponse
from app.services.styles import (
    create_style,
    delete_style,
    get_style,
    list_styles,
    update_style,
)


router = APIRouter(prefix="/styles", tags=["styles"])


@router.get("", response_model=list[StyleResponse])
async def read_styles(
    session: AsyncSession = Depends(get_session),
) -> list[StyleResponse]:
    return await list_styles(session)


@router.post("", response_model=StyleResponse, status_code=status.HTTP_201_CREATED)
async def create_style_route(
    payload: StyleCreate,
    session: AsyncSession = Depends(get_session),
) -> StyleResponse:
    return await create_style(session, payload)


@router.get("/{style_id}", response_model=StyleResponse)
async def read_style(
    style_id: int,
    session: AsyncSession = Depends(get_session),
) -> StyleResponse:
    return await get_style(session, style_id)


@router.patch("/{style_id}", response_model=StyleResponse)
async def update_style_route(
    style_id: int,
    payload: StylePatch,
    session: AsyncSession = Depends(get_session),
) -> StyleResponse:
    return await update_style(session, style_id, payload)


@router.delete("/{style_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_style_route(
    style_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await delete_style(session, style_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
