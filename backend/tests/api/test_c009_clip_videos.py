from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import asyncpg
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import engine
from app.main import app
from app.services.video_files import clip_video_paths
from app.tasks.queue import TaskQueue
from tests.api.test_c009_generate_video import (
    _cleanup_fixture,
    _create_fixture,
    _HealthProbe,
    _idle_worker,
)
from tests.task_system.test_c009_clip_video_commit import _video_bytes


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _configure_app(monkeypatch) -> None:
    monkeypatch.setattr(TaskQueue, "run_worker", _idle_worker)
    monkeypatch.setattr(
        app.state,
        "vllm_client_factory",
        lambda _url: _HealthProbe(),
    )
    monkeypatch.setattr(
        app.state,
        "comfy_client_factory",
        lambda _url: _HealthProbe(),
    )


async def _insert_video(
    fixture: dict[str, object],
    data_dir: Path,
    *,
    seed: int,
    is_current: bool,
    content: bytes | None = None,
) -> tuple[int, str, bytes]:
    raw = _video_bytes() if content is None else content
    digest = hashlib.sha256(raw).hexdigest()
    snapshot = {"seed": seed, "marker": f"snapshot-{seed}"}
    connection = await asyncpg.connect(_database_url())
    try:
        video_id = await connection.fetchval(
            """
            INSERT INTO clip_videos
                (clip_id, file_path, sha256, seed, requested_duration,
                 actual_duration, is_current, built_prompt, input_hash,
                 input_snapshot)
            VALUES ($1, 'pending', $2, $3, 5, 2.25, $4, $5, $6, $7::jsonb)
            RETURNING id
            """,
            fixture["clip_id"],
            digest,
            seed,
            is_current,
            f"built-{seed}",
            f"hash-{seed}",
            json.dumps(snapshot),
        )
        assert video_id is not None
        relative, _, _ = clip_video_paths(
            data_dir,
            int(fixture["project_id"]),
            int(fixture["episode_id"]),
            int(fixture["clip_id"]),
            int(video_id),
        )
        await connection.execute(
            "UPDATE clip_videos SET file_path = $1 WHERE id = $2",
            relative.as_posix(),
            video_id,
        )
    finally:
        await connection.close()

    file_path = data_dir / relative
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(raw)
    return int(video_id), relative.as_posix(), raw


async def _read_clip_projection(clip_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT revision, freshness, generation_state
            FROM clips
            WHERE id = $1
            """,
            clip_id,
        )
        assert row is not None
        return dict(row)
    finally:
        await connection.close()


async def _read_video_rows(clip_id: int) -> list[dict[str, object]]:
    connection = await asyncpg.connect(_database_url())
    try:
        rows = await connection.fetch(
            """
            SELECT id, file_path, sha256, is_current
            FROM clip_videos
            WHERE clip_id = $1
            ORDER BY id
            """,
            clip_id,
        )
        return [dict(row) for row in rows]
    finally:
        await connection.close()


async def _read_stored_snapshot(video_id: int) -> object:
    connection = await asyncpg.connect(_database_url())
    try:
        return await connection.fetchval(
            "SELECT input_snapshot FROM clip_videos WHERE id = $1",
            video_id,
        )
    finally:
        await connection.close()


def _assert_error(
    response, status_code: int, code: str, message: str
) -> None:
    assert response.status_code == status_code
    assert response.json() == {
        "detail": {"code": code, "message": message}
    }


def _assert_base_item(item: dict[str, object], *, seed: int, digest: str) -> None:
    assert set(item) == {
        "id",
        "clip_id",
        "sha256",
        "seed",
        "requested_duration",
        "actual_duration",
        "is_current",
        "media_url",
        "created_at",
    }
    assert item["seed"] == str(seed)
    assert item["sha256"] == digest
    assert item["requested_duration"] == 5
    assert item["actual_duration"] == 2.25
    assert item["media_url"] == f"/media/clip-videos/{item['id']}"
    assert isinstance(item["created_at"], str)
    datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))


def test_c009_clip_videos_list_current_switch_and_debug_contract(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        first_id, _, first_bytes = asyncio.run(
            _insert_video(
                fixture,
                tmp_path,
                seed=9_223_372_036_854_775_807,
                is_current=True,
            )
        )
        second_id, _, second_bytes = asyncio.run(
            _insert_video(fixture, tmp_path, seed=17, is_current=False)
        )
        del first_bytes, second_bytes
        first_digest = hashlib.sha256(_video_bytes()).hexdigest()
        second_digest = first_digest
        before = asyncio.run(_read_clip_projection(int(fixture["clip_id"])))
        _configure_app(monkeypatch)

        with TestClient(app, raise_server_exceptions=False) as client:
            listed = client.get(f"/api/clips/{fixture['clip_id']}/videos")
            assert listed.status_code == 200
            items = listed.json()
            assert [item["id"] for item in items] == [first_id, second_id]
            _assert_base_item(
                items[0], seed=9_223_372_036_854_775_807, digest=first_digest
            )
            _assert_base_item(items[1], seed=17, digest=second_digest)
            assert [item["is_current"] for item in items] == [True, False]
            assert all(
                field not in listed.text
                for field in ("file_path", "built_prompt", "input_hash", "input_snapshot")
            )

            switched = client.put(
                f"/api/clips/{fixture['clip_id']}/current-video",
                json={"video_id": second_id},
            )
            assert switched.status_code == 200
            switched_item = switched.json()
            _assert_base_item(switched_item, seed=17, digest=second_digest)
            assert switched_item["is_current"] is True

            after_switch = asyncio.run(
                _read_clip_projection(int(fixture["clip_id"]))
            )
            assert after_switch == before
            rows = asyncio.run(_read_video_rows(int(fixture["clip_id"])))
            assert [row["is_current"] for row in rows] == [False, True]

            no_op = client.put(
                f"/api/clips/{fixture['clip_id']}/current-video",
                json={"video_id": second_id},
            )
            assert no_op.status_code == 200
            assert no_op.json() == switched_item

            monkeypatch.setattr(settings, "DEBUG_PROMPTS", True)
            debug = client.get(f"/api/clips/{fixture['clip_id']}/videos")
            assert debug.status_code == 200
            debug_items = debug.json()
            assert set(debug_items[0]) == {
                "id",
                "clip_id",
                "sha256",
                "seed",
                "requested_duration",
                "actual_duration",
                "is_current",
                "media_url",
                "created_at",
                "built_prompt",
                "input_snapshot",
            }
            first_debug = debug_items[0]
            assert first_debug["built_prompt"] == "built-9223372036854775807"
            assert first_debug["input_snapshot"] == {
                "seed": "9223372036854775807",
                "marker": "snapshot-9223372036854775807",
            }
            assert debug_items[1]["built_prompt"] == "built-17"
            assert debug_items[1]["input_snapshot"] == {
                "seed": "17",
                "marker": "snapshot-17",
            }

        stored = asyncio.run(_read_stored_snapshot(first_id))
        if isinstance(stored, str):
            stored = json.loads(stored)
        assert stored["seed"] == 9_223_372_036_854_775_807
    finally:
        asyncio.run(_cleanup_fixture(fixture))
        asyncio.run(engine.dispose())


def test_c009_clip_videos_current_rejects_unknown_cross_clip_and_extra_body(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    first_fixture = asyncio.run(_create_fixture(tmp_path))
    second_fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        first_id, _, _ = asyncio.run(
            _insert_video(first_fixture, tmp_path, seed=101, is_current=True)
        )
        second_id, _, _ = asyncio.run(
            _insert_video(second_fixture, tmp_path, seed=202, is_current=True)
        )
        _configure_app(monkeypatch)
        with TestClient(app, raise_server_exceptions=False) as client:
            _assert_error(
                client.get("/api/clips/2147483647/videos"),
                404,
                "not_found",
                "Clip not found",
            )
            _assert_error(
                client.put(
                    "/api/clips/2147483647/current-video",
                    json={"video_id": first_id},
                ),
                404,
                "not_found",
                "Clip not found",
            )
            _assert_error(
                client.put(
                    f"/api/clips/{first_fixture['clip_id']}/current-video",
                    json={"video_id": 2147483647},
                ),
                404,
                "not_found",
                "Clip video not found",
            )
            _assert_error(
                client.put(
                    f"/api/clips/{first_fixture['clip_id']}/current-video",
                    json={"video_id": second_id},
                ),
                422,
                "validation_error",
                "video_id does not reference a video of this clip",
            )
            _assert_error(
                client.put(
                    f"/api/clips/{first_fixture['clip_id']}/current-video",
                    json={"video_id": first_id, "extra": True},
                ),
                422,
                "validation_error",
                "Request validation failed",
            )
    finally:
        asyncio.run(_cleanup_fixture(second_fixture))
        asyncio.run(_cleanup_fixture(first_fixture))
        asyncio.run(engine.dispose())
