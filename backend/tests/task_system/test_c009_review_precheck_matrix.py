from __future__ import annotations

import asyncio
import json
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
)


_MATRIX_CASES = (
    "r5-order-non-contiguous",
    "r5a-cross-scene",
    "r5a-multi-scene-shot",
    "r10-deleted-no-override",
    "r10-active-no-current",
    "r10-asset-current-path",
    "r10-asset-current-missing",
    "r10-asset-current-extension",
    "r10-asset-current-hash",
    "r10-override-path",
    "r10-override-missing",
    "r10-override-extension",
    "r10-override-hash",
)


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


class _HealthProbe:
    def __init__(self) -> None:
        self.calls = 0

    async def health(self) -> None:
        self.calls += 1
        return None


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


async def _prepare_case(
    case_name: str, fixture: dict[str, object], data_dir: Path
) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    state: dict[str, object] = {}
    try:
        if case_name == "r5-order-non-contiguous":
            await connection.execute(
                "UPDATE shots SET order_index = 4 WHERE id = $1",
                fixture["shot_ids"][1],
            )
        elif case_name in {"r5a-cross-scene", "r5a-multi-scene-shot"}:
            extra_scene_id = await connection.fetchval(
                """
                INSERT INTO assets (project_id, type, name, description, source)
                VALUES ($1, 'scene', $2, 'T24 second scene', 'manual')
                RETURNING id
                """,
                fixture["project_id"],
                f"T24 second scene {case_name}",
            )
            assert extra_scene_id is not None
            if case_name == "r5a-cross-scene":
                shot_id = fixture["shot_ids"][1]
                await connection.execute(
                    "DELETE FROM shot_assets WHERE shot_id = $1 AND asset_id = $2",
                    shot_id,
                    fixture["scene_id"],
                )
            else:
                shot_id = fixture["shot_ids"][0]
            await connection.execute(
                "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
                shot_id,
                extra_scene_id,
            )
            state["extra_scene_id"] = int(extra_scene_id)
            state["extra_scene_shot_id"] = int(shot_id)
        elif case_name == "r10-deleted-no-override":
            await connection.execute(
                """
                UPDATE clip_ref_slots
                SET override_image_path = NULL, override_sha256 = NULL
                WHERE id = $1
                """,
                fixture["slot_ids"]["deleted"],
            )
        elif case_name == "r10-active-no-current":
            await connection.execute(
                "UPDATE asset_images SET is_current = false WHERE asset_id = $1",
                fixture["character_id"],
            )
        elif case_name == "r10-asset-current-path":
            await connection.execute(
                "UPDATE asset_images SET file_path = $1 WHERE id = $2",
                "../outside.png",
                fixture["image_id"],
            )
        elif case_name == "r10-asset-current-missing":
            (data_dir / str(fixture["image_relative_path"])).unlink()
        elif case_name == "r10-asset-current-extension":
            await connection.execute(
                "UPDATE asset_images SET file_path = $1 WHERE id = $2",
                (
                    f"projects/{fixture['project_id']}/assets/"
                    f"{fixture['character_id']}/{fixture['image_id']}.gif"
                ),
                fixture["image_id"],
            )
        elif case_name == "r10-asset-current-hash":
            await connection.execute(
                "UPDATE asset_images SET sha256 = $1 WHERE id = $2",
                "0" * 64,
                fixture["image_id"],
            )
        elif case_name == "r10-override-path":
            await connection.execute(
                "UPDATE clip_ref_slots SET override_image_path = $1 WHERE id = $2",
                "../outside.png",
                fixture["slot_ids"]["deleted"],
            )
        elif case_name == "r10-override-missing":
            (data_dir / str(fixture["override_relative_path"])).unlink()
        elif case_name == "r10-override-extension":
            await connection.execute(
                "UPDATE clip_ref_slots SET override_image_path = $1 WHERE id = $2",
                (
                    f"projects/{fixture['project_id']}/episodes/"
                    f"{fixture['episode_id']}/clips/{fixture['clip_id']}/slots/"
                    f"{fixture['slot_ids']['deleted']}.gif"
                ),
                fixture["slot_ids"]["deleted"],
            )
        elif case_name == "r10-override-hash":
            await connection.execute(
                "UPDATE clip_ref_slots SET override_sha256 = $1 WHERE id = $2",
                "0" * 64,
                fixture["slot_ids"]["deleted"],
            )
        else:
            raise AssertionError(f"unknown T24 matrix case: {case_name}")
    finally:
        await connection.close()
    return state


async def _cleanup_case(
    fixture: dict[str, object], state: dict[str, object]
) -> None:
    extra_scene_id = state.get("extra_scene_id")
    extra_scene_shot_id = state.get("extra_scene_shot_id")
    if extra_scene_id is None or extra_scene_shot_id is None:
        return
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM shot_assets WHERE shot_id = $1 AND asset_id = $2",
            extra_scene_shot_id,
            extra_scene_id,
        )
        await connection.execute(
            "DELETE FROM assets WHERE id = $1",
            extra_scene_id,
        )
    finally:
        await connection.close()


def _expected_failure(
    case_name: str, fixture: dict[str, object]
) -> tuple[str, str]:
    if case_name == "r5-order-non-contiguous":
        return "R5", "Selected shots must have consecutive order indexes."
    if case_name == "r5a-cross-scene":
        return "R5a", "Selected shots reference more than one scene asset."
    if case_name == "r5a-multi-scene-shot":
        return (
            "R5a",
            f"Shot {fixture['shot_ids'][0]} is bound to more than one scene asset.",
        )
    if case_name == "r10-deleted-no-override":
        return "R10", "R10 slot 3: 资产已删无 override"
    if case_name == "r10-active-no-current":
        return "R10", "R10 slot 1: 活资产无 current 图片"
    if case_name == "r10-asset-current-path":
        return (
            "R10",
            "R10 slot 1: 路径、文件或 hash 不可用 "
            "(asset image path is not canonical)",
        )
    if case_name == "r10-asset-current-missing":
        return (
            "R10",
            "R10 slot 1: 路径、文件或 hash 不可用 "
            "(asset image file does not exist)",
        )
    if case_name == "r10-asset-current-extension":
        return (
            "R10",
            "R10 slot 1: 路径、文件或 hash 不可用 "
            "(Unsupported image extension: gif)",
        )
    if case_name == "r10-asset-current-hash":
        return (
            "R10",
            "R10 slot 1: 路径、文件或 hash 不可用 "
            "(asset image hash does not match)",
        )
    if case_name in {
        "r10-override-path",
        "r10-override-missing",
        "r10-override-extension",
        "r10-override-hash",
    }:
        return (
            "R10",
            "R10 slot 3: 路径、文件或 hash 不可用 "
            "(Clip source data is inconsistent)",
        )
    raise AssertionError(f"unknown T24 matrix case: {case_name}")


async def _read_clip(clip_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT user_note, revision, freshness, generation_state,
                   prompt_cache, prompt_input_hash
            FROM clips
            WHERE id = $1
            """,
            clip_id,
        )
        assert row is not None
        return {
            "user_note": row["user_note"],
            "revision": int(row["revision"]),
            "freshness": row["freshness"],
            "generation_state": row["generation_state"],
            "prompt_cache": row["prompt_cache"],
            "prompt_input_hash": row["prompt_input_hash"],
        }
    finally:
        await connection.close()


async def _read_task(task_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT id, type, target_id, request_id, payload, status, progress,
                   error_msg, started_at, finished_at
            FROM tasks
            WHERE id = $1
            """,
            task_id,
        )
        assert row is not None
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        assert isinstance(payload, dict)
        return {
            "id": int(row["id"]),
            "type": row["type"],
            "target_id": int(row["target_id"]),
            "request_id": row["request_id"],
            "payload": payload,
            "status": row["status"],
            "progress": float(row["progress"]),
            "error_msg": row["error_msg"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }
    finally:
        await connection.close()


async def _read_task_counts(clip_id: int) -> dict[str, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE status = 'queued') AS queued,
                   count(*) FILTER (WHERE status = 'running') AS running,
                   count(*) FILTER (WHERE status = 'failed') AS failed,
                   count(*) FILTER (WHERE started_at IS NOT NULL) AS started
            FROM tasks
            WHERE type = 'gen_clip_video' AND target_id = $1
            """,
            clip_id,
        )
        assert row is not None
        return {key: int(row[key]) for key in ("total", "queued", "running", "failed", "started")}
    finally:
        await connection.close()


async def _read_clip_video_count(clip_id: int) -> int:
    connection = await asyncpg.connect(_database_url())
    try:
        return int(
            await connection.fetchval(
                "SELECT count(*) FROM clip_videos WHERE clip_id = $1",
                clip_id,
            )
        )
    finally:
        await connection.close()


def _file_inventory(data_dir: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(data_dir).as_posix()
            for path in data_dir.rglob("*")
            if path.is_file()
        )
    )


def _assert_failed_task(
    response,
    task: dict[str, object],
    *,
    clip_id: int,
    request_id: str,
    user_note_provided: bool,
    user_note: str,
    clip_after: dict[str, object],
    rule: str,
    reason: str,
) -> None:
    assert response.status_code == 202
    response_body = response.json()
    assert set(response_body) == {"task_id"}
    assert response_body["task_id"] == task["id"]
    assert task["type"] == "gen_clip_video"
    assert task["target_id"] == clip_id
    assert task["request_id"] == request_id
    assert task["status"] == "failed"
    assert task["progress"] == 0.0
    assert task["started_at"] is None
    assert task["finished_at"] is not None
    assert task["error_msg"] == f"{rule}: {reason}"

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
    assert snapshot["request_identity"] == {
        "user_note_provided": user_note_provided,
        "user_note": user_note,
    }
    assert snapshot["clip"] == {
        "id": clip_id,
        "revision": clip_after["revision"],
    }
    assert snapshot["user_note"] == user_note
    assert snapshot["requested_duration"] == 5
    assert snapshot["precheck"] == {"rule": rule, "reason": reason}
    assert payload["source_revisions"]["clip"] == {
        "id": clip_id,
        "revision": clip_after["revision"],
    }


def test_c009_review_precheck_matrix_and_r5_exclusive_invariant(
    monkeypatch, tmp_path: Path
) -> None:
    data_dir = Path(tmp_path)
    monkeypatch.setattr(settings, "DATA_DIR", data_dir)
    monkeypatch.setattr(TaskQueue, "run_worker", _idle_worker)
    vllm_probe = _HealthProbe()
    comfy_probe = _HealthProbe()
    monkeypatch.setattr(app.state, "vllm_client_factory", lambda _url: vllm_probe)
    monkeypatch.setattr(app.state, "comfy_client_factory", lambda _url: comfy_probe)

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            assert vllm_probe.calls == 1
            assert comfy_probe.calls == 1
            startup_probe_calls = (vllm_probe.calls, comfy_probe.calls)

            for case_name in _MATRIX_CASES:
                for mutation in (False, True):
                    fixture = asyncio.run(_create_fixture(data_dir))
                    case_state: dict[str, object] = {}
                    try:
                        case_state = asyncio.run(
                            _prepare_case(case_name, fixture, data_dir)
                        )
                        rule, reason = _expected_failure(case_name, fixture)
                        before_clip = asyncio.run(_read_clip(fixture["clip_id"]))
                        assert before_clip == {
                            "user_note": "原始意见",
                            "revision": 1,
                            "freshness": "fresh",
                            "generation_state": "empty",
                            "prompt_cache": None,
                            "prompt_input_hash": None,
                        }
                        before_files = _file_inventory(data_dir)
                        user_note = "T24 实际 mutation" if mutation else "原始意见"
                        user_note_provided = mutation
                        request_id = f"t24-{case_name}-{'changed' if mutation else 'same'}"

                        body = {"request_id": request_id}
                        if mutation:
                            body["user_note"] = user_note
                        response = client.post(
                            f"/api/clips/{fixture['clip_id']}/generate-video",
                            json=body,
                        )
                        response_body = response.json()
                        assert response.status_code == 202
                        assert set(response_body) == {"task_id"}
                        task_id = response_body["task_id"]
                        assert isinstance(task_id, int) and task_id > 0

                        after_clip = asyncio.run(_read_clip(fixture["clip_id"]))
                        assert after_clip["user_note"] == user_note
                        assert after_clip["revision"] == (2 if mutation else 1)
                        assert after_clip["freshness"] == ("stale" if mutation else "fresh")
                        assert after_clip["generation_state"] == "failed"
                        assert after_clip["prompt_cache"] is None
                        assert after_clip["prompt_input_hash"] is None

                        task = asyncio.run(_read_task(task_id))
                        _assert_failed_task(
                            response,
                            task,
                            clip_id=fixture["clip_id"],
                            request_id=request_id,
                            user_note_provided=user_note_provided,
                            user_note=user_note,
                            clip_after=after_clip,
                            rule=rule,
                            reason=reason,
                        )
                        assert asyncio.run(_read_task_counts(fixture["clip_id"])) == {
                            "total": 1,
                            "queued": 0,
                            "running": 0,
                            "failed": 1,
                            "started": 0,
                        }
                        assert asyncio.run(_read_clip_video_count(fixture["clip_id"])) == 0
                        assert _file_inventory(data_dir) == before_files
                        assert (vllm_probe.calls, comfy_probe.calls) == startup_probe_calls
                    finally:
                        asyncio.run(_cleanup_case(fixture, case_state))
                        asyncio.run(_cleanup_fixture(fixture))
    finally:
        asyncio.run(engine.dispose())
