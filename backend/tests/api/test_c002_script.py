import asyncio
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient

from app.main import app


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _create_downstream_rows(
    project_id: int, episode_id: int, sentinel_path: Path
) -> tuple[int, int, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        asset_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source)
            VALUES ($1, 'character', 'Sentinel Character', 'unchanged', 'manual')
            RETURNING id
            """,
            project_id,
        )
        shot_id = await connection.fetchval(
            """
            INSERT INTO shots (
                episode_id, order_index, duration_est, shot_type, camera,
                description, dialogue, status
            )
            VALUES ($1, 1, 1.0, 'wide', 'static', 'unchanged', '', 'changed')
            RETURNING id
            """,
            episode_id,
        )
        clip_id = await connection.fetchval(
            """
            INSERT INTO clips (
                episode_id, generation_mode, requested_duration,
                generation_state, freshness
            )
            VALUES ($1, 'ref2v', 5, 'ready', 'stale')
            RETURNING id
            """,
            episode_id,
        )
        await connection.execute(
            "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, 1)",
            clip_id,
            shot_id,
        )
        await connection.execute(
            """
            INSERT INTO clip_videos (
                clip_id, file_path, sha256, seed, requested_duration, is_current
            )
            VALUES ($1, $2, 'sentinel-sha256', 1, 5, false)
            """,
            clip_id,
            str(sentinel_path),
        )
        return asset_id, shot_id, clip_id
    finally:
        await connection.close()


async def _snapshot_downstream(project_id: int, episode_id: int) -> dict[str, list[tuple]]:
    connection = await asyncpg.connect(_database_url())
    try:
        tables = {
            "assets": await connection.fetch(
                """
                SELECT id, project_id, type, name, description, source, revision,
                       image_prompt_cache, image_prompt_hash
                FROM assets WHERE project_id = $1 ORDER BY id
                """,
                project_id,
            ),
            "shots": await connection.fetch(
                """
                SELECT id, episode_id, order_index, duration_est, shot_type, camera,
                       description, dialogue, status, revision
                FROM shots WHERE episode_id = $1 ORDER BY id
                """,
                episode_id,
            ),
            "clips": await connection.fetch(
                """
                SELECT id, episode_id, generation_mode, user_note,
                       requested_duration, prompt_cache, prompt_input_hash,
                       generation_state, freshness, revision
                FROM clips WHERE episode_id = $1 ORDER BY id
                """,
                episode_id,
            ),
            "clip_videos": await connection.fetch(
                """
                SELECT cv.id, cv.clip_id, cv.file_path, cv.sha256, cv.seed,
                       cv.requested_duration, cv.actual_duration, cv.is_current,
                       cv.built_prompt, cv.input_hash, cv.input_snapshot
                FROM clip_videos cv
                JOIN clips c ON c.id = cv.clip_id
                WHERE c.episode_id = $1 ORDER BY cv.id
                """,
                episode_id,
            ),
        }
        return {name: [tuple(row.values()) for row in rows] for name, rows in tables.items()}
    finally:
        await connection.close()


async def _cleanup(
    style_id: int | None,
    project_id: int | None,
    episode_id: int | None,
    asset_id: int | None,
    shot_id: int | None,
    clip_id: int | None,
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        if clip_id is not None:
            await connection.execute("DELETE FROM clip_videos WHERE clip_id = $1", clip_id)
            await connection.execute("DELETE FROM clip_shots WHERE clip_id = $1", clip_id)
            await connection.execute("DELETE FROM clips WHERE id = $1", clip_id)
        if shot_id is not None:
            await connection.execute("DELETE FROM shots WHERE id = $1", shot_id)
        if asset_id is not None:
            await connection.execute("DELETE FROM assets WHERE id = $1", asset_id)
        if episode_id is not None:
            await connection.execute("DELETE FROM episodes WHERE id = $1", episode_id)
        if project_id is not None:
            await connection.execute("DELETE FROM projects WHERE id = $1", project_id)
        if style_id is not None:
            await connection.execute("DELETE FROM styles WHERE id = $1", style_id)
    finally:
        await connection.close()


def test_script_revision_preserves_downstream_rows() -> None:
    style_id = project_id = episode_id = asset_id = shot_id = clip_id = None
    sentinel_fd, sentinel_name = tempfile.mkstemp(prefix="c002-script-")
    os.close(sentinel_fd)
    sentinel_path = Path(sentinel_name)
    sentinel_path.write_text("sentinel", encoding="utf-8")

    try:
        with TestClient(app) as client:
            style_response = client.post(
                "/api/styles",
                json={
                    "name": "Script Test Style " + uuid4().hex,
                    "prompt_fragment": "script test",
                },
            )
            assert style_response.status_code == 201
            style_id = style_response.json()["id"]

            project_response = client.post(
                "/api/projects",
                json={
                    "name": "Script Test Project " + uuid4().hex,
                    "style_id": style_id,
                },
            )
            assert project_response.status_code == 201
            project_id = project_response.json()["id"]

            episode_response = client.post(
                f"/api/projects/{project_id}/episodes",
                json={"seq": 1, "title": "Episode", "script_text": "draft"},
            )
            assert episode_response.status_code == 201
            episode = episode_response.json()
            episode_id = episode["id"]
            assert episode["script_revision"] == 1
            assert episode["assets_generated_script_revision"] is None
            assert episode["shots_generated_script_revision"] is None

            asset_id, shot_id, clip_id = asyncio.run(
                _create_downstream_rows(project_id, episode_id, sentinel_path)
            )
            before = asyncio.run(_snapshot_downstream(project_id, episode_id))
            before_file = sentinel_path.read_text(encoding="utf-8")

            first_change = client.patch(
                f"/api/episodes/{episode_id}",
                json={"script_text": "first revision"},
            )
            assert first_change.status_code == 200
            assert first_change.json()["script_revision"] == 2

            second_change = client.patch(
                f"/api/episodes/{episode_id}",
                json={"script_text": "second revision"},
            )
            assert second_change.status_code == 200
            assert second_change.json()["script_revision"] == 3

            metadata_change = client.patch(
                f"/api/episodes/{episode_id}",
                json={"seq": 2, "title": "Renamed Episode"},
            )
            assert metadata_change.status_code == 200
            assert metadata_change.json()["script_revision"] == 3

            same_script = client.patch(
                f"/api/episodes/{episode_id}",
                json={"script_text": "second revision"},
            )
            assert same_script.status_code == 200
            assert same_script.json()["script_revision"] == 3
            assert same_script.json()["updated_at"] == metadata_change.json()["updated_at"]

            too_long = client.patch(
                f"/api/episodes/{episode_id}",
                json={"script_text": "x" * 2001},
            )
            assert too_long.status_code == 422
            assert too_long.json()["detail"]["code"] == "validation_error"
            assert "2000" in too_long.json()["detail"]["message"]

            after = asyncio.run(_snapshot_downstream(project_id, episode_id))
            assert after == before
            assert sentinel_path.read_text(encoding="utf-8") == before_file
    finally:
        asyncio.run(
            _cleanup(style_id, project_id, episode_id, asset_id, shot_id, clip_id)
        )
        sentinel_path.unlink(missing_ok=True)
