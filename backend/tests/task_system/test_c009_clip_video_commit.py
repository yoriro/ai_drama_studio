from __future__ import annotations

import asyncio
import copy
import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

import asyncpg
import av
import pytest
from app.core.config import settings
from app.db.session import async_session_factory, engine
from app.integrations.workflow_binding import load_minimax_binding_snapshot
from app.services import clip_video_commit
from app.services.clip_video_commit import (
    ClipVideoPersistenceError,
    commit_generated_clip_video,
)
from app.services.generate_clip_video import enqueue_generate_clip_video
from app.services.video_files import clip_video_paths, temporary_clip_video_path
from app.tasks import gen_clip_video as video_task
from app.tasks.gen_clip_video import GeneratedClipVideo
from app.tasks.queue import ClaimedTask, TaskQueue
from tests.api.test_c009_generate_video import (
    _cleanup_fixture,
    _create_fixture,
)


def _database_url() -> str:
    return settings.DATABASE_URL.get_secret_value().replace("+asyncpg", "", 1)


def _video_bytes() -> bytes:
    output = io.BytesIO()
    container = av.open(output, mode="w", format="mp4")
    stream = container.add_stream("mpeg4", rate=24)
    stream.width = 16
    stream.height = 16
    stream.pix_fmt = "yuv420p"
    for _ in range(3):
        frame = av.VideoFrame(16, 16, "yuv420p")
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return output.getvalue()


async def _enqueue_and_claim(fixture: dict[str, object]) -> tuple[TaskQueue, ClaimedTask]:
    queue = TaskQueue(async_session_factory)
    async with async_session_factory() as session:
        await enqueue_generate_clip_video(
            session,
            queue,
            fixture["clip_id"],
            user_note=None,
            user_note_provided=False,
            request_id=None,
            workflow_binding=load_minimax_binding_snapshot(),
        )

    async with async_session_factory() as session:
        async with session.begin():
            change = await queue.claim_next(session)
        assert change is not None and change.changed and change.task is not None
        task = change.task
        return queue, ClaimedTask(
            id=int(task.id),
            type="gen_clip_video",
            target_id=int(task.target_id),
            request_id=task.request_id,
            payload=copy.deepcopy(task.payload),
        )


async def _cleanup_fixture_and_engine(fixture: dict[str, object]) -> None:
    try:
        await _cleanup_fixture(fixture)
    finally:
        await engine.dispose()


def _write_temp(data_dir: Path, task: ClaimedTask) -> tuple[Path, bytes]:
    raw = _video_bytes()
    temp_path = temporary_clip_video_path(data_dir, task.id)
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_bytes(raw)
    return temp_path, raw


async def _read_commit_state(fixture: dict[str, object]) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        clip = await connection.fetchrow(
            """
            SELECT prompt_cache, prompt_input_hash, freshness, generation_state
            FROM clips WHERE id = $1
            """,
            fixture["clip_id"],
        )
        shots = await connection.fetch(
            "SELECT id, status, revision FROM shots WHERE id = ANY($1::int[]) ORDER BY id",
            fixture["shot_ids"],
        )
        videos = await connection.fetch(
            """
            SELECT id, clip_id, file_path, sha256, seed, requested_duration,
                   actual_duration, is_current, built_prompt, input_hash
            FROM clip_videos WHERE clip_id = $1 ORDER BY id
            """,
            fixture["clip_id"],
        )
        tasks = await connection.fetch(
            """
            SELECT id, status, progress, error_msg, finished_at
            FROM tasks WHERE target_id = $1 AND type = 'gen_clip_video'
            ORDER BY id
            """,
            fixture["clip_id"],
        )
        assert clip is not None
        return {
            "clip": dict(clip),
            "shots": [dict(row) for row in shots],
            "videos": [dict(row) for row in videos],
            "tasks": [dict(row) for row in tasks],
        }
    finally:
        await connection.close()


def test_c009_clip_video_commit_first_take_is_atomic_and_uses_probed_duration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    async def run() -> None:
        fixture = await _create_fixture(tmp_path)
        try:
            queue, task = await _enqueue_and_claim(fixture)
            temp_path, raw = _write_temp(tmp_path, task)
            expected_hash = task.payload["input_hash"]
            generated = GeneratedClipVideo(temp_path=temp_path, built_prompt="built prompt")

            async with async_session_factory() as session:
                completed = await commit_generated_clip_video(
                    session,
                    queue,
                    task,
                    generated,
                    data_dir=tmp_path,
                )
            assert completed is not None and completed.changed is True
            assert completed.task is not None and completed.task.status == "done"

            state = await _read_commit_state(fixture)
            clip = state["clip"]
            videos = state["videos"]
            tasks = state["tasks"]
            assert clip["prompt_cache"] == "built prompt"
            assert clip["prompt_input_hash"] == expected_hash
            assert clip["freshness"] == "fresh"
            assert clip["generation_state"] == "ready"
            assert [row["status"] for row in state["shots"]] == ["normal", "normal"]
            assert len(videos) == 1
            video = videos[0]
            relative, formal, trash = clip_video_paths(
                tmp_path,
                fixture["project_id"],
                fixture["episode_id"],
                fixture["clip_id"],
                video["id"],
            )
            assert video["file_path"] == relative.as_posix()
            assert video["sha256"] == hashlib.sha256(raw).hexdigest()
            assert video["seed"] == task.payload["input_snapshot"]["seed"]
            assert video["requested_duration"] == 5
            assert video["actual_duration"] == pytest.approx(0.125)
            assert video["actual_duration"] != video["requested_duration"]
            assert video["is_current"] is True
            assert video["built_prompt"] == "built prompt"
            assert video["input_hash"] == expected_hash
            assert formal.read_bytes() == raw
            assert not temp_path.exists()
            assert not trash.exists()
            assert len(tasks) == 1
            assert tasks[0]["status"] == "done"
            assert tasks[0]["progress"] == 1
            assert tasks[0]["finished_at"] is not None
        finally:
            await _cleanup_fixture_and_engine(fixture)

    asyncio.run(run())


def test_c009_clip_video_commit_subsequent_take_keeps_current_and_cache_hit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    async def run() -> None:
        fixture = await _create_fixture(tmp_path)
        try:
            queue, first_task = await _enqueue_and_claim(fixture)
            first_temp, _ = _write_temp(tmp_path, first_task)
            async with async_session_factory() as session:
                first_completed = await commit_generated_clip_video(
                    session,
                    queue,
                    first_task,
                    GeneratedClipVideo(first_temp, "first prompt"),
                    data_dir=tmp_path,
                )
            assert first_completed is not None

            second_queue, second_task = await _enqueue_and_claim(fixture)
            assert second_task.payload["input_snapshot"]["cached_prompt"] == "first prompt"
            second_temp, _ = _write_temp(tmp_path, second_task)
            async with async_session_factory() as session:
                second_completed = await commit_generated_clip_video(
                    session,
                    second_queue,
                    second_task,
                    GeneratedClipVideo(second_temp, "first prompt"),
                    data_dir=tmp_path,
                )
            assert second_completed is not None

            state = await _read_commit_state(fixture)
            assert state["clip"]["prompt_cache"] == "first prompt"
            assert state["clip"]["prompt_input_hash"] == first_task.payload["input_hash"]
            assert state["clip"]["generation_state"] == "ready"
            assert [row["is_current"] for row in state["videos"]] == [True, False]
            assert [row["built_prompt"] for row in state["videos"]] == [
                "first prompt",
                "first prompt",
            ]
            assert [row["status"] for row in state["tasks"]] == ["done", "done"]
        finally:
            await _cleanup_fixture_and_engine(fixture)

    asyncio.run(run())


@pytest.mark.parametrize("drift", ["clip", "shot", "asset", "delete_asset"])
def test_c009_clip_video_commit_saves_take_without_promoting_drifted_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, drift: str
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    async def run() -> None:
        fixture = await _create_fixture(tmp_path)
        try:
            queue, task = await _enqueue_and_claim(fixture)
            connection = await asyncpg.connect(_database_url())
            try:
                await connection.execute(
                    "UPDATE clips SET freshness = 'stale' WHERE id = $1",
                    fixture["clip_id"],
                )
                await connection.execute(
                    "UPDATE shots SET status = 'changed' WHERE id = ANY($1::int[])",
                    fixture["shot_ids"],
                )
                if drift == "clip":
                    await connection.execute(
                        "UPDATE clips SET revision = revision + 1 WHERE id = $1",
                        fixture["clip_id"],
                    )
                elif drift == "shot":
                    await connection.execute(
                        "UPDATE shots SET revision = revision + 1 WHERE id = $1",
                        fixture["shot_ids"][0],
                    )
                elif drift == "asset":
                    await connection.execute(
                        "UPDATE assets SET revision = revision + 1 WHERE id = $1",
                        fixture["character_id"],
                    )
                else:
                    await connection.execute(
                        "DELETE FROM asset_images WHERE asset_id = $1",
                        fixture["character_id"],
                    )
                    await connection.execute(
                        "DELETE FROM shot_assets WHERE asset_id = $1",
                        fixture["character_id"],
                    )
                    await connection.execute(
                        "DELETE FROM assets WHERE id = $1",
                        fixture["character_id"],
                    )
            finally:
                await connection.close()

            temp_path, _ = _write_temp(tmp_path, task)
            async with async_session_factory() as session:
                completed = await commit_generated_clip_video(
                    session,
                    queue,
                    task,
                    GeneratedClipVideo(temp_path, f"{drift} prompt"),
                    data_dir=tmp_path,
                )
            assert completed is not None

            state = await _read_commit_state(fixture)
            assert len(state["videos"]) == 1
            assert state["clip"]["freshness"] == "stale"
            assert [row["status"] for row in state["shots"]] == ["changed", "changed"]
            assert state["clip"]["generation_state"] == "ready"
            assert state["tasks"][0]["status"] == "done"
            assert not temp_path.exists()
        finally:
            await _cleanup_fixture_and_engine(fixture)

    asyncio.run(run())


def test_c009_registered_task_handler_commits_core_result_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    async def run() -> None:
        fixture = await _create_fixture(tmp_path)
        try:
            queue, task = await _enqueue_and_claim(fixture)
            temp_path, _ = _write_temp(tmp_path, task)
            generated = GeneratedClipVideo(temp_path, "adapter prompt")

            async def fake_core(
                _task: ClaimedTask, _context: object
            ) -> GeneratedClipVideo:
                return generated

            monkeypatch.setattr(video_task, "gen_clip_video_handler", fake_core)
            await video_task.gen_clip_video_task_handler(
                task, SimpleNamespace(queue=queue)
            )

            state = await _read_commit_state(fixture)
            assert len(state["videos"]) == 1
            assert state["tasks"][0]["status"] == "done"
            assert state["tasks"][0]["progress"] == 1
            assert not temp_path.exists()
        finally:
            await _cleanup_fixture_and_engine(fixture)

    asyncio.run(run())


@pytest.mark.parametrize(
    ("failure_at_flush", "error_text", "formal_is_compensated"),
    [
        (1, "insert-flush-primary", False),
        (2, "final-flush-primary", True),
    ],
    ids=["before-rename", "after-rename"],
)
def test_c009_clip_video_commit_db_write_failure_has_no_orphan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_at_flush: int,
    error_text: str,
    formal_is_compensated: bool,
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    async def run() -> None:
        fixture = await _create_fixture(tmp_path)
        try:
            queue, task = await _enqueue_and_claim(fixture)
            temp_path, _ = _write_temp(tmp_path, task)
            async with async_session_factory() as session:
                original_flush = session.flush
                flush_count = 0

                async def failing_flush(*args: object, **kwargs: object) -> None:
                    nonlocal flush_count
                    flush_count += 1
                    if flush_count == failure_at_flush:
                        raise RuntimeError(error_text)
                    await original_flush(*args, **kwargs)

                monkeypatch.setattr(session, "flush", failing_flush)
                with pytest.raises(RuntimeError, match=error_text):
                    await commit_generated_clip_video(
                        session,
                        queue,
                        task,
                        GeneratedClipVideo(temp_path, "failed prompt"),
                        data_dir=tmp_path,
                    )

            state = await _read_commit_state(fixture)
            assert state["videos"] == []
            assert state["tasks"][0]["status"] == "running"
            assert state["clip"]["prompt_cache"] is None
            assert not temp_path.exists()
            formal_files = list((tmp_path / "projects").rglob("*.mp4"))
            trash_files = list((tmp_path / "trash").rglob("*.mp4"))
            if formal_is_compensated:
                assert formal_files == []
                assert len(trash_files) == 1
            else:
                assert formal_files == []
                assert trash_files == []
        finally:
            await _cleanup_fixture_and_engine(fixture)

    asyncio.run(run())


def test_c009_clip_video_commit_preserves_primary_and_trash_compensation_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    async def run() -> None:
        fixture = await _create_fixture(tmp_path)
        try:
            queue, task = await _enqueue_and_claim(fixture)
            temp_path, _ = _write_temp(tmp_path, task)

            async def fail_complete(_session: object, _task_id: int) -> object:
                raise RuntimeError("db-primary")

            def fail_trash(_formal: Path, _trash: Path) -> None:
                raise OSError("trash-secondary")

            monkeypatch.setattr(queue, "complete", fail_complete)
            monkeypatch.setattr(clip_video_commit, "_move_formal_to_trash", fail_trash)
            async with async_session_factory() as session:
                with pytest.raises(ClipVideoPersistenceError) as raised:
                    await commit_generated_clip_video(
                        session,
                        queue,
                        task,
                        GeneratedClipVideo(temp_path, "failed prompt"),
                        data_dir=tmp_path,
                    )
            assert "db-primary" in str(raised.value)
            assert "trash-secondary" in str(raised.value)
            state = await _read_commit_state(fixture)
            assert state["videos"] == []
            assert state["tasks"][0]["status"] == "running"
            assert not temp_path.exists()
            assert len(list((tmp_path / "projects").rglob("*.mp4"))) == 1
            assert list((tmp_path / "trash").rglob("*.mp4")) == []
        finally:
            await _cleanup_fixture_and_engine(fixture)

    asyncio.run(run())


def test_c009_clip_video_commit_cancellation_marker_wins_before_insert(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    async def run() -> None:
        fixture = await _create_fixture(tmp_path)
        try:
            queue, task = await _enqueue_and_claim(fixture)
            connection = await asyncpg.connect(_database_url())
            try:
                await connection.execute(
                    "UPDATE tasks SET cancel_requested_at = now() WHERE id = $1",
                    task.id,
                )
            finally:
                await connection.close()
            temp_path, _ = _write_temp(tmp_path, task)

            async with async_session_factory() as session:
                completed = await commit_generated_clip_video(
                    session,
                    queue,
                    task,
                    GeneratedClipVideo(temp_path, "cancelled prompt"),
                    data_dir=tmp_path,
                )
            assert completed is None
            state = await _read_commit_state(fixture)
            assert state["videos"] == []
            assert state["tasks"][0]["status"] == "running"
            assert state["clip"]["prompt_cache"] is None
            assert not temp_path.exists()
            assert list((tmp_path / "projects").rglob("*.mp4")) == []
        finally:
            await _cleanup_fixture_and_engine(fixture)

    asyncio.run(run())
