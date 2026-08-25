from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.assets import (
    AssetCreate,
    CurrentImagePatch,
    AssetImageResponse,
    AssetPatch,
    AssetResponse,
)
from app.services.assets import (
    create_asset,
    get_asset,
    list_assets,
    list_asset_images,
    delete_asset_image,
    set_current_asset_image,
    upload_asset_image,
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


@router.get("/assets/{asset_id}/images", response_model=list[AssetImageResponse])
async def read_asset_images(
    asset_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[AssetImageResponse]:
    return await list_asset_images(session, asset_id)


@router.post(
    "/assets/{asset_id}/images",
    response_model=AssetImageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_asset_image(
    asset_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> AssetImageResponse:
    return await upload_asset_image(session, asset_id, file)


@router.put(
    "/assets/{asset_id}/current-image", response_model=AssetImageResponse
)
async def update_current_asset_image(
    asset_id: int,
    payload: CurrentImagePatch,
    session: AsyncSession = Depends(get_session),
) -> AssetImageResponse:
    return await set_current_asset_image(session, asset_id, payload.image_id)


@router.delete(
    "/asset-images/{image_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_asset_image_route(
    image_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await delete_asset_image(session, image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
