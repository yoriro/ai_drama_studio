from __future__ import annotations

import asyncio
import os
from typing import Any
from uuid import uuid4

import asyncpg
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine
from app.models import Task
from app.schemas.shots import ShotPatch
from app.services.shots import update_shot


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _create_fixture() -> dict[str, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        suffix = uuid4().hex
        style_id = await connection.fetchval(
            "INSERT INTO styles (name, prompt_fragment) VALUES ($1, $2) RETURNING id",
            f"C012 T38 style {suffix}",
            "C012 T38 style prompt",
        )
        project_id = await connection.fetchval(
            "INSERT INTO projects (name, style_id) VALUES ($1, $2) RETURNING id",
            f"C012 T38 project {suffix}",
            style_id,
        )
        episode_id = await connection.fetchval(
            "INSERT INTO episodes (project_id, seq, title, script_text) "
            "VALUES ($1, 1, 'C012 T38 episode', 'C012 T38 script') RETURNING id",
            project_id,
        )
        character_id = await connection.fetchval(
            "INSERT INTO assets "
            "(project_id, type, name, description, source) "
            "VALUES ($1, 'character', 'T38人物', '初始绑定', 'manual') RETURNING id",
            project_id,
        )
        scene_one_id = await connection.fetchval(
            "INSERT INTO assets "
            "(project_id, type, name, description, source) "
            "VALUES ($1, 'scene', 'T38场景甲', '同集合目标', 'manual') RETURNING id",
            project_id,
        )
        scene_two_id = await connection.fetchval(
            "INSERT INTO assets "
            "(project_id, type, name, description, source) "
            "VALUES ($1, 'scene', 'T38场景乙', '不同集合目标', 'manual') RETURNING id",
            project_id,
        )
        shot_id = await connection.fetchval(
            "INSERT INTO shots "
            "(episode_id, order_index, duration_est, shot_type, camera, "
            "description, dialogue, status, revision) "
            "VALUES ($1, 1, 2, '中景', '固定', 'T38初始镜头', '', 'normal', 1) "
            "RETURNING id",
            episode_id,
        )
        await connection.execute(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
            shot_id,
            character_id,
        )
        clip_id = await connection.fetchval(
            "INSERT INTO clips (episode_id, requested_duration) VALUES ($1, 5) RETURNING id",
            episode_id,
        )
        await connection.execute(
            "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, 1)",
            clip_id,
            shot_id,
        )
        return {
            "style_id": int(style_id),
            "project_id": int(project_id),
            "episode_id": int(episode_id),
            "character_id": int(character_id),
            "scene_one_id": int(scene_one_id),
            "scene_two_id": int(scene_two_id),
            "shot_id": int(shot_id),
            "clip_id": int(clip_id),
        }
    finally:
        await connection.close()


async def _cleanup_fixture(fixture: dict[str, int]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute("DELETE FROM tasks WHERE target_id = $1", fixture["clip_id"])
        await connection.execute("DELETE FROM clip_videos WHERE clip_id = $1", fixture["clip_id"])
        await connection.execute("DELETE FROM clip_shots WHERE clip_id = $1", fixture["clip_id"])
        await connection.execute("DELETE FROM clips WHERE id = $1", fixture["clip_id"])
        await connection.execute(
            "DELETE FROM shot_assets WHERE shot_id = $1", fixture["shot_id"]
        )
        await connection.execute("DELETE FROM shots WHERE id = $1", fixture["shot_id"])
        await connection.execute(
            "DELETE FROM assets WHERE project_id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM episodes WHERE id = $1", fixture["episode_id"]
        )
        await connection.execute(
            "DELETE FROM projects WHERE id = $1", fixture["project_id"]
        )
        await connection.execute("DELETE FROM styles WHERE id = $1", fixture["style_id"])
    finally:
        await connection.close()


async def _open_operation_connection(label: str):
    connection = await engine.connect()
    connection.sync_connection.info["c012_operation"] = label
    await connection.execute(
        text("SELECT set_config('application_name', :value, false)"),
        {"value": label},
    )
    await connection.execute(text("SET lock_timeout = '15s'"))
    await connection.commit()
    return connection


async def _read_state(fixture: dict[str, int]) -> dict[str, Any]:
    connection = await asyncpg.connect(_database_url())
    try:
        shot = await connection.fetchrow(
            "SELECT revision, status FROM shots WHERE id = $1", fixture["shot_id"]
        )
        assets = await connection.fetch(
            "SELECT asset_id FROM shot_assets WHERE shot_id = $1 ORDER BY asset_id",
            fixture["shot_id"],
        )
        clip = await connection.fetchrow(
            "SELECT freshness FROM clips WHERE id = $1", fixture["clip_id"]
        )
        if shot is None or clip is None:
            raise AssertionError("T38 fixture state disappeared")
        return {
            "shot": dict(shot),
            "asset_ids": [int(row[0]) for row in assets],
            "clip": dict(clip),
        }
    finally:
        await connection.close()


async def _wait_for_blocked_workers(
    observer: asyncpg.Connection, worker_pids: list[int], blocker_pid: int
) -> None:
    async def wait() -> None:
        while True:
            rows = await observer.fetch(
                "SELECT pid, wait_event_type, pg_blocking_pids(pid) AS blockers "
                "FROM pg_stat_activity WHERE pid = ANY($1::int[])",
                worker_pids,
            )
            blockers_by_pid = {
                int(row["pid"]): [int(pid) for pid in row["blockers"]]
                for row in rows
            }

            def reaches_blocker(pid: int, visited: set[int]) -> bool:
                if pid == blocker_pid:
                    return True
                if pid in visited:
                    return False
                visited.add(pid)
                return any(
                    reaches_blocker(blocker, visited)
                    for blocker in blockers_by_pid.get(pid, [])
                )

            if len(rows) == len(worker_pids) and all(
                row["wait_event_type"] == "Lock"
                and reaches_blocker(int(row["pid"]), set())
                for row in rows
            ):
                return
            await asyncio.sleep(0.01)

    try:
        await asyncio.wait_for(wait(), timeout=5)
    except asyncio.TimeoutError as exc:
        snapshot = await observer.fetch(
            "SELECT pid, application_name, state, wait_event_type, wait_event, "
            "pg_blocking_pids(pid) AS blockers, left(query, 180) AS query "
            "FROM pg_stat_activity WHERE pid = ANY($1::int[]) ORDER BY pid",
            worker_pids,
        )
        raise AssertionError(
            f"C012 T38 workers were not all blocked by {blocker_pid}: "
            f"{[dict(row) for row in snapshot]}"
        ) from exc


async def _run_binding_pair(
    fixture: dict[str, int], requested_asset_ids: list[list[int]], label: str
) -> list[dict[str, Any]]:
    blocker = await asyncpg.connect(_database_url())
    observer = await asyncpg.connect(_database_url())
    transaction = blocker.transaction()
    transaction_active = True
    workers: list[asyncio.Task[dict[str, Any]]] = []
    worker_pids: list[int | None] = [None] * len(requested_asset_ids)
    await transaction.start()
    loop = asyncio.get_running_loop()
    lock_events: dict[str, asyncio.Event] = {}

    def observe_episode_lock(
        connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        operation = connection.info.get("c012_operation")
        normalized = " ".join(str(statement).lower().split())
        if (
            operation in lock_events
            and " from episodes" in normalized
            and " for update" in normalized
        ):
            loop.call_soon_threadsafe(lock_events[operation].set)

    event.listen(engine.sync_engine, "before_cursor_execute", observe_episode_lock)
    try:
        blocker_pid = int(await blocker.fetchval("SELECT pg_backend_pid()"))
        await blocker.execute(
            "SELECT id FROM episodes WHERE id = $1 FOR UPDATE",
            fixture["episode_id"],
        )
        labels = [f"c012-t38-{label}-{index}" for index in range(2)]
        lock_events.update({operation: asyncio.Event() for operation in labels})

        async def worker(index: int) -> dict[str, Any]:
            connection = await _open_operation_connection(labels[index])
            try:
                worker_pids[index] = int(
                    (
                        await connection.execute(text("SELECT pg_backend_pid()"))
                    ).scalar_one()
                )
                await connection.commit()
                async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                    return await update_shot(
                        session,
                        fixture["shot_id"],
                        ShotPatch(asset_ids=requested_asset_ids[index]),
                    )
            finally:
                await connection.close()

        workers = [
            asyncio.create_task(worker(index))
            for index in range(len(requested_asset_ids))
        ]
        await asyncio.wait_for(
            asyncio.gather(*(lock_events[operation].wait() for operation in labels)),
            timeout=5,
        )
        if any(pid is None for pid in worker_pids):
            raise AssertionError(f"C012 T38 worker backend PIDs missing: {worker_pids}")
        await _wait_for_blocked_workers(
            observer, [int(pid) for pid in worker_pids], blocker_pid
        )
        await transaction.commit()
        transaction_active = False
        return await asyncio.wait_for(asyncio.gather(*workers), timeout=10)
    finally:
        pending = [worker_task for worker_task in workers if not worker_task.done()]
        for worker_task in pending:
            worker_task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if transaction_active:
            await transaction.rollback()
        await observer.close()
        await blocker.close()
        event.remove(engine.sync_engine, "before_cursor_execute", observe_episode_lock)


def test_c012_identical_binding_after_lock_wait_is_noop() -> None:
    async def run() -> None:
        fixture = await _create_fixture()
        try:
            results = await _run_binding_pair(
                fixture,
                [[fixture["scene_one_id"]], [fixture["scene_one_id"]]],
                "same",
            )
            state = await _read_state(fixture)
            assert [result["revision"] for result in results] == [2, 2]
            assert [result["asset_ids"] for result in results] == [
                [fixture["scene_one_id"]],
                [fixture["scene_one_id"]],
            ]
            assert state == {
                "shot": {"revision": 2, "status": "changed"},
                "asset_ids": [fixture["scene_one_id"]],
                "clip": {"freshness": "stale"},
            }
        finally:
            await _cleanup_fixture(fixture)
            await engine.dispose()

    asyncio.run(run())


def test_c012_different_bindings_after_lock_wait_are_serial_equivalent() -> None:
    async def run() -> None:
        fixture = await _create_fixture()
        try:
            requested = [
                [fixture["scene_one_id"]],
                [fixture["scene_two_id"]],
            ]
            results = await _run_binding_pair(fixture, requested, "different")
            state = await _read_state(fixture)
            assert sorted(result["revision"] for result in results) == [2, 3]
            assert sorted(tuple(result["asset_ids"]) for result in results) == sorted(
                tuple(asset_ids) for asset_ids in requested
            )
            assert state["shot"] == {"revision": 3, "status": "changed"}
            assert state["asset_ids"] in requested
            assert state["clip"] == {"freshness": "stale"}
        finally:
            await _cleanup_fixture(fixture)
            await engine.dispose()

    asyncio.run(run())
