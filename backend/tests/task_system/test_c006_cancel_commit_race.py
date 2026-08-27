import asyncio
import os
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.tasks.gen_shots import gen_shots_handler
from app.tasks.queue import (
    ClaimedTask,
    TaskChange,
    TaskConflictError,
    TaskQueue,
    WorkerContext,
)
from tests.task_system.test_c006_gen_shots import (
    _FakeVLLM,
    _cleanup_replace_fixture,
    _create_replace_fixture,
    _insert_task,
    _read_replace_structure,
    _read_task,
    _replace_payload,
    _response,
    _shot,
)


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


class _RaceQueue(TaskQueue):
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        super().__init__(session_factory)
        self.complete_entered = asyncio.Event()
        self.allow_complete = asyncio.Event()
        self.business_committed = asyncio.Event()

    async def complete(self, session: AsyncSession, task_id: int) -> TaskChange:
        self.complete_entered.set()
        await self.allow_complete.wait()
        return await super().complete(session, task_id)

    async def publish_committed(
        self,
        result: TaskChange,
        publisher=None,
    ) -> None:
        await super().publish_committed(result, publisher)
        if result.task is not None and result.task.status == "done":
            self.business_committed.set()


async def _mark_running(
    task_id: int,
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            """
            UPDATE tasks
            SET status = 'running', progress = 0.5,
                started_at = now(), heartbeat_at = now()
            WHERE id = $1
            """,
            task_id,
        )
    finally:
        await connection.close()


async def _request_cancel(
    queue: TaskQueue,
    task_id: int,
    session_factory: async_sessionmaker[AsyncSession],
) -> TaskChange:
    async with session_factory() as session:
        async with session.begin():
            return await queue.request_cancel(session, task_id)


async def _run_handler(
    queue: TaskQueue,
    task_id: int,
    episode_id: int,
    payload: dict[str, object],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    claimed = ClaimedTask(
        id=task_id,
        type="gen_shots",
        target_id=episode_id,
        request_id=None,
        payload=payload,
    )
    context = WorkerContext(queue, claimed, session_factory)
    await gen_shots_handler(claimed, context)


def test_cancel_and_gen_shots_commit_have_one_atomic_winner(
    monkeypatch, tmp_path
) -> None:
    async def run() -> None:
        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
        engine = create_async_engine(os.environ["DATABASE_URL"])
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(
            "app.services.gen_shots.async_session_factory", session_factory
        )
        monkeypatch.setattr(
            "app.tasks.gen_shots.async_session_factory", session_factory
        )
        fake_holder: dict[str, _FakeVLLM | None] = {"value": None}
        monkeypatch.setattr(
            "app.tasks.gen_shots.VLLMClient",
            lambda base_url: fake_holder["value"],
        )
        fixtures: list[dict[str, object]] = []
        task_ids: list[int] = []

        try:
            cancel_fixture = await _create_replace_fixture(tmp_path)
            fixtures.append(cancel_fixture)
            cancel_before, cancel_other_before = await _read_replace_structure(
                cancel_fixture
            )
            cancel_fake = _FakeVLLM(
                _response({"shots": [_shot(asset_ids=[])]})
            )
            fake_holder["value"] = cancel_fake
            cancel_task_id = await _insert_task(
                _replace_payload(cancel_fixture),
                cancel_fixture["target_episode_id"],
                session_factory,
            )
            task_ids.append(cancel_task_id)
            await _mark_running(cancel_task_id)
            cancel_queue = _RaceQueue(session_factory)
            handler_task = asyncio.create_task(
                _run_handler(
                    cancel_queue,
                    cancel_task_id,
                    cancel_fixture["target_episode_id"],
                    _replace_payload(cancel_fixture),
                    session_factory,
                )
            )
            await asyncio.wait_for(cancel_queue.complete_entered.wait(), 5)

            requested = await _request_cancel(
                cancel_queue, cancel_task_id, session_factory
            )
            assert requested.changed
            assert requested.task is not None
            assert requested.task.status == "running"
            assert requested.task.cancel_requested_at is not None
            cancel_queue.allow_complete.set()
            await asyncio.wait_for(handler_task, 5)

            cancel_status, cancel_error = await _read_task(
                cancel_task_id, session_factory
            )
            assert cancel_status == "canceled"
            assert cancel_error is None
            cancel_after, cancel_other_after = await _read_replace_structure(
                cancel_fixture
            )
            assert cancel_after == cancel_before
            assert cancel_other_after == cancel_other_before
            for media in cancel_fixture["target_media"]:
                path = Path(media["path"])
                assert (tmp_path / path).is_file()
                assert not (tmp_path / "trash" / path).exists()

            done_fixture = await _create_replace_fixture(tmp_path)
            fixtures.append(done_fixture)
            done_before, done_other_before = await _read_replace_structure(
                done_fixture
            )
            done_fake = _FakeVLLM(_response({"shots": [_shot(asset_ids=[])]}))
            fake_holder["value"] = done_fake
            done_task_id = await _insert_task(
                _replace_payload(done_fixture),
                done_fixture["target_episode_id"],
                session_factory,
            )
            task_ids.append(done_task_id)
            await _mark_running(done_task_id)
            done_queue = _RaceQueue(session_factory)
            done_handler_task = asyncio.create_task(
                _run_handler(
                    done_queue,
                    done_task_id,
                    done_fixture["target_episode_id"],
                    _replace_payload(done_fixture),
                    session_factory,
                )
            )
            await asyncio.wait_for(done_queue.complete_entered.wait(), 5)
            done_queue.allow_complete.set()
            await asyncio.wait_for(done_queue.business_committed.wait(), 5)

            with pytest.raises(TaskConflictError) as cancel_error_info:
                await _request_cancel(done_queue, done_task_id, session_factory)
            assert cancel_error_info.value.conflict_kind == "terminal_cancel"
            await asyncio.wait_for(done_handler_task, 5)

            done_status, done_error = await _read_task(
                done_task_id, session_factory
            )
            assert done_status == "done"
            assert done_error is None
            done_after, done_other_after = await _read_replace_structure(done_fixture)
            assert done_after["clips"] == []
            assert done_after["clip_shots"] == []
            assert done_after["clip_videos"] == []
            assert done_after["clip_ref_slots"] == []
            assert len(done_after["shots"]) == 1
            assert done_after["shot_assets"] == []
            assert done_after["marker"] == done_fixture["script_revision"]
            assert done_other_after == done_other_before
            assert done_after != done_before
            for media in done_fixture["target_media"]:
                path = Path(media["path"])
                assert not (tmp_path / path).exists()
                assert (tmp_path / "trash" / path).is_file()
        finally:
            for fixture in reversed(fixtures):
                await _cleanup_replace_fixture(fixture, task_ids)
            await engine.dispose()

    asyncio.run(run())
