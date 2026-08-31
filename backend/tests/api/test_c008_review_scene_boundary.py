from __future__ import annotations

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
            VALUES ($1, 'C008 review scene style')
            RETURNING id
            """,
            "C008 review scene style " + uuid4().hex,
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C008 review scene project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, 'Review scene episode', 'scene boundary')
            RETURNING id
            """,
            project_id,
        )
        character_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source)
            VALUES ($1, 'character', 'shared character', 'character description', 'manual')
            RETURNING id
            """,
            project_id,
        )
        scene_ids = []
        for name in ("scene A", "scene B"):
            scene_ids.append(
                await connection.fetchval(
                    """
                    INSERT INTO assets (project_id, type, name, description, source)
                    VALUES ($1, 'scene', $2, $3, 'manual')
                    RETURNING id
                    """,
                    project_id,
                    name,
                    name + " description",
                )
            )

        shot_ids = []
        for order_index, scene_id in enumerate(scene_ids, start=1):
            shot_id = await connection.fetchval(
                """
                INSERT INTO shots
                    (episode_id, order_index, duration_est, shot_type, camera,
                     description, dialogue, status, revision)
                VALUES ($1, $2, 2.5, 'medium', 'fixed', $3, '', 'normal', 1)
                RETURNING id
                """,
                episode_id,
                order_index,
                f"single-scene shot {order_index}",
            )
            await connection.executemany(
                "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
                [(shot_id, character_id), (shot_id, scene_id)],
            )
            shot_ids.append(shot_id)
        return {
            "style_id": style_id,
            "project_id": project_id,
            "episode_id": episode_id,
            "character_id": character_id,
            "shot_ids": shot_ids,
        }
    finally:
        await connection.close()


async def _counts(fixture: dict[str, object]) -> tuple[int, int, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        values = []
        for query in (
            "SELECT count(*) FROM clips WHERE episode_id = $1",
            """
            SELECT count(*)
            FROM clip_shots
            WHERE clip_id IN (SELECT id FROM clips WHERE episode_id = $1)
            """,
            """
            SELECT count(*)
            FROM clip_ref_slots
            WHERE clip_id IN (SELECT id FROM clips WHERE episode_id = $1)
            """,
        ):
            values.append(int(await connection.fetchval(query, fixture["episode_id"])))
        return values[0], values[1], values[2]
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


def test_c008_two_single_scene_shots_are_rejected_as_multiple_scenes() -> None:
    fixture = asyncio.run(_create_fixture())
    try:
        before = asyncio.run(_counts(fixture))
        with TestClient(app, raise_server_exceptions=False) as client:
            preview = client.post(
                f"/api/episodes/{fixture['episode_id']}/clips/preview",
                json={"shot_ids": list(reversed(fixture["shot_ids"]))},
            )
            assert preview.status_code == 200
            preview_body = preview.json()
            assert preview_body["shot_ids"] == fixture["shot_ids"]
            assert [item["code"] for item in preview_body["violations"]] == [
                "multiple_scenes"
            ]
            assert preview_body["warnings"] == []
            assert asyncio.run(_counts(fixture)) == before

            create = client.post(
                f"/api/episodes/{fixture['episode_id']}/clips",
                json={
                    "shot_ids": fixture["shot_ids"],
                    "reference_asset_ids": [fixture["character_id"]],
                },
            )
            assert create.status_code == 422
            assert create.json() == {
                "detail": {
                    "code": "validation_error",
                    "message": "Selected shots reference more than one scene asset.",
                }
            }
            assert asyncio.run(_counts(fixture)) == before
    finally:
        asyncio.run(_cleanup_fixture(fixture))
