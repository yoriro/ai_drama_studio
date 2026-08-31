from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Path,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import AssetImage
from app.schemas.assets import (
    AssetCreate,
    CurrentImagePatch,
    AssetImageResponse,
    AssetPatch,
    AssetResponse,
)
from app.schemas.generation import (
    GenerateAssetImageRequest,
    GenerateAssetImageResponse,
)
from app.services.assets import (
    create_asset,
    delete_asset,
    get_asset,
    list_assets,
    list_asset_images,
    delete_asset_image,
    set_current_asset_image,
    upload_asset_image,
    update_asset,
)
from app.services.generate_asset_image import enqueue_generate_asset_image
from app.tasks.queue import TaskConflictError, TaskQueue, TaskValidationError


router = APIRouter(tags=["assets"])


def _asset_image_payload(
    image: AssetImage, *, include_debug: bool
) -> dict[str, object]:
    payload = AssetImageResponse.model_validate(image).model_dump(mode="json")
    if include_debug:
        payload["built_prompt"] = image.built_prompt
        input_snapshot = image.input_snapshot
        if input_snapshot is not None:
            input_snapshot = dict(input_snapshot)
            if input_snapshot.get("seed") is not None:
                input_snapshot["seed"] = str(input_snapshot["seed"])
        payload["input_snapshot"] = input_snapshot
    return payload


@router.post(
    "/assets/{asset_id}/generate-image",
    response_model=GenerateAssetImageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_asset_image_route(
    asset_id: Annotated[
        int, Path(ge=-2_147_483_648, le=2_147_483_647)
    ],
    payload: GenerateAssetImageRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> GenerateAssetImageResponse:
    queue: TaskQueue = request.app.state.task_queue
    try:
        result = await enqueue_generate_asset_image(
            session,
            queue,
            asset_id,
            user_note=payload.user_note,
            request_id=payload.request_id,
            workflow_binding=request.app.state.workflow_binding_snapshot,
        )
    except TaskValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TaskConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await queue.publish_committed(result)
    return GenerateAssetImageResponse(task_id=result.task.id)


@router.get(
    "/projects/{project_id}/assets", response_model=list[AssetResponse]
)
async def read_assets(
    project_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[AssetResponse]:
    return await list_assets(session, project_id)


@router.post(
    "/projects/{project_id}/assets",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_asset_route(
    project_id: int,
    payload: AssetCreate,
    session: AsyncSession = Depends(get_session),
) -> AssetResponse:
    return await create_asset(session, project_id, payload)


@router.get("/assets/{asset_id}", response_model=AssetResponse)
async def read_asset(
    asset_id: int,
    session: AsyncSession = Depends(get_session),
) -> AssetResponse:
    return await get_asset(session, asset_id)


@router.patch("/assets/{asset_id}", response_model=AssetResponse)
async def update_asset_route(
    asset_id: int,
    payload: AssetPatch,
    session: AsyncSession = Depends(get_session),
) -> AssetResponse:
    return await update_asset(session, asset_id, payload)


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset_route(
    asset_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await delete_asset(session, asset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/assets/{asset_id}/images", response_model=list[dict[str, object]])
async def read_asset_images(
    asset_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    images = await list_asset_images(session, asset_id)
    return [
        _asset_image_payload(
            image, include_debug=request.app.state.settings.DEBUG_PROMPTS
        )
        for image in images
    ]


@router.post(
    "/assets/{asset_id}/images",
    response_model=AssetImageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_asset_image(
    asset_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> AssetImageResponse:
    return await upload_asset_image(session, asset_id, file)


@router.put(
    "/assets/{asset_id}/current-image", response_model=AssetImageResponse
)
async def update_current_asset_image(
    asset_id: int,
    payload: CurrentImagePatch,
    session: AsyncSession = Depends(get_session),
) -> AssetImageResponse:
    return await set_current_asset_image(session, asset_id, payload.image_id)


@router.delete(
    "/asset-images/{image_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_asset_image_route(
    image_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await delete_asset_image(session, image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
