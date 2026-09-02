from __future__ import annotations

import asyncio
import copy
import os
from pathlib import Path

import asyncpg
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import engine
from app.main import app
from app.tasks.queue import TaskQueue
from tests.api.test_c009_generate_video import (
    _cleanup_fixture,
    _create_fixture,
    _read_task,
)


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _read_clip_state(clip_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT generation_mode, user_note, revision, freshness, generation_state
            FROM clips
            WHERE id = $1
            """,
            clip_id,
        )
        assert row is not None
        slot_rows = await connection.fetch(
            """
            SELECT slot_no, enabled
            FROM clip_ref_slots
            WHERE clip_id = $1
            ORDER BY slot_no, id
            """,
            clip_id,
        )
        return {
            "generation_mode": row["generation_mode"],
            "user_note": row["user_note"],
            "revision": int(row["revision"]),
            "freshness": row["freshness"],
            "generation_state": row["generation_state"],
            "slots": [(int(item["slot_no"]), bool(item["enabled"])) for item in slot_rows],
        }
    finally:
        await connection.close()


async def _read_task_count(clip_id: int) -> int:
    connection = await asyncpg.connect(_database_url())
    try:
        return int(
            await connection.fetchval(
                """
                SELECT count(*)
                FROM tasks
                WHERE type = 'gen_clip_video' AND target_id = $1
                """,
                clip_id,
            )
        )
    finally:
        await connection.close()


async def _set_all_slots_disabled(clip_id: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE clip_ref_slots SET enabled = false WHERE clip_id = $1",
            clip_id,
        )
    finally:
        await connection.close()


async def _set_generation_mode(clip_id: int, mode: str) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE clips SET generation_mode = $1 WHERE id = $2",
            mode,
            clip_id,
        )
    finally:
        await connection.close()


async def _idle_worker(
    self,
    *,
    handlers,
    stop_event=None,
    poll_interval=0.5,
    stop_when_idle=False,
) -> None:
    del self, handlers, poll_interval, stop_when_idle
    assert stop_event is not None
    await stop_event.wait()


class _HealthProbe:
    def __init__(self) -> None:
        self.calls = 0

    async def health(self) -> None:
        self.calls += 1
        return None


def _assert_conflict(response, message: str) -> None:
    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "conflict",
            "message": message,
        }
    }


def test_c009_zero_enabled_and_unsupported_modes_are_atomic_conflicts(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(TaskQueue, "run_worker", _idle_worker)
    vllm_probe = _HealthProbe()
    comfy_probe = _HealthProbe()
    monkeypatch.setattr(app.state, "vllm_client_factory", lambda _url: vllm_probe)
    monkeypatch.setattr(app.state, "comfy_client_factory", lambda _url: comfy_probe)
    fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            startup_probe_calls = (vllm_probe.calls, comfy_probe.calls)
            asyncio.run(_set_all_slots_disabled(fixture["clip_id"]))
            before_clip = asyncio.run(_read_clip_state(fixture["clip_id"]))
            assert before_clip["slots"] == [(1, False), (2, False), (3, False)]
            assert asyncio.run(_read_task_count(fixture["clip_id"])) == 0
            response = client.post(
                f"/api/clips/{fixture['clip_id']}/generate-video",
                json={"user_note": "零槽位新意见"},
            )
            _assert_conflict(
                response,
                "At least one reference slot must be enabled",
            )
            assert asyncio.run(_read_clip_state(fixture["clip_id"])) == before_clip
            assert asyncio.run(_read_task_count(fixture["clip_id"])) == 0
            assert (vllm_probe.calls, comfy_probe.calls) == startup_probe_calls

            for mode in ("fl2v", "context_loop"):
                mode_fixture = asyncio.run(_create_fixture(tmp_path))
                try:
                    asyncio.run(_set_generation_mode(mode_fixture["clip_id"], mode))
                    mode_before = asyncio.run(_read_clip_state(mode_fixture["clip_id"]))
                    assert mode_before["generation_mode"] == mode
                    assert asyncio.run(_read_task_count(mode_fixture["clip_id"])) == 0
                    mode_response = client.post(
                        f"/api/clips/{mode_fixture['clip_id']}/generate-video",
                        json={"user_note": f"{mode} 新意见"},
                    )
                    _assert_conflict(
                        mode_response,
                        "Clip generation mode is not supported in v1",
                    )
                    assert asyncio.run(_read_clip_state(mode_fixture["clip_id"])) == mode_before
                    assert asyncio.run(_read_task_count(mode_fixture["clip_id"])) == 0
                    assert (vllm_probe.calls, comfy_probe.calls) == startup_probe_calls
                finally:
                    asyncio.run(_cleanup_fixture(mode_fixture))
    finally:
        asyncio.run(_cleanup_fixture(fixture))
        asyncio.run(engine.dispose())


def test_c009_request_id_replay_skips_current_prerequisite_recheck(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(TaskQueue, "run_worker", _idle_worker)
    vllm_probe = _HealthProbe()
    comfy_probe = _HealthProbe()
    monkeypatch.setattr(app.state, "vllm_client_factory", lambda _url: vllm_probe)
    monkeypatch.setattr(app.state, "comfy_client_factory", lambda _url: comfy_probe)
    fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            startup_probe_calls = (vllm_probe.calls, comfy_probe.calls)
            first_response = client.post(
                f"/api/clips/{fixture['clip_id']}/generate-video",
                json={"user_note": "冻结意见", "request_id": " replay-id "},
            )
            assert first_response.status_code == 202
            first_body = first_response.json()
            assert set(first_body) == {"task_id"}
            first_task_id = first_body["task_id"]
            frozen_task = copy.deepcopy(asyncio.run(_read_task(first_task_id)))
            frozen_clip = asyncio.run(_read_clip_state(fixture["clip_id"]))
            assert frozen_task["request_id"] == "replay-id"
            assert frozen_clip["user_note"] == "冻结意见"
            assert asyncio.run(_read_task_count(fixture["clip_id"])) == 1

            asyncio.run(_set_all_slots_disabled(fixture["clip_id"]))
            asyncio.run(_set_generation_mode(fixture["clip_id"], "fl2v"))
            changed_clip = asyncio.run(_read_clip_state(fixture["clip_id"]))
            assert changed_clip["generation_mode"] == "fl2v"
            assert changed_clip["slots"] == [(1, False), (2, False), (3, False)]

            replay = client.post(
                f"/api/clips/{fixture['clip_id']}/generate-video",
                json={"user_note": "冻结意见", "request_id": "replay-id"},
            )
            assert replay.status_code == 202
            assert replay.json() == {"task_id": first_task_id}
            assert asyncio.run(_read_task(first_task_id)) == frozen_task
            assert asyncio.run(_read_task_count(fixture["clip_id"])) == 1
            assert asyncio.run(_read_clip_state(fixture["clip_id"])) == changed_clip
            assert (vllm_probe.calls, comfy_probe.calls) == startup_probe_calls
    finally:
        asyncio.run(_cleanup_fixture(fixture))
        asyncio.run(engine.dispose())
