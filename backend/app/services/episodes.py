from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    Clip,
    ClipRefSlot,
    ClipShot,
    ClipVideo,
    Episode,
    Project,
    Shot,
    ShotAsset,
)
from app.schemas.episodes import EpisodeCreate, EpisodePatch
from app.services.asset_files import resolve_data_path


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


def _episode_media_moves(
    relative_paths: list[str],
) -> list[tuple[Path, Path]]:
    trash_root = (settings.DATA_DIR / "trash").resolve()
    moves: list[tuple[Path, Path]] = []
    for relative_path in relative_paths:
        relative = Path(relative_path)
        source = resolve_data_path(settings.DATA_DIR, relative)
        destination = (trash_root / relative).resolve()
        try:
            destination.relative_to(trash_root)
        except ValueError as exc:
            raise HTTPException(
                status_code=500, detail="Clip media file is unavailable"
            ) from exc
        moves.append((source, destination))
    return moves


def move_episode_media_to_trash(
    media_moves: list[tuple[Path, Path]],
) -> None:
    for source, destination in media_moves:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)


async def delete_episode_cascade_data(
    session: AsyncSession, episode_id: int
) -> list[tuple[Path, Path]]:
    shot_result = await session.execute(
        select(Shot.id)
        .where(Shot.episode_id == episode_id)
        .order_by(Shot.id)
        .with_for_update()
    )
    shot_ids = [int(shot_id) for shot_id in shot_result.scalars().all()]

    clip_result = await session.execute(
        select(Clip.id)
        .where(Clip.episode_id == episode_id)
        .order_by(Clip.id)
        .with_for_update()
    )
    clip_ids = [int(clip_id) for clip_id in clip_result.scalars().all()]

    relative_paths: list[str] = []
    if clip_ids:
        video_result = await session.execute(
            select(ClipVideo.file_path)
            .where(ClipVideo.clip_id.in_(clip_ids))
            .order_by(ClipVideo.id)
            .with_for_update()
        )
        relative_paths.extend(str(path) for path in video_result.scalars().all())

        override_result = await session.execute(
            select(ClipRefSlot.override_image_path)
            .where(
                ClipRefSlot.clip_id.in_(clip_ids),
                ClipRefSlot.override_image_path.is_not(None),
            )
            .order_by(ClipRefSlot.id)
            .with_for_update()
        )
        relative_paths.extend(
            str(path) for path in override_result.scalars().all()
        )

        await session.execute(
            delete(ClipShot).where(ClipShot.clip_id.in_(clip_ids))
        )
        await session.execute(
            delete(ClipRefSlot).where(ClipRefSlot.clip_id.in_(clip_ids))
        )
        await session.execute(
            delete(ClipVideo).where(ClipVideo.clip_id.in_(clip_ids))
        )
        await session.execute(delete(Clip).where(Clip.id.in_(clip_ids)))

    if shot_ids:
        await session.execute(
            delete(ShotAsset).where(ShotAsset.shot_id.in_(shot_ids))
        )
        await session.execute(delete(Shot).where(Shot.id.in_(shot_ids)))

    return _episode_media_moves(relative_paths)


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
            episode = await _get_episode_for_update(session, episode_id)
            media_moves = await delete_episode_cascade_data(session, episode.id)
            await session.delete(episode)
            await session.flush()
            move_episode_media_to_trash(media_moves)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="Episode cannot be deleted because it has dependent data",
        ) from exc
