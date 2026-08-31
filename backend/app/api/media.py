import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.models import AssetImage, Clip, ClipRefSlot, Episode
from app.services.asset_files import resolve_data_path, slot_override_relative_path


logger = logging.getLogger("app.media")
router = APIRouter(tags=["media"])

_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
}


def _media_storage_error(image_id: int, reason: str) -> HTTPException:
    logger.exception("Asset image media unavailable image_id=%s reason=%s", image_id, reason)
    return HTTPException(status_code=500, detail="Asset image media is unavailable")


def _slot_override_media_error(slot_id: int, reason: str) -> HTTPException:
    logger.error(
        "Slot override media unavailable slot_id=%s reason=%s", slot_id, reason
    )
    return HTTPException(status_code=500, detail="Slot override media is unavailable")


@router.get("/media/asset-images/{image_id}")
async def read_asset_image_media(
    image_id: int,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    image = await session.get(AssetImage, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Asset image not found")

    try:
        path = resolve_data_path(settings.DATA_DIR, image.file_path)
        mime_type = _IMAGE_MIME_TYPES[path.suffix.lower()]
        with path.open("rb"):
            pass
    except (KeyError, OSError, ValueError) as exc:
        raise _media_storage_error(image_id, str(exc)) from exc

    return FileResponse(path, media_type=mime_type)


@router.get("/media/slot-overrides/{slot_id}", response_class=FileResponse)
async def read_slot_override_media(
    slot_id: int,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    slot = await session.get(ClipRefSlot, slot_id)
    if slot is None or slot.override_image_path is None:
        if slot is not None and slot.override_sha256 is not None:
            raise _slot_override_media_error(
                slot_id, "override hash exists without an override path"
            )
        raise HTTPException(status_code=404, detail="Slot override not found")

    clip = await session.get(Clip, slot.clip_id)
    if clip is None:
        raise _slot_override_media_error(slot_id, "clip is missing")
    episode = await session.get(Episode, clip.episode_id)
    if episode is None:
        raise _slot_override_media_error(slot_id, "episode is missing")

    relative_path = Path(slot.override_image_path)
    extension = relative_path.suffix.removeprefix(".").lower()
    try:
        expected_relative_path = slot_override_relative_path(
            int(episode.project_id),
            int(episode.id),
            int(clip.id),
            int(slot.id),
            extension,
        )
        if relative_path.as_posix() != expected_relative_path.as_posix():
            raise ValueError("slot override path does not match its slot")
        path = resolve_data_path(settings.DATA_DIR, relative_path)
        if not path.is_file():
            raise OSError("slot override file is missing")
        with path.open("rb"):
            pass
        mime_type = _IMAGE_MIME_TYPES[f".{extension}"]
    except (KeyError, OSError, ValueError) as exc:
        raise _slot_override_media_error(slot_id, str(exc)) from exc

    return FileResponse(path, media_type=mime_type)
