from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.shots import ShotPatch, ShotResponse
from app.services.shots import list_shots, update_shot


router = APIRouter(tags=["shots"])


@router.get(
    "/episodes/{episode_id}/shots", response_model=list[ShotResponse]
)
async def read_shots(
    episode_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[ShotResponse]:
    return await list_shots(session, episode_id)


@router.patch("/shots/{shot_id}", response_model=ShotResponse)
async def update_shot_route(
    shot_id: int,
    payload: ShotPatch,
    session: AsyncSession = Depends(get_session),
) -> ShotResponse:
    return await update_shot(session, shot_id, payload)
