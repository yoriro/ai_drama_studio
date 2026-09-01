from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session_factory, engine
from app.integrations.workflow_binding import load_minimax_binding_snapshot
from app.models import Clip, Shot
from app.services.generate_clip_video import enqueue_generate_clip_video
from app.tasks.queue import TaskQueue
from tests.api.test_c009_generate_video import (
    _cleanup_fixture,
    _create_fixture,
    _read_task,
)


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _update_clip_cache(
    clip_id: int, input_hash: str, cached_prompt: str
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            """
            UPDATE clips
            SET prompt_input_hash = $1, prompt_cache = $2
            WHERE id = $3
            """,
            input_hash,
            cached_prompt,
            clip_id,
        )
    finally:
        await connection.close()


async def _set_noncontiguous_order(shot_id: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE shots SET order_index = 4 WHERE id = $1", shot_id
        )
    finally:
        await connection.close()


async def _set_current_image(asset_id: int, is_current: bool) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE asset_images SET is_current = $1 WHERE asset_id = $2",
            is_current,
            asset_id,
        )
    finally:
        await connection.close()


async def _add_second_scene(fixture: dict[str, object]) -> int:
    connection = await asyncpg.connect(_database_url())
    try:
        asset_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source)
            VALUES ($1, 'scene', '第二场景', '第二场景描述', 'manual')
            RETURNING id
            """,
            fixture["project_id"],
        )
        await connection.execute(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
            fixture["shot_ids"][0],
            asset_id,
        )
        assert asset_id is not None
        return int(asset_id)
    finally:
        await connection.close()


async def _delete_extra_scene(asset_id: int, shot_id: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM shot_assets WHERE shot_id = $1 AND asset_id = $2",
            shot_id,
            asset_id,
        )
        await connection.execute("DELETE FROM assets WHERE id = $1", asset_id)
    finally:
        await connection.close()


async def _enqueue(
    fixture: dict[str, object],
    *,
    user_note: str | None,
    user_note_provided: bool,
    request_id: str | None = None,
):
    queue = TaskQueue(async_session_factory)
    async with async_session_factory() as session:
        return await enqueue_generate_clip_video(
            session,
            queue,
            fixture["clip_id"],
            user_note=user_note,
            user_note_provided=user_note_provided,
            request_id=request_id,
            workflow_binding=load_minimax_binding_snapshot(),
        )


async def _claim_once() -> object:
    queue = TaskQueue(async_session_factory)
    async with async_session_factory() as session:
        async with session.begin():
            return await queue.claim_next(session)


def _assert_failed_task(task: dict[str, object], rule: str) -> None:
    assert task["type"] == "gen_clip_video"
    assert task["status"] == "failed"
    assert task["progress"] == 0
    assert task["started_at"] is None
    assert task["finished_at"] is not None
    assert isinstance(task["error_msg"], str)
    assert rule in task["error_msg"]
    payload = task["payload"]
    assert set(payload) == {"input_snapshot", "input_hash", "source_revisions"}
    assert payload["input_hash"] is None
    snapshot = payload["input_snapshot"]
    assert set(snapshot) == {
        "request_identity",
        "clip",
        "user_note",
        "requested_duration",
        "precheck",
    }
    assert snapshot["precheck"]["rule"] == rule
    assert isinstance(snapshot["precheck"]["reason"], str)
    assert snapshot["precheck"]["reason"]


def test_c009_enqueue_video_success_cache_and_immediate_failures(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", Path(tmp_path))

    async def run() -> None:
        fixture = await _create_fixture(Path(tmp_path))
        try:
            first = await _enqueue(
                fixture, user_note=None, user_note_provided=False
            )
            first_task = await _read_task(first.task.id)
            assert first.created is True
            assert first_task["status"] == "queued"
            first_payload = first_task["payload"]
            assert first_payload["input_hash"]
            assert first_payload["input_snapshot"]["cached_prompt"] is None

            await _update_clip_cache(
                fixture["clip_id"], first_payload["input_hash"], "缓存的 prompt"
            )
            cache_hit = await _enqueue(
                fixture, user_note=None, user_note_provided=False
            )
            cache_task = await _read_task(cache_hit.task.id)
            assert cache_hit.created is True
            assert cache_task["payload"]["input_hash"] == first_payload["input_hash"]
            assert cache_task["payload"]["input_snapshot"]["cached_prompt"] == (
                "缓存的 prompt"
            )

            fixed = await _enqueue(
                fixture,
                user_note="固定",
                user_note_provided=True,
                request_id=" abc ",
            )
            fixed_task = await _read_task(fixed.task.id)
            assert fixed_task["request_id"] == "abc"
            assert fixed_task["payload"]["input_snapshot"]["seed"] == (
                679630015510424864
            )
            assert fixed_task["payload"]["input_snapshot"]["comfy_prompt_id"] == (
                "3088d9e1-4253-5fff-896e-87e5f5312d20"
            )
        finally:
            await _cleanup_fixture(fixture)

        r5_fixture = await _create_fixture(Path(tmp_path))
        try:
            await _set_noncontiguous_order(r5_fixture["shot_ids"][1])
            failed = await _enqueue(
                r5_fixture,
                user_note="保留失败意见",
                user_note_provided=True,
                request_id="r5",
            )
            task = await _read_task(failed.task.id)
            _assert_failed_task(task, "R5")
            assert task["request_id"] == "r5"
            assert await _claim_once() is None
            async with async_session_factory() as session:
                clip = await session.scalar(
                    select(Clip).where(Clip.id == r5_fixture["clip_id"])
                )
                assert clip is not None
                assert clip.user_note == "保留失败意见"
                assert clip.revision == 2
                assert clip.freshness == "stale"
                assert clip.generation_state == "failed"
        finally:
            await _cleanup_fixture(r5_fixture)

        r5a_fixture = await _create_fixture(Path(tmp_path))
        extra_scene_id: int | None = None
        try:
            extra_scene_id = await _add_second_scene(r5a_fixture)
            failed = await _enqueue(
                r5a_fixture,
                user_note=None,
                user_note_provided=False,
                request_id="r5a",
            )
            task = await _read_task(failed.task.id)
            _assert_failed_task(task, "R5a")
            assert "more than one scene" in task["error_msg"]
            assert await _claim_once() is None
        finally:
            if extra_scene_id is not None:
                await _delete_extra_scene(
                    extra_scene_id, r5a_fixture["shot_ids"][0]
                )
            await _cleanup_fixture(r5a_fixture)

        r10_fixture = await _create_fixture(Path(tmp_path))
        try:
            await _set_current_image(r10_fixture["character_id"], False)
            failed = await _enqueue(
                r10_fixture,
                user_note=None,
                user_note_provided=False,
                request_id="r10",
            )
            task = await _read_task(failed.task.id)
            _assert_failed_task(task, "R10")
            assert "slot 1" in task["error_msg"]
            assert "活资产无 current" in task["error_msg"]
            assert await _claim_once() is None
        finally:
            await _cleanup_fixture(r10_fixture)

    try:
        asyncio.run(run())
    finally:
        asyncio.run(engine.dispose())
