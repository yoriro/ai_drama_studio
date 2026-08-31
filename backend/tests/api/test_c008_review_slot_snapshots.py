from __future__ import annotations

import asyncio
import os
from io import BytesIO
from pathlib import Path

import asyncpg
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.main import app
from tests.api.test_c008_clip_create import _cleanup_fixture, _create_fixture


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _image_bytes(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 3), color).save(output, format="PNG")
    return output.getvalue()


async def _read_state(clip_id: int, slot_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        clip = await connection.fetchrow(
            "SELECT revision, freshness FROM clips WHERE id = $1", clip_id
        )
        slot = await connection.fetchrow(
            """
            SELECT slot_no, asset_id, asset_name_snapshot, asset_type_snapshot
            FROM clip_ref_slots
            WHERE id = $1
            """,
            slot_id,
        )
        return {
            "clip": None if clip is None else dict(clip),
            "slot": None if slot is None else dict(slot),
        }
    finally:
        await connection.close()


async def _delete_fixture_images(asset_id: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM asset_images WHERE asset_id = $1", asset_id
        )
    finally:
        await connection.close()


def test_c008_slot_snapshots_survive_live_asset_edits_and_current_switch(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture())
    try:
        first_bytes = _image_bytes((255, 0, 0))
        second_bytes = _image_bytes((0, 255, 0))
        with TestClient(app) as client:
            first_image = client.post(
                f"/api/assets/{fixture['assets']['character_first']}/images",
                files={"file": ("first.png", first_bytes, "image/png")},
            )
            assert first_image.status_code == 201
            first_image_id = first_image.json()["id"]

            created = client.post(
                f"/api/episodes/{fixture['episode_id']}/clips",
                json={
                    "shot_ids": [fixture["shots"]["first"]],
                    "reference_asset_ids": [
                        fixture["assets"]["character_first"]
                    ],
                },
            )
            assert created.status_code == 201
            clip_id = created.json()["id"]
            initial_slots = client.get(f"/api/clips/{clip_id}/slots")
            assert initial_slots.status_code == 200
            initial_items = initial_slots.json()["items"]
            assert [item["slot_no"] for item in initial_items] == [1]
            initial_item = initial_items[0]
            slot_id = initial_item["id"]
            assert initial_item["asset_id"] == fixture["assets"]["character_first"]
            assert initial_item["asset_name_snapshot"] == "先出现人物"
            assert initial_item["asset_type_snapshot"] == "character"
            assert initial_item["image_source"] == "asset_current"
            assert initial_item["image_url"] == (
                f"/media/asset-images/{first_image_id}"
            )

            second_image = client.post(
                f"/api/assets/{fixture['assets']['character_first']}/images",
                files={"file": ("second.png", second_bytes, "image/png")},
            )
            assert second_image.status_code == 201
            second_image_id = second_image.json()["id"]
            assert second_image.json()["is_current"] is False

            edited = client.patch(
                f"/api/assets/{fixture['assets']['character_first']}",
                json={"name": "活资产改名", "description": "活资产新描述"},
            )
            assert edited.status_code == 200
            switched = client.put(
                f"/api/assets/{fixture['assets']['character_first']}/current-image",
                json={"image_id": second_image_id},
            )
            assert switched.status_code == 200
            assert switched.json()["is_current"] is True

            final_slots = client.get(f"/api/clips/{clip_id}/slots")
            assert final_slots.status_code == 200
            final_items = final_slots.json()["items"]
            assert [item["slot_no"] for item in final_items] == [1]
            final_item = final_items[0]
            assert final_item["id"] == slot_id
            assert final_item["asset_id"] == fixture["assets"]["character_first"]
            assert final_item["asset_name_snapshot"] == "先出现人物"
            assert final_item["asset_type_snapshot"] == "character"
            assert final_item["asset_deleted"] is False
            assert final_item["image_source"] == "asset_current"
            assert final_item["image_url"] == (
                f"/media/asset-images/{second_image_id}"
            )
            media = client.get(final_item["image_url"])
            assert media.status_code == 200
            assert media.content == second_bytes

            clip = client.get(f"/api/clips/{clip_id}")
            assert clip.status_code == 200
            assert clip.json()["freshness"] == "stale"
            assert clip.json()["revision"] == 1

        assert asyncio.run(_read_state(clip_id, slot_id)) == {
            "clip": {"revision": 1, "freshness": "stale"},
            "slot": {
                "slot_no": 1,
                "asset_id": fixture["assets"]["character_first"],
                "asset_name_snapshot": "先出现人物",
                "asset_type_snapshot": "character",
            },
        }
        expected_files = {
            f"projects/{fixture['project_id']}/assets/"
            f"{fixture['assets']['character_first']}/{first_image_id}.png",
            f"projects/{fixture['project_id']}/assets/"
            f"{fixture['assets']['character_first']}/{second_image_id}.png",
        }
        assert {
            path.relative_to(tmp_path).as_posix()
            for path in tmp_path.rglob("*")
            if path.is_file()
        } == expected_files
        assert not (tmp_path / "trash").exists()
    finally:
        asyncio.run(_delete_fixture_images(fixture["assets"]["character_first"]))
        asyncio.run(_cleanup_fixture(fixture))
