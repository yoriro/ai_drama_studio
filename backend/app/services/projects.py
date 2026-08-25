from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Episode, Project, Style
from app.schemas.projects import ProjectCreate, ProjectPatch


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
            await session.execute(
                delete(Episode).where(Episode.project_id == project_id)
            )
            await session.delete(project)
            await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="Project cannot be deleted because it has dependent data",
        ) from exc
