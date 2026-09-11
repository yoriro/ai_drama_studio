from __future__ import annotations

import asyncio
import os
from typing import Any

import asyncpg
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.tasks.queue as queue_module
from app.models import Asset, Episode, Project, Style, Task
from app.tasks.queue import (
    ClaimedTask,
    TaskConflictError,
    TaskQueue,
    WorkerContext,
)


def _database_url() -> str:
    return os.environ["DATABASE_URL"]


def _payload(episode_id: int, project_id: int) -> dict[str, object]:
    return {
        "input_snapshot": {
            "episode_id": episode_id,
            "project_id": project_id,
            "template_key": "script2assets",
            "rendered_prompt": "recovery test prompt",
        },
        "input_hash": None,
        "source_revisions": {
            "assets": [],
            "episode": {"id": episode_id, "script_revision": 1},
        },
    }


async def _create_fixture(
    factory: async_sessionmaker[AsyncSession], token: str
) -> dict[str, object]:
    async with factory() as session:
        async with session.begin():
            style = Style(
                name=f"C012 worker recovery style {token}",
                prompt_fragment="recovery style",
            )
            session.add(style)
            await session.flush()
            project = Project(
                name=f"C012 worker recovery project {token}",
                style_id=style.id,
            )
            session.add(project)
            await session.flush()
            episodes = [
                Episode(
                    project_id=project.id,
                    seq=index,
                    title=f"recovery episode {index}",
                    script_text=f"recovery script {index}",
                )
                for index in (1, 2)
            ]
            session.add_all(episodes)
            await session.flush()
            return {
                "style_id": style.id,
                "project_id": project.id,
                "episode_ids": [episode.id for episode in episodes],
            }


async def _insert_task(
    factory: async_sessionmaker[AsyncSession],
    *,
    episode_id: int,
    project_id: int,
    status: str,
) -> int:
    async with factory() as session:
        async with session.begin():
            task = Task(
                type="gen_assets",
                target_id=episode_id,
                payload=_payload(episode_id, project_id),
                status=status,
                progress=0.2 if status == "running" else 0.0,
            )
            session.add(task)
            await session.flush()
            return task.id


async def _read_task(
    factory: async_sessionmaker[AsyncSession], task_id: int
) -> dict[str, object]:
    async with factory() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        return {
            "id": task.id,
            "status": task.status,
            "progress": task.progress,
            "payload": task.payload,
            "error_msg": task.error_msg,
            "heartbeat_at": task.heartbeat_at,
            "cancel_requested_at": task.cancel_requested_at,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
        }


async def _read_assets(
    factory: async_sessionmaker[AsyncSession], project_id: int
) -> list[dict[str, object]]:
    async with factory() as session:
        result = await session.execute(
            select(Asset)
            .where(Asset.project_id == project_id)
            .order_by(Asset.id)
        )
        return [
            {
                "id": asset.id,
                "project_id": asset.project_id,
                "type": asset.type,
                "name": asset.name,
                "description": asset.description,
                "source": asset.source,
            }
            for asset in result.scalars().all()
        ]


async def _cleanup_fixture(
    factory: async_sessionmaker[AsyncSession],
    fixture: dict[str, object],
    task_ids: list[int],
) -> None:
    async with factory() as session:
        async with session.begin():
            project_id = int(fixture["project_id"])
            style_id = int(fixture["style_id"])
            episode_ids = [int(value) for value in fixture["episode_ids"]]
            await session.execute(delete(Task).where(Task.id.in_(task_ids)))
            await session.execute(
                delete(Asset).where(Asset.project_id == project_id)
            )
            await session.execute(
                delete(Episode).where(Episode.id.in_(episode_ids))
            )
            await session.execute(delete(Project).where(Project.id == project_id))
            await session.execute(delete(Style).where(Style.id == style_id))


def test_c012_worker_recovery_queued_cancel_and_completion_have_one_winner() -> None:
    async def run() -> None:
        database_engine = create_async_engine(_database_url())
        factory = async_sessionmaker(database_engine, expire_on_commit=False)
        fixture = await _create_fixture(factory, "cancel-winner")
        task_ids: list[int] = []
        try:
            episode_ids = [int(value) for value in fixture["episode_ids"]]
            project_id = int(fixture["project_id"])
            queued_id = await _insert_task(
                factory,
                episode_id=episode_ids[0],
                project_id=project_id,
                status="queued",
            )
            cancel_first_id = await _insert_task(
                factory,
                episode_id=episode_ids[1],
                project_id=project_id,
                status="running",
            )
            task_ids.extend((queued_id, cancel_first_id))
            queue = TaskQueue(factory)

            async with factory() as session:
                async with session.begin():
                    queued_cancel = await queue.request_cancel(session, queued_id)
            assert queued_cancel.changed is True
            assert queued_cancel.task is not None
            assert queued_cancel.task.status == "canceled"
            assert queued_cancel.task.started_at is None
            assert queued_cancel.task.finished_at is not None

            async with factory() as session:
                async with session.begin():
                    running_request = await queue.request_cancel(session, cancel_first_id)
            assert running_request.changed is True
            assert running_request.task is not None
            assert running_request.task.status == "running"
            assert running_request.task.cancel_requested_at is not None

            async def cancel_at_safe_point() -> object:
                async with factory() as session:
                    async with session.begin():
                        return await queue.cancel_safe_point(session, cancel_first_id)

            async def complete() -> object:
                async with factory() as session:
                    async with session.begin():
                        return await queue.complete(session, cancel_first_id)

            race_results = await asyncio.gather(
                cancel_at_safe_point(),
                complete(),
            )
            assert sum(bool(result.changed) for result in race_results) == 1

            queued = await _read_task(factory, queued_id)
            canceled = await _read_task(factory, cancel_first_id)
            assert queued["status"] == "canceled"
            assert queued["finished_at"] is not None
            assert canceled["status"] == "canceled"
            assert canceled["cancel_requested_at"] is not None
            assert canceled["finished_at"] is not None
            assert canceled["error_msg"] is None

            complete_first_id = await _insert_task(
                factory,
                episode_id=episode_ids[1],
                project_id=project_id,
                status="running",
            )
            task_ids.append(complete_first_id)
            async with factory() as session:
                async with session.begin():
                    completed = await queue.complete(session, complete_first_id)
            assert completed.changed is True
            assert completed.task is not None
            assert completed.task.status == "done"
            with pytest.raises(TaskConflictError) as conflict:
                async with factory() as session:
                    async with session.begin():
                        await queue.request_cancel(session, complete_first_id)
            assert conflict.value.conflict_kind == "terminal_cancel"

            async with factory() as session:
                async with session.begin():
                    no_queued_claim = await queue.claim_next(session)
            assert no_queued_claim is None
            assert await _read_assets(factory, project_id) == []
            print(
                "C012 worker recovery cancel observations "
                f"queued={queued['status']} cancel_first={canceled['status']} "
                f"complete_first={completed.task.status} "
                f"safe_point_winners={sum(bool(result.changed) for result in race_results)} "
                "asset_count=0"
            )
        finally:
            await _cleanup_fixture(factory, fixture, task_ids)
            await database_engine.dispose()

    asyncio.run(run())


def test_c012_worker_recovery_restarted_queue_claims_once_and_records_exact_asset() -> None:
    async def run() -> None:
        database_engine = create_async_engine(_database_url())
        factory = async_sessionmaker(database_engine, expire_on_commit=False)
        fixture = await _create_fixture(factory, "queued-restart")
        task_ids: list[int] = []
        try:
            episode_ids = [int(value) for value in fixture["episode_ids"]]
            project_id = int(fixture["project_id"])
            running_id = await _insert_task(
                factory,
                episode_id=episode_ids[0],
                project_id=project_id,
                status="running",
            )
            queued_id = await _insert_task(
                factory,
                episode_id=episode_ids[1],
                project_id=project_id,
                status="queued",
            )
            task_ids.extend((running_id, queued_id))
            queue = TaskQueue(factory)
            async with factory() as session:
                async with session.begin():
                    recovered = await queue.recover_running_tasks(session)
            assert [
                change.task.id
                for change in recovered
                if change.task is not None
            ] == [running_id]
            assert (await _read_task(factory, running_id))["status"] == "failed"
            assert (await _read_task(factory, running_id))["error_msg"] == (
                "server restarted"
            )
            assert (await _read_task(factory, queued_id))["status"] == "queued"

            handler_calls: list[int] = []
            handler_payloads: list[dict[str, object]] = []

            async def handler(
                task: ClaimedTask, _context: WorkerContext
            ) -> None:
                handler_calls.append(task.id)
                handler_payloads.append(task.payload)
                async with factory() as session:
                    async with session.begin():
                        session.add(
                            Asset(
                                project_id=project_id,
                                type="character",
                                name="恢复后唯一资产",
                                description="由queued任务恰一次写入",
                                source="generated",
                            )
                        )

            expected_payload = _payload(episode_ids[1], project_id)
            await queue.run_worker(
                handlers={"gen_assets": handler},
                stop_when_idle=True,
                poll_interval=0.01,
            )

            queued = await _read_task(factory, queued_id)
            assets = await _read_assets(factory, project_id)
            assert handler_calls == [queued_id]
            assert handler_payloads == [expected_payload]
            assert queued["status"] == "done"
            assert queued["progress"] == 1.0
            assert queued["error_msg"] is None
            assert queued["started_at"] is not None
            assert queued["finished_at"] is not None
            assert len(assets) == 1
            assert assets[0] == {
                "id": assets[0]["id"],
                "project_id": project_id,
                "type": "character",
                "name": "恢复后唯一资产",
                "description": "由queued任务恰一次写入",
                "source": "generated",
            }
            print(
                "C012 worker recovery queued observations "
                f"recovered_running={running_id}:failed/server restarted "
                f"queued={queued_id}:{queued['status']} "
                f"handler_calls={len(handler_calls)} asset_count={len(assets)}"
            )
        finally:
            await _cleanup_fixture(factory, fixture, task_ids)
            await database_engine.dispose()

    asyncio.run(run())


def test_c012_worker_recovery_heartbeat_failure_cancels_handler_without_swallowing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenSession:
        async def __aenter__(self) -> Any:
            raise asyncpg.PostgresConnectionError("controlled database unavailable")

        async def __aexit__(self, *_args: object) -> None:
            return None

    class BrokenFactory:
        def __init__(self) -> None:
            self.attempts = 0

        def __call__(self) -> BrokenSession:
            self.attempts += 1
            return BrokenSession()

    async def run() -> None:
        monkeypatch.setattr(queue_module, "HEARTBEAT_INTERVAL_SECONDS", 0.001)
        broken_factory = BrokenFactory()
        queue = TaskQueue(broken_factory)  # type: ignore[arg-type]
        handler_started = asyncio.Event()
        handler_canceled = asyncio.Event()

        async def handler(
            _task: ClaimedTask, _context: WorkerContext
        ) -> None:
            handler_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                handler_canceled.set()
                raise

        claimed = ClaimedTask(
            id=910001,
            type="gen_assets",
            target_id=910001,
            request_id=None,
            payload={
                "input_snapshot": {"test": "heartbeat"},
                "input_hash": None,
                "source_revisions": {},
            },
        )
        execution = asyncio.create_task(
            queue._execute_claimed(claimed, {"gen_assets": handler})
        )
        await asyncio.wait_for(handler_started.wait(), timeout=1)
        with pytest.raises(
            asyncpg.PostgresConnectionError,
            match="controlled database unavailable",
        ):
            await execution
        assert handler_canceled.is_set()
        assert broken_factory.attempts >= 2
        print(
            "C012 worker recovery heartbeat observations "
            f"handler_canceled={handler_canceled.is_set()} "
            f"database_attempts={broken_factory.attempts}"
        )

    asyncio.run(run())


def test_c012_worker_recovery_database_outage_leaves_running_for_restart_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenSession:
        async def __aenter__(self) -> Any:
            raise asyncpg.PostgresConnectionError("controlled database unavailable")

        async def __aexit__(self, *_args: object) -> None:
            return None

    class BrokenFactory:
        def __init__(self) -> None:
            self.attempts = 0

        def __call__(self) -> BrokenSession:
            self.attempts += 1
            return BrokenSession()

    async def run() -> None:
        database_engine = create_async_engine(_database_url())
        factory = async_sessionmaker(database_engine, expire_on_commit=False)
        fixture = await _create_fixture(factory, "database-outage")
        task_ids: list[int] = []
        try:
            episode_ids = [int(value) for value in fixture["episode_ids"]]
            episode_id = episode_ids[0]
            project_id = int(fixture["project_id"])
            task_id = await _insert_task(
                factory,
                episode_id=episode_id,
                project_id=project_id,
                status="running",
            )
            task_ids.append(task_id)
            monkeypatch.setattr(queue_module, "HEARTBEAT_INTERVAL_SECONDS", 0.001)
            broken_factory = BrokenFactory()
            broken_queue = TaskQueue(broken_factory)  # type: ignore[arg-type]
            handler_started = asyncio.Event()
            handler_canceled = asyncio.Event()

            async def handler(
                _task: ClaimedTask, _context: WorkerContext
            ) -> None:
                handler_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    handler_canceled.set()
                    raise

            claimed = ClaimedTask(
                id=task_id,
                type="gen_assets",
                target_id=episode_id,
                request_id=None,
                payload=_payload(episode_id, project_id),
            )
            execution = asyncio.create_task(
                broken_queue._execute_claimed(claimed, {"gen_assets": handler})
            )
            await asyncio.wait_for(handler_started.wait(), timeout=1)
            with pytest.raises(
                asyncpg.PostgresConnectionError,
                match="controlled database unavailable",
            ):
                await execution
            assert handler_canceled.is_set()
            assert broken_factory.attempts >= 2

            after_outage = await _read_task(factory, task_id)
            assert after_outage["status"] == "running"
            assert after_outage["error_msg"] is None
            assert after_outage["finished_at"] is None
            assert await _read_assets(factory, project_id) == []

            queue = TaskQueue(factory)
            async with factory() as session:
                async with session.begin():
                    recovered = await queue.recover_running_tasks(session)
            assert [
                change.task.id
                for change in recovered
                if change.task is not None
            ] == [task_id]
            after_restart = await _read_task(factory, task_id)
            assert after_restart["status"] == "failed"
            assert after_restart["error_msg"] == "server restarted"
            assert after_restart["finished_at"] is not None
            assert await _read_assets(factory, project_id) == []
            print(
                "C012 worker recovery outage observations "
                f"during_outage={after_outage['status']} "
                f"after_restart={after_restart['status']}:{after_restart['error_msg']} "
                f"handler_canceled={handler_canceled.is_set()} asset_count=0"
            )
        finally:
            await _cleanup_fixture(factory, fixture, task_ids)
            await database_engine.dispose()

    asyncio.run(run())
