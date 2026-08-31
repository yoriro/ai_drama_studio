from __future__ import annotations

import asyncio
import copy
import os
import time
from typing import Any
from uuid import uuid4

import asyncpg

from app.db.session import async_session_factory, engine
from app.integrations.workflow_binding import load_binding_snapshot
from app.services.generate_asset_image import enqueue_generate_asset_image
from app.tasks.queue import TaskQueue


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _create_fixture() -> dict[str, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        suffix = uuid4().hex
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, '入队前风格')
            RETURNING id
            """,
            f"C007 lock style {suffix}",
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            f"C007 lock project {suffix}",
            style_id,
        )
        asset_id = await connection.fetchval(
            """
            INSERT INTO assets
                (project_id, type, name, description, source, revision)
            VALUES ($1, 'character', '入队前角色', '入队前描述', 'manual', 1)
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


async def _read_template() -> str:
    connection = await asyncpg.connect(_database_url())
    try:
        content = await connection.fetchval(
            "SELECT content FROM prompt_templates WHERE key = 'zimage'"
        )
        assert isinstance(content, str)
        return content
    finally:
        await connection.close()


async def _write_template(content: str) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE prompt_templates SET content = $1 WHERE key = 'zimage'",
            content,
        )
    finally:
        await connection.close()


async def _read_sources(fixture: dict[str, int]) -> dict[str, Any]:
    connection = await asyncpg.connect(_database_url())
    try:
        asset = await connection.fetchrow(
            "SELECT name, description, revision FROM assets WHERE id = $1",
            fixture["asset_id"],
        )
        style = await connection.fetchval(
            "SELECT prompt_fragment FROM styles WHERE id = $1",
            fixture["style_id"],
        )
        template = await connection.fetchval(
            "SELECT content FROM prompt_templates WHERE key = 'zimage'"
        )
        assert asset is not None
        assert isinstance(style, str)
        assert isinstance(template, str)
        return {
            "asset": dict(asset),
            "style": style,
            "template": template,
        }
    finally:
        await connection.close()


async def _cleanup_fixture(fixture: dict[str, int], task_id: int | None) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        if task_id is not None:
            await connection.execute("DELETE FROM tasks WHERE id = $1", task_id)
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


async def _writer(
    kind: str,
    fixture: dict[str, int],
    started: asyncio.Queue[tuple[str, int]],
    updated: asyncio.Queue[tuple[str, float]],
    enqueue_returned: asyncio.Event,
) -> None:
    connection = await asyncpg.connect(
        _database_url(),
        server_settings={"application_name": f"c007-final-lock-{kind}"},
    )
    try:
        backend_pid = await connection.fetchval("SELECT pg_backend_pid()")
        assert backend_pid is not None
        await started.put((kind, int(backend_pid)))
        async with connection.transaction():
            if kind == "asset":
                await connection.execute(
                    """
                    UPDATE assets
                    SET name = '入队后角色', description = '入队后描述', revision = 2
                    WHERE id = $1
                    """,
                    fixture["asset_id"],
                )
            elif kind == "style":
                await connection.execute(
                    "UPDATE styles SET prompt_fragment = '入队后风格' WHERE id = $1",
                    fixture["style_id"],
                )
            else:
                await connection.execute(
                    """
                    UPDATE prompt_templates
                    SET content = $1
                    WHERE key = 'zimage'
                    """,
                    "asset={{asset}}|style={{style}}|note={{user_note}}|入队后",
                )
            await updated.put((kind, time.monotonic()))
            await enqueue_returned.wait()
    finally:
        await connection.close()


async def _lock_waiters(expected: set[str]) -> dict[str, str]:
    connection = await asyncpg.connect(_database_url())
    try:
        for _ in range(80):
            rows = await connection.fetch(
                """
                SELECT application_name, wait_event_type
                FROM pg_stat_activity
                WHERE application_name LIKE 'c007-final-lock-%'
                  AND state = 'active'
                """
            )
            waiters = {
                str(row["application_name"])[len("c007-final-lock-") :]: str(
                    row["wait_event_type"]
                )
                for row in rows
                if row["wait_event_type"] == "Lock"
            }
            if set(waiters) == expected:
                return waiters
            await asyncio.sleep(0.05)
        raise AssertionError(f"expected row-lock waiters, observed {waiters}")
    finally:
        await connection.close()


async def _enqueue(
    fixture: dict[str, int],
    binding: object,
    queue: TaskQueue,
) -> object:
    async with async_session_factory() as session:
        return await enqueue_generate_asset_image(
            session,
            queue,
            fixture["asset_id"],
            user_note=None,
            request_id=None,
            workflow_binding=binding,
        )


def test_enqueue_holds_asset_style_template_locks_until_commit_and_worker_uses_copy(
) -> None:
    async def run() -> None:
        original_template = await _read_template()
        fixture = await _create_fixture()
        binding = load_binding_snapshot()
        queue = TaskQueue(async_session_factory)
        lock_acquired = asyncio.Event()
        release_enqueue = asyncio.Event()
        enqueue_returned = asyncio.Event()
        started: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        updated: asyncio.Queue[tuple[str, float]] = asyncio.Queue()
        writer_tasks: list[asyncio.Task[None]] = []
        enqueue_task: asyncio.Task[object] | None = None
        task_id: int | None = None
        template = "asset={{asset}}|style={{style}}|note={{user_note}}"
        try:
            await _write_template(template)
            original_enqueue = queue.enqueue

            async def gated_enqueue(
                session: Any,
                task_type: str,
                target_id: int,
                payload: dict[str, Any],
                request_id: str | None = None,
            ) -> object:
                lock_acquired.set()
                await release_enqueue.wait()
                return await original_enqueue(
                    session,
                    task_type,
                    target_id,
                    payload,
                    request_id=request_id,
                )

            queue.enqueue = gated_enqueue  # type: ignore[method-assign]
            enqueue_task = asyncio.create_task(_enqueue(fixture, binding, queue))
            await lock_acquired.wait()

            writer_tasks = [
                asyncio.create_task(
                    _writer(kind, fixture, started, updated, enqueue_returned)
                )
                for kind in ("asset", "style", "template")
            ]
            started_rows = [await started.get() for _ in writer_tasks]
            assert {kind for kind, _pid in started_rows} == {
                "asset",
                "style",
                "template",
            }
            assert len({pid for _kind, pid in started_rows}) == 3

            waiters = await _lock_waiters(
                {"asset", "style", "template"}
            )
            assert waiters == {
                "asset": "Lock",
                "style": "Lock",
                "template": "Lock",
            }
            assert all(not task.done() for task in writer_tasks)

            release_at = time.monotonic()
            release_enqueue.set()
            result = await enqueue_task
            assert result.created is True  # type: ignore[union-attr]
            task_id = int(result.task.id)  # type: ignore[union-attr]
            frozen_payload = copy.deepcopy(result.task.payload)  # type: ignore[union-attr]
            enqueue_returned.set()
            await asyncio.gather(*writer_tasks)
            writer_updates = [await updated.get() for _ in writer_tasks]
            assert {kind for kind, _timestamp in writer_updates} == {
                "asset",
                "style",
                "template",
            }
            assert all(timestamp >= release_at for _kind, timestamp in writer_updates)

            snapshot = frozen_payload["input_snapshot"]
            assert snapshot["asset"] == {
                "id": fixture["asset_id"],
                "project_id": fixture["project_id"],
                "type": "character",
                "name": "入队前角色",
                "description": "入队前描述",
                "revision": 1,
            }
            assert snapshot["style"] == "入队前风格"
            assert snapshot["template_content"] == template
            assert snapshot["rendered_prompt"] == (
                'asset={"type":"character","name":"入队前角色","description":"入队前描述"}'
                "|style=入队前风格|note="
            )

            sources = await _read_sources(fixture)
            assert sources == {
                "asset": {
                    "name": "入队后角色",
                    "description": "入队后描述",
                    "revision": 2,
                },
                "style": "入队后风格",
                "template": template + "|入队后",
            }

            captured: list[dict[str, Any]] = []

            async def capture_worker(task: object, _context: object) -> None:
                captured.append(copy.deepcopy(task.payload))  # type: ignore[union-attr]

            await TaskQueue(async_session_factory).run_worker(
                handlers={"gen_asset_image": capture_worker},
                poll_interval=0,
                stop_when_idle=True,
            )
            assert captured == [frozen_payload]
        finally:
            if enqueue_task is not None and not enqueue_task.done():
                release_enqueue.set()
                enqueue_task.cancel()
                try:
                    await enqueue_task
                except asyncio.CancelledError:
                    pass
            release_enqueue.set()
            enqueue_returned.set()
            for writer_task in writer_tasks:
                if not writer_task.done():
                    writer_task.cancel()
            if writer_tasks:
                await asyncio.gather(*writer_tasks, return_exceptions=True)
            await _write_template(original_template)
            await _cleanup_fixture(fixture, task_id)
            await engine.dispose()

    asyncio.run(run())
