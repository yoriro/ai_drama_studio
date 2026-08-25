from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, Project
from app.schemas.assets import AssetCreate, AssetPatch


_VISIBLE_ASSET_TYPES = ("character", "scene")


def _asset_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Asset not found")


def _project_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Project not found")


def _is_visible_asset(asset: Asset) -> bool:
    return asset.type in _VISIBLE_ASSET_TYPES


async def list_assets(session: AsyncSession, project_id: int) -> list[Asset]:
    if await session.get(Project, project_id) is None:
        raise _project_not_found()
    result = await session.execute(
        select(Asset)
        .where(
            Asset.project_id == project_id,
            Asset.type.in_(_VISIBLE_ASSET_TYPES),
        )
        .order_by(Asset.id)
    )
    return list(result.scalars().all())


async def create_asset(
    session: AsyncSession, project_id: int, payload: AssetCreate
) -> Asset:
    async with session.begin():
        if await session.get(Project, project_id) is None:
            raise _project_not_found()
        asset = Asset(
            project_id=project_id,
            type=payload.type,
            name=payload.name,
            description=payload.description,
            source="manual",
            revision=1,
        )
        session.add(asset)
        await session.flush()
    return asset


async def get_asset(session: AsyncSession, asset_id: int) -> Asset:
    asset = await session.get(Asset, asset_id)
    if asset is None or not _is_visible_asset(asset):
        raise _asset_not_found()
    return asset


async def update_asset(
    session: AsyncSession, asset_id: int, payload: AssetPatch
) -> Asset:
    async with session.begin():
        result = await session.execute(
            select(Asset).where(Asset.id == asset_id).with_for_update()
        )
        asset = result.scalar_one_or_none()
        if asset is None or not _is_visible_asset(asset):
            raise _asset_not_found()

        changed = False
        if "name" in payload.model_fields_set and payload.name != asset.name:
            asset.name = payload.name
            changed = True
        if (
            "description" in payload.model_fields_set
            and payload.description != asset.description
        ):
            asset.description = payload.description
            changed = True
        if changed:
            asset.revision += 1
            asset.updated_at = datetime.now(timezone.utc)
        await session.flush()
    return asset
