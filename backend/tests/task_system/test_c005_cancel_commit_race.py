import asyncio
import json
import os
from typing import Any
from uuid import uuid4

import asyncpg

from app.db.session import async_session_factory, engine
from app.tasks.gen_assets import gen_assets_handler
from app.tasks.queue import (
    ClaimedTask,
    EnqueueResult,
    TaskChange,
    TaskConflictError,
    TaskQueue,
    WorkerContext,
)


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


class _ControlledVLLM:
    calls = 0

    def __init__(self, base_url: str) -> None:
        del base_url

    async def wake(self) -> None:
        return None

    async def structured_chat(self, **request: object) -> dict[str, object]:
        del request
        type(self).calls += 1
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "assets": [
                                    {
                                        "existing_id": None,
                                        "type": "character",
                                        "name": "竞态新增",
                                        "description": "竞态描述",
                                    }
                                ]
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }


class _RaceQueue(TaskQueue):
    def __init__(self) -> None:
        super().__init__(async_session_factory)
        self.complete_entered = asyncio.Event()
        self.allow_complete = asyncio.Event()
        self.business_committed = asyncio.Event()

    async def complete(self, session, task_id: int) -> TaskChange:
        self.complete_entered.set()
        await self.allow_complete.wait()
        return await super().complete(session, task_id)

    async def publish_committed(
        self,
        result: TaskChange | EnqueueResult,
        publisher: Any = None,
    ) -> None:
        await super().publish_committed(result, publisher)
        if result.event is not None and result.event.status == "done":
            self.business_committed.set()


async def _create_fixture(
    marker: int,
) -> tuple[int, int, int, int, int, dict[str, object]]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            """
            INSERT INTO styles(name, prompt_fragment)
            VALUES ($1, 'race style') RETURNING id
            """,
            "C005 T11 style " + uuid4().hex,
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects(name, style_id)
            VALUES ($1, $2) RETURNING id
            """,
            "C005 T11 project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes(
                project_id, seq, title, script_text,
                assets_generated_script_revision
            )
            VALUES ($1, 1, 'T11 episode', 'T11 script', $2)
            RETURNING id
            """,
            project_id,
            marker,
        )
        current_asset_id = await connection.fetchval(
            """
            INSERT INTO assets(project_id, type, name, description, source)
            VALUES ($1, 'character', '竞态原资产', '保持不变', 'manual')
            RETURNING id
            """,
            project_id,
        )
        payload = {
            "input_snapshot": {
                "episode_id": episode_id,
                "project_id": project_id,
                "script_revision": marker,
                "rendered_prompt": "T11 prompt",
                "model": "T11 model",
                "temperature": 0.2,
            },
            "input_hash": None,
            "source_revisions": {},
        }
        task_id = await connection.fetchval(
            """
            INSERT INTO tasks(type, target_id, payload, status, progress)
            VALUES ('gen_assets', $1, $2::jsonb, 'running', 0.5)
            RETURNING id
            """,
            episode_id,
            json.dumps(payload),
        )
        assert all(
            value is not None
            for value in (style_id, project_id, episode_id, current_asset_id, task_id)
        )
        return (
            int(style_id),
            int(project_id),
            int(episode_id),
            int(current_asset_id),
            int(task_id),
            payload,
        )
    finally:
        await connection.close()


async def _cleanup_fixture(
    style_id: int,
    project_id: int,
    episode_id: int,
    task_id: int,
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute("DELETE FROM tasks WHERE id = $1", task_id)
        await connection.execute("DELETE FROM assets WHERE project_id = $1", project_id)
        await connection.execute("DELETE FROM episodes WHERE id = $1", episode_id)
        await connection.execute("DELETE FROM projects WHERE id = $1", project_id)
        await connection.execute("DELETE FROM styles WHERE id = $1", style_id)
    finally:
        await connection.close()


async def _request_cancel(task_id: int) -> TaskChange:
    queue = TaskQueue(async_session_factory)
    async with async_session_factory() as session:
        async with session.begin():
            return await queue.request_cancel(session, task_id)


async def _request_cancel_expect_conflict(task_id: int) -> None:
    queue = TaskQueue(async_session_factory)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await queue.request_cancel(session, task_id)
    except TaskConflictError as exc:
        assert exc.conflict_kind == "terminal_cancel"
        return
    raise AssertionError("cancel after done must be a terminal conflict")


async def _read_state(
    task_id: int, episode_id: int, project_id: int
) -> tuple[asyncpg.Record, int | None, list[asyncpg.Record]]:
    connection = await asyncpg.connect(_database_url())
    try:
        task = await connection.fetchrow(
            """
            SELECT status, cancel_requested_at, error_msg
            FROM tasks WHERE id = $1
            """,
            task_id,
        )
        marker = await connection.fetchval(
            """
            SELECT assets_generated_script_revision
            FROM episodes WHERE id = $1
            """,
            episode_id,
        )
        assets = await connection.fetch(
            """
            SELECT name, description, source
            FROM assets WHERE project_id = $1 ORDER BY id
            """,
            project_id,
        )
        assert task is not None
        return task, marker, assets
    finally:
        await connection.close()


async def _run_handler(
    queue: _RaceQueue,
    task_id: int,
    episode_id: int,
    payload: dict[str, object],
) -> None:
    claimed = ClaimedTask(
        id=task_id,
        type="gen_assets",
        target_id=episode_id,
        request_id=None,
        payload=payload,
    )
    await gen_assets_handler(
        claimed,
        WorkerContext(queue, claimed, async_session_factory),
    )


def test_cancel_and_gen_assets_commit_have_one_atomic_winner(
    monkeypatch,
) -> None:
    async def run() -> None:
        import app.tasks.gen_assets as gen_assets_module

        monkeypatch.setattr(gen_assets_module, "VLLMClient", _ControlledVLLM)
        try:
            cancel_fixture = await _create_fixture(marker=7)
            try:
                (
                    style_id,
                    project_id,
                    episode_id,
                    current_asset_id,
                    task_id,
                    payload,
                ) = cancel_fixture
                _ControlledVLLM.calls = 0
                queue = _RaceQueue()
                handler_task = asyncio.create_task(
                    _run_handler(queue, task_id, episode_id, payload)
                )
                await asyncio.wait_for(queue.complete_entered.wait(), timeout=5)

                cancel_change = await asyncio.wait_for(
                    _request_cancel(task_id), timeout=5
                )
                assert cancel_change.task is not None
                assert cancel_change.task.status == "running"
                assert cancel_change.task.cancel_requested_at is not None
                queue.allow_complete.set()
                await handler_task

                task, marker, assets = await _read_state(
                    task_id, episode_id, project_id
                )
                assert task["status"] == "canceled"
                assert task["cancel_requested_at"] is not None
                assert task["error_msg"] is None
                assert marker == 7
                assert [row["name"] for row in assets] == ["竞态原资产"]
                assert assets[0]["source"] == "manual"
                assert current_asset_id is not None
                assert _ControlledVLLM.calls == 1
            finally:
                await _cleanup_fixture(
                    cancel_fixture[0],
                    cancel_fixture[1],
                    cancel_fixture[2],
                    cancel_fixture[3],
                )

            done_fixture = await _create_fixture(marker=9)
            try:
                (
                    style_id,
                    project_id,
                    episode_id,
                    current_asset_id,
                    task_id,
                    payload,
                ) = done_fixture
                _ControlledVLLM.calls = 0
                queue = _RaceQueue()
                handler_task = asyncio.create_task(
                    _run_handler(queue, task_id, episode_id, payload)
                )
                await asyncio.wait_for(queue.complete_entered.wait(), timeout=5)
                queue.allow_complete.set()
                await asyncio.wait_for(queue.business_committed.wait(), timeout=5)

                await _request_cancel_expect_conflict(task_id)
                await handler_task

                task, marker, assets = await _read_state(
                    task_id, episode_id, project_id
                )
                assert task["status"] == "done"
                assert task["cancel_requested_at"] is None
                assert task["error_msg"] is None
                assert marker == 9
                assert [row["name"] for row in assets] == [
                    "竞态原资产",
                    "竞态新增",
                ]
                assert assets[0]["source"] == "manual"
                assert assets[1]["source"] == "generated"
                assert current_asset_id is not None
                assert _ControlledVLLM.calls == 1
            finally:
                await _cleanup_fixture(
                    done_fixture[0],
                    done_fixture[1],
                    done_fixture[2],
                    done_fixture[3],
                )
        finally:
            await engine.dispose()

    asyncio.run(run())
