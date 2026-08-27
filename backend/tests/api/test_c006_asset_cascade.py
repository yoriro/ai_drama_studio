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
            VALUES ($1, 'T8 style')
            RETURNING id
            """,
            "C006 T8 style " + uuid4().hex,
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C006 T8 project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, 'T8 episode', '资产级联剧本')
            RETURNING id
            """,
            project_id,
        )
        bound_asset_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source, revision)
            VALUES ($1, 'character', '林夏', '人物描述', 'manual', 4)
            RETURNING id
            """,
            project_id,
        )
        other_asset_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source)
            VALUES ($1, 'scene', '旧车站', '场景描述', 'manual')
            RETURNING id
            """,
            project_id,
        )

        image_ids: list[int] = []
        image_paths: list[str] = []
        for is_current in (True, False):
            image_id = await connection.fetchval(
                """
                INSERT INTO asset_images
                    (asset_id, file_path, sha256, source, is_current)
                VALUES ($1, 'pending', $2, 'uploaded', $3)
                RETURNING id
                """,
                bound_asset_id,
                uuid4().hex,
                is_current,
            )
            image_path = (
                f"projects/{project_id}/assets/{bound_asset_id}/{image_id}.png"
            )
            await connection.execute(
                "UPDATE asset_images SET file_path = $1 WHERE id = $2",
                image_path,
                image_id,
            )
            image_ids.append(image_id)
            image_paths.append(image_path)

        shot_ids: list[int] = []
        for order_index, revision in ((1, 2), (2, 3), (3, 5)):
            shot_id = await connection.fetchval(
                """
                INSERT INTO shots
                    (episode_id, order_index, duration_est, shot_type, camera,
                     description, dialogue, status, revision)
                VALUES ($1, $2, 2.5, '中景', '固定', $3, '', 'normal', $4)
                RETURNING id
                """,
                episode_id,
                order_index,
                f"镜头{order_index}",
                revision,
            )
            shot_ids.append(shot_id)
        await connection.executemany(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
            [
                (shot_ids[0], bound_asset_id),
                (shot_ids[1], bound_asset_id),
                (shot_ids[2], other_asset_id),
            ],
        )

        clip_ids: list[int] = []
        video_paths: list[str] = []
        for shot_id, generation_state, revision in zip(
            shot_ids,
            ("generating", "ready", "failed"),
            (8, 9, 10),
        ):
            clip_id = await connection.fetchval(
                """
                INSERT INTO clips
                    (episode_id, requested_duration, generation_state, freshness, revision)
                VALUES ($1, 5, $2, 'fresh', $3)
                RETURNING id
                """,
                episode_id,
                generation_state,
                revision,
            )
            clip_ids.append(clip_id)
            await connection.execute(
                "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, 1)",
                clip_id,
                shot_id,
            )
            video_path = (
                f"projects/{project_id}/episodes/{episode_id}/clips/{clip_id}/1.mp4"
            )
            await connection.execute(
                """
                INSERT INTO clip_videos
                    (clip_id, file_path, sha256, seed, requested_duration, is_current)
                VALUES ($1, $2, $3, 11, 5, true)
                """,
                clip_id,
                video_path,
                uuid4().hex,
            )
            video_paths.append(video_path)

        slot_id = await connection.fetchval(
            """
            INSERT INTO clip_ref_slots
                (clip_id, slot_no, asset_id, asset_name_snapshot,
                 asset_type_snapshot, override_image_path, override_sha256)
            VALUES ($1, 1, $2, '林夏', 'character', NULL, NULL)
            RETURNING id
            """,
            clip_ids[0],
            bound_asset_id,
        )
    finally:
        await connection.close()

    for relative_path in [*image_paths, *video_paths]:
        media_path = data_dir / Path(relative_path)
        media_path.parent.mkdir(parents=True, exist_ok=True)
        media_path.write_bytes(f"media-{relative_path}".encode())
    return {
        "style_id": style_id,
        "project_id": project_id,
        "episode_id": episode_id,
        "bound_asset_id": bound_asset_id,
        "other_asset_id": other_asset_id,
        "image_ids": image_ids,
        "image_paths": image_paths,
        "shot_ids": shot_ids,
        "clip_ids": clip_ids,
        "video_paths": video_paths,
        "slot_id": slot_id,
        "data_dir": data_dir,
    }


async def _cleanup_fixture(fixture: dict[str, object]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM clip_ref_slots WHERE clip_id = ANY($1::int[])",
            fixture["clip_ids"],
        )
        await connection.execute(
            "DELETE FROM clip_shots WHERE clip_id = ANY($1::int[])",
            fixture["clip_ids"],
        )
        await connection.execute(
            "DELETE FROM clip_videos WHERE clip_id = ANY($1::int[])",
            fixture["clip_ids"],
        )
        await connection.execute(
            "DELETE FROM clips WHERE id = ANY($1::int[])", fixture["clip_ids"]
        )
        await connection.execute(
            "DELETE FROM shot_assets WHERE shot_id = ANY($1::int[])",
            fixture["shot_ids"],
        )
        await connection.execute(
            "DELETE FROM shots WHERE id = ANY($1::int[])", fixture["shot_ids"]
        )
        await connection.execute(
            "DELETE FROM asset_images WHERE asset_id = $1",
            fixture["bound_asset_id"],
        )
        await connection.execute(
            "DELETE FROM assets WHERE id IN ($1, $2)",
            fixture["bound_asset_id"],
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

    data_dir = fixture["data_dir"]
    for relative_path in [*fixture["image_paths"], *fixture["video_paths"]]:
        path = Path(relative_path)
        (data_dir / path).unlink(missing_ok=True)
        (data_dir / "trash" / path).unlink(missing_ok=True)


async def _read_state(fixture: dict[str, object]) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        shot_rows = await connection.fetch(
            """
            SELECT id, revision, status
            FROM shots WHERE id = ANY($1::int[]) ORDER BY id
            """,
            fixture["shot_ids"],
        )
        shot_assets = await connection.fetch(
            """
            SELECT shot_id, asset_id
            FROM shot_assets WHERE shot_id = ANY($1::int[])
            ORDER BY shot_id, asset_id
            """,
            fixture["shot_ids"],
        )
        clip_rows = await connection.fetch(
            """
            SELECT c.id, c.generation_state, c.freshness, c.revision,
                   cv.file_path
            FROM clips c
            JOIN clip_videos cv ON cv.clip_id = c.id
            WHERE c.id = ANY($1::int[]) ORDER BY c.id
            """,
            fixture["clip_ids"],
        )
        slot_asset_id = await connection.fetchval(
            "SELECT asset_id FROM clip_ref_slots WHERE id = $1",
            fixture["slot_id"],
        )
        asset_revision = await connection.fetchval(
            "SELECT revision FROM assets WHERE id = $1",
            fixture["bound_asset_id"],
        )
        return {
            "shots": [dict(row) for row in shot_rows],
            "shot_assets": [dict(row) for row in shot_assets],
            "clips": [dict(row) for row in clip_rows],
            "slot_asset_id": slot_asset_id,
            "asset_revision": asset_revision,
        }
    finally:
        await connection.close()


def test_asset_edit_and_current_image_mark_bound_shots_and_clips(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        before = asyncio.run(_read_state(fixture))
        with TestClient(app) as client:
            name_response = client.patch(
                f"/api/assets/{fixture['bound_asset_id']}",
                json={"name": "林夏改名"},
            )
            assert name_response.status_code == 200
            after_name = asyncio.run(_read_state(fixture))
            assert after_name["asset_revision"] == before["asset_revision"] + 1

            for shot in after_name["shots"][:2]:
                original = next(
                    row for row in before["shots"] if row["id"] == shot["id"]
                )
                assert shot["revision"] == original["revision"] + 1
                assert shot["status"] == "changed"
            assert after_name["shots"][2] == before["shots"][2]
            for clip in after_name["clips"][:2]:
                original = next(
                    row for row in before["clips"] if row["id"] == clip["id"]
                )
                assert clip["freshness"] == "stale"
                assert clip["generation_state"] == original["generation_state"]
                assert clip["revision"] == original["revision"]
                assert clip["file_path"] == original["file_path"]
            assert after_name["clips"][2] == before["clips"][2]

            same_name = client.patch(
                f"/api/assets/{fixture['bound_asset_id']}",
                json={"name": "林夏改名"},
            )
            assert same_name.status_code == 200
            assert asyncio.run(_read_state(fixture)) == after_name

            description_response = client.patch(
                f"/api/assets/{fixture['bound_asset_id']}",
                json={"description": "人物描述更新"},
            )
            assert description_response.status_code == 200
            after_description = asyncio.run(_read_state(fixture))
            assert (
                after_description["asset_revision"]
                == after_name["asset_revision"] + 1
            )
            for shot, original in zip(
                after_description["shots"], after_name["shots"]
            ):
                if shot["id"] in fixture["shot_ids"][:2]:
                    assert shot["revision"] == original["revision"] + 1

            switch_response = client.put(
                f"/api/assets/{fixture['bound_asset_id']}/current-image",
                json={"image_id": fixture["image_ids"][1]},
            )
            assert switch_response.status_code == 200
            after_switch = asyncio.run(_read_state(fixture))
            assert (
                after_switch["asset_revision"]
                == after_description["asset_revision"] + 1
            )
            for shot, original in zip(after_switch["shots"], after_description["shots"]):
                if shot["id"] in fixture["shot_ids"][:2]:
                    assert shot["revision"] == original["revision"] + 1

            same_switch = client.put(
                f"/api/assets/{fixture['bound_asset_id']}/current-image",
                json={"image_id": fixture["image_ids"][1]},
            )
            assert same_switch.status_code == 200
            assert asyncio.run(_read_state(fixture)) == after_switch

        for relative_path in [*fixture["image_paths"], *fixture["video_paths"]]:
            path = Path(relative_path)
            assert (tmp_path / path).is_file()
            assert not (tmp_path / "trash" / path).exists()
    finally:
        asyncio.run(_cleanup_fixture(fixture))


def test_asset_delete_unbinds_and_marks_downstream(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        before = asyncio.run(_read_state(fixture))
        with TestClient(app) as client:
            response = client.delete(f"/api/assets/{fixture['bound_asset_id']}")
            assert response.status_code == 204
        after = asyncio.run(_read_state(fixture))
        assert after["asset_revision"] is None
        assert after["shot_assets"] == [
            {
                "shot_id": fixture["shot_ids"][2],
                "asset_id": fixture["other_asset_id"],
            }
        ]
        for shot, original in zip(after["shots"], before["shots"]):
            if shot["id"] in fixture["shot_ids"][:2]:
                assert shot["revision"] == original["revision"] + 1
                assert shot["status"] == "changed"
            else:
                assert shot == original
        for clip, original in zip(after["clips"], before["clips"]):
            if clip["id"] in fixture["clip_ids"][:2]:
                assert clip["freshness"] == "stale"
            else:
                assert clip["freshness"] == original["freshness"]
            assert clip["generation_state"] == original["generation_state"]
            assert clip["revision"] == original["revision"]
            assert clip["file_path"] == original["file_path"]
        assert after["slot_asset_id"] is None

        for relative_path in fixture["image_paths"]:
            path = Path(relative_path)
            assert not (tmp_path / path).exists()
            assert (tmp_path / "trash" / path).is_file()
        for relative_path in fixture["video_paths"]:
            path = Path(relative_path)
            assert (tmp_path / path).is_file()
            assert not (tmp_path / "trash" / path).exists()
    finally:
        asyncio.run(_cleanup_fixture(fixture))
