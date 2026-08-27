from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.episodes import EpisodeCreate, EpisodePatch, EpisodeResponse
from app.schemas.generation import (
    GenerateAssetsResponse,
    GenerateShotsImpactResponse,
)
from app.services.episodes import (
    create_episode,
    delete_episode,
    get_episode,
    list_episodes,
    update_episode,
)
from app.services.generate_assets import enqueue_generate_assets
from app.services.generate_shots import read_generate_shots_impact
from app.tasks.queue import TaskConflictError, TaskQueue


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


@router.post(
    "/episodes/{episode_id}/generate-assets",
    response_model=GenerateAssetsResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_assets_route(
    episode_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> GenerateAssetsResponse:
    body = await request.body()
    if body:
        raise HTTPException(
            status_code=422, detail="Generate-assets request body must be empty"
        )

    queue: TaskQueue = request.app.state.task_queue
    try:
        result = await enqueue_generate_assets(session, queue, episode_id)
    except TaskConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await queue.publish_committed(result)
    return GenerateAssetsResponse(task_id=result.task.id)


@router.post(
    "/episodes/{episode_id}/generate-shots/impact",
    response_model=GenerateShotsImpactResponse,
)
async def generate_shots_impact_route(
    episode_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> GenerateShotsImpactResponse:
    body = await request.body()
    if body:
        raise HTTPException(
            status_code=422,
            detail="Generate-shots impact request body must be empty",
        )
    return await read_generate_shots_impact(session, episode_id)


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
