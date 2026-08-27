from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Clip, ClipRefSlot, ClipVideo, Episode
from app.schemas.generation import GenerateShotsImpactResponse


IMPACT_TOKEN_TTL_SECONDS = 600


@dataclass(frozen=True, slots=True)
class GenerateShotsImpactSnapshot:
    episode_id: int
    clip_revisions: tuple[tuple[int, int], ...]
    clip_video_ids: tuple[int, ...]
    clip_override_media: tuple[tuple[int, int, str], ...]


@dataclass(frozen=True, slots=True)
class _ImpactToken:
    episode_id: int
    snapshot: GenerateShotsImpactSnapshot
    expires_at: float


_impact_tokens: dict[str, _ImpactToken] = {}


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Episode not found")


def _token_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=(
            "Generate-shots confirmation token is missing, expired, "
            "invalid, or no longer matches the current impact"
        ),
    )


async def read_generate_shots_impact(
    session: AsyncSession, episode_id: int
) -> GenerateShotsImpactResponse:
    snapshot = await _read_impact_snapshot(session, episode_id)
    clips_count = len(snapshot.clip_revisions)
    videos_count = len(snapshot.clip_video_ids)
    if clips_count == 0:
        return GenerateShotsImpactResponse(
            clips_count=0,
            videos_count=0,
            confirm_token=None,
            expires_in=None,
        )

    token = secrets.token_urlsafe(32)
    _prune_expired_tokens(time.monotonic())
    _impact_tokens[token] = _ImpactToken(
        episode_id=episode_id,
        snapshot=snapshot,
        expires_at=time.monotonic() + IMPACT_TOKEN_TTL_SECONDS,
    )
    return GenerateShotsImpactResponse(
        clips_count=clips_count,
        videos_count=videos_count,
        confirm_token=token,
        expires_in=IMPACT_TOKEN_TTL_SECONDS,
    )


async def require_generate_shots_impact_token(
    session: AsyncSession,
    episode_id: int,
    token: str | None,
) -> GenerateShotsImpactSnapshot:
    if token is None:
        raise _token_conflict()

    now = time.monotonic()
    record = _impact_tokens.get(token)
    if record is None or record.expires_at <= now:
        if record is not None:
            _impact_tokens.pop(token, None)
        raise _token_conflict()
    if record.episode_id != episode_id:
        raise _token_conflict()

    current = await _read_impact_snapshot(session, episode_id)
    if current != record.snapshot:
        raise _token_conflict()
    return record.snapshot


async def _read_impact_snapshot(
    session: AsyncSession, episode_id: int
) -> GenerateShotsImpactSnapshot:
    episode = await session.get(Episode, episode_id)
    if episode is None:
        raise _not_found()

    clip_result = await session.execute(
        select(Clip.id, Clip.revision)
        .where(Clip.episode_id == episode_id)
        .order_by(Clip.id)
    )
    clip_rows = clip_result.all()
    clip_revisions = tuple((int(row.id), int(row.revision)) for row in clip_rows)
    clip_ids = tuple(row[0] for row in clip_rows)

    if not clip_ids:
        return GenerateShotsImpactSnapshot(
            episode_id=episode_id,
            clip_revisions=(),
            clip_video_ids=(),
            clip_override_media=(),
        )

    video_result = await session.execute(
        select(ClipVideo.id)
        .where(ClipVideo.clip_id.in_(clip_ids))
        .order_by(ClipVideo.id)
    )
    clip_video_ids = tuple(int(row.id) for row in video_result.all())

    override_result = await session.execute(
        select(ClipRefSlot.id, ClipRefSlot.clip_id, ClipRefSlot.override_image_path)
        .where(
            ClipRefSlot.clip_id.in_(clip_ids),
            ClipRefSlot.override_image_path.is_not(None),
        )
        .order_by(ClipRefSlot.id)
    )
    clip_override_media = tuple(
        (int(row.id), int(row.clip_id), str(row.override_image_path))
        for row in override_result.all()
    )
    return GenerateShotsImpactSnapshot(
        episode_id=episode_id,
        clip_revisions=clip_revisions,
        clip_video_ids=clip_video_ids,
        clip_override_media=clip_override_media,
    )


def _prune_expired_tokens(now: float) -> None:
    expired = [
        token
        for token, record in _impact_tokens.items()
        if record.expires_at <= now
    ]
    for token in expired:
        _impact_tokens.pop(token, None)
