from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.projects import ProjectCreate, ProjectPatch, ProjectResponse
from app.services.projects import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    update_project,
)


router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
async def read_projects(
    session: AsyncSession = Depends(get_session),
) -> list[ProjectResponse]:
    return await list_projects(session)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project_route(
    payload: ProjectCreate,
    session: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    return await create_project(session, payload)


@router.get("/{project_id}", response_model=ProjectResponse)
async def read_project(
    project_id: int,
    session: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    return await get_project(session, project_id)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project_route(
    project_id: int,
    payload: ProjectPatch,
    session: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    return await update_project(session, project_id, payload)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_route(
    project_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await delete_project(session, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
