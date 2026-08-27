from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
import json
import re
from collections.abc import Mapping

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    Asset,
    Clip,
    ClipRefSlot,
    ClipVideo,
    Episode,
    Project,
    PromptTemplate,
    Shot,
    Style,
)
from app.schemas.generation import (
    GenerateShotsImpactResponse,
)
from app.tasks.queue import EnqueueResult, TaskQueue


IMPACT_TOKEN_TTL_SECONDS = 600
_TEMPLATE_KEY = "script2shots"
_PLACEHOLDER_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")
_REQUIRED_PLACEHOLDERS = frozenset({"assets", "style", "script"})
_SHOT_TYPES = ("远景", "全景", "中景", "近景", "特写")
_CAMERAS = ("固定", "推", "拉", "摇", "移", "跟", "手持")


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


def render_generate_shots_prompt(
    template_content: str,
    *,
    assets: list[dict[str, object]],
    style: str,
    script: str,
) -> str:
    values: Mapping[str, str] = {
        "assets": json.dumps(assets, ensure_ascii=False, separators=(",", ":")),
        "style": style,
        "script": script,
    }
    matches = list(_PLACEHOLDER_PATTERN.finditer(template_content))
    names = [match.group(1) for match in matches]
    if set(names) != _REQUIRED_PLACEHOLDERS:
        raise _conflict(
            "script2shots 模板必须包含且只能使用 "
            "{{assets}}、{{style}}、{{script}} 占位符"
        )
    return _PLACEHOLDER_PATTERN.sub(
        lambda match: values[match.group(1)], template_content
    )


def build_generate_shots_response_format(
    asset_ids: list[int],
) -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": _TEMPLATE_KEY,
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "shots": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "order": {"type": "integer"},
                                "duration_est": {
                                    "type": "number",
                                    "minimum": 1,
                                    "maximum": 5,
                                },
                                "shot_type": {
                                    "type": "string",
                                    "enum": list(_SHOT_TYPES),
                                },
                                "camera": {
                                    "type": "string",
                                    "enum": list(_CAMERAS),
                                },
                                "description": {"type": "string"},
                                "dialogue": {"type": "string"},
                                "asset_ids": {
                                    "type": "array",
                                    "items": {
                                        "type": "integer",
                                        "enum": asset_ids,
                                    },
                                },
                            },
                            "required": [
                                "order",
                                "duration_est",
                                "shot_type",
                                "camera",
                                "description",
                                "dialogue",
                                "asset_ids",
                            ],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["shots"],
                "additionalProperties": False,
            },
        },
    }


async def enqueue_generate_shots(
    session: AsyncSession,
    queue: TaskQueue,
    episode_id: int,
    confirm_token: str | None,
) -> EnqueueResult:
    async with session.begin():
        episode_result = await session.execute(
            select(Episode)
            .where(Episode.id == episode_id)
            .with_for_update()
        )
        episode = episode_result.scalar_one_or_none()
        if episode is None:
            raise _not_found()

        project = await session.get(Project, episode.project_id)
        if project is None:
            raise _conflict("项目不存在")
        style = await session.get(Style, project.style_id)
        if style is None:
            raise _conflict("项目风格不存在")
        template = await session.scalar(
            select(PromptTemplate).where(PromptTemplate.key == _TEMPLATE_KEY)
        )
        if template is None:
            raise _conflict("script2shots 模板不存在")

        impact_snapshot = await _read_impact_snapshot(session, episode_id)
        if confirm_token is None:
            if impact_snapshot.clip_revisions:
                raise _token_conflict()
        else:
            await require_generate_shots_impact_token(
                session, episode_id, confirm_token
            )

        asset_result = await session.execute(
            select(Asset)
            .where(
                Asset.project_id == project.id,
                Asset.type.in_(("character", "scene")),
            )
            .order_by(Asset.id)
        )
        assets = list(asset_result.scalars().all())
        if not assets:
            raise _conflict("项目没有可用于生成分镜的 character/scene 资产")
        asset_snapshot = [
            {
                "id": asset.id,
                "type": asset.type,
                "name": asset.name,
                "description": asset.description,
            }
            for asset in assets
        ]
        guided_json_schema = build_generate_shots_response_format(
            [asset.id for asset in assets]
        )
        rendered_prompt = render_generate_shots_prompt(
            template.content,
            assets=asset_snapshot,
            style=style.prompt_fragment,
            script=episode.script_text,
        )
        replacement_snapshot = await _read_replacement_snapshot(
            session, episode_id
        )
        input_snapshot = {
            "episode_id": episode.id,
            "project_id": project.id,
            "script": episode.script_text,
            "script_revision": episode.script_revision,
            "style": style.prompt_fragment,
            "template_key": _TEMPLATE_KEY,
            "template_content": template.content,
            "assets": asset_snapshot,
            "rendered_prompt": rendered_prompt,
            "model": settings.VLLM_MODEL,
            "temperature": settings.VLLM_TEMPERATURE,
            "guided_json_schema": guided_json_schema,
            "replacement_snapshot": replacement_snapshot,
        }
        payload = {
            "input_snapshot": input_snapshot,
            "input_hash": None,
            "source_revisions": {
                "episode": {
                    "id": episode.id,
                    "script_revision": episode.script_revision,
                },
                "assets": [
                    {"id": asset.id, "revision": asset.revision}
                    for asset in assets
                ],
                "shots": replacement_snapshot["shots"],
                "clips": replacement_snapshot["clips"],
            },
        }
        return await queue.enqueue(
            session,
            "gen_shots",
            episode.id,
            payload,
            request_id=None,
        )


async def _read_replacement_snapshot(
    session: AsyncSession, episode_id: int
) -> dict[str, object]:
    shot_result = await session.execute(
        select(Shot.id, Shot.revision)
        .where(Shot.episode_id == episode_id)
        .order_by(Shot.id)
    )
    shot_rows = shot_result.all()
    shots = [{"id": int(row.id), "revision": int(row.revision)} for row in shot_rows]

    clip_result = await session.execute(
        select(Clip.id, Clip.revision)
        .where(Clip.episode_id == episode_id)
        .order_by(Clip.id)
    )
    clip_rows = clip_result.all()
    clips = [{"id": int(row.id), "revision": int(row.revision)} for row in clip_rows]
    clip_ids = [item["id"] for item in clips]
    if not clip_ids:
        return {
            "shots": shots,
            "clips": clips,
            "clip_video_ids": [],
            "clip_media": [],
        }

    video_result = await session.execute(
        select(ClipVideo.id, ClipVideo.file_path)
        .where(ClipVideo.clip_id.in_(clip_ids))
        .order_by(ClipVideo.id)
    )
    video_rows = video_result.all()
    video_ids = [int(row.id) for row in video_rows]
    clip_media: list[dict[str, object]] = [
        {"kind": "clip_video", "id": int(row.id), "path": row.file_path}
        for row in video_rows
    ]

    override_result = await session.execute(
        select(ClipRefSlot.id, ClipRefSlot.override_image_path)
        .where(
            ClipRefSlot.clip_id.in_(clip_ids),
            ClipRefSlot.override_image_path.is_not(None),
        )
        .order_by(ClipRefSlot.id)
    )
    override_rows = override_result.all()
    clip_media.extend(
        {
            "kind": "slot_override",
            "id": int(row.id),
            "path": row.override_image_path,
        }
        for row in override_rows
    )
    return {
        "shots": shots,
        "clips": clips,
        "clip_video_ids": video_ids,
        "clip_media": clip_media,
    }


def _conflict(message: str) -> HTTPException:
    return HTTPException(status_code=409, detail=message)


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
