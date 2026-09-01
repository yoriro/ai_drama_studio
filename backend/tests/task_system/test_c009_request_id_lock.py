from __future__ import annotations

import asyncio
import json
import os
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import text

from app.db.session import async_session_factory, engine
from app.integrations.workflow_binding import load_binding_snapshot
from app.services.generate_asset_image import enqueue_generate_asset_image
from app.tasks.queue import TaskQueue


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


class _StartGate:
    def __init__(self, parties: int) -> None:
        self._parties = parties
        self._arrived = 0
        self._lock = asyncio.Lock()
        self._open = asyncio.Event()

    async def wait(self) -> None:
        async with self._lock:
            self._arrived += 1
            if self._arrived == self._parties:
                self._open.set()
        await self._open.wait()


async def _set_application_name(session, name: str) -> None:
    await session.execute(
        text("SELECT set_config('application_name', :name, false)"),
        {"name": name},
    )


async def _wait_for_lock_waiter(application_name: str) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        for _ in range(100):
            row = await connection.fetchrow(
                """
                SELECT state, wait_event_type
                FROM pg_stat_activity
                WHERE application_name = $1
                  AND state = 'active'
                  AND wait_event_type = 'Lock'
                """,
                application_name,
            )
            if row is not None:
                assert row["state"] == "active"
                assert row["wait_event_type"] == "Lock"
                return
            await asyncio.sleep(0.01)
        raise AssertionError(
            f"request-id lock waiter was not visible for {application_name}"
        )
    finally:
        await connection.close()


async def _acquire_lock(
    request_id: str,
    application_name: str,
    started: asyncio.Event,
    acquired: asyncio.Event,
) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await _set_application_name(session, application_name)
            started.set()
            await TaskQueue(async_session_factory).acquire_request_id_lock(
                session, request_id
            )
            acquired.set()


def test_request_id_lock_blocks_same_id_and_allows_different_id() -> None:
    async def run() -> None:
        queue = TaskQueue(async_session_factory)
        same_task: asyncio.Task[None] | None = None
        try:
            same_started = asyncio.Event()
            same_acquired = asyncio.Event()
            async with async_session_factory() as first:
                async with first.begin():
                    await _set_application_name(
                        first, "c009-request-lock-same-first"
                    )
                    assert await queue.acquire_request_id_lock(first, " same ") == (
                        "same"
                    )
                    same_task = asyncio.create_task(
                        _acquire_lock(
                            "same",
                            "c009-request-lock-same-second",
                            same_started,
                            same_acquired,
                        )
                    )
                    await same_started.wait()
                    await _wait_for_lock_waiter(
                        "c009-request-lock-same-second"
                    )
                    assert not same_acquired.is_set()
                await asyncio.wait_for(same_acquired.wait(), timeout=2)
            assert same_task is not None
            await same_task

            different_started = asyncio.Event()
            different_acquired = asyncio.Event()
            different_task: asyncio.Task[None]
            async with async_session_factory() as first:
                async with first.begin():
                    await _set_application_name(
                        first, "c009-request-lock-different-first"
                    )
                    await queue.acquire_request_id_lock(first, "first")
                    different_task = asyncio.create_task(
                        _acquire_lock(
                            "second",
                            "c009-request-lock-different-second",
                            different_started,
                            different_acquired,
                        )
                    )
                    await different_started.wait()
                    await asyncio.wait_for(
                        different_acquired.wait(), timeout=2
                    )
                await different_task
        finally:
            for task in (same_task, locals().get("different_task")):
                if isinstance(task, asyncio.Task) and not task.done():
                    task.cancel()
            await engine.dispose()

    asyncio.run(run())


async def _create_asset_fixture() -> dict[str, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        suffix = uuid4().hex
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, '锁测试风格')
            RETURNING id
            """,
            f"C009 lock style {suffix}",
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            f"C009 lock project {suffix}",
            style_id,
        )
        asset_id = await connection.fetchval(
            """
            INSERT INTO assets
                (project_id, type, name, description, source, revision)
            VALUES ($1, 'character', '锁测试角色', '锁测试描述', 'manual', 1)
            RETURNING id
            """,
            project_id,
        )
        assert style_id is not None
        assert project_id is not None
        assert asset_id is not None
        return {
            "style_id": int(style_id),
            "project_id": int(project_id),
            "asset_id": int(asset_id),
        }
    finally:
        await connection.close()


async def _read_zimage_template() -> str:
    connection = await asyncpg.connect(_database_url())
    try:
        content = await connection.fetchval(
            "SELECT content FROM prompt_templates WHERE key = 'zimage'"
        )
        assert isinstance(content, str)
        return content
    finally:
        await connection.close()


async def _write_zimage_template(content: str) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE prompt_templates SET content = $1 WHERE key = 'zimage'",
            content,
        )
    finally:
        await connection.close()


async def _read_request_tasks(request_id: str) -> list[dict[str, object]]:
    connection = await asyncpg.connect(_database_url())
    try:
        rows = await connection.fetch(
            """
            SELECT id, type, target_id, request_id, status, payload
            FROM tasks
            WHERE request_id = $1
            ORDER BY id
            """,
            request_id,
        )
        result: list[dict[str, object]] = []
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            assert isinstance(payload, dict)
            result.append(
                {
                    "id": int(row["id"]),
                    "type": row["type"],
                    "target_id": int(row["target_id"]),
                    "request_id": row["request_id"],
                    "status": row["status"],
                    "payload": payload,
                }
            )
        return result
    finally:
        await connection.close()


async def _mark_task_done(task_id: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            """
            UPDATE tasks
            SET status = 'done', progress = 1.0, finished_at = now()
            WHERE id = $1
            """,
            task_id,
        )
    finally:
        await connection.close()


async def _cleanup_asset_fixture(
    fixture: dict[str, int], task_ids: list[int]
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        if task_ids:
            await connection.execute(
                "DELETE FROM tasks WHERE id = ANY($1::int[])", task_ids
            )
        await connection.execute(
            "DELETE FROM assets WHERE id = $1", fixture["asset_id"]
        )
        await connection.execute(
            "DELETE FROM projects WHERE id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM styles WHERE id = $1", fixture["style_id"]
        )
    finally:
        await connection.close()


def test_gen_asset_image_request_id_is_one_row_and_terminal_replay() -> None:
    async def run() -> None:
        original_template = await _read_zimage_template()
        fixture = await _create_asset_fixture()
        binding = load_binding_snapshot()
        task_ids: list[int] = []
        template = "asset={{asset}}|style={{style}}|note={{user_note}}"
        try:
            await _write_zimage_template(template)
            gate = _StartGate(2)

            async def attempt() -> object:
                await gate.wait()
                async with async_session_factory() as session:
                    return await enqueue_generate_asset_image(
                        session,
                        TaskQueue(async_session_factory),
                        fixture["asset_id"],
                        user_note=None,
                        request_id=" abc ",
                        workflow_binding=binding,
                    )

            results = await asyncio.gather(attempt(), attempt())
            result_ids = [int(result.task.id) for result in results]
            task_ids.extend(sorted(set(result_ids)))
            assert len(set(result_ids)) == 1
            assert {result.created for result in results} == {True, False}

            rows = await _read_request_tasks("abc")
            assert len(rows) == 1
            assert rows[0]["id"] == result_ids[0]
            assert rows[0]["type"] == "gen_asset_image"
            assert rows[0]["target_id"] == fixture["asset_id"]
            assert rows[0]["request_id"] == "abc"
            assert rows[0]["status"] == "queued"

            await _mark_task_done(result_ids[0])
            replay = None
            async with async_session_factory() as session:
                replay = await enqueue_generate_asset_image(
                    session,
                    TaskQueue(async_session_factory),
                    fixture["asset_id"],
                    user_note=None,
                    request_id="abc",
                    workflow_binding=binding,
                )
            assert replay.task.id == result_ids[0]
            assert replay.created is False
            rows_after_replay = await _read_request_tasks("abc")
            assert len(rows_after_replay) == 1
            assert rows_after_replay[0]["status"] == "done"
        finally:
            await _write_zimage_template(original_template)
            await _cleanup_asset_fixture(fixture, task_ids)
            await engine.dispose()

    asyncio.run(run())
