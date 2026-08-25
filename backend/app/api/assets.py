from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.assets import AssetCreate, AssetPatch, AssetResponse
from app.services.assets import (
    create_asset,
    get_asset,
    list_assets,
    update_asset,
)


router = APIRouter(tags=["assets"])


@router.get(
    "/projects/{project_id}/assets", response_model=list[AssetResponse]
)
async def read_assets(
    project_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[AssetResponse]:
    return await list_assets(session, project_id)


@router.post(
    "/projects/{project_id}/assets",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_asset_route(
    project_id: int,
    payload: AssetCreate,
    session: AsyncSession = Depends(get_session),
) -> AssetResponse:
    return await create_asset(session, project_id, payload)


@router.get("/assets/{asset_id}", response_model=AssetResponse)
async def read_asset(
    asset_id: int,
    session: AsyncSession = Depends(get_session),
) -> AssetResponse:
    return await get_asset(session, asset_id)


@router.patch("/assets/{asset_id}", response_model=AssetResponse)
async def update_asset_route(
    asset_id: int,
    payload: AssetPatch,
    session: AsyncSession = Depends(get_session),
) -> AssetResponse:
    return await update_asset(session, asset_id, payload)
