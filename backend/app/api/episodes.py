from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.episodes import EpisodeCreate, EpisodePatch, EpisodeResponse
from app.services.episodes import (
    create_episode,
    delete_episode,
    get_episode,
    list_episodes,
    update_episode,
)


router = APIRouter(tags=["episodes"])


@router.get(
    "/projects/{project_id}/episodes", response_model=list[EpisodeResponse]
)
async def read_episodes(
    project_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[EpisodeResponse]:
    return await list_episodes(session, project_id)


@router.post(
    "/projects/{project_id}/episodes",
    response_model=EpisodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_episode_route(
    project_id: int,
    payload: EpisodeCreate,
    session: AsyncSession = Depends(get_session),
) -> EpisodeResponse:
    return await create_episode(session, project_id, payload)


@router.get("/episodes/{episode_id}", response_model=EpisodeResponse)
async def read_episode(
    episode_id: int,
    session: AsyncSession = Depends(get_session),
) -> EpisodeResponse:
    return await get_episode(session, episode_id)


@router.patch("/episodes/{episode_id}", response_model=EpisodeResponse)
async def update_episode_route(
    episode_id: int,
    payload: EpisodePatch,
    session: AsyncSession = Depends(get_session),
) -> EpisodeResponse:
    return await update_episode(session, episode_id, payload)


@router.delete("/episodes/{episode_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_episode_route(
    episode_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await delete_episode(session, episode_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
