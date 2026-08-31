import asyncio
import os
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient

from app.main import app


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _create_fixture() -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, 'C008 slots style')
            RETURNING id
            """,
            "C008 slots style " + uuid4().hex,
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C008 slots project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, 'Slots episode', 'slots')
            RETURNING id
            """,
            project_id,
        )
        asset_ids: dict[str, int] = {}
        for key, name in (
            ("first", "当前人物"),
            ("missing", "缺图人物"),
            ("disabled", "停用人物"),
            ("deleted_snapshot", "已删人物"),
            ("warning", "告警人物"),
            ("last", "末位人物"),
        ):
            asset_ids[key] = await connection.fetchval(
                """
                INSERT INTO assets (project_id, type, name, description, source)
                VALUES ($1, 'character', $2, $3, 'manual')
                RETURNING id
                """,
                project_id,
                name,
                name + "描述",
            )
        shot_id = await connection.fetchval(
            """
            INSERT INTO shots
                (episode_id, order_index, duration_est, shot_type, camera,
                 description, dialogue, status, revision)
            VALUES ($1, 1, 5, '中景', '固定', 'slot shot', '', 'normal', 1)
            RETURNING id
            """,
            episode_id,
        )
        await connection.execute(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
            shot_id,
            asset_ids["first"],
        )
        clip_id = await connection.fetchval(
            """
            INSERT INTO clips (episode_id, requested_duration)
            VALUES ($1, 5)
            RETURNING id
            """,
            episode_id,
        )
        await connection.execute(
            "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, 1)",
            clip_id,
            shot_id,
        )

        slot_ids: dict[str, int] = {}
        for key, asset_key, enabled, name, asset_type in (
            ("first", "first", True, "当前人物", "character"),
            ("missing", "missing", True, "缺图人物", "character"),
            ("disabled", "disabled", False, "停用人物", "character"),
            ("deleted", None, True, "已删人物", "character"),
            ("warning", "warning", True, "告警人物", "character"),
            ("last", "last", False, "末位人物", "character"),
        ):
            slot_ids[key] = await connection.fetchval(
                """
                INSERT INTO clip_ref_slots
                    (clip_id, slot_no, asset_id, asset_name_snapshot,
                     asset_type_snapshot, enabled, override_image_path,
                     override_sha256)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                clip_id,
                len(slot_ids) + 1,
                None if asset_key is None else asset_ids[asset_key],
                name,
                asset_type,
                enabled,
                "pending" if key == "deleted" else None,
                "d" * 64 if key == "deleted" else None,
            )
        override_path = (
            f"projects/{project_id}/episodes/{episode_id}/clips/"
            f"{clip_id}/slots/{slot_ids['deleted']}.png"
        )
        await connection.execute(
            "UPDATE clip_ref_slots SET override_image_path = $1 WHERE id = $2",
            override_path,
            slot_ids["deleted"],
        )

        image_ids: dict[str, int] = {}
        for key in ("first", "disabled"):
            image_ids[key] = await connection.fetchval(
                """
                INSERT INTO asset_images
                    (asset_id, file_path, sha256, source, is_current)
                VALUES ($1, 'pending', $2, 'uploaded', true)
                RETURNING id
                """,
                asset_ids[key],
                key[0] * 64,
            )
            await connection.execute(
                "UPDATE asset_images SET file_path = $1 WHERE id = $2",
                f"projects/{project_id}/assets/{asset_ids[key]}/{image_ids[key]}.png",
                image_ids[key],
            )
    finally:
        await connection.close()
    return {
        "style_id": style_id,
        "project_id": project_id,
        "episode_id": episode_id,
        "clip_id": clip_id,
        "shot_id": shot_id,
        "asset_ids": asset_ids,
        "slot_ids": slot_ids,
        "image_ids": image_ids,
    }


async def _set_last_enabled(fixture: dict[str, object], enabled: bool) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE clip_ref_slots SET enabled = $1 WHERE id = $2",
            enabled,
            fixture["slot_ids"]["last"],
        )
    finally:
        await connection.close()


async def _corrupt_slot_asset_type(fixture: dict[str, object]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            """
            UPDATE clip_ref_slots
            SET asset_type_snapshot = 'scene'
            WHERE id = $1
            """,
            fixture["slot_ids"]["first"],
        )
    finally:
        await connection.close()


async def _cleanup_fixture(fixture: dict[str, object]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM clip_shots WHERE clip_id = $1", fixture["clip_id"]
        )
        await connection.execute(
            "DELETE FROM clip_ref_slots WHERE clip_id = $1", fixture["clip_id"]
        )
        await connection.execute(
            "DELETE FROM asset_images WHERE asset_id IN "
            "(SELECT id FROM assets WHERE project_id = $1)",
            fixture["project_id"],
        )
        await connection.execute(
            "DELETE FROM clips WHERE id = $1", fixture["clip_id"]
        )
        await connection.execute(
            "DELETE FROM shot_assets WHERE shot_id = $1", fixture["shot_id"]
        )
        await connection.execute(
            "DELETE FROM shots WHERE id = $1", fixture["shot_id"]
        )
        await connection.execute(
            "DELETE FROM episodes WHERE id = $1", fixture["episode_id"]
        )
        await connection.execute(
            "DELETE FROM assets WHERE project_id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM projects WHERE id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM styles WHERE id = $1", fixture["style_id"]
        )
    finally:
        await connection.close()


def _assert_error(response, status_code: int) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert body["detail"]["code"]
    assert body["detail"]["message"]


def test_slots_return_fixed_order_and_r9_source_without_r10() -> None:
    fixture = asyncio.run(_create_fixture())
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/clips/{fixture['clip_id']}/slots")
            assert response.status_code == 200
            body = response.json()
            assert set(body) == {"clip_id", "items", "warnings"}
            assert body["clip_id"] == fixture["clip_id"]
            assert [item["slot_no"] for item in body["items"]] == [1, 2, 3, 4, 5, 6]
            assert body["items"][0]["image_source"] == "asset_current"
            assert body["items"][0]["image_url"] == (
                f"/media/asset-images/{fixture['image_ids']['first']}"
            )
            assert body["items"][1]["image_source"] is None
            assert body["items"][1]["image_url"] is None
            assert body["items"][2]["enabled"] is False
            assert body["items"][2]["image_source"] == "asset_current"
            assert body["items"][3]["asset_id"] is None
            assert body["items"][3]["asset_deleted"] is True
            assert body["items"][3]["asset_name_snapshot"] == "已删人物"
            assert body["items"][3]["image_source"] == "override"
            assert body["items"][3]["image_url"] == (
                f"/media/slot-overrides/{fixture['slot_ids']['deleted']}"
            )
            assert body["items"][4]["image_source"] is None
            assert body["items"][5]["image_source"] is None
            assert body["warnings"] == []

            asyncio.run(_set_last_enabled(fixture, True))
            enabled_body = client.get(
                f"/api/clips/{fixture['clip_id']}/slots"
            ).json()
            assert enabled_body["items"][5]["image_source"] is None
            assert [item["code"] for item in enabled_body["warnings"]] == [
                "enabled_slots_exceed_recommendation"
            ]
            assert "建议 4 张以内" in enabled_body["warnings"][0]["message"]
            assert all(
                "path" not in item and "sha256" not in item
                for item in enabled_body["items"]
            )
            _assert_error(client.get("/api/clips/2147483647/slots"), 404)

            asyncio.run(_corrupt_slot_asset_type(fixture))
            _assert_error(
                client.get(f"/api/clips/{fixture['clip_id']}/slots"), 500
            )
    finally:
        asyncio.run(_cleanup_fixture(fixture))
