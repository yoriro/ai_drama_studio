import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.models import AssetImage
from app.services.asset_files import resolve_data_path


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
