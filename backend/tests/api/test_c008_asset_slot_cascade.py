import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _create_fixture(data_dir: Path) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, 'C008 R12 style')
            RETURNING id
            """,
            "C008 R12 style " + uuid4().hex,
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C008 R12 project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, 'R12 episode', 'R12')
            RETURNING id
            """,
            project_id,
        )
        target_asset_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source, revision)
            VALUES ($1, 'character', '目标人物', '目标描述', 'manual', 4)
            RETURNING id
            """,
            project_id,
        )
        other_asset_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source, revision)
            VALUES ($1, 'scene', '其他场景', '其他描述', 'manual', 2)
            RETURNING id
            """,
            project_id,
        )

        shot_target_id = await connection.fetchval(
            """
            INSERT INTO shots
                (episode_id, order_index, duration_est, shot_type, camera,
                 description, dialogue, status, revision)
            VALUES ($1, 1, 2.0, '中景', '固定', '目标分镜', '', 'normal', 6)
            RETURNING id
            """,
            episode_id,
        )
        shot_detached_id = await connection.fetchval(
            """
            INSERT INTO shots
                (episode_id, order_index, duration_est, shot_type, camera,
                 description, dialogue, status, revision)
            VALUES ($1, 2, 2.0, '中景', '固定', '脱钩分镜', '', 'normal', 3)
            RETURNING id
            """,
            episode_id,
        )
        shot_other_id = await connection.fetchval(
            """
            INSERT INTO shots
                (episode_id, order_index, duration_est, shot_type, camera,
                 description, dialogue, status, revision)
            VALUES ($1, 3, 2.0, '中景', '固定', '其他分镜', '', 'normal', 5)
            RETURNING id
            """,
            episode_id,
        )
        await connection.execute(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
            shot_target_id,
            target_asset_id,
        )
        await connection.execute(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
            shot_other_id,
            other_asset_id,
        )

        target_clip_id = await connection.fetchval(
            """
            INSERT INTO clips
                (episode_id, requested_duration, generation_state, freshness, revision)
            VALUES ($1, 5, 'generating', 'fresh', 7)
            RETURNING id
            """,
            episode_id,
        )
        detached_clip_id = await connection.fetchval(
            """
            INSERT INTO clips
                (episode_id, requested_duration, generation_state, freshness, revision)
            VALUES ($1, 5, 'ready', 'fresh', 8)
            RETURNING id
            """,
            episode_id,
        )
        other_clip_id = await connection.fetchval(
            """
            INSERT INTO clips
                (episode_id, requested_duration, generation_state, freshness, revision)
            VALUES ($1, 5, 'failed', 'fresh', 9)
            RETURNING id
            """,
            episode_id,
        )
        await connection.executemany(
            "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, 1)",
            [
                (target_clip_id, shot_target_id),
                (detached_clip_id, shot_detached_id),
                (other_clip_id, shot_other_id),
            ],
        )

        target_slot_without_override_id = await connection.fetchval(
            """
            INSERT INTO clip_ref_slots
                (clip_id, slot_no, asset_id, asset_name_snapshot,
                 asset_type_snapshot, enabled, override_image_path, override_sha256)
            VALUES ($1, 1, $2, '目标人物', 'character', true, NULL, NULL)
            RETURNING id
            """,
            target_clip_id,
            target_asset_id,
        )
        target_slot_with_override_id = await connection.fetchval(
            """
            INSERT INTO clip_ref_slots
                (clip_id, slot_no, asset_id, asset_name_snapshot,
                 asset_type_snapshot, enabled, override_image_path, override_sha256)
            VALUES ($1, 2, $2, '目标人物', 'character', false, $3, $4)
            RETURNING id
            """,
            target_clip_id,
            target_asset_id,
            "pending",
            "o" * 64,
        )
        detached_slot_id = await connection.fetchval(
            """
            INSERT INTO clip_ref_slots
                (clip_id, slot_no, asset_id, asset_name_snapshot,
                 asset_type_snapshot, enabled, override_image_path, override_sha256)
            VALUES ($1, 1, $2, '目标人物', 'character', true, NULL, NULL)
            RETURNING id
            """,
            detached_clip_id,
            target_asset_id,
        )
        other_slot_id = await connection.fetchval(
            """
            INSERT INTO clip_ref_slots
                (clip_id, slot_no, asset_id, asset_name_snapshot,
                 asset_type_snapshot, enabled, override_image_path, override_sha256)
            VALUES ($1, 1, $2, '其他场景', 'scene', true, NULL, NULL)
            RETURNING id
            """,
            other_clip_id,
            other_asset_id,
        )

        target_image_id = await connection.fetchval(
            """
            INSERT INTO asset_images
                (asset_id, file_path, sha256, source, is_current)
            VALUES ($1, 'pending', $2, 'uploaded', true)
            RETURNING id
            """,
            target_asset_id,
            "t" * 64,
        )
        other_image_id = await connection.fetchval(
            """
            INSERT INTO asset_images
                (asset_id, file_path, sha256, source, is_current)
            VALUES ($1, 'pending', $2, 'uploaded', true)
            RETURNING id
            """,
            other_asset_id,
            "r" * 64,
        )
        target_image_path = (
            f"projects/{project_id}/assets/{target_asset_id}/{target_image_id}.png"
        )
        other_image_path = (
            f"projects/{project_id}/assets/{other_asset_id}/{other_image_id}.png"
        )
        await connection.execute(
            "UPDATE asset_images SET file_path = $1 WHERE id = $2",
            target_image_path,
            target_image_id,
        )
        await connection.execute(
            "UPDATE asset_images SET file_path = $1 WHERE id = $2",
            other_image_path,
            other_image_id,
        )
        override_path = (
            f"projects/{project_id}/episodes/{episode_id}/clips/{target_clip_id}"
            f"/slots/{target_slot_with_override_id}.png"
        )
        await connection.execute(
            "UPDATE clip_ref_slots SET override_image_path = $1 WHERE id = $2",
            override_path,
            target_slot_with_override_id,
        )
    finally:
        await connection.close()

    target_image_file = data_dir / Path(target_image_path)
    target_image_file.parent.mkdir(parents=True, exist_ok=True)
    target_image_file.write_bytes(b"target asset image")
    other_image_file = data_dir / Path(other_image_path)
    other_image_file.parent.mkdir(parents=True, exist_ok=True)
    other_image_file.write_bytes(b"other asset image")
    override_file = data_dir / Path(override_path)
    override_file.parent.mkdir(parents=True, exist_ok=True)
    override_file.write_bytes(b"slot override remains")
    return {
        "style_id": style_id,
        "project_id": project_id,
        "episode_id": episode_id,
        "target_asset_id": target_asset_id,
        "other_asset_id": other_asset_id,
        "shot_target_id": shot_target_id,
        "shot_detached_id": shot_detached_id,
        "shot_other_id": shot_other_id,
        "target_clip_id": target_clip_id,
        "detached_clip_id": detached_clip_id,
        "other_clip_id": other_clip_id,
        "target_slot_without_override_id": target_slot_without_override_id,
        "target_slot_with_override_id": target_slot_with_override_id,
        "detached_slot_id": detached_slot_id,
        "other_slot_id": other_slot_id,
        "target_image_id": target_image_id,
        "target_image_path": target_image_path,
        "other_image_path": other_image_path,
        "override_path": override_path,
        "data_dir": data_dir,
    }


async def _read_state(fixture: dict[str, object]) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        asset_exists = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM assets WHERE id = $1)",
            fixture["target_asset_id"],
        )
        shot_rows = await connection.fetch(
            """
            SELECT id, revision, status
            FROM shots
            WHERE id = ANY($1::int[])
            ORDER BY id
            """,
            [
                fixture["shot_target_id"],
                fixture["shot_detached_id"],
                fixture["shot_other_id"],
            ],
        )
        shot_assets = await connection.fetch(
            """
            SELECT shot_id, asset_id
            FROM shot_assets
            WHERE shot_id = ANY($1::int[])
            ORDER BY shot_id, asset_id
            """,
            [
                fixture["shot_target_id"],
                fixture["shot_detached_id"],
                fixture["shot_other_id"],
            ],
        )
        clip_rows = await connection.fetch(
            """
            SELECT id, generation_state, freshness, revision
            FROM clips
            WHERE id = ANY($1::int[])
            ORDER BY id
            """,
            [
                fixture["target_clip_id"],
                fixture["detached_clip_id"],
                fixture["other_clip_id"],
            ],
        )
        slot_rows = await connection.fetch(
            """
            SELECT id, clip_id, slot_no, asset_id, asset_name_snapshot,
                   asset_type_snapshot, enabled, override_image_path,
                   override_sha256
            FROM clip_ref_slots
            WHERE id = ANY($1::int[])
            ORDER BY id
            """,
            [
                fixture["target_slot_without_override_id"],
                fixture["target_slot_with_override_id"],
                fixture["detached_slot_id"],
                fixture["other_slot_id"],
            ],
        )
        target_image_exists = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM asset_images WHERE id = $1)",
            fixture["target_image_id"],
        )
        return {
            "asset_exists": bool(asset_exists),
            "shots": [dict(row) for row in shot_rows],
            "shot_assets": [dict(row) for row in shot_assets],
            "clips": [dict(row) for row in clip_rows],
            "slots": [dict(row) for row in slot_rows],
            "target_image_exists": bool(target_image_exists),
        }
    finally:
        await connection.close()


async def _cleanup_fixture(fixture: dict[str, object]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM clip_ref_slots WHERE clip_id IN ($1, $2, $3)",
            fixture["target_clip_id"],
            fixture["detached_clip_id"],
            fixture["other_clip_id"],
        )
        await connection.execute(
            "DELETE FROM clip_shots WHERE clip_id IN ($1, $2, $3)",
            fixture["target_clip_id"],
            fixture["detached_clip_id"],
            fixture["other_clip_id"],
        )
        await connection.execute(
            "DELETE FROM clips WHERE id IN ($1, $2, $3)",
            fixture["target_clip_id"],
            fixture["detached_clip_id"],
            fixture["other_clip_id"],
        )
        await connection.execute(
            "DELETE FROM shot_assets WHERE shot_id IN ($1, $2, $3)",
            fixture["shot_target_id"],
            fixture["shot_detached_id"],
            fixture["shot_other_id"],
        )
        await connection.execute(
            "DELETE FROM shots WHERE id IN ($1, $2, $3)",
            fixture["shot_target_id"],
            fixture["shot_detached_id"],
            fixture["shot_other_id"],
        )
        await connection.execute(
            "DELETE FROM asset_images WHERE asset_id IN ($1, $2)",
            fixture["target_asset_id"],
            fixture["other_asset_id"],
        )
        await connection.execute(
            "DELETE FROM assets WHERE id IN ($1, $2)",
            fixture["target_asset_id"],
            fixture["other_asset_id"],
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


def test_asset_delete_preserves_slots_and_marks_all_r12_clips_stale(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        before = asyncio.run(_read_state(fixture))
        target_clip_before = next(
            row
            for row in before["clips"]
            if row["id"] == fixture["target_clip_id"]
        )
        detached_clip_before = next(
            row
            for row in before["clips"]
            if row["id"] == fixture["detached_clip_id"]
        )
        other_clip_before = next(
            row for row in before["clips"] if row["id"] == fixture["other_clip_id"]
        )
        override_path = tmp_path / Path(fixture["override_path"])
        override_bytes = override_path.read_bytes()
        with TestClient(app) as client:
            response = client.delete(
                f"/api/assets/{fixture['target_asset_id']}"
            )
            assert response.status_code == 204
            slots = client.get(
                f"/api/clips/{fixture['target_clip_id']}/slots"
            )
            assert slots.status_code == 200
            assert [item["asset_deleted"] for item in slots.json()["items"]] == [
                True,
                True,
            ]
            assert slots.json()["items"][1]["image_source"] == "override"

        after = asyncio.run(_read_state(fixture))
        assert after["asset_exists"] is False
        assert after["target_image_exists"] is False
        assert after["shot_assets"] == [
            {
                "shot_id": fixture["shot_other_id"],
                "asset_id": fixture["other_asset_id"],
            }
        ]
        target_shot = next(
            row for row in after["shots"] if row["id"] == fixture["shot_target_id"]
        )
        detached_shot = next(
            row for row in after["shots"] if row["id"] == fixture["shot_detached_id"]
        )
        other_shot = next(
            row for row in after["shots"] if row["id"] == fixture["shot_other_id"]
        )
        assert target_shot == {
            "id": fixture["shot_target_id"],
            "revision": 7,
            "status": "changed",
        }
        assert detached_shot == {
            "id": fixture["shot_detached_id"],
            "revision": 3,
            "status": "normal",
        }
        assert other_shot == {
            "id": fixture["shot_other_id"],
            "revision": 5,
            "status": "normal",
        }

        target_clip_after = next(
            row
            for row in after["clips"]
            if row["id"] == fixture["target_clip_id"]
        )
        detached_clip_after = next(
            row
            for row in after["clips"]
            if row["id"] == fixture["detached_clip_id"]
        )
        other_clip_after = next(
            row for row in after["clips"] if row["id"] == fixture["other_clip_id"]
        )
        assert target_clip_after == {
            "id": fixture["target_clip_id"],
            "generation_state": target_clip_before["generation_state"],
            "freshness": "stale",
            "revision": target_clip_before["revision"],
        }
        assert detached_clip_after == {
            "id": fixture["detached_clip_id"],
            "generation_state": detached_clip_before["generation_state"],
            "freshness": "stale",
            "revision": detached_clip_before["revision"],
        }
        assert other_clip_after == other_clip_before

        target_slots = [
            row
            for row in after["slots"]
            if row["clip_id"] == fixture["target_clip_id"]
        ]
        assert target_slots == [
            {
                "id": fixture["target_slot_without_override_id"],
                "clip_id": fixture["target_clip_id"],
                "slot_no": 1,
                "asset_id": None,
                "asset_name_snapshot": "目标人物",
                "asset_type_snapshot": "character",
                "enabled": True,
                "override_image_path": None,
                "override_sha256": None,
            },
            {
                "id": fixture["target_slot_with_override_id"],
                "clip_id": fixture["target_clip_id"],
                "slot_no": 2,
                "asset_id": None,
                "asset_name_snapshot": "目标人物",
                "asset_type_snapshot": "character",
                "enabled": False,
                "override_image_path": fixture["override_path"],
                "override_sha256": "o" * 64,
            },
        ]
        detached_slot = next(
            row for row in after["slots"] if row["id"] == fixture["detached_slot_id"]
        )
        assert detached_slot["asset_id"] is None
        assert detached_slot["slot_no"] == 1
        assert detached_slot["enabled"] is True
        assert next(
            row for row in after["slots"] if row["id"] == fixture["other_slot_id"]
        )["asset_id"] == fixture["other_asset_id"]

        target_image_path = tmp_path / Path(fixture["target_image_path"])
        assert not target_image_path.exists()
        assert (tmp_path / "trash" / Path(fixture["target_image_path"])).is_file()
        assert override_path.is_file()
        assert override_path.read_bytes() == override_bytes
        assert not (tmp_path / "trash" / Path(fixture["override_path"])).exists()
    finally:
        asyncio.run(_cleanup_fixture(fixture))
