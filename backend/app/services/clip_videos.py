from __future__ import annotations

import copy
import sys
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Clip, ClipVideo, Episode
from app.schemas.clips import ClipVideoResponse
from app.services.asset_files import resolve_data_path, sha256_file
from app.services.video_files import clip_video_paths


def _clip_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Clip not found")


def _video_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Clip video not found")


def _video_cross_clip() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail="video_id does not reference a video of this clip",
    )


def _current_video_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail="Current clip video cannot be deleted directly",
    )


def _storage_error() -> HTTPException:
    return HTTPException(status_code=500, detail="Clip video file is unavailable")


def _media_storage_error() -> HTTPException:
    return HTTPException(
        status_code=500, detail="Clip video media is unavailable"
    )


def _clip_video_payload(
    video: ClipVideo, *, include_debug: bool
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": int(video.id),
        "clip_id": int(video.clip_id),
        "sha256": video.sha256,
        "seed": str(video.seed),
        "requested_duration": int(video.requested_duration),
        "actual_duration": video.actual_duration,
        "is_current": bool(video.is_current),
        "media_url": f"/media/clip-videos/{int(video.id)}",
        "created_at": video.created_at,
    }
    if include_debug:
        payload["built_prompt"] = video.built_prompt
        input_snapshot = copy.deepcopy(video.input_snapshot)
        if isinstance(input_snapshot, dict) and input_snapshot.get("seed") is not None:
            input_snapshot["seed"] = str(input_snapshot["seed"])
        payload["input_snapshot"] = input_snapshot
    return ClipVideoResponse.model_validate(payload).model_dump(mode="json")


async def list_clip_videos(
    session: AsyncSession,
    clip_id: int,
    *,
    include_debug: bool,
) -> list[dict[str, object]]:
    clip = await session.get(Clip, clip_id)
    if clip is None:
        raise _clip_not_found()

    result = await session.execute(
        select(ClipVideo).where(ClipVideo.clip_id == clip.id).order_by(ClipVideo.id)
    )
    return [
        _clip_video_payload(video, include_debug=include_debug)
        for video in result.scalars().all()
    ]


async def set_current_clip_video(
    session: AsyncSession,
    clip_id: int,
    video_id: int,
    *,
    include_debug: bool,
) -> dict[str, object]:
    async with session.begin():
        clip = await session.scalar(
            select(Clip).where(Clip.id == clip_id).with_for_update()
        )
        if clip is None:
            raise _clip_not_found()

        result = await session.execute(
            select(ClipVideo)
            .where(ClipVideo.clip_id == clip.id)
            .order_by(ClipVideo.id)
            .with_for_update()
        )
        videos = list(result.scalars().all())
        target = next((video for video in videos if video.id == video_id), None)
        if target is None:
            other = await session.scalar(
                select(ClipVideo).where(ClipVideo.id == video_id)
            )
            if other is None:
                raise _video_not_found()
            raise _video_cross_clip()

        if not target.is_current:
            await session.execute(
                update(ClipVideo)
                .where(
                    ClipVideo.clip_id == clip.id,
                    ClipVideo.is_current.is_(True),
                )
                .values(is_current=False)
            )
            target.is_current = True
            await session.flush()

    return _clip_video_payload(target, include_debug=include_debug)


def _validate_stored_video_path(
    video: ClipVideo,
    *,
    project_id: int,
    episode_id: int,
    clip_id: int,
    data_dir: Path,
) -> tuple[Path, Path, Path]:
    try:
        relative_path, formal_path, trash_path = clip_video_paths(
            data_dir, project_id, episode_id, clip_id, int(video.id)
        )
    except ValueError as exc:
        raise _storage_error() from exc
    try:
        stored_path = Path(video.file_path)
    except (TypeError, ValueError) as exc:
        raise _storage_error() from exc
    if stored_path.as_posix() != relative_path.as_posix():
        raise _storage_error()
    return relative_path, formal_path, trash_path


def _raise_delete_cleanup_errors(
    primary_error: BaseException | None,
    cleanup_errors: list[tuple[str, OSError]],
) -> None:
    if not cleanup_errors:
        return
    details = "; ".join(f"{label}: {error}" for label, error in cleanup_errors)
    if primary_error is not None:
        raise RuntimeError(f"{primary_error}; {details}") from primary_error
    raise RuntimeError(details)


async def delete_clip_video(session: AsyncSession, video_id: int) -> None:
    moved_media: tuple[Path, Path] | None = None
    transaction_committed = False
    try:
        async with session.begin():
            target = await session.scalar(
                select(ClipVideo).where(ClipVideo.id == video_id)
            )
            if target is None:
                raise _video_not_found()

            clip = await session.scalar(
                select(Clip).where(Clip.id == target.clip_id).with_for_update()
            )
            if clip is None:
                raise _storage_error()

            result = await session.execute(
                select(ClipVideo)
                .where(ClipVideo.clip_id == clip.id)
                .order_by(ClipVideo.id)
                .with_for_update()
            )
            videos = list(result.scalars().all())
            video = next((item for item in videos if item.id == video_id), None)
            if video is None:
                raise _video_not_found()
            if video.is_current:
                raise _current_video_conflict()

            episode = await session.scalar(
                select(Episode).where(Episode.id == clip.episode_id)
            )
            if episode is None:
                raise _storage_error()

            _, formal_path, trash_path = _validate_stored_video_path(
                video,
                project_id=int(episode.project_id),
                episode_id=int(episode.id),
                clip_id=int(clip.id),
                data_dir=settings.DATA_DIR,
            )
            if not formal_path.is_file():
                raise _storage_error()
            try:
                digest = sha256_file(formal_path)
            except OSError as exc:
                raise _storage_error() from exc
            if digest != video.sha256:
                raise _storage_error()

            trash_path.parent.mkdir(parents=True, exist_ok=True)
            formal_path.replace(trash_path)
            moved_media = (formal_path, trash_path)
            await session.delete(video)
            await session.flush()

        transaction_committed = True
    finally:
        primary_error = sys.exc_info()[1]
        cleanup_errors: list[tuple[str, OSError]] = []
        if not transaction_committed and moved_media is not None:
            source, trash = moved_media
            if source.exists():
                cleanup_errors.append(
                    ("clip video restore failed", FileExistsError(str(source)))
                )
            elif not trash.exists():
                cleanup_errors.append(
                    ("clip video restore failed", FileNotFoundError(str(trash)))
                )
            else:
                try:
                    trash.replace(source)
                except OSError as exc:
                    cleanup_errors.append(("clip video restore failed", exc))
        _raise_delete_cleanup_errors(primary_error, cleanup_errors)


async def get_clip_video_media(session: AsyncSession, video_id: int) -> Path:
    video = await session.scalar(
        select(ClipVideo).where(ClipVideo.id == video_id)
    )
    if video is None:
        raise _video_not_found()

    clip = await session.scalar(select(Clip).where(Clip.id == video.clip_id))
    if clip is None:
        raise _media_storage_error()
    episode = await session.scalar(select(Episode).where(Episode.id == clip.episode_id))
    if episode is None:
        raise _media_storage_error()

    try:
        relative_path, formal_path, _ = clip_video_paths(
            settings.DATA_DIR,
            int(episode.project_id),
            int(episode.id),
            int(clip.id),
            int(video.id),
        )
        stored_path = Path(video.file_path)
        if stored_path.as_posix() != relative_path.as_posix():
            raise ValueError("clip video path does not match its canonical path")
        resolve_data_path(settings.DATA_DIR, stored_path)
        if not formal_path.is_file():
            raise OSError("clip video media file is missing")
        with formal_path.open("rb"):
            pass
    except (OSError, TypeError, ValueError) as exc:
        raise _media_storage_error() from exc
    return formal_path
