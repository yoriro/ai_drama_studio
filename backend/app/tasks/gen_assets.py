import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
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

_POSTGRES_INTEGER_MIN = -(2**31)
_POSTGRES_INTEGER_MAX = 2**31 - 1
_ASSET_NAME_CONSTRAINT = "uq_assets_project_name"


class _CanceledBeforeCommit(Exception):
    """The task cancellation won the final business commit race."""


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
    queryable_existing_ids = {
        existing_id
        for existing_id in existing_ids
        if _POSTGRES_INTEGER_MIN <= existing_id <= _POSTGRES_INTEGER_MAX
    }
    if queryable_existing_ids:
        asset_result = await session.execute(
            select(Asset)
            .where(Asset.id.in_(queryable_existing_ids))
            .with_for_update()
        )
        existing_by_id = {
            asset.id: asset for asset in asset_result.scalars().all()
        }

    for response_position, generated in enumerate(result.assets, start=1):
        existing_id = generated.existing_id
        if (
            existing_id is not None
            and existing_by_id.get(existing_id) is not None
            and existing_by_id[existing_id].project_id == project_id
        ):
            continue
        invalid_existing_reason: str | None = None
        if existing_id is not None:
            if not (
                _POSTGRES_INTEGER_MIN <= existing_id <= _POSTGRES_INTEGER_MAX
            ):
                invalid_existing_reason = "existing_id_out_of_postgres_integer_range"
            elif existing_by_id.get(existing_id) is None:
                invalid_existing_reason = "existing_id_not_found"
            else:
                invalid_existing_reason = "existing_id_not_in_project"
            logger.warning(
                "gen_assets candidate warning task_id=%s episode_id=%s "
                "project_id=%s response_position=%s normalized_name=%r "
                "reused_asset_id=%s reason=%s existing_id=%s",
                task.id,
                task.target_id,
                project_id,
                response_position,
                generated.name,
                None,
                invalid_existing_reason,
                existing_id,
            )
        inserted_id = (
            await session.execute(
                insert(Asset)
                .values(
                    project_id=project_id,
                    type=generated.type,
                    name=generated.name,
                    description=generated.description,
                    source="generated",
                    revision=1,
                )
                .on_conflict_do_nothing(constraint=_ASSET_NAME_CONSTRAINT)
                .returning(Asset.id)
            )
        ).scalar_one_or_none()
        if inserted_id is not None:
            continue

        conflict_result = await session.execute(
            select(Asset)
            .where(Asset.project_id == project_id, Asset.name == generated.name)
            .with_for_update()
        )
        conflict = conflict_result.scalar_one_or_none()
        if conflict is None:
            raise RuntimeError(
                "gen_assets name conflict did not expose the existing asset"
            )
        if conflict.type != generated.type:
            raise ValueError(
                "gen_assets normalized asset name conflicts across asset types: "
                f"project_id={project_id} response_position={response_position} "
                f"normalized_name={generated.name!r} existing_asset_id={conflict.id}"
            )
        logger.warning(
            "gen_assets candidate warning task_id=%s episode_id=%s "
            "project_id=%s response_position=%s normalized_name=%r "
            "reused_asset_id=%s reason=%s",
            task.id,
            task.target_id,
            project_id,
            response_position,
            generated.name,
            conflict.id,
            "same_normalized_name_same_type",
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
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await _merge_generated_assets(session, task, result)
                completed = await context.queue.complete(session, task.id)
                if not completed.changed:
                    if completed.task is not None and (
                        completed.task.status == "canceled"
                        or (
                            completed.task.status == "running"
                            and completed.task.cancel_requested_at is not None
                        )
                    ):
                        raise _CanceledBeforeCommit
                    raise RuntimeError(
                        f"gen_assets task {task.id} did not transition to done"
                    )
    except _CanceledBeforeCommit:
        await context.cancel_safe_point()
        return
    await context.queue.publish_committed(completed)
