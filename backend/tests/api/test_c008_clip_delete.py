import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

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
            VALUES ($1, 'C008 delete style')
            RETURNING id
            """,
            "C008 delete style " + uuid4().hex,
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C008 delete project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, 'Delete episode', 'delete')
            RETURNING id
            """,
            project_id,
        )
        asset_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source)
            VALUES ($1, 'character', '删除人物', '删除描述', 'manual')
            RETURNING id
            """,
            project_id,
        )
        shot_ids: list[int] = []
        for order_index in (1, 2):
            shot_ids.append(
                await connection.fetchval(
                    """
                    INSERT INTO shots
                        (episode_id, order_index, duration_est, shot_type, camera,
                         description, dialogue, status, revision)
                    VALUES ($1, $2, 2, '中景', '固定', $3, '', 'normal', $4)
                    RETURNING id
                    """,
                    episode_id,
                    order_index,
                    f"delete shot {order_index}",
                    order_index + 3,
                )
            )
        await connection.executemany(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
            [(shot_id, asset_id) for shot_id in shot_ids],
        )
        clip_id = await connection.fetchval(
            """
            INSERT INTO clips
                (episode_id, requested_duration, generation_state, freshness, revision)
            VALUES ($1, 5, 'ready', 'stale', 6)
            RETURNING id
            """,
            episode_id,
        )
        await connection.executemany(
            "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, $3)",
            [
                (clip_id, shot_ids[0], 1),
                (clip_id, shot_ids[1], 2),
            ],
        )
        slot_id = await connection.fetchval(
            """
            INSERT INTO clip_ref_slots
                (clip_id, slot_no, asset_id, asset_name_snapshot,
                 asset_type_snapshot, enabled, override_image_path, override_sha256)
            VALUES ($1, 1, $2, '删除人物', 'character', true, $3, $4)
            RETURNING id
            """,
            clip_id,
            asset_id,
            "pending",
            "s" * 64,
        )
        override_path = (
            f"projects/{project_id}/episodes/{episode_id}/clips/{clip_id}"
            f"/slots/{slot_id}.png"
        )
        override_bytes = b"clip override bytes"
        await connection.execute(
            "UPDATE clip_ref_slots SET override_image_path = $1, override_sha256 = $2 WHERE id = $3",
            override_path,
            __import__("hashlib").sha256(override_bytes).hexdigest(),
            slot_id,
        )
        video_ids: list[int] = []
        video_paths: list[str] = []
        video_bytes: dict[str, bytes] = {}
        for seed in (11, 12):
            video_id = await connection.fetchval(
                """
                INSERT INTO clip_videos
                    (clip_id, file_path, sha256, seed, requested_duration, is_current)
                VALUES ($1, 'pending', $2, $3, 5, $4)
                RETURNING id
                """,
                clip_id,
                f"v{seed}" * 16,
                seed,
                seed == 12,
            )
            video_path = (
                f"projects/{project_id}/episodes/{episode_id}/clips/{clip_id}"
                f"/{video_id}.mp4"
            )
            await connection.execute(
                "UPDATE clip_videos SET file_path = $1 WHERE id = $2",
                video_path,
                video_id,
            )
            video_ids.append(video_id)
            video_paths.append(video_path)
            video_bytes[video_path] = f"video-{seed}".encode()
    finally:
        await connection.close()

    override_file = data_dir / Path(override_path)
    override_file.parent.mkdir(parents=True, exist_ok=True)
    override_file.write_bytes(override_bytes)
    for path, content in video_bytes.items():
        video_file = data_dir / Path(path)
        video_file.parent.mkdir(parents=True, exist_ok=True)
        video_file.write_bytes(content)
    return {
        "style_id": style_id,
        "project_id": project_id,
        "episode_id": episode_id,
        "asset_id": asset_id,
        "shot_ids": shot_ids,
        "clip_id": clip_id,
        "slot_id": slot_id,
        "override_path": override_path,
        "override_bytes": override_bytes,
        "video_ids": video_ids,
        "video_paths": video_paths,
        "video_bytes": video_bytes,
        "data_dir": data_dir,
    }


async def _read_state(fixture: dict[str, object]) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        shots = await connection.fetch(
            """
            SELECT id, order_index, status, revision
            FROM shots
            WHERE id = ANY($1::int[])
            ORDER BY id
            """,
            fixture["shot_ids"],
        )
        clip_shots = await connection.fetch(
            "SELECT clip_id, shot_id, position FROM clip_shots WHERE clip_id = $1 ORDER BY position",
            fixture["clip_id"],
        )
        slots = await connection.fetch(
            """
            SELECT id, clip_id, slot_no, asset_id, override_image_path,
                   override_sha256, enabled
            FROM clip_ref_slots
            WHERE clip_id = $1
            ORDER BY slot_no
            """,
            fixture["clip_id"],
        )
        videos = await connection.fetch(
            """
            SELECT id, clip_id, file_path, is_current
            FROM clip_videos
            WHERE clip_id = $1
            ORDER BY id
            """,
            fixture["clip_id"],
        )
        clip = await connection.fetchrow(
            "SELECT id, revision, freshness, generation_state FROM clips WHERE id = $1",
            fixture["clip_id"],
        )
        return {
            "shots": [dict(row) for row in shots],
            "clip_shots": [dict(row) for row in clip_shots],
            "slots": [dict(row) for row in slots],
            "videos": [dict(row) for row in videos],
            "clip": None if clip is None else dict(clip),
        }
    finally:
        await connection.close()


async def _set_video_path(fixture: dict[str, object], video_id: int, path: str) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE clip_videos SET file_path = $1 WHERE id = $2", path, video_id
        )
    finally:
        await connection.close()


async def _cleanup_fixture(fixture: dict[str, object]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM clip_ref_slots WHERE clip_id IN "
            "(SELECT id FROM clips WHERE episode_id = $1)",
            fixture["episode_id"],
        )
        await connection.execute(
            "DELETE FROM clip_shots WHERE clip_id IN "
            "(SELECT id FROM clips WHERE episode_id = $1)",
            fixture["episode_id"],
        )
        await connection.execute(
            "DELETE FROM clip_videos WHERE clip_id IN "
            "(SELECT id FROM clips WHERE episode_id = $1)",
            fixture["episode_id"],
        )
        await connection.execute(
            "DELETE FROM clips WHERE episode_id = $1", fixture["episode_id"]
        )
        await connection.execute(
            "DELETE FROM shot_assets WHERE shot_id = ANY($1::int[])",
            fixture["shot_ids"],
        )
        await connection.execute(
            "DELETE FROM shots WHERE id = ANY($1::int[])", fixture["shot_ids"]
        )
        await connection.execute(
            "DELETE FROM assets WHERE id = $1", fixture["asset_id"]
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


def _assert_error(response, status_code: int) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"detail"}
    assert body["detail"]["code"]
    assert body["detail"]["message"]


def _delete_url(fixture: dict[str, object]) -> str:
    return f"/api/clips/{fixture['clip_id']}"


def test_clip_delete_moves_all_media_releases_shots_and_allows_recreate(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        before = asyncio.run(_read_state(fixture))
        with TestClient(app) as client:
            response = client.delete(_delete_url(fixture))
            assert response.status_code == 204
            assert response.content == b""
            assert client.get(_delete_url(fixture)).status_code == 404
            assert client.get(
                f"/media/slot-overrides/{fixture['slot_id']}"
            ).status_code == 404
            recreate = client.post(
                f"/api/episodes/{fixture['episode_id']}/clips",
                json={
                    "shot_ids": fixture["shot_ids"],
                    "reference_asset_ids": [fixture["asset_id"]],
                },
            )
            assert recreate.status_code == 201
            assert recreate.json()["shot_ids"] == fixture["shot_ids"]
        after = asyncio.run(_read_state(fixture))
        assert after["clip"] is None
        assert after["clip_shots"] == []
        assert after["slots"] == []
        assert after["videos"] == []
        assert after["shots"] == before["shots"]
        override_path = Path(fixture["override_path"])
        assert not (tmp_path / override_path).exists()
        assert (tmp_path / "trash" / override_path).read_bytes() == fixture[
            "override_bytes"
        ]
        for path, content in fixture["video_bytes"].items():
            assert not (tmp_path / Path(path)).exists()
            assert (tmp_path / "trash" / Path(path)).read_bytes() == content
    finally:
        asyncio.run(_cleanup_fixture(fixture))


def test_clip_delete_rejects_bad_media_paths_without_database_changes(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        before = asyncio.run(_read_state(fixture))
        with TestClient(app, raise_server_exceptions=False) as client:
            asyncio.run(
                _set_video_path(
                    fixture,
                    fixture["video_ids"][0],
                    "../outside.mp4",
                )
            )
            _assert_error(client.delete(_delete_url(fixture)), 500)
            assert asyncio.run(_read_state(fixture))["clip"] == before["clip"]
            assert all(
                (tmp_path / Path(path)).is_file()
                for path in [fixture["override_path"], *fixture["video_paths"]]
            )
            awaitable_path = fixture["video_paths"][0]
            asyncio.run(_set_video_path(fixture, fixture["video_ids"][0], awaitable_path))
            asyncio.run(
                _set_video_path(
                    fixture,
                    fixture["video_ids"][1],
                    _relative_bad_extension(fixture),
                )
            )
            _assert_error(client.delete(_delete_url(fixture)), 500)
            asyncio.run(
                _set_video_path(fixture, fixture["video_ids"][1], fixture["video_paths"][1])
            )
            (tmp_path / Path(fixture["video_paths"][0])).unlink()
            _assert_error(client.delete(_delete_url(fixture)), 500)
        assert asyncio.run(_read_state(fixture)) == before
    finally:
        asyncio.run(_cleanup_fixture(fixture))


def _relative_bad_extension(fixture: dict[str, object]) -> str:
    return (
        f"projects/{fixture['project_id']}/episodes/{fixture['episode_id']}"
        f"/clips/{fixture['clip_id']}/{fixture['video_ids'][1]}.avi"
    )


def test_clip_delete_restores_partial_and_database_failures(
    tmp_path, monkeypatch, caplog
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    original_replace = Path.replace
    original_flush = AsyncSession.flush
    try:
        before = asyncio.run(_read_state(fixture))
        sources = [
            tmp_path / Path(fixture["override_path"]),
            *(tmp_path / Path(path) for path in fixture["video_paths"]),
        ]
        with TestClient(app, raise_server_exceptions=False) as client:
            replace_calls = 0

            def fail_second_move(self, target):
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 2:
                    raise OSError("C008 injected partial media move failure")
                return original_replace(self, target)

            monkeypatch.setattr(Path, "replace", fail_second_move)
            partial_failure = client.delete(_delete_url(fixture))
            _assert_error(partial_failure, 500)
            assert all(path.is_file() for path in sources)
            assert all(
                not (tmp_path / "trash" / path.relative_to(tmp_path)).exists()
                for path in sources
            )
            assert asyncio.run(_read_state(fixture)) == before

            monkeypatch.setattr(Path, "replace", original_replace)

            async def failing_flush(self, *args, **kwargs):
                await original_flush(self, *args, **kwargs)
                raise RuntimeError("C008 injected clip delete database failure")

            monkeypatch.setattr(AsyncSession, "flush", failing_flush)
            database_failure = client.delete(_delete_url(fixture))
            _assert_error(database_failure, 500)
            assert all(path.is_file() for path in sources)
            assert asyncio.run(_read_state(fixture)) == before

            monkeypatch.setattr(AsyncSession, "flush", original_flush)
            caplog.clear()
            old_override = tmp_path / Path(fixture["override_path"])
            old_override_trash = tmp_path / "trash" / Path(fixture["override_path"])

            def fail_override_restore(self, target):
                if self == old_override_trash and Path(target) == old_override:
                    raise OSError("C008 injected clip media restore failure")
                return original_replace(self, target)

            monkeypatch.setattr(Path, "replace", fail_override_restore)
            monkeypatch.setattr(AsyncSession, "flush", failing_flush)
            restore_failure = client.delete(_delete_url(fixture))
            _assert_error(restore_failure, 500)
            assert "C008 injected clip delete database failure" in caplog.text
            assert "clip media restore failed" in caplog.text
            assert asyncio.run(_read_state(fixture)) == before
            assert not old_override.exists()
            assert old_override_trash.read_bytes() == fixture["override_bytes"]
    finally:
        monkeypatch.setattr(Path, "replace", original_replace)
        monkeypatch.setattr(AsyncSession, "flush", original_flush)
        asyncio.run(_cleanup_fixture(fixture))
