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
            VALUES ($1, 'T7 style')
            RETURNING id
            """,
            "C006 T7 style " + uuid4().hex,
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C006 T7 project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, 'T7 episode', '分镜测试剧本')
            RETURNING id
            """,
            project_id,
        )
        empty_episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 2, 'T7 empty episode', '')
            RETURNING id
            """,
            project_id,
        )
        assets: dict[str, int] = {}
        for asset_type, key, name in (
            ("character", "character_id", "林夏"),
            ("scene", "scene_one_id", "旧车站"),
            ("scene", "scene_two_id", "河岸"),
            ("prop", "prop_id", "旧伞"),
        ):
            assets[key] = await connection.fetchval(
                """
                INSERT INTO assets (project_id, type, name, description, source)
                VALUES ($1, $2, $3, $4, 'manual')
                RETURNING id
                """,
                project_id,
                asset_type,
                name,
                f"{name}描述",
            )

        foreign_style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, 'foreign style')
            RETURNING id
            """,
            "C006 T7 foreign style " + uuid4().hex,
        )
        foreign_project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C006 T7 foreign project " + uuid4().hex,
            foreign_style_id,
        )
        foreign_asset_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source)
            VALUES ($1, 'character', '外部人物', '外部项目人物', 'manual')
            RETURNING id
            """,
            foreign_project_id,
        )
        assets["foreign_asset_id"] = foreign_asset_id

        shot_no_clip_id = await connection.fetchval(
            """
            INSERT INTO shots
                (episode_id, order_index, duration_est, shot_type, camera,
                 description, dialogue, status, revision)
            VALUES ($1, 1, 2.5, '中景', '固定', '未归属镜头', '', 'normal', 2)
            RETURNING id
            """,
            episode_id,
        )
        shot_with_clip_id = await connection.fetchval(
            """
            INSERT INTO shots
                (episode_id, order_index, duration_est, shot_type, camera,
                 description, dialogue, status, revision)
            VALUES ($1, 2, 3.0, '近景', '推', '已归属镜头', '林夏:你好', 'normal', 4)
            RETURNING id
            """,
            episode_id,
        )
        await connection.executemany(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
            [
                (shot_no_clip_id, assets["character_id"]),
                (shot_no_clip_id, assets["scene_one_id"]),
                (shot_with_clip_id, assets["scene_one_id"]),
            ],
        )
        clip_id = await connection.fetchval(
            """
            INSERT INTO clips
                (episode_id, requested_duration, generation_state, freshness, revision)
            VALUES ($1, 5, 'ready', 'fresh', 9)
            RETURNING id
            """,
            episode_id,
        )
        await connection.execute(
            "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, 1)",
            clip_id,
            shot_with_clip_id,
        )
        clip_video_path = (
            f"projects/{project_id}/episodes/{episode_id}/clips/"
            f"{clip_id}/1.mp4"
        )
        await connection.execute(
            """
            INSERT INTO clip_videos
                (clip_id, file_path, sha256, seed, requested_duration,
                 actual_duration, is_current)
            VALUES ($1, $2, $3, 7, 5, 4.5, true)
            """,
            clip_id,
            clip_video_path,
            uuid4().hex,
        )
    finally:
        await connection.close()

    media_path = data_dir / Path(clip_video_path)
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"T7 clip media")
    return {
        "style_id": style_id,
        "project_id": project_id,
        "foreign_style_id": foreign_style_id,
        "foreign_project_id": foreign_project_id,
        "episode_id": episode_id,
        "empty_episode_id": empty_episode_id,
        "shot_no_clip_id": shot_no_clip_id,
        "shot_with_clip_id": shot_with_clip_id,
        "clip_id": clip_id,
        "clip_video_path": clip_video_path,
        "data_dir": data_dir,
        **assets,
    }


async def _cleanup_fixture(fixture: dict[str, object]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM clip_shots WHERE clip_id = $1", fixture["clip_id"]
        )
        await connection.execute(
            "DELETE FROM clip_videos WHERE clip_id = $1", fixture["clip_id"]
        )
        await connection.execute(
            "DELETE FROM clips WHERE id = $1", fixture["clip_id"]
        )
        await connection.execute(
            "DELETE FROM shot_assets WHERE shot_id IN ($1, $2)",
            fixture["shot_no_clip_id"],
            fixture["shot_with_clip_id"],
        )
        await connection.execute(
            "DELETE FROM shots WHERE id IN ($1, $2)",
            fixture["shot_no_clip_id"],
            fixture["shot_with_clip_id"],
        )
        await connection.execute(
            "DELETE FROM episodes WHERE id IN ($1, $2)",
            fixture["episode_id"],
            fixture["empty_episode_id"],
        )
        await connection.execute(
            "DELETE FROM assets WHERE project_id IN ($1, $2)",
            fixture["project_id"],
            fixture["foreign_project_id"],
        )
        await connection.execute(
            "DELETE FROM projects WHERE id IN ($1, $2)",
            fixture["project_id"],
            fixture["foreign_project_id"],
        )
        await connection.execute(
            "DELETE FROM styles WHERE id IN ($1, $2)",
            fixture["style_id"],
            fixture["foreign_style_id"],
        )
    finally:
        await connection.close()
    data_dir = fixture["data_dir"]
    media_path = data_dir / Path(fixture["clip_video_path"])
    media_path.unlink(missing_ok=True)


async def _read_shot_state(shot_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT id, order_index, duration_est, shot_type, camera,
                   description, dialogue, status, revision
            FROM shots WHERE id = $1
            """,
            shot_id,
        )
        assert row is not None
        asset_rows = await connection.fetch(
            "SELECT asset_id FROM shot_assets WHERE shot_id = $1 ORDER BY asset_id",
            shot_id,
        )
        return {**dict(row), "asset_ids": [item[0] for item in asset_rows]}
    finally:
        await connection.close()


async def _read_clip_state(clip_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT c.id, c.generation_state, c.freshness, c.revision,
                   cv.file_path
            FROM clips c
            JOIN clip_videos cv ON cv.clip_id = c.id
            WHERE c.id = $1
            """,
            clip_id,
        )
        assert row is not None
        return dict(row)
    finally:
        await connection.close()


def _assert_validation(response) -> None:
    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["code"] == "validation_error"
    assert body["detail"]["message"]


def test_shot_get_and_patch_contract(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/episodes/{fixture['episode_id']}/shots"
            )
            assert response.status_code == 200
            shots = response.json()
            assert [shot["order_index"] for shot in shots] == [1, 2]
            expected_fields = {
                "id",
                "episode_id",
                "order_index",
                "duration_est",
                "shot_type",
                "camera",
                "description",
                "dialogue",
                "asset_ids",
                "status",
                "revision",
                "created_at",
                "updated_at",
            }
            assert set(shots[0]) == expected_fields
            assert shots[0]["asset_ids"] == sorted(shots[0]["asset_ids"])
            assert isinstance(shots[0]["duration_est"], (int, float))
            assert shots[0]["status"] == "normal"

            empty_response = client.get(
                f"/api/episodes/{fixture['empty_episode_id']}/shots"
            )
            assert empty_response.status_code == 200
            assert empty_response.json() == []
            assert client.get("/api/episodes/999999999/shots").status_code == 404

            original = shots[0]
            no_op = client.patch(
                f"/api/shots/{fixture['shot_no_clip_id']}",
                json={"description": original["description"]},
            )
            assert no_op.status_code == 200
            assert no_op.json() == original

            valid_patch = client.patch(
                f"/api/shots/{fixture['shot_no_clip_id']}",
                json={
                    "shot_type": "特写",
                    "camera": "摇",
                    "description": "  保留原始空格  ",
                    "dialogue": "林夏:原文",
                    "asset_ids": [fixture["scene_one_id"], fixture["character_id"]],
                },
            )
            assert valid_patch.status_code == 200
            patched = valid_patch.json()
            assert patched["shot_type"] == "特写"
            assert patched["camera"] == "摇"
            assert patched["description"] == "  保留原始空格  "
            assert patched["dialogue"] == "林夏:原文"
            assert patched["asset_ids"] == sorted(
                [fixture["scene_one_id"], fixture["character_id"]]
            )
            assert patched["revision"] == original["revision"] + 1
            assert patched["status"] == "changed"

            for body in (
                {},
                {"status": "normal"},
                {"order_index": 2},
                {"duration_est": 3},
                {"revision": 1},
                {"episode_id": fixture["episode_id"]},
                {"description": None},
                {"shot_type": "非法景别"},
                {"camera": "非法运镜"},
                {"asset_ids": [fixture["character_id"], fixture["character_id"]]},
                {"asset_ids": [fixture["prop_id"]]},
                {"asset_ids": [fixture["foreign_asset_id"]]},
                {"asset_ids": [999999999]},
            ):
                _assert_validation(
                    client.patch(
                        f"/api/shots/{fixture['shot_no_clip_id']}", json=body
                    )
                )
            _assert_validation(
                client.patch(
                    f"/api/shots/{fixture['shot_no_clip_id']}",
                    json={"asset_ids": [True]},
                )
            )
            assert client.patch("/api/shots/999999999", json={"dialogue": "x"}).status_code == 404
    finally:
        asyncio.run(_cleanup_fixture(fixture))


def test_shot_patch_changes_revision_and_stales_clips(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        before_unbound = asyncio.run(
            _read_shot_state(fixture["shot_no_clip_id"])
        )
        before_bound = asyncio.run(
            _read_shot_state(fixture["shot_with_clip_id"])
        )
        before_clip = asyncio.run(_read_clip_state(fixture["clip_id"]))
        media_path = tmp_path / Path(fixture["clip_video_path"])
        assert media_path.is_file()
        with TestClient(app) as client:
            unbound_response = client.patch(
                f"/api/shots/{fixture['shot_no_clip_id']}",
                json={"dialogue": "未归属镜头台词"},
            )
            assert unbound_response.status_code == 200
            unbound = unbound_response.json()
            assert unbound["revision"] == before_unbound["revision"] + 1
            assert unbound["status"] == "changed"
            assert asyncio.run(_read_clip_state(fixture["clip_id"])) == before_clip

            bound_response = client.patch(
                f"/api/shots/{fixture['shot_with_clip_id']}",
                json={"description": "已归属镜头新描述"},
            )
            assert bound_response.status_code == 200
            bound = bound_response.json()
            assert bound["revision"] == before_bound["revision"] + 1
            assert bound["status"] == "changed"
            assert asyncio.run(_read_clip_state(fixture["clip_id"])) == {
                **before_clip,
                "freshness": "stale",
            }
            assert media_path.is_file()
    finally:
        asyncio.run(_cleanup_fixture(fixture))


def test_shot_patch_accepts_zero_and_multiple_scene_bindings(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        with TestClient(app) as client:
            zero_scene = client.patch(
                f"/api/shots/{fixture['shot_no_clip_id']}",
                json={"asset_ids": []},
            )
            assert zero_scene.status_code == 200
            assert zero_scene.json()["asset_ids"] == []

            multiple_scene = client.patch(
                f"/api/shots/{fixture['shot_no_clip_id']}",
                json={
                    "asset_ids": [
                        fixture["scene_two_id"],
                        fixture["scene_one_id"],
                    ]
                },
            )
            assert multiple_scene.status_code == 200
            assert multiple_scene.json()["asset_ids"] == sorted(
                [fixture["scene_one_id"], fixture["scene_two_id"]]
            )
        state = asyncio.run(_read_shot_state(fixture["shot_no_clip_id"]))
        assert state["asset_ids"] == sorted(
            [fixture["scene_one_id"], fixture["scene_two_id"]]
        )
    finally:
        asyncio.run(_cleanup_fixture(fixture))
