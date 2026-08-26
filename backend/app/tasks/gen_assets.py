import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.core.config import settings
from app.models import Asset, Episode
from app.services.gen_assets import (
    GeneratedAssetsResponse,
    extract_assets,
)
from app.services.vllm import VLLMClient
from app.tasks.queue import ClaimedTask, WorkerContext


logger = logging.getLogger("app.tasks.gen_assets")


async def _merge_generated_assets(
    session: AsyncSession,
    task: ClaimedTask,
    result: GeneratedAssetsResponse,
) -> None:
    snapshot = task.payload["input_snapshot"]
    if not isinstance(snapshot, dict):
        raise ValueError("gen_assets input_snapshot must be an object")
    project_id = snapshot.get("project_id")
    script_revision = snapshot.get("script_revision")
    if (
        isinstance(project_id, bool)
        or not isinstance(project_id, int)
        or project_id <= 0
    ):
        raise ValueError("gen_assets project_id must be a positive integer")
    if (
        isinstance(script_revision, bool)
        or not isinstance(script_revision, int)
        or script_revision < 1
    ):
        raise ValueError("gen_assets script_revision must be a positive integer")

    existing_ids = {
        asset.existing_id
        for asset in result.assets
        if asset.existing_id is not None
    }
    episode_result = await session.execute(
        select(Episode)
        .where(
            Episode.id == task.target_id,
            Episode.project_id == project_id,
        )
        .with_for_update()
    )
    episode = episode_result.scalar_one_or_none()
    if episode is None:
        raise ValueError("gen_assets target episode no longer exists")

    existing_by_id: dict[int, Asset] = {}
    if existing_ids:
        asset_result = await session.execute(
            select(Asset)
            .where(Asset.id.in_(existing_ids))
            .with_for_update()
        )
        existing_by_id = {
            asset.id: asset for asset in asset_result.scalars().all()
        }

    for generated in result.assets:
        existing_id = generated.existing_id
        if (
            existing_id is not None
            and existing_by_id.get(existing_id) is not None
            and existing_by_id[existing_id].project_id == project_id
        ):
            continue
        if existing_id is not None:
            logger.warning(
                "gen_assets invalid existing_id task_id=%s "
                "episode_id=%s project_id=%s existing_id=%s",
                task.id,
                task.target_id,
                project_id,
                existing_id,
            )
        session.add(
            Asset(
                project_id=project_id,
                type=generated.type,
                name=generated.name,
                description=generated.description,
                source="generated",
                revision=1,
            )
        )

    episode.assets_generated_script_revision = script_revision


async def merge_generated_assets(
    task: ClaimedTask,
    result: GeneratedAssetsResponse,
) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await _merge_generated_assets(session, task, result)


async def gen_assets_handler(
    task: ClaimedTask, context: WorkerContext
) -> None:
    result = await extract_assets(
        task,
        context,
        VLLMClient(str(settings.VLLM_BASE_URL)),
    )
    if result is None:
        return
    safe_point = await context.cancel_safe_point()
    if safe_point.task is not None and safe_point.task.status == "canceled":
        return
    async with async_session_factory() as session:
        async with session.begin():
            await _merge_generated_assets(session, task, result)
