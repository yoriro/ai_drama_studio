from fastapi import HTTPException
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Asset, AssetImage, Episode, Project, Style
from app.schemas.projects import ProjectCreate, ProjectPatch
from app.services.asset_files import (
    asset_image_relative_path,
    move_asset_image_to_trash,
    resolve_data_path,
)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Project not found")


def _invalid_style() -> HTTPException:
    return HTTPException(
        status_code=422, detail="style_id does not reference an existing style"
    )


def _style_conflict() -> HTTPException:
    return HTTPException(
        status_code=409, detail="Project style reference conflict"
    )


async def _require_style(session: AsyncSession, style_id: int) -> None:
    if await session.get(Style, style_id) is None:
        raise _invalid_style()


async def list_projects(session: AsyncSession) -> list[Project]:
    result = await session.execute(select(Project).order_by(Project.id))
    return list(result.scalars().all())


async def get_project(session: AsyncSession, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise _not_found()
    return project


async def create_project(
    session: AsyncSession, payload: ProjectCreate
) -> Project:
    try:
        async with session.begin():
            await _require_style(session, payload.style_id)
            project = Project(name=payload.name, style_id=payload.style_id)
            session.add(project)
            await session.flush()
    except IntegrityError as exc:
        raise _style_conflict() from exc
    return project


async def update_project(
    session: AsyncSession, project_id: int, payload: ProjectPatch
) -> Project:
    try:
        async with session.begin():
            project = await get_project(session, project_id)
            if "style_id" in payload.model_fields_set:
                await _require_style(session, payload.style_id)
            if "name" in payload.model_fields_set and payload.name != project.name:
                project.name = payload.name
            if (
                "style_id" in payload.model_fields_set
                and payload.style_id != project.style_id
            ):
                project.style_id = payload.style_id
            await session.flush()
    except IntegrityError as exc:
        raise _style_conflict() from exc
    return project


async def delete_project(session: AsyncSession, project_id: int) -> None:
    try:
        async with session.begin():
            project = await get_project(session, project_id)

            asset_result = await session.execute(
                select(Asset)
                .where(Asset.project_id == project_id)
                .order_by(Asset.id)
                .with_for_update()
            )
            assets = list(asset_result.scalars().all())
            asset_by_id = {asset.id: asset for asset in assets}
            asset_ids = list(asset_by_id)
            image_result = await session.execute(
                select(AssetImage)
                .where(AssetImage.asset_id.in_(asset_ids))
                .order_by(AssetImage.id)
                .with_for_update()
            ) if asset_ids else None
            images = list(image_result.scalars().all()) if image_result else []
            image_moves: list[tuple[int, int, int, str]] = []
            for image in images:
                asset = asset_by_id[image.asset_id]
                relative_path = Path(image.file_path)
                extension = relative_path.suffix.removeprefix(".").lower()
                expected_path = asset_image_relative_path(
                    asset.project_id, asset.id, image.id, extension
                )
                if relative_path.as_posix() != expected_path.as_posix():
                    raise HTTPException(
                        status_code=500,
                        detail="Asset image file is unavailable",
                    )
                resolve_data_path(settings.DATA_DIR, relative_path)
                image_moves.append((asset.project_id, asset.id, image.id, extension))

            image_ids = [image.id for image in images]
            if image_ids:
                await session.execute(
                    delete(AssetImage).where(AssetImage.id.in_(image_ids))
                )
            if asset_ids:
                await session.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
            await session.execute(
                delete(Episode).where(Episode.project_id == project_id)
            )
            await session.delete(project)
            await session.flush()
            for project_id_for_file, asset_id, image_id, extension in image_moves:
                move_asset_image_to_trash(
                    settings.DATA_DIR,
                    project_id_for_file,
                    asset_id,
                    image_id,
                    extension,
                )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="Project cannot be deleted because it has dependent data",
        ) from exc
