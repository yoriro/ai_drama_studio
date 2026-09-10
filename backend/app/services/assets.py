from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    Asset,
    AssetImage,
    Clip,
    ClipRefSlot,
    ClipShot,
    Episode,
    Project,
    Shot,
    ShotAsset,
)
from app.schemas.assets import AssetCreate, AssetPatch
from app.services.asset_files import (
    asset_image_path,
    asset_image_relative_path,
    image_storage_format,
    move_asset_image_to_trash,
    resolve_data_path,
    sha256_file,
    temporary_asset_image_path,
)
from app.tasks.queue import _constraint_name


_VISIBLE_ASSET_TYPES = ("character", "scene")
_ASSET_NAME_CONSTRAINT = "uq_assets_project_name"


def _asset_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Asset not found")


def _project_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Project not found")


def _asset_name_conflict() -> HTTPException:
    return HTTPException(status_code=409, detail="资产名称已存在")


def _is_visible_asset(asset: Asset) -> bool:
    return asset.type in _VISIBLE_ASSET_TYPES


async def _mark_asset_dependents_changed(
    session: AsyncSession,
    asset_id: int,
    *,
    shot_ids: list[int] | None = None,
    clip_ids: set[int] | None = None,
) -> None:
    if shot_ids is None:
        shot_result = await session.execute(
            select(ShotAsset.shot_id).where(ShotAsset.asset_id == asset_id)
        )
        shot_ids = sorted({int(row[0]) for row in shot_result.all()})
    if clip_ids is None:
        slot_result = await session.execute(
            select(ClipRefSlot.clip_id)
            .where(ClipRefSlot.asset_id == asset_id)
            .order_by(ClipRefSlot.clip_id, ClipRefSlot.slot_no, ClipRefSlot.id)
        )
        clip_ids = {int(row[0]) for row in slot_result.all()}
        if shot_ids:
            clip_result = await session.execute(
                select(ClipShot.clip_id)
                .where(ClipShot.shot_id.in_(shot_ids))
                .distinct()
            )
            clip_ids.update(int(row[0]) for row in clip_result.all())
    if shot_ids:
        await session.execute(
            update(Shot)
            .where(Shot.id.in_(sorted(shot_ids)))
            .values(status="changed", revision=Shot.revision + 1)
        )
    if clip_ids:
        await session.execute(
            update(Clip)
            .where(Clip.id.in_(sorted(clip_ids)))
            .values(freshness="stale")
        )


async def _lock_asset_source_dependencies(
    session: AsyncSession, asset_id: int
) -> tuple[Asset, list[int], set[int]]:
    identity_result = await session.execute(
        select(Asset.id, Asset.type).where(Asset.id == asset_id)
    )
    identity = identity_result.one_or_none()
    if identity is None or identity.type not in _VISIBLE_ASSET_TYPES:
        raise _asset_not_found()

    episode_result = await session.execute(
        select(Episode.id)
        .join(Shot, Shot.episode_id == Episode.id)
        .join(ShotAsset, ShotAsset.shot_id == Shot.id)
        .where(ShotAsset.asset_id == asset_id)
        .union(
            select(Episode.id)
            .join(Clip, Clip.episode_id == Episode.id)
            .join(ClipRefSlot, ClipRefSlot.clip_id == Clip.id)
            .where(ClipRefSlot.asset_id == asset_id)
        )
    )
    episode_ids = sorted({int(row[0]) for row in episode_result.all()})
    if episode_ids:
        await session.execute(
            select(Episode)
            .where(Episode.id.in_(episode_ids))
            .order_by(Episode.id)
            .with_for_update()
        )

    asset_result = await session.execute(
        select(Asset).where(Asset.id == asset_id).with_for_update()
    )
    asset = asset_result.scalar_one_or_none()
    if asset is None or not _is_visible_asset(asset):
        raise _asset_not_found()

    shot_result = await session.execute(
        select(Shot.id)
        .join(ShotAsset, ShotAsset.shot_id == Shot.id)
        .where(ShotAsset.asset_id == asset_id)
        .order_by(Shot.id)
    )
    shot_ids = sorted({int(row[0]) for row in shot_result.all()})
    if shot_ids:
        await session.execute(
            select(Shot)
            .where(Shot.id.in_(shot_ids))
            .order_by(Shot.id)
            .with_for_update()
        )

    slot_clip_result = await session.execute(
        select(ClipRefSlot.clip_id)
        .where(ClipRefSlot.asset_id == asset_id)
        .order_by(ClipRefSlot.clip_id, ClipRefSlot.slot_no, ClipRefSlot.id)
    )
    clip_ids = {int(row[0]) for row in slot_clip_result.all()}
    if shot_ids:
        clip_result = await session.execute(
            select(ClipShot.clip_id)
            .where(ClipShot.shot_id.in_(shot_ids))
            .distinct()
        )
        clip_ids.update(int(row[0]) for row in clip_result.all())
    if clip_ids:
        await session.execute(
            select(Clip)
            .where(Clip.id.in_(sorted(clip_ids)))
            .order_by(Clip.id)
            .with_for_update()
        )

    return asset, shot_ids, clip_ids


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
    try:
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
    except IntegrityError as exc:
        if _constraint_name(exc) != _ASSET_NAME_CONSTRAINT:
            raise
        raise _asset_name_conflict() from exc
    return asset


async def get_asset(session: AsyncSession, asset_id: int) -> Asset:
    asset = await session.get(Asset, asset_id)
    if asset is None or not _is_visible_asset(asset):
        raise _asset_not_found()
    return asset


async def update_asset(
    session: AsyncSession, asset_id: int, payload: AssetPatch
) -> Asset:
    try:
        async with session.begin():
            asset, shot_ids, clip_ids = await _lock_asset_source_dependencies(
                session, asset_id
            )

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
                await _mark_asset_dependents_changed(
                    session,
                    asset.id,
                    shot_ids=shot_ids,
                    clip_ids=clip_ids,
                )
            await session.flush()
    except IntegrityError as exc:
        if _constraint_name(exc) != _ASSET_NAME_CONSTRAINT:
            raise
        raise _asset_name_conflict() from exc
    return asset


async def list_asset_images(
    session: AsyncSession, asset_id: int
) -> list[AssetImage]:
    await get_asset(session, asset_id)
    result = await session.execute(
        select(AssetImage)
        .where(AssetImage.asset_id == asset_id)
        .order_by(AssetImage.id)
    )
    return list(result.scalars().all())


def _invalid_upload(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _validate_decoded_image(path: Path, declared_mime: str) -> tuple[str, str]:
    try:
        with Image.open(path) as image:
            detected_format = image.format
            image.verify()
        with Image.open(path) as image:
            image.load()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise _invalid_upload("file is not a complete PNG, JPEG, or WebP image") from exc

    if not isinstance(detected_format, str):
        raise _invalid_upload("file is not a complete PNG, JPEG, or WebP image")
    try:
        storage_format = image_storage_format(detected_format)
    except ValueError as exc:
        raise _invalid_upload("file format is not PNG, JPEG, or WebP") from exc
    if storage_format.mime_type != declared_mime:
        raise _invalid_upload("declared MIME type does not match the image format")
    return storage_format.extension, storage_format.mime_type


async def upload_asset_image(
    session: AsyncSession, asset_id: int, upload: UploadFile
) -> AssetImage:
    temp_path: Path | None = None
    formal_path: Path | None = None
    project_id_for_file: int | None = None
    stored_image_id: int | None = None
    extension_for_file: str | None = None
    transaction_committed = False
    try:
        async with session.begin():
            result = await session.execute(
                select(Asset).where(Asset.id == asset_id).with_for_update()
            )
            asset = result.scalar_one_or_none()
            if asset is None or not _is_visible_asset(asset):
                raise _asset_not_found()
            project_id_for_file = asset.project_id

            declared_mime = upload.content_type
            if declared_mime not in {"image/png", "image/jpeg", "image/webp"}:
                raise _invalid_upload(
                    "MIME type must be image/png, image/jpeg, or image/webp"
                )

            temp_path = temporary_asset_image_path(settings.DATA_DIR)
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            bytes_written = 0
            with temp_path.open("wb") as file_handle:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    bytes_written += len(chunk)
                    if bytes_written > settings.UPLOAD_MAX_MB * 1024 * 1024:
                        raise _invalid_upload(
                            f"file exceeds UPLOAD_MAX_MB ({settings.UPLOAD_MAX_MB})"
                        )
                    file_handle.write(chunk)

            extension, _ = _validate_decoded_image(temp_path, declared_mime)
            digest = sha256_file(temp_path)

            current_result = await session.execute(
                select(AssetImage.id)
                .where(
                    AssetImage.asset_id == asset_id,
                    AssetImage.is_current.is_(True),
                )
                .limit(1)
            )
            has_current = current_result.scalar_one_or_none() is not None
            is_current = not has_current

            image = AssetImage(
                asset_id=asset.id,
                file_path="pending",
                sha256=digest,
                seed=None,
                source="uploaded",
                is_current=is_current,
            )
            session.add(image)
            await session.flush()
            stored_image_id = image.id
            extension_for_file = extension

            relative_path = asset_image_relative_path(
                asset.project_id, asset.id, image.id, extension
            )
            formal_path = asset_image_path(
                settings.DATA_DIR,
                asset.project_id,
                asset.id,
                image.id,
                extension,
            )
            image.file_path = relative_path.as_posix()
            formal_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.replace(formal_path)

            if is_current:
                asset.revision += 1
                asset.updated_at = datetime.now(timezone.utc)
            await session.flush()

        transaction_committed = True
        return image
    finally:
        if formal_path is not None and not transaction_committed and formal_path.exists():
            if (
                project_id_for_file is None
                or stored_image_id is None
                or extension_for_file is None
            ):
                raise RuntimeError("asset image storage state is incomplete")
            move_asset_image_to_trash(
                settings.DATA_DIR,
                project_id_for_file,
                asset_id,
                stored_image_id,
                extension_for_file,
            )
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _image_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Asset image not found")


def _image_validation_error() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail="image_id does not reference an image of this asset",
    )


def _current_image_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail="Current asset image cannot be deleted directly",
    )


def _stored_image_extension(asset: Asset, image: AssetImage) -> str:
    relative_path = Path(image.file_path)
    expected_path = asset_image_relative_path(
        asset.project_id,
        asset.id,
        image.id,
        relative_path.suffix.removeprefix(".").lower(),
    )
    if relative_path.as_posix() != expected_path.as_posix():
        raise HTTPException(status_code=500, detail="Asset image file is unavailable")
    extension = relative_path.suffix.removeprefix(".").lower()
    resolve_data_path(settings.DATA_DIR, relative_path)
    return extension


async def set_current_asset_image(
    session: AsyncSession, asset_id: int, image_id: int
) -> AssetImage:
    async with session.begin():
        asset, shot_ids, clip_ids = await _lock_asset_source_dependencies(
            session, asset_id
        )

        image = await session.get(AssetImage, image_id)
        if image is None:
            raise _image_validation_error()
        if image.asset_id != asset_id:
            raise _image_validation_error()
        if not image.is_current:
            await session.execute(
                AssetImage.__table__.update()
                .where(
                    AssetImage.asset_id == asset_id,
                    AssetImage.is_current.is_(True),
                )
                .values(is_current=False)
            )
            await session.flush()
            image.is_current = True
            asset.revision += 1
            asset.updated_at = datetime.now(timezone.utc)
            await _mark_asset_dependents_changed(
                session,
                asset.id,
                shot_ids=shot_ids,
                clip_ids=clip_ids,
            )
            await session.flush()
    return image


async def delete_asset_image(session: AsyncSession, image_id: int) -> None:
    async with session.begin():
        image = await session.get(AssetImage, image_id)
        if image is None:
            raise _image_not_found()

        asset_result = await session.execute(
            select(Asset).where(Asset.id == image.asset_id).with_for_update()
        )
        asset = asset_result.scalar_one_or_none()
        if asset is None or not _is_visible_asset(asset):
            raise _image_not_found()
        if image.is_current:
            raise _current_image_conflict()

        extension = _stored_image_extension(asset, image)
        move_asset_image_to_trash(
            settings.DATA_DIR,
            asset.project_id,
            asset.id,
            image.id,
            extension,
        )
        await session.delete(image)
        await session.flush()


async def delete_asset(session: AsyncSession, asset_id: int) -> None:
    try:
        async with session.begin():
            asset, shot_ids, clip_ids = await _lock_asset_source_dependencies(
                session, asset_id
            )

            await _mark_asset_dependents_changed(
                session,
                asset.id,
                shot_ids=shot_ids,
                clip_ids=clip_ids,
            )

            image_result = await session.execute(
                select(AssetImage)
                .where(AssetImage.asset_id == asset_id)
                .order_by(AssetImage.id)
                .with_for_update()
            )
            images = list(image_result.scalars().all())
            for image in images:
                extension = _stored_image_extension(asset, image)
                move_asset_image_to_trash(
                    settings.DATA_DIR,
                    asset.project_id,
                    asset.id,
                    image.id,
                    extension,
                )

            await session.execute(
                delete(AssetImage).where(AssetImage.asset_id == asset_id)
            )
            await session.execute(
                delete(ShotAsset).where(ShotAsset.asset_id == asset_id)
            )
            await session.delete(asset)
            await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="Asset cannot be deleted because it has dependent data",
        ) from exc
