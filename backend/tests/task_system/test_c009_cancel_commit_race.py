from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings
from app.db.session import async_session_factory, engine
from app.services.clip_video_commit import commit_generated_clip_video
from app.tasks.gen_clip_video import GeneratedClipVideo
from app.tasks.queue import (
    ClaimedTask,
    TaskChange,
    TaskConflictError,
    TaskQueue,
)
from tests.task_system.test_c009_clip_video_commit import (
    _cleanup_fixture_and_engine,
    _create_fixture,
    _enqueue_and_claim,
    _write_temp,
)


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _read_state(clip_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        clip = await connection.fetchrow(
            """
            SELECT generation_state, freshness, revision,
                   prompt_cache, prompt_input_hash
            FROM clips
            WHERE id = $1
            """,
            clip_id,
        )
        tasks = await connection.fetch(
            """
            SELECT id, status, progress, cancel_requested_at, finished_at
            FROM tasks
            WHERE type = 'gen_clip_video' AND target_id = $1
            ORDER BY id
            """,
            clip_id,
        )
        videos = await connection.fetch(
            """
            SELECT id, file_path, is_current
            FROM clip_videos
            WHERE clip_id = $1
            ORDER BY id
            """,
            clip_id,
        )
        assert clip is not None
        return {
            "clip": dict(clip),
            "tasks": [dict(task) for task in tasks],
            "videos": [dict(video) for video in videos],
        }
    finally:
        await connection.close()


async def _request_cancel(queue: TaskQueue, task_id: int) -> TaskChange:
    async with async_session_factory() as session:
        async with session.begin():
            return await queue.request_cancel(session, task_id)


async def _cancel_safe_point(queue: TaskQueue, task_id: int) -> TaskChange:
    async with async_session_factory() as session:
        async with session.begin():
            return await queue.cancel_safe_point(session, task_id)


async def _commit(
    queue: TaskQueue,
    task: ClaimedTask,
    temp_path: Path,
    data_dir: Path,
    built_prompt: str,
) -> TaskChange | None:
    async with async_session_factory() as session:
        return await commit_generated_clip_video(
            session,
            queue,
            task,
            GeneratedClipVideo(temp_path=temp_path, built_prompt=built_prompt),
            data_dir=data_dir,
        )


def _assert_no_video_files(data_dir: Path) -> None:
    assert list((data_dir / "projects").rglob("*.mp4")) == []
    assert list((data_dir / "trash").rglob("*.mp4")) == []


class _FinalCommitBarrierQueue(TaskQueue):
    def __init__(self) -> None:
        super().__init__(async_session_factory)
        self.complete_entered = asyncio.Event()
        self.allow_complete = asyncio.Event()
        self.cancel_entered = asyncio.Event()

    async def complete(self, session, task_id: int) -> TaskChange:
        self.complete_entered.set()
        await self.allow_complete.wait()
        return await super().complete(session, task_id)

    async def request_cancel(self, session, task_id: int) -> TaskChange:
        self.cancel_entered.set()
        return await super().request_cancel(session, task_id)


def test_c009_cancel_marker_before_final_commit_wins_without_take(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    async def run() -> None:
        fixture = await _create_fixture(tmp_path)
        try:
            queue, task = await _enqueue_and_claim(fixture)
            before = await _read_state(int(fixture["clip_id"]))
            baseline_revision = before["clip"]["revision"]
            baseline_freshness = before["clip"]["freshness"]
            temp_path, _ = _write_temp(tmp_path, task)

            requested = await _request_cancel(queue, task.id)
            assert requested.changed is True
            assert requested.task is not None
            assert requested.task.status == "running"
            assert requested.task.cancel_requested_at is not None

            committed = await _commit(
                queue, task, temp_path, tmp_path, "cancelled before commit"
            )
            assert committed is None

            canceled = await _cancel_safe_point(queue, task.id)
            assert canceled.changed is True
            assert canceled.task is not None
            assert canceled.task.status == "canceled"

            after = await _read_state(int(fixture["clip_id"]))
            assert after["clip"]["generation_state"] == "empty"
            assert after["clip"]["freshness"] == baseline_freshness
            assert after["clip"]["revision"] == baseline_revision
            assert after["clip"]["prompt_cache"] is None
            assert after["clip"]["prompt_input_hash"] is None
            assert [task_row["status"] for task_row in after["tasks"]] == [
                "canceled"
            ]
            assert after["tasks"][0]["cancel_requested_at"] is not None
            assert after["videos"] == []
            assert not temp_path.exists()
            _assert_no_video_files(tmp_path)
        finally:
            await _cleanup_fixture_and_engine(fixture)

    asyncio.run(run())


def test_c009_cancel_marker_during_final_commit_lets_done_win(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    async def run() -> None:
        fixture = await _create_fixture(tmp_path)
        try:
            _, task = await _enqueue_and_claim(fixture)
            queue = _FinalCommitBarrierQueue()
            before = await _read_state(int(fixture["clip_id"]))
            baseline_revision = before["clip"]["revision"]
            temp_path, _ = _write_temp(tmp_path, task)
            commit_task = asyncio.create_task(
                _commit(queue, task, temp_path, tmp_path, "commit wins")
            )
            await asyncio.wait_for(queue.complete_entered.wait(), timeout=5)

            cancel_task = asyncio.create_task(_request_cancel(queue, task.id))
            await asyncio.wait_for(queue.cancel_entered.wait(), timeout=5)
            assert not cancel_task.done()

            queue.allow_complete.set()
            completed = await asyncio.wait_for(commit_task, timeout=5)
            assert completed is not None
            assert completed.changed is True
            assert completed.task is not None
            assert completed.task.status == "done"

            with pytest.raises(TaskConflictError) as raised:
                await asyncio.wait_for(cancel_task, timeout=5)
            assert raised.value.conflict_kind == "terminal_cancel"

            after = await _read_state(int(fixture["clip_id"]))
            assert after["clip"]["generation_state"] == "ready"
            assert after["clip"]["freshness"] == "fresh"
            assert after["clip"]["revision"] == baseline_revision
            assert after["clip"]["prompt_cache"] == "commit wins"
            assert len(after["videos"]) == 1
            assert after["videos"][0]["is_current"] is True
            assert after["tasks"][0]["status"] == "done"
            assert after["tasks"][0]["cancel_requested_at"] is None
            assert not temp_path.exists()
            formal_path = tmp_path / after["videos"][0]["file_path"]
            assert formal_path.is_file()
            assert list((tmp_path / "trash").rglob("*.mp4")) == []
        finally:
            if "cancel_task" in locals() and not cancel_task.done():
                cancel_task.cancel()
                await asyncio.gather(cancel_task, return_exceptions=True)
            if "commit_task" in locals() and not commit_task.done():
                commit_task.cancel()
                await asyncio.gather(commit_task, return_exceptions=True)
            await _cleanup_fixture_and_engine(fixture)

    asyncio.run(run())


def test_c009_cancel_marker_after_final_commit_is_terminal_conflict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    async def run() -> None:
        fixture = await _create_fixture(tmp_path)
        try:
            queue, task = await _enqueue_and_claim(fixture)
            temp_path, _ = _write_temp(tmp_path, task)
            completed = await _commit(
                queue, task, temp_path, tmp_path, "done before cancel"
            )
            assert completed is not None
            assert completed.task is not None
            assert completed.task.status == "done"

            with pytest.raises(TaskConflictError) as raised:
                await _request_cancel(queue, task.id)
            assert raised.value.conflict_kind == "terminal_cancel"

            after = await _read_state(int(fixture["clip_id"]))
            assert after["clip"]["generation_state"] == "ready"
            assert after["clip"]["freshness"] == "fresh"
            assert after["clip"]["prompt_cache"] == "done before cancel"
            assert len(after["videos"]) == 1
            assert after["videos"][0]["is_current"] is True
            assert after["tasks"][0]["status"] == "done"
            assert after["tasks"][0]["cancel_requested_at"] is None
            assert not temp_path.exists()
            assert (tmp_path / after["videos"][0]["file_path"]).is_file()
            assert list((tmp_path / "trash").rglob("*.mp4")) == []
        finally:
            await _cleanup_fixture_and_engine(fixture)

    asyncio.run(run())


def test_c009_generation_state_active_priority_survives_immediate_failed_insert(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    async def run() -> None:
        fixture = await _create_fixture(tmp_path)
        try:
            queue, running_task = await _enqueue_and_claim(fixture)
            payload = running_task.payload
            baseline = await _read_state(int(fixture["clip_id"]))
            baseline_revision = baseline["clip"]["revision"]
            baseline_freshness = baseline["clip"]["freshness"]

            async with async_session_factory() as session:
                async with session.begin():
                    queued = await queue.enqueue(
                        session,
                        "gen_clip_video",
                        int(fixture["clip_id"]),
                        payload,
                    )
            assert queued.task is not None
            queued_id = int(queued.task.id)

            async with async_session_factory() as session:
                async with session.begin():
                    immediate_failed = await queue.record_failed(
                        session,
                        "gen_clip_video",
                        int(fixture["clip_id"]),
                        payload,
                        "R10 immediate failed while active",
                    )
            assert immediate_failed.task.status == "failed"

            after_insert = await _read_state(int(fixture["clip_id"]))
            assert after_insert["clip"]["generation_state"] == "generating"
            assert after_insert["clip"]["revision"] == baseline_revision
            assert after_insert["clip"]["freshness"] == baseline_freshness
            assert [task_row["status"] for task_row in after_insert["tasks"]] == [
                "running",
                "queued",
                "failed",
            ]

            requested = await _request_cancel(queue, running_task.id)
            assert requested.task is not None
            assert requested.task.status == "running"
            canceled_running = await _cancel_safe_point(queue, running_task.id)
            assert canceled_running.task is not None
            assert canceled_running.task.status == "canceled"

            after_running_cancel = await _read_state(int(fixture["clip_id"]))
            assert after_running_cancel["clip"]["generation_state"] == "queued"
            assert after_running_cancel["clip"]["revision"] == baseline_revision
            assert after_running_cancel["clip"]["freshness"] == baseline_freshness
            assert [task_row["status"] for task_row in after_running_cancel["tasks"]] == [
                "canceled",
                "queued",
                "failed",
            ]

            queued_canceled = await _request_cancel(queue, queued_id)
            assert queued_canceled.task is not None
            assert queued_canceled.task.status == "canceled"
            after_queued_cancel = await _read_state(int(fixture["clip_id"]))
            assert after_queued_cancel["clip"]["generation_state"] == "failed"
            assert after_queued_cancel["clip"]["revision"] == baseline_revision
            assert after_queued_cancel["clip"]["freshness"] == baseline_freshness
            assert [task_row["status"] for task_row in after_queued_cancel["tasks"]] == [
                "canceled",
                "canceled",
                "failed",
            ]
            assert after_queued_cancel["videos"] == []
        finally:
            await _cleanup_fixture_and_engine(fixture)

    asyncio.run(run())
