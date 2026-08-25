import asyncio
from uuid import uuid4

from sqlalchemy import delete

from app.db.session import async_session_factory, engine
from app.models import Task
from app.tasks.queue import ClaimedTask, TaskQueue, WorkerContext


def _target_id() -> int:
    return int(uuid4().hex[:7], 16)


async def _insert_task(status: str, target_id: int) -> int:
    async with async_session_factory() as session:
        async with session.begin():
            task = Task(
                type="gen_assets",
                target_id=target_id,
                payload={
                    "input_snapshot": {"source": "task-system-test"},
                    "input_hash": None,
                    "source_revisions": {},
                },
                status=status,
                progress=0.2 if status == "running" else 0.0,
            )
            session.add(task)
            await session.flush()
            return task.id


async def _delete_tasks(task_ids: list[int]) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(Task).where(Task.id.in_(task_ids)))


def test_queued_cancel_is_terminal() -> None:
    async def run() -> None:
        task_id = await _insert_task("queued", _target_id())
        try:
            queue = TaskQueue(async_session_factory)
            async with async_session_factory() as session:
                async with session.begin():
                    first = await queue.request_cancel(session, task_id)
            assert first.changed is True
            assert first.task is not None
            assert first.task.status == "canceled"
            assert first.task.cancel_requested_at is None
            assert first.task.finished_at is not None

            async with async_session_factory() as session:
                async with session.begin():
                    repeat = await queue.request_cancel(session, task_id)
            assert repeat.changed is False
            assert repeat.task is not None
            assert repeat.task.status == "canceled"
        finally:
            await _delete_tasks([task_id])
            await engine.dispose()

    asyncio.run(run())


def test_running_cancel_stops_at_safe_point() -> None:
    async def run() -> None:
        task_id = await _insert_task("queued", _target_id())
        try:
            queue = TaskQueue(async_session_factory)
            async with async_session_factory() as session:
                async with session.begin():
                    claimed = await queue.claim_next(session)
            assert claimed is not None and claimed.changed is True

            async with async_session_factory() as session:
                async with session.begin():
                    requested = await queue.request_cancel(session, task_id)
            assert requested.changed is True
            assert requested.task is not None
            assert requested.task.status == "running"
            assert requested.task.cancel_requested_at is not None

            async with async_session_factory() as session:
                async with session.begin():
                    canceled = await queue.cancel_safe_point(session, task_id)
            assert canceled.changed is True
            assert canceled.task is not None
            assert canceled.task.status == "canceled"
            assert canceled.task.finished_at is not None

            async with async_session_factory() as session:
                async with session.begin():
                    complete = await queue.complete(session, task_id)
            assert complete.changed is False
            assert complete.task is not None
            assert complete.task.status == "canceled"
        finally:
            await _delete_tasks([task_id])
            await engine.dispose()

    asyncio.run(run())


def test_restart_fails_running_and_continues_queued() -> None:
    async def run() -> None:
        running_id = await _insert_task("running", _target_id())
        queued_id = await _insert_task("queued", _target_id())
        try:
            queue = TaskQueue(async_session_factory)
            async with async_session_factory() as session:
                async with session.begin():
                    recovery = await queue.recover_running_tasks(session)
            assert [change.task.id for change in recovery if change.task is not None] == [
                running_id
            ]

            async with async_session_factory() as session:
                recovered = await session.get(Task, running_id)
                queued = await session.get(Task, queued_id)
            assert recovered is not None
            assert recovered.status == "failed"
            assert recovered.error_msg == "server restarted"
            assert recovered.finished_at is not None
            assert queued is not None
            assert queued.status == "queued"

            async def handler(
                task: ClaimedTask, context: WorkerContext
            ) -> None:
                del task
                await context.heartbeat(0.5)

            await queue.run_worker(
                handlers={"gen_assets": handler},
                stop_when_idle=True,
                poll_interval=0.05,
            )
            async with async_session_factory() as session:
                queued = await session.get(Task, queued_id)
            assert queued is not None
            assert queued.status == "done"
        finally:
            await _delete_tasks([running_id, queued_id])
            await engine.dispose()

    asyncio.run(run())
