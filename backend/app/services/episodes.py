from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Episode, Project
from app.schemas.episodes import EpisodeCreate, EpisodePatch


def _episode_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Episode not found")


def _project_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Project not found")


def _script_too_long() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail=(
            "script_text exceeds SCRIPT_CHAR_LIMIT "
            f"({settings.SCRIPT_CHAR_LIMIT})"
        ),
    )


def _validate_script_length(script_text: str) -> None:
    if len(script_text) > settings.SCRIPT_CHAR_LIMIT:
        raise _script_too_long()


async def list_episodes(
    session: AsyncSession, project_id: int
) -> list[Episode]:
    if await session.get(Project, project_id) is None:
        raise _project_not_found()
    result = await session.execute(
        select(Episode)
        .where(Episode.project_id == project_id)
        .order_by(Episode.seq, Episode.id)
    )
    return list(result.scalars().all())


async def create_episode(
    session: AsyncSession, project_id: int, payload: EpisodeCreate
) -> Episode:
    _validate_script_length(payload.script_text)
    try:
        async with session.begin():
            if await session.get(Project, project_id) is None:
                raise _project_not_found()
            episode = Episode(
                project_id=project_id,
                seq=payload.seq,
                title=payload.title,
                script_text=payload.script_text,
                script_revision=1,
            )
            session.add(episode)
            await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Episode sequence already exists"
        ) from exc
    return episode


async def get_episode(session: AsyncSession, episode_id: int) -> Episode:
    episode = await session.get(Episode, episode_id)
    if episode is None:
        raise _episode_not_found()
    return episode


async def _get_episode_for_update(
    session: AsyncSession, episode_id: int
) -> Episode:
    result = await session.execute(
        select(Episode)
        .where(Episode.id == episode_id)
        .with_for_update()
    )
    episode = result.scalar_one_or_none()
    if episode is None:
        raise _episode_not_found()
    return episode


async def update_episode(
    session: AsyncSession, episode_id: int, payload: EpisodePatch
) -> Episode:
    if "script_text" in payload.model_fields_set:
        _validate_script_length(payload.script_text)
    try:
        async with session.begin():
            episode = await _get_episode_for_update(session, episode_id)
            changed = False
            if "seq" in payload.model_fields_set and payload.seq != episode.seq:
                episode.seq = payload.seq
                changed = True
            if (
                "title" in payload.model_fields_set
                and payload.title != episode.title
            ):
                episode.title = payload.title
                changed = True
            if (
                "script_text" in payload.model_fields_set
                and payload.script_text != episode.script_text
            ):
                episode.script_text = payload.script_text
                episode.script_revision += 1
                changed = True
            if changed:
                episode.updated_at = datetime.now(timezone.utc)
            await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Episode sequence already exists"
        ) from exc
    return episode


async def delete_episode(session: AsyncSession, episode_id: int) -> None:
    try:
        async with session.begin():
            episode = await get_episode(session, episode_id)
            await session.delete(episode)
            await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="Episode cannot be deleted because it has dependent data",
        ) from exc
