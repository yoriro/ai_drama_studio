import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException

from app.db.session import get_session
from app.schemas.clips import (
    ClipCreateRequest,
    ClipPatchRequest,
    ClipPreviewRequest,
    ClipPreviewResponse,
    ClipResponse,
    ClipSlotEnabledPatch,
    ClipSlotMutationResponse,
    ClipSlotsResponse,
    ClipVideoResponse,
    CurrentClipVideoRequest,
    POSTGRES_INTEGER_MAX,
)
from app.schemas.generation import (
    GenerateClipVideoRequest,
    GenerateClipVideoResponse,
)
from app.services.clips import (
    create_clip,
    delete_clip,
    get_clip,
    list_clips,
    preview_clip,
    list_clip_slots,
    update_clip,
    update_clip_slot_enabled,
    update_clip_slot_override,
)
from app.services.clip_videos import (
    delete_clip_video,
    list_clip_videos,
    set_current_clip_video,
)
from app.services.generate_clip_video import enqueue_generate_clip_video
from app.tasks.queue import TaskConflictError, TaskQueue, TaskValidationError


router = APIRouter(tags=["clips"])


@router.post(
    "/episodes/{episode_id}/clips/preview",
    response_model=ClipPreviewResponse,
)
async def preview_clip_route(
    episode_id: Annotated[int, Path(ge=-2_147_483_648, le=POSTGRES_INTEGER_MAX)],
    payload: ClipPreviewRequest,
    session: AsyncSession = Depends(get_session),
) -> ClipPreviewResponse:
    return await preview_clip(session, episode_id, payload)


@router.get("/episodes/{episode_id}/clips", response_model=list[ClipResponse])
async def list_clips_route(
    episode_id: Annotated[int, Path(ge=-2_147_483_648, le=POSTGRES_INTEGER_MAX)],
    session: AsyncSession = Depends(get_session),
) -> list[ClipResponse]:
    return await list_clips(session, episode_id)


@router.post(
    "/episodes/{episode_id}/clips",
    response_model=ClipResponse,
    status_code=201,
)
async def create_clip_route(
    episode_id: Annotated[int, Path(ge=-2_147_483_648, le=POSTGRES_INTEGER_MAX)],
    payload: ClipCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> ClipResponse:
    return await create_clip(session, episode_id, payload)


@router.get("/clips/{clip_id}", response_model=ClipResponse)
async def get_clip_route(
    clip_id: Annotated[int, Path(ge=-2_147_483_648, le=POSTGRES_INTEGER_MAX)],
    session: AsyncSession = Depends(get_session),
) -> ClipResponse:
    return await get_clip(session, clip_id)


@router.post(
    "/clips/{clip_id}/generate-video",
    response_model=GenerateClipVideoResponse,
    status_code=202,
)
async def generate_clip_video_route(
    clip_id: Annotated[int, Path(ge=-2_147_483_648, le=POSTGRES_INTEGER_MAX)],
    payload: GenerateClipVideoRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> GenerateClipVideoResponse:
    queue: TaskQueue = request.app.state.task_queue
    try:
        result = await enqueue_generate_clip_video(
            session,
            queue,
            clip_id,
            user_note=payload.user_note,
            user_note_provided="user_note" in payload.model_fields_set,
            request_id=payload.request_id,
            workflow_binding=request.app.state.minimax_workflow_binding_snapshot,
        )
    except TaskValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TaskConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await queue.publish_committed(result)
    return GenerateClipVideoResponse(task_id=result.task.id)


@router.get("/clips/{clip_id}/videos", response_model=list[ClipVideoResponse])
async def list_clip_videos_route(
    clip_id: Annotated[int, Path(ge=-2_147_483_648, le=POSTGRES_INTEGER_MAX)],
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    return await list_clip_videos(
        session,
        clip_id,
        include_debug=request.app.state.settings.DEBUG_PROMPTS,
    )


@router.put(
    "/clips/{clip_id}/current-video",
    response_model=ClipVideoResponse,
)
async def set_current_clip_video_route(
    clip_id: Annotated[int, Path(ge=-2_147_483_648, le=POSTGRES_INTEGER_MAX)],
    payload: CurrentClipVideoRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return await set_current_clip_video(
        session,
        clip_id,
        payload.video_id,
        include_debug=request.app.state.settings.DEBUG_PROMPTS,
    )


@router.delete("/clip-videos/{video_id}", status_code=204)
async def delete_clip_video_route(
    video_id: Annotated[int, Path(ge=-2_147_483_648, le=POSTGRES_INTEGER_MAX)],
    session: AsyncSession = Depends(get_session),
) -> Response:
    await delete_clip_video(session, video_id)
    return Response(status_code=204)


@router.patch("/clips/{clip_id}", response_model=ClipResponse)
async def update_clip_route(
    clip_id: Annotated[int, Path(ge=-2_147_483_648, le=POSTGRES_INTEGER_MAX)],
    payload: ClipPatchRequest,
    session: AsyncSession = Depends(get_session),
) -> ClipResponse:
    return await update_clip(session, clip_id, payload)


@router.delete("/clips/{clip_id}", status_code=204)
async def delete_clip_route(
    clip_id: Annotated[int, Path(ge=-2_147_483_648, le=POSTGRES_INTEGER_MAX)],
    session: AsyncSession = Depends(get_session),
) -> Response:
    await delete_clip(session, clip_id)
    return Response(status_code=204)


@router.get("/clips/{clip_id}/slots", response_model=ClipSlotsResponse)
async def list_clip_slots_route(
    clip_id: Annotated[int, Path(ge=-2_147_483_648, le=POSTGRES_INTEGER_MAX)],
    session: AsyncSession = Depends(get_session),
) -> ClipSlotsResponse:
    return await list_clip_slots(session, clip_id)


def _slot_mutation_validation_error(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


async def _parse_slot_mutation(
    request: Request,
) -> tuple[ClipSlotEnabledPatch | None, UploadFile | None, bool]:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    if media_type == "application/json":
        try:
            payload = ClipSlotEnabledPatch.model_validate(await request.json())
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
            raise _slot_mutation_validation_error(
                "JSON slot mutation must be exactly {enabled: boolean}"
            ) from exc
        return payload, None, False

    if media_type != "multipart/form-data":
        raise _slot_mutation_validation_error(
            "slot mutation must use application/json or multipart/form-data"
        )

    try:
        form = await request.form()
    except MultiPartException as exc:
        raise _slot_mutation_validation_error(
            "multipart slot mutation is invalid"
        ) from exc

    items = list(form.multi_items())
    keys = [key for key, _ in items]
    if "file" in keys:
        if len(items) != 1 or not isinstance(items[0][1], UploadFile):
            raise _slot_mutation_validation_error(
                "multipart upload must contain exactly one file part"
            )
        return None, items[0][1], False

    if (
        len(items) == 1
        and items[0][0] == "clear_override"
        and items[0][1] == "true"
    ):
        return None, None, True
    raise _slot_mutation_validation_error(
        "multipart slot mutation must upload one file or set clear_override=true"
    )


@router.patch(
    "/clips/{clip_id}/slots/{slot_no}",
    response_model=ClipSlotMutationResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/ClipSlotEnabledPatch"
                    }
                },
                "multipart/form-data": {
                    "schema": {
                        "oneOf": [
                            {
                                "type": "object",
                                "required": ["file"],
                                "properties": {
                                    "file": {
                                        "type": "string",
                                        "format": "binary",
                                    }
                                },
                                "additionalProperties": False,
                            },
                            {
                                "type": "object",
                                "required": ["clear_override"],
                                "properties": {
                                    "clear_override": {
                                        "type": "string",
                                        "enum": ["true"],
                                    }
                                },
                                "additionalProperties": False,
                            },
                        ]
                    }
                },
            },
        }
    },
)
async def update_clip_slot_route(
    request: Request,
    clip_id: Annotated[int, Path(ge=-2_147_483_648, le=POSTGRES_INTEGER_MAX)],
    slot_no: int = Path(ge=1, le=9),
    session: AsyncSession = Depends(get_session),
) -> ClipSlotMutationResponse:
    payload, upload, clear_override = await _parse_slot_mutation(request)
    if payload is not None:
        return await update_clip_slot_enabled(session, clip_id, slot_no, payload)
    try:
        return await update_clip_slot_override(
            session,
            clip_id,
            slot_no,
            upload=upload,
            clear_override=clear_override,
        )
    finally:
        if upload is not None:
            await upload.close()
