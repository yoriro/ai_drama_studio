from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import engine
from app.main import app
from app.services.asset_files import asset_image_relative_path
from app.services.clip_video_inputs import build_clip_video_input_hash
from app.tasks.queue import TaskQueue


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


async def _create_fixture(data_dir: Path) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        suffix = uuid4().hex
        original_template = await connection.fetchval(
            "SELECT content FROM prompt_templates WHERE key = 'minimaxh3'"
        )
        assert isinstance(original_template, str)
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, '电影写实')
            RETURNING id
            """,
            f"C009 T9 style {suffix}",
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            f"C009 T9 project {suffix}",
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, 'T9 episode', 'T9')
            RETURNING id
            """,
            project_id,
        )
        character_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source)
            VALUES ($1, 'character', '林夏', '黑发白衬衫', 'manual')
            RETURNING id
            """,
            project_id,
        )
        scene_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source)
            VALUES ($1, 'scene', '雨夜街道', '霓虹灯下的街道', 'manual')
            RETURNING id
            """,
            project_id,
        )
        shot_ids: list[int] = []
        for order_index, description in ((1, "街角等待"), (2, "抬头望雨")):
            shot_id = await connection.fetchval(
                """
                INSERT INTO shots
                    (episode_id, order_index, duration_est, shot_type, camera,
                     description, dialogue, status, revision)
                VALUES ($1, $2, 2, '中景', '固定', $3, '', 'normal', 1)
                RETURNING id
                """,
                episode_id,
                order_index,
                description,
            )
            shot_ids.append(int(shot_id))
            await connection.executemany(
                "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
                [(shot_id, character_id), (shot_id, scene_id)],
            )

        clip_id = await connection.fetchval(
            """
            INSERT INTO clips (episode_id, user_note, requested_duration)
            VALUES ($1, '原始意见', 5)
            RETURNING id
            """,
            episode_id,
        )
        await connection.executemany(
            "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, $3)",
            [(clip_id, shot_ids[0], 1), (clip_id, shot_ids[1], 2)],
        )
        slot_ids: dict[str, int] = {}
        slot_ids["current"] = int(
            await connection.fetchval(
                """
                INSERT INTO clip_ref_slots
                    (clip_id, slot_no, asset_id, asset_name_snapshot,
                     asset_type_snapshot, enabled)
                VALUES ($1, 1, $2, '林夏', 'character', true)
                RETURNING id
                """,
                clip_id,
                character_id,
            )
        )
        slot_ids["disabled"] = int(
            await connection.fetchval(
                """
                INSERT INTO clip_ref_slots
                    (clip_id, slot_no, asset_id, asset_name_snapshot,
                     asset_type_snapshot, enabled)
                VALUES ($1, 2, $2, '雨夜街道', 'scene', false)
                RETURNING id
                """,
                clip_id,
                scene_id,
            )
        )
        slot_ids["deleted"] = int(
            await connection.fetchval(
                """
                INSERT INTO clip_ref_slots
                    (clip_id, slot_no, asset_id, asset_name_snapshot,
                     asset_type_snapshot, enabled)
                VALUES ($1, 3, NULL, '已删人物', 'character', true)
                RETURNING id
                """,
                clip_id,
            )
        )

        image_id = int(
            await connection.fetchval(
                """
                INSERT INTO asset_images
                    (asset_id, file_path, sha256, source, is_current)
                VALUES ($1, 'pending', $2, 'uploaded', true)
                RETURNING id
                """,
                character_id,
                "0" * 64,
            )
        )
        image_relative_path = asset_image_relative_path(
            int(project_id), int(character_id), image_id, "png"
        )
        image_path = data_dir / image_relative_path
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_bytes = b"c009-t9-current-image"
        image_path.write_bytes(image_bytes)
        image_digest = hashlib.sha256(image_bytes).hexdigest()
        await connection.execute(
            """
            UPDATE asset_images
            SET file_path = $1, sha256 = $2
            WHERE id = $3
            """,
            image_relative_path.as_posix(),
            image_digest,
            image_id,
        )

        override_relative_path = Path(
            "projects",
            str(project_id),
            "episodes",
            str(episode_id),
            "clips",
            str(clip_id),
            "slots",
            f"{slot_ids['deleted']}.png",
        )
        override_path = data_dir / override_relative_path
        override_path.parent.mkdir(parents=True, exist_ok=True)
        override_bytes = b"c009-t9-override-image"
        override_path.write_bytes(override_bytes)
        await connection.execute(
            """
            UPDATE clip_ref_slots
            SET override_image_path = $1, override_sha256 = $2
            WHERE id = $3
            """,
            override_relative_path.as_posix(),
            hashlib.sha256(override_bytes).hexdigest(),
            slot_ids["deleted"],
        )
        template = (
            "shots={{shots}}|references={{references}}|style={{style}}|"
            "duration={{requested_duration}}|note={{user_note}}"
        )
        await connection.execute(
            "UPDATE prompt_templates SET content = $1 WHERE key = 'minimaxh3'",
            template,
        )
    finally:
        await connection.close()
    return {
        "style_id": int(style_id),
        "project_id": int(project_id),
        "episode_id": int(episode_id),
        "clip_id": int(clip_id),
        "shot_ids": shot_ids,
        "character_id": int(character_id),
        "scene_id": int(scene_id),
        "slot_ids": slot_ids,
        "image_id": image_id,
        "image_relative_path": image_relative_path.as_posix(),
        "override_relative_path": override_relative_path.as_posix(),
        "original_template": original_template,
    }


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


async def _read_clip(clip_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            "SELECT user_note, revision, freshness, generation_state FROM clips WHERE id = $1",
            clip_id,
        )
        assert row is not None
        return dict(row)
    finally:
        await connection.close()


async def _read_task_count(request_id: str) -> int:
    connection = await asyncpg.connect(_database_url())
    try:
        return int(
            await connection.fetchval(
                "SELECT count(*) FROM tasks WHERE request_id = $1", request_id
            )
        )
    finally:
        await connection.close()


async def _cleanup_fixture(fixture: dict[str, object]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE prompt_templates SET content = $1 WHERE key = 'minimaxh3'",
            fixture["original_template"],
        )
        await connection.execute(
            "DELETE FROM tasks WHERE target_id = $1 AND type = 'gen_clip_video'",
            fixture["clip_id"],
        )
        await connection.execute(
            "DELETE FROM clip_videos WHERE clip_id = $1", fixture["clip_id"]
        )
        await connection.execute(
            "DELETE FROM clip_ref_slots WHERE clip_id = $1", fixture["clip_id"]
        )
        await connection.execute(
            "DELETE FROM clip_shots WHERE clip_id = $1", fixture["clip_id"]
        )
        await connection.execute(
            "DELETE FROM asset_images WHERE asset_id = ANY($1::int[])",
            [fixture["character_id"], fixture["scene_id"]],
        )
        await connection.execute(
            "DELETE FROM shot_assets WHERE shot_id = ANY($1::int[])",
            fixture["shot_ids"],
        )
        await connection.execute("DELETE FROM clips WHERE id = $1", fixture["clip_id"])
        await connection.execute(
            "DELETE FROM shots WHERE id = ANY($1::int[])", fixture["shot_ids"]
        )
        await connection.execute(
            "DELETE FROM assets WHERE id = ANY($1::int[])",
            [fixture["character_id"], fixture["scene_id"]],
        )
        await connection.execute("DELETE FROM episodes WHERE id = $1", fixture["episode_id"])
        await connection.execute("DELETE FROM projects WHERE id = $1", fixture["project_id"])
        await connection.execute("DELETE FROM styles WHERE id = $1", fixture["style_id"])
    finally:
        await connection.close()


def _assert_error(response, status_code: int) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"detail"}
    assert set(body["detail"]) == {"code", "message"}
    assert body["detail"]["code"] == (
        "validation_error"
        if status_code == 422
        else "not_found"
        if status_code == 404
        else "conflict"
    )
    assert isinstance(body["detail"]["message"], str)
    assert body["detail"]["message"]


def test_c009_generate_video_request_snapshot_and_identity_contract(
    monkeypatch, tmp_path
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
            before_clip = asyncio.run(_read_clip(fixture["clip_id"]))
            response = client.post(
                f"/api/clips/{fixture['clip_id']}/generate-video", json={}
            )
            assert response.status_code == 202
            assert set(response.json()) == {"task_id"}
            first_task_id = response.json()["task_id"]
            assert isinstance(first_task_id, int) and first_task_id > 0
            first_task = asyncio.run(_read_task(first_task_id))
            assert first_task["type"] == "gen_clip_video"
            assert first_task["target_id"] == fixture["clip_id"]
            assert first_task["request_id"] is None
            assert first_task["status"] == "queued"
            assert first_task["progress"] == 0
            payload = first_task["payload"]
            assert set(payload) == {"input_snapshot", "input_hash", "source_revisions"}
            snapshot = payload["input_snapshot"]
            assert isinstance(snapshot, dict)
            assert snapshot["request_identity"] == {
                "user_note_provided": False,
                "user_note": "原始意见",
            }
            assert snapshot["user_note"] == "原始意见"
            assert [item["order"] for item in snapshot["shots"]] == [1, 2]
            assert [item["asset_ids"] for item in snapshot["shots"]] == [
                sorted([fixture["character_id"], fixture["scene_id"]]),
                sorted([fixture["character_id"], fixture["scene_id"]]),
            ]
            assert snapshot["references"] == [
                {
                    "slot_no": 1,
                    "reference_name": "subject1",
                    "asset_type": "character",
                    "asset_name": "林夏",
                    "asset_description": "黑发白衬衫",
                    "image_source": "asset_current",
                    "image_id": fixture["image_id"],
                    "override_sha256": None,
                },
                {
                    "slot_no": 3,
                    "reference_name": "subject2",
                    "asset_type": "character",
                    "asset_name": "已删人物",
                    "asset_description": None,
                    "image_source": "override",
                    "image_id": None,
                    "override_sha256": hashlib.sha256(
                        b"c009-t9-override-image"
                    ).hexdigest(),
                },
            ]
            assert [item["file_path"] for item in snapshot["reference_media"]] == [
                fixture["image_relative_path"],
                fixture["override_relative_path"],
            ]
            assert all(
                not Path(item["file_path"]).is_absolute()
                for item in snapshot["reference_media"]
            )
            assert snapshot["template_key"] == "minimaxh3"
            assert snapshot["style"] == "电影写实"
            assert snapshot["cached_prompt"] is None
            assert snapshot["comfy_prompt_id"]
            assert isinstance(snapshot["seed"], int)
            assert payload["source_revisions"]["clip"] == {
                "id": fixture["clip_id"],
                "revision": before_clip["revision"],
            }
            expected_hash = build_clip_video_input_hash(
                shots=snapshot["shots"],
                references=snapshot["references"],
                style_prompt_fragment=snapshot["style"],
                template_content=snapshot["template_content"],
                user_note="原始意见",
                requested_duration=5,
                model=settings.VLLM_MODEL,
                workflow_hash=snapshot["workflow"]["hash"],
            )
            assert payload["input_hash"] == expected_hash
            after_clip = asyncio.run(_read_clip(fixture["clip_id"]))
            assert after_clip["user_note"] == before_clip["user_note"]
            assert after_clip["revision"] == before_clip["revision"]
            assert after_clip["freshness"] == before_clip["freshness"]
            assert after_clip["generation_state"] == "queued"
            assert vllm_probe.calls == 1
            assert comfy_probe.calls == 1

            explicit_null = client.post(
                f"/api/clips/{fixture['clip_id']}/generate-video",
                json={"user_note": None},
            )
            assert explicit_null.status_code == 202
            assert explicit_null.json()["task_id"] != first_task_id
            null_task = asyncio.run(_read_task(explicit_null.json()["task_id"]))
            assert null_task["payload"]["input_snapshot"]["request_identity"] == {
                "user_note_provided": True,
                "user_note": None,
            }
            null_clip = asyncio.run(_read_clip(fixture["clip_id"]))
            assert null_clip["user_note"] is None
            assert null_clip["revision"] == before_clip["revision"] + 1
            assert null_clip["freshness"] == "stale"

            explicit_empty = client.post(
                f"/api/clips/{fixture['clip_id']}/generate-video",
                json={"user_note": ""},
            )
            assert explicit_empty.status_code == 202
            assert explicit_empty.json()["task_id"] != explicit_null.json()["task_id"]
            empty_task = asyncio.run(_read_task(explicit_empty.json()["task_id"]))
            assert empty_task["payload"]["input_snapshot"]["request_identity"] == {
                "user_note_provided": True,
                "user_note": "",
            }
            empty_clip = asyncio.run(_read_clip(fixture["clip_id"]))
            assert empty_clip["user_note"] == ""
            assert empty_clip["revision"] == before_clip["revision"] + 2

            explicit_whitespace = client.post(
                f"/api/clips/{fixture['clip_id']}/generate-video",
                json={"user_note": "  "},
            )
            assert explicit_whitespace.status_code == 202
            assert explicit_whitespace.json()["task_id"] != explicit_empty.json()["task_id"]
            whitespace_task = asyncio.run(
                _read_task(explicit_whitespace.json()["task_id"])
            )
            assert whitespace_task["payload"]["input_snapshot"]["request_identity"] == {
                "user_note_provided": True,
                "user_note": "  ",
            }
            whitespace_clip = asyncio.run(_read_clip(fixture["clip_id"]))
            assert whitespace_clip["user_note"] == "  "
            assert whitespace_clip["revision"] == before_clip["revision"] + 3

            fixed_before = asyncio.run(_read_clip(fixture["clip_id"]))
            fixed = client.post(
                f"/api/clips/{fixture['clip_id']}/generate-video",
                json={"user_note": "固定意见", "request_id": " abc "},
            )
            assert fixed.status_code == 202
            fixed_task_id = fixed.json()["task_id"]
            fixed_task = asyncio.run(_read_task(fixed_task_id))
            fixed_snapshot = fixed_task["payload"]["input_snapshot"]
            assert fixed_task["request_id"] == "abc"
            assert fixed_snapshot["request_identity"] == {
                "user_note_provided": True,
                "user_note": "固定意见",
            }
            assert fixed_snapshot["comfy_prompt_id"] == (
                "3088d9e1-4253-5fff-896e-87e5f5312d20"
            )
            assert fixed_snapshot["seed"] == 679630015510424864
            changed_clip = asyncio.run(_read_clip(fixture["clip_id"]))
            assert changed_clip["user_note"] == "固定意见"
            assert changed_clip["revision"] == fixed_before["revision"] + 1
            assert changed_clip["freshness"] == "stale"

            replay = client.post(
                f"/api/clips/{fixture['clip_id']}/generate-video",
                json={"user_note": "固定意见", "request_id": "abc"},
            )
            assert replay.status_code == 202
            assert replay.json() == {"task_id": fixed_task_id}
            assert asyncio.run(_read_task_count("abc")) == 1
            assert asyncio.run(_read_clip(fixture["clip_id"])) == changed_clip

            identity_conflict = client.post(
                f"/api/clips/{fixture['clip_id']}/generate-video",
                json={"request_id": "identity"},
            )
            assert identity_conflict.status_code == 202
            identity_error = client.post(
                f"/api/clips/{fixture['clip_id']}/generate-video",
                json={"user_note": None, "request_id": "identity"},
            )
            _assert_error(identity_error, 409)

            cross_type = client.post(
                f"/api/clips/{fixture['clip_id']}/generate-video",
                json={"request_id": "cross-type"},
            )
            assert cross_type.status_code == 202
            cross_asset = client.post(
                f"/api/assets/{fixture['character_id']}/generate-image",
                json={"request_id": "cross-type"},
            )
            _assert_error(cross_asset, 409)

            invalid_requests = [
                client.post(f"/api/clips/{fixture['clip_id']}/generate-video"),
                client.post(
                    f"/api/clips/{fixture['clip_id']}/generate-video",
                    content="null",
                    headers={"content-type": "application/json"},
                ),
                client.post(
                    f"/api/clips/{fixture['clip_id']}/generate-video", json=[]
                ),
                client.post(
                    f"/api/clips/{fixture['clip_id']}/generate-video",
                    json={"unknown": True},
                ),
                client.post(
                    f"/api/clips/{fixture['clip_id']}/generate-video",
                    json={"user_note": 3},
                ),
                client.post(
                    f"/api/clips/{fixture['clip_id']}/generate-video",
                    json={"request_id": 3},
                ),
                client.post(
                    f"/api/clips/{fixture['clip_id']}/generate-video",
                    json={"request_id": "   "},
                ),
                client.post(
                    f"/api/clips/{fixture['clip_id']}/generate-video",
                    json={"request_id": "a" * 129},
                ),
                client.post(
                    f"/api/clips/{fixture['clip_id']}/generate-video",
                    json={"request_id": "bad\x00id"},
                ),
                client.post(
                    f"/api/clips/{fixture['clip_id']}/generate-video",
                    json={"user_note": "bad\x00note"},
                ),
            ]
            for invalid in invalid_requests:
                _assert_error(invalid, 422)
            _assert_error(
                client.post("/api/clips/2147483648/generate-video", json={}),
                422,
            )
            _assert_error(
                client.post("/api/clips/-2147483649/generate-video", json={}),
                422,
            )
            _assert_error(
                client.post("/api/clips/0/generate-video", json={}),
                404,
            )
            _assert_error(
                client.post("/api/clips/2147483647/generate-video", json={}),
                404,
            )
    finally:
        asyncio.run(_cleanup_fixture(fixture))
        asyncio.run(engine.dispose())
