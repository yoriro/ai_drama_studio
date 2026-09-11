from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import asyncpg
from app.models import Task
from app.tasks.queue import TaskQueue
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _database_url() -> str:
    return __import__("os").environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _insert_task(status: str, task_type: str = "gen_assets") -> int:
    connection = await asyncpg.connect(_database_url())
    try:
        return int(
            await connection.fetchval(
                """
                INSERT INTO tasks (type, target_id, request_id, payload, status, progress)
                VALUES ($1, $2, NULL, '{"input_snapshot": {"test": true}, "input_hash": null, "source_revisions": {}}'::jsonb, $3, $4)
                RETURNING id
                """,
                task_type,
                900000 + (await connection.fetchval("SELECT COALESCE(MAX(id), 0) FROM tasks")),
                status,
                1.0 if status == "done" else 0.0,
            )
        )
    finally:
        await connection.close()


async def _task(task_id: int, factory: async_sessionmaker) -> Task:
    async with factory() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        return task


async def _delete_tasks(task_ids: list[int]) -> None:
    if not task_ids:
        return
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute("DELETE FROM tasks WHERE id = ANY($1::int[])", task_ids)
    finally:
        await connection.close()


def test_c012_recovery_cancel_success_race_and_single_claim() -> None:
    async def run() -> None:
        database_engine = create_async_engine(
            __import__("os").environ["DATABASE_URL"]
        )
        factory = async_sessionmaker(database_engine, expire_on_commit=False)
        queue = TaskQueue(factory)
        task_ids: list[int] = []
        try:
            queued_id = await _insert_task("queued")
            running_id = await _insert_task("running")
            claim_id = await _insert_task("queued", "gen_shots")
            task_ids.extend((queued_id, running_id, claim_id))

            async with factory() as session:
                async with session.begin():
                    queued_change = await queue.request_cancel(session, queued_id)
            assert queued_change.changed
            queued = await _task(queued_id, factory)
            assert queued.status == "canceled"
            assert queued.finished_at is not None

            async with factory() as session:
                async with session.begin():
                    running_change = await queue.request_cancel(session, running_id)
            assert running_change.changed
            assert running_change.task is not None
            assert running_change.task.status == "running"
            assert running_change.task.cancel_requested_at is not None

            async def cancel_at_safe_point() -> object:
                async with factory() as session:
                    async with session.begin():
                        return await queue.cancel_safe_point(session, running_id)

            async def complete() -> object:
                async with factory() as session:
                    async with session.begin():
                        return await queue.complete(session, running_id)

            race_results = await asyncio.gather(cancel_at_safe_point(), complete())
            assert sum(bool(result.changed) for result in race_results) == 1
            final_running = await _task(running_id, factory)
            assert final_running.status in {"canceled", "done"}
            if final_running.status == "canceled":
                assert final_running.cancel_requested_at is not None
            else:
                assert final_running.cancel_requested_at is not None

            async def claim() -> object:
                async with factory() as session:
                    async with session.begin():
                        return await queue.claim_next(session)

            claims = await asyncio.gather(claim(), claim())
            claimed = [change for change in claims if change is not None]
            assert len(claimed) == 1
            assert claimed[0].task is not None
            assert claimed[0].task.id == claim_id
            assert (await _task(claim_id, factory)).status == "running"
            print(
                "C012 recovery observations "
                f"queued_cancel={queued.status} race_final={final_running.status} "
                f"race_winners={sum(bool(result.changed) for result in race_results)} "
                f"claimers_with_task={len(claimed)}"
            )
        finally:
            await _delete_tasks(task_ids)
            await database_engine.dispose()

    asyncio.run(run())

def test_c012_recovery_restart_marks_running_only_and_preserves_queued() -> None:
    async def run() -> None:
        database_engine = create_async_engine(
            __import__("os").environ["DATABASE_URL"]
        )
        factory = async_sessionmaker(database_engine, expire_on_commit=False)
        queue = TaskQueue(factory)
        task_ids: list[int] = []
        try:
            running_id = await _insert_task("running")
            queued_id = await _insert_task("queued", "gen_shots")
            task_ids.extend((running_id, queued_id))
            async with factory() as session:
                async with session.begin():
                    changes = await queue.recover_running_tasks(session)
            assert [change.task.id for change in changes if change.task is not None] == [running_id]
            running = await _task(running_id, factory)
            queued = await _task(queued_id, factory)
            assert running.status == "failed"
            assert running.error_msg == "server restarted"
            assert queued.status == "queued"
            assert queued.started_at is None
            print(
                "C012 restart observations "
                f"running={running.status}:{running.error_msg} queued={queued.status}"
            )
        finally:
            await _delete_tasks(task_ids)
            await database_engine.dispose()

    asyncio.run(run())


def test_c012_recovery_heartbeat_database_error_is_not_swallowed() -> None:
    class BrokenSession:
        async def __aenter__(self) -> AsyncIterator[object]:
            raise asyncpg.PostgresConnectionError("controlled database unavailable")

        async def __aexit__(self, *_args: object) -> None:
            return None

    class BrokenFactory:
        def __call__(self) -> BrokenSession:
            return BrokenSession()

    async def run() -> None:
        queue = TaskQueue(BrokenFactory())
        stop = asyncio.Event()
        original_interval = __import__("app.tasks.queue", fromlist=["HEARTBEAT_INTERVAL_SECONDS"]).HEARTBEAT_INTERVAL_SECONDS
        __import__("app.tasks.queue", fromlist=["HEARTBEAT_INTERVAL_SECONDS"]).__dict__["HEARTBEAT_INTERVAL_SECONDS"] = 0.001
        try:
            try:
                await queue._heartbeat_loop(999999, stop)
            except asyncpg.PostgresConnectionError as exc:
                assert str(exc) == "controlled database unavailable"
            else:
                raise AssertionError("heartbeat database error was swallowed")
            print("C012 heartbeat observation database_error=propagated")
        finally:
            __import__("app.tasks.queue", fromlist=["HEARTBEAT_INTERVAL_SECONDS"]).__dict__["HEARTBEAT_INTERVAL_SECONDS"] = original_interval

    asyncio.run(run())


def test_c012_recovery_advisory_lock_rejects_second_session_and_releases() -> None:
    async def run() -> None:
        database_engine = create_async_engine(
            __import__("os").environ["DATABASE_URL"]
        )
        factory = async_sessionmaker(database_engine, expire_on_commit=False)
        queue = TaskQueue(factory)

        owner_connection = await database_engine.connect()
        probe_connection = await database_engine.connect()
        owner_acquired = False
        try:
            owner_acquired = await queue.acquire_advisory_lock(owner_connection)
            assert owner_acquired
            assert not await queue.acquire_advisory_lock(probe_connection)
            assert await queue.release_advisory_lock(owner_connection)
            owner_acquired = False
            assert await queue.acquire_advisory_lock(probe_connection)
            assert await queue.release_advisory_lock(probe_connection)
            print("C012 advisory observations first=acquired second=blocked after_release=acquired")
        finally:
            if owner_acquired:
                await queue.release_advisory_lock(owner_connection)
            await probe_connection.close()
            await owner_connection.close()
            await database_engine.dispose()

    asyncio.run(run())
