from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, Clip, ClipShot, Episode, Shot, ShotAsset
from app.schemas.shots import ShotPatch


_VISIBLE_ASSET_TYPES = ("character", "scene")


def _episode_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Episode not found")


def _shot_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Shot not found")


def _asset_validation_error() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail="asset_ids must reference character or scene assets in the shot project",
    )


async def _shot_response(
    session: AsyncSession, shot: Shot
) -> dict[str, Any]:
    asset_result = await session.execute(
        select(ShotAsset.asset_id)
        .where(ShotAsset.shot_id == shot.id)
        .order_by(ShotAsset.asset_id)
    )
    return {
        "id": shot.id,
        "episode_id": shot.episode_id,
        "order_index": shot.order_index,
        "duration_est": shot.duration_est,
        "shot_type": shot.shot_type,
        "camera": shot.camera,
        "description": shot.description,
        "dialogue": shot.dialogue,
        "asset_ids": [row[0] for row in asset_result.all()],
        "status": shot.status,
        "revision": shot.revision,
        "created_at": shot.created_at,
        "updated_at": shot.updated_at,
    }


async def list_shots(
    session: AsyncSession, episode_id: int
) -> list[dict[str, Any]]:
    if await session.get(Episode, episode_id) is None:
        raise _episode_not_found()
    result = await session.execute(
        select(Shot)
        .where(Shot.episode_id == episode_id)
        .order_by(Shot.order_index, Shot.id)
    )
    shots = list(result.scalars().all())
    return [await _shot_response(session, shot) for shot in shots]


async def update_shot(
    session: AsyncSession, shot_id: int, payload: ShotPatch
) -> dict[str, Any]:
    async with session.begin():
        identity_result = await session.execute(
            select(Shot.id, Shot.episode_id).where(Shot.id == shot_id)
        )
        identity = identity_result.one_or_none()
        if identity is None:
            raise _shot_not_found()

        current_asset_result = await session.execute(
            select(ShotAsset.asset_id)
            .where(ShotAsset.shot_id == shot_id)
            .order_by(ShotAsset.asset_id)
        )
        current_asset_ids = {
            int(row[0]) for row in current_asset_result.all()
        }
        requested_asset_ids = payload.asset_ids
        candidate_asset_ids = current_asset_ids | (
            set(requested_asset_ids) if requested_asset_ids is not None else set()
        )

        episode_result = await session.execute(
            select(Episode).where(Episode.id == identity.episode_id).with_for_update()
        )
        episode = episode_result.scalar_one_or_none()
        if episode is None:
            raise _shot_not_found()

        assets: list[Asset] = []
        if candidate_asset_ids:
            asset_result = await session.execute(
                select(Asset)
                .where(
                    Asset.id.in_(sorted(candidate_asset_ids)),
                    Asset.project_id == episode.project_id,
                    Asset.type.in_(_VISIBLE_ASSET_TYPES),
                )
                .order_by(Asset.id)
                .with_for_update()
            )
            assets = list(asset_result.scalars().all())
            if requested_asset_ids is not None and len(assets) != len(
                candidate_asset_ids
            ):
                raise _asset_validation_error()
            if requested_asset_ids is None and len(assets) != len(
                current_asset_ids
            ):
                raise _asset_validation_error()

        result = await session.execute(
            select(Shot).where(Shot.id == shot_id).with_for_update()
        )
        shot = result.scalar_one_or_none()
        if shot is None:
            raise _shot_not_found()

        clip_result = await session.execute(
            select(ClipShot.clip_id)
            .where(ClipShot.shot_id == shot.id)
            .order_by(ClipShot.clip_id)
        )
        clip_ids = sorted({int(row[0]) for row in clip_result.all()})
        if clip_ids:
            await session.execute(
                select(Clip)
                .where(Clip.id.in_(clip_ids))
                .order_by(Clip.id)
                .with_for_update()
            )

        locked_asset_result = await session.execute(
            select(ShotAsset.asset_id)
            .where(ShotAsset.shot_id == shot.id)
            .order_by(ShotAsset.asset_id)
        )
        locked_current_asset_ids = {
            int(row[0]) for row in locked_asset_result.all()
        }
        if requested_asset_ids is not None and locked_current_asset_ids != set(
            requested_asset_ids
        ):
            current_asset_ids = locked_current_asset_ids

        changed = False
        for field in ("shot_type", "camera", "description", "dialogue"):
            if field in payload.model_fields_set:
                value = getattr(payload, field)
                if value != getattr(shot, field):
                    setattr(shot, field, value)
                    changed = True

        if requested_asset_ids is not None:
            if current_asset_ids != set(requested_asset_ids):
                await session.execute(
                    delete(ShotAsset).where(ShotAsset.shot_id == shot.id)
                )
                for asset_id in requested_asset_ids:
                    session.add(ShotAsset(shot_id=shot.id, asset_id=asset_id))
                changed = True

        if changed:
            shot.revision += 1
            shot.status = "changed"
            shot.updated_at = datetime.now(timezone.utc)
            if clip_ids:
                await session.execute(
                    update(Clip)
                    .where(Clip.id.in_(clip_ids))
                    .values(freshness="stale")
                )

        await session.flush()
        return await _shot_response(session, shot)
