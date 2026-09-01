from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import asyncpg

from app.db.session import async_session_factory, engine
from app.tasks.queue import TaskQueue, aggregate_clip_generation_state


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _payload(label: str) -> dict[str, object]:
    return {
        "input_snapshot": {"label": label},
        "input_hash": f"hash-{label}",
        "source_revisions": {"clip": {"revision": 1}},
    }


async def _create_clip_fixture(
    *, generation_state: str = "empty", freshness: str = "stale"
) -> dict[str, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        suffix = uuid4().hex
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, '状态测试风格')
            RETURNING id
            """,
            f"C009 state style {suffix}",
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            f"C009 state project {suffix}",
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, '状态测试集', '状态测试剧本')
            RETURNING id
            """,
            project_id,
        )
        clip_id = await connection.fetchval(
            """
            INSERT INTO clips
                (episode_id, requested_duration, generation_state, freshness, revision)
            VALUES ($1, 5, $2, $3, 11)
            RETURNING id
            """,
            episode_id,
            generation_state,
            freshness,
        )
        assert style_id is not None
        assert project_id is not None
        assert episode_id is not None
        assert clip_id is not None
        return {
            "style_id": int(style_id),
            "project_id": int(project_id),
            "episode_id": int(episode_id),
            "clip_id": int(clip_id),
        }
    finally:
        await connection.close()


async def _insert_video_task(
    clip_id: int,
    status: str,
    *,
    finished_at: datetime | None = None,
    error_msg: str | None = None,
) -> int:
    started_at = datetime.now(timezone.utc) if status == "running" else None
    progress = 0.25 if status == "running" else 0.0
    if status in {"failed", "canceled"} and finished_at is None:
        finished_at = datetime.now(timezone.utc)
    connection = await asyncpg.connect(_database_url())
    try:
        task_id = await connection.fetchval(
            """
            INSERT INTO tasks
                (type, target_id, request_id, payload, status, progress,
                 error_msg, started_at, finished_at)
            VALUES
                ('gen_clip_video', $1, NULL, $2::jsonb, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            clip_id,
            json.dumps(_payload(f"insert-{status}"), ensure_ascii=False),
            status,
            progress,
            error_msg,
            started_at,
            finished_at,
        )
        assert task_id is not None
        return int(task_id)
    finally:
        await connection.close()


async def _read_pair(clip_id: int) -> tuple[dict[str, object], list[dict[str, object]]]:
    connection = await asyncpg.connect(_database_url())
    try:
        clip = await connection.fetchrow(
            """
            SELECT generation_state, freshness, revision, updated_at
            FROM clips
            WHERE id = $1
            """,
            clip_id,
        )
        assert clip is not None
        tasks = await connection.fetch(
            """
            SELECT id, status, progress, error_msg, started_at, finished_at,
                   cancel_requested_at
            FROM tasks
            WHERE type = 'gen_clip_video' AND target_id = $1
            ORDER BY id
            """,
            clip_id,
        )
        return dict(clip), [dict(task) for task in tasks]
    finally:
        await connection.close()


async def _delete_video_tasks(clip_id: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM tasks WHERE type = 'gen_clip_video' AND target_id = $1",
            clip_id,
        )
    finally:
        await connection.close()


async def _cleanup_clip_fixture(fixture: dict[str, int]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM tasks WHERE type = 'gen_clip_video' AND target_id = $1",
            fixture["clip_id"],
        )
        await connection.execute(
            "DELETE FROM clips WHERE id = $1", fixture["clip_id"]
        )
        await connection.execute(
            "DELETE FROM episodes WHERE id = $1", fixture["episode_id"]
        )
        await connection.execute(
            "DELETE FROM projects WHERE id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM styles WHERE id = $1", fixture["style_id"]
        )
    finally:
        await connection.close()


def test_aggregate_priorities_ties_and_canceled() -> None:
    async def run() -> None:
        fixture = await _create_clip_fixture()
        clip_id = fixture["clip_id"]
        try:
            base, _ = await _read_pair(clip_id)
            first_finished = datetime(2026, 1, 1, tzinfo=timezone.utc)
            second_finished = first_finished + timedelta(seconds=1)
            await _insert_video_task(
                clip_id, "done", finished_at=first_finished
            )
            await _insert_video_task(
                clip_id,
                "failed",
                finished_at=second_finished,
                error_msg="newer failure",
            )
            await _insert_video_task(clip_id, "queued")
            await _insert_video_task(clip_id, "running")

            async with async_session_factory() as session:
                async with session.begin():
                    assert (
                        await aggregate_clip_generation_state(session, clip_id)
                        == "generating"
                    )
            generating, _ = await _read_pair(clip_id)
            assert generating["generation_state"] == "generating"
            assert generating["freshness"] == base["freshness"]
            assert generating["revision"] == base["revision"]

            await _delete_video_tasks(clip_id)
            await _insert_video_task(clip_id, "queued")
            async with async_session_factory() as session:
                async with session.begin():
                    assert (
                        await aggregate_clip_generation_state(session, clip_id)
                        == "queued"
                    )

            await _delete_video_tasks(clip_id)
            await _insert_video_task(
                clip_id, "done", finished_at=first_finished
            )
            await _insert_video_task(
                clip_id,
                "failed",
                finished_at=second_finished,
                error_msg="latest failure",
            )
            async with async_session_factory() as session:
                async with session.begin():
                    assert (
                        await aggregate_clip_generation_state(session, clip_id)
                        == "failed"
                    )

            await _delete_video_tasks(clip_id)
            failed_id = await _insert_video_task(
                clip_id,
                "failed",
                finished_at=first_finished,
                error_msg="tie failure",
            )
            done_id = await _insert_video_task(
                clip_id, "done", finished_at=first_finished
            )
            assert done_id > failed_id
            async with async_session_factory() as session:
                async with session.begin():
                    assert (
                        await aggregate_clip_generation_state(session, clip_id)
                        == "ready"
                    )

            stable, _ = await _read_pair(clip_id)
            stable_updated_at = stable["updated_at"]
            async with async_session_factory() as session:
                async with session.begin():
                    assert (
                        await aggregate_clip_generation_state(session, clip_id)
                        == "ready"
                    )
            stable_again, _ = await _read_pair(clip_id)
            assert stable_again["updated_at"] == stable_updated_at

            await _delete_video_tasks(clip_id)
            canceled_id = await _insert_video_task(clip_id, "canceled")
            del canceled_id
            async with async_session_factory() as session:
                async with session.begin():
                    assert (
                        await aggregate_clip_generation_state(session, clip_id)
                        == "empty"
                    )
            empty, _ = await _read_pair(clip_id)
            assert empty["generation_state"] == "empty"
            assert empty["freshness"] == base["freshness"]
            assert empty["revision"] == base["revision"]
        finally:
            await _cleanup_clip_fixture(fixture)
            await engine.dispose()

    asyncio.run(run())


def test_queue_video_lifecycle_projects_state_and_commit_visibility() -> None:
    async def run() -> None:
        fixture = await _create_clip_fixture()
        clip_id = fixture["clip_id"]
        queue = TaskQueue(async_session_factory)
        task_ids: list[int] = []
        try:
            initial, _ = await _read_pair(clip_id)
            initial_revision = initial["revision"]
            initial_freshness = initial["freshness"]

            async with async_session_factory() as session:
                async with session.begin():
                    enqueued = await queue.enqueue(
                        session,
                        "gen_clip_video",
                        clip_id,
                        _payload("queued"),
                    )
                    task_ids.append(int(enqueued.task.id))
                    before_commit, before_tasks = await _read_pair(clip_id)
                    assert before_tasks == []
                    assert before_commit["generation_state"] == "empty"
            after_enqueue, after_tasks = await _read_pair(clip_id)
            assert after_enqueue["generation_state"] == "queued"
            assert after_tasks[0]["status"] == "queued"

            async with async_session_factory() as session:
                async with session.begin():
                    claimed = await queue.claim_next(session)
                    assert claimed is not None
                    assert claimed.task is not None
                    assert claimed.task.id == task_ids[0]
                    before_commit, before_tasks = await _read_pair(clip_id)
                    assert before_tasks[0]["status"] == "queued"
                    assert before_commit["generation_state"] == "queued"
            after_claim, after_tasks = await _read_pair(clip_id)
            assert after_claim["generation_state"] == "generating"
            assert after_tasks[0]["status"] == "running"

            async with async_session_factory() as session:
                async with session.begin():
                    completed = await queue.complete(session, task_ids[0])
                    assert completed.changed is True
                    before_commit, before_tasks = await _read_pair(clip_id)
                    assert before_tasks[0]["status"] == "running"
                    assert before_commit["generation_state"] == "generating"
            after_complete, after_tasks = await _read_pair(clip_id)
            assert after_complete["generation_state"] == "ready"
            assert after_tasks[0]["status"] == "done"

            async with async_session_factory() as session:
                async with session.begin():
                    enqueued = await queue.enqueue(
                        session,
                        "gen_clip_video",
                        clip_id,
                        _payload("failed"),
                    )
                    task_ids.append(int(enqueued.task.id))
            after_enqueue, _ = await _read_pair(clip_id)
            assert after_enqueue["generation_state"] == "queued"

            async with async_session_factory() as session:
                async with session.begin():
                    claimed = await queue.claim_next(session)
                    assert claimed is not None
                    failed = await queue.fail(session, task_ids[1], "worker failed")
                    assert failed.changed is True
            after_failed, after_tasks = await _read_pair(clip_id)
            assert after_failed["generation_state"] == "failed"
            assert after_tasks[1]["status"] == "failed"
            assert after_tasks[1]["error_msg"] == "worker failed"

            async with async_session_factory() as session:
                async with session.begin():
                    enqueued = await queue.enqueue(
                        session,
                        "gen_clip_video",
                        clip_id,
                        _payload("queued-cancel"),
                    )
                    task_ids.append(int(enqueued.task.id))
            async with async_session_factory() as session:
                async with session.begin():
                    canceled = await queue.request_cancel(session, task_ids[2])
                    assert canceled.changed is True
                    before_commit, before_tasks = await _read_pair(clip_id)
                    assert before_tasks[2]["status"] == "queued"
                    assert before_commit["generation_state"] == "queued"
            after_cancel, after_tasks = await _read_pair(clip_id)
            assert after_tasks[2]["status"] == "canceled"
            assert after_cancel["generation_state"] == "failed"

            async with async_session_factory() as session:
                async with session.begin():
                    enqueued = await queue.enqueue(
                        session,
                        "gen_clip_video",
                        clip_id,
                        _payload("running-cancel"),
                    )
                    task_ids.append(int(enqueued.task.id))
            async with async_session_factory() as session:
                async with session.begin():
                    claimed = await queue.claim_next(session)
                    assert claimed is not None
            async with async_session_factory() as session:
                async with session.begin():
                    requested = await queue.request_cancel(session, task_ids[3])
                    assert requested.task is not None
                    assert requested.task.status == "running"
            after_request, after_tasks = await _read_pair(clip_id)
            assert after_tasks[3]["status"] == "running"
            assert after_tasks[3]["cancel_requested_at"] is not None
            assert after_request["generation_state"] == "generating"

            async with async_session_factory() as session:
                async with session.begin():
                    canceled = await queue.cancel_safe_point(session, task_ids[3])
                    assert canceled.changed is True
            after_safe_point, after_tasks = await _read_pair(clip_id)
            assert after_tasks[3]["status"] == "canceled"
            assert after_safe_point["generation_state"] == "failed"
            assert after_safe_point["revision"] == initial_revision
            assert after_safe_point["freshness"] == initial_freshness
        finally:
            await _cleanup_clip_fixture(fixture)
            await engine.dispose()

    asyncio.run(run())


def test_immediate_failed_and_restart_recovery_project_state_atomically() -> None:
    async def run() -> None:
        queue = TaskQueue(async_session_factory)
        immediate_fixture = await _create_clip_fixture()
        recovery_fixture = await _create_clip_fixture()
        recovery_ids: list[int] = []
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    recorded = await queue.record_failed(
                        session,
                        "gen_clip_video",
                        immediate_fixture["clip_id"],
                        _payload("immediate-failed"),
                        "R10 slot 2 has no usable image",
                    )
                    assert recorded.created is True
                    assert recorded.task.status == "failed"
                    assert recorded.task.progress == 0.0
                    assert recorded.task.started_at is None
                    assert recorded.task.finished_at is not None
                    assert recorded.task.error_msg == (
                        "R10 slot 2 has no usable image"
                    )
                    assert set(recorded.task.payload) == {
                        "input_snapshot",
                        "input_hash",
                        "source_revisions",
                    }
                    before_commit, before_tasks = await _read_pair(
                        immediate_fixture["clip_id"]
                    )
                    assert before_tasks == []
                    assert before_commit["generation_state"] == "empty"
            immediate_clip, immediate_tasks = await _read_pair(
                immediate_fixture["clip_id"]
            )
            assert immediate_clip["generation_state"] == "failed"
            assert len(immediate_tasks) == 1
            assert immediate_tasks[0]["status"] == "failed"
            assert immediate_tasks[0]["progress"] == 0.0
            assert immediate_tasks[0]["started_at"] is None
            assert immediate_tasks[0]["finished_at"] is not None
            assert immediate_tasks[0]["error_msg"] == (
                "R10 slot 2 has no usable image"
            )

            running_id = await _insert_video_task(
                recovery_fixture["clip_id"], "running"
            )
            queued_id = await _insert_video_task(
                recovery_fixture["clip_id"], "queued"
            )
            recovery_ids.extend([running_id, queued_id])
            async with async_session_factory() as session:
                async with session.begin():
                    recovered = await queue.recover_running_tasks(session)
                    assert [change.task.id for change in recovered if change.task] == [
                        running_id
                    ]
                    before_commit, before_tasks = await _read_pair(
                        recovery_fixture["clip_id"]
                    )
                    assert [task["status"] for task in before_tasks] == [
                        "running",
                        "queued",
                    ]
                    assert before_commit["generation_state"] == "empty"
            after_recovery, after_tasks = await _read_pair(
                recovery_fixture["clip_id"]
            )
            assert [task["status"] for task in after_tasks] == [
                "failed",
                "queued",
            ]
            assert after_tasks[0]["error_msg"] == "server restarted"
            assert after_tasks[0]["finished_at"] is not None
            assert after_recovery["generation_state"] == "queued"

            async with async_session_factory() as session:
                async with session.begin():
                    canceled = await queue.request_cancel(session, queued_id)
                    assert canceled.task is not None
                    assert canceled.task.status == "canceled"
            after_cancel, after_tasks = await _read_pair(
                recovery_fixture["clip_id"]
            )
            assert [task["status"] for task in after_tasks] == [
                "failed",
                "canceled",
            ]
            assert after_cancel["generation_state"] == "failed"
        finally:
            await _cleanup_clip_fixture(immediate_fixture)
            await _cleanup_clip_fixture(recovery_fixture)
            await engine.dispose()

    asyncio.run(run())
