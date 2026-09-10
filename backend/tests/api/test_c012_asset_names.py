from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient

from app.main import app


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _asset_rows(project_id: int) -> list[tuple[object, ...]]:
    connection = await asyncpg.connect(_database_url())
    try:
        rows = await connection.fetch(
            "SELECT id, name, description, revision "
            "FROM assets WHERE project_id = $1 ORDER BY id",
            project_id,
        )
        return [tuple(row) for row in rows]
    finally:
        await connection.close()


async def _create_downstream(project_id: int, asset_id: int) -> tuple[int, int, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        episode_id = await connection.fetchval(
            "INSERT INTO episodes "
            "(project_id, seq, title, script_text, script_revision) "
            "VALUES ($1, 1, 'C012 names episode', 'C012 names script', 1) RETURNING id",
            project_id,
        )
        shot_id = await connection.fetchval(
            "INSERT INTO shots "
            "(episode_id, order_index, duration_est, shot_type, camera, "
            "description, dialogue, status, revision) "
            "VALUES ($1, 1, 5.0, 'wide', 'fixed', 'C012 names shot', '', 'normal', 1) "
            "RETURNING id",
            episode_id,
        )
        clip_id = await connection.fetchval(
            "INSERT INTO clips "
            "(episode_id, requested_duration, generation_state, freshness, revision) "
            "VALUES ($1, 5, 'ready', 'fresh', 1) RETURNING id",
            episode_id,
        )
        await connection.execute(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
            shot_id,
            asset_id,
        )
        await connection.execute(
            "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, 1)",
            clip_id,
            shot_id,
        )
        return int(episode_id), int(shot_id), int(clip_id)
    finally:
        await connection.close()


async def _downstream_state(
    asset_id: int,
    episode_id: int,
    shot_id: int,
    clip_id: int,
) -> tuple[object, ...]:
    connection = await asyncpg.connect(_database_url())
    try:
        asset = await connection.fetchrow(
            "SELECT id, name, description, revision FROM assets WHERE id = $1",
            asset_id,
        )
        episode = await connection.fetchrow(
            "SELECT id, project_id, seq, title, script_text, script_revision "
            "FROM episodes WHERE id = $1",
            episode_id,
        )
        shot = await connection.fetchrow(
            "SELECT id, episode_id, order_index, status, revision, description "
            "FROM shots WHERE id = $1",
            shot_id,
        )
        clip = await connection.fetchrow(
            "SELECT id, episode_id, generation_state, freshness, revision "
            "FROM clips WHERE id = $1",
            clip_id,
        )
        shot_assets = await connection.fetch(
            "SELECT shot_id, asset_id FROM shot_assets WHERE shot_id = $1",
            shot_id,
        )
        clip_shots = await connection.fetch(
            "SELECT clip_id, shot_id, position FROM clip_shots WHERE clip_id = $1",
            clip_id,
        )
        return (
            tuple(asset) if asset is not None else None,
            tuple(episode) if episode is not None else None,
            tuple(shot) if shot is not None else None,
            tuple(clip) if clip is not None else None,
            [tuple(row) for row in shot_assets],
            [tuple(row) for row in clip_shots],
        )
    finally:
        await connection.close()


async def _cleanup(
    style_id: int | None,
    project_ids: list[int],
    asset_ids: list[int],
    episode_id: int | None,
    shot_id: int | None,
    clip_id: int | None,
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        if clip_id is not None:
            await connection.execute("DELETE FROM clip_shots WHERE clip_id = $1", clip_id)
            await connection.execute("DELETE FROM clips WHERE id = $1", clip_id)
        if shot_id is not None:
            await connection.execute("DELETE FROM shot_assets WHERE shot_id = $1", shot_id)
            await connection.execute("DELETE FROM shots WHERE id = $1", shot_id)
        if episode_id is not None:
            await connection.execute("DELETE FROM episodes WHERE id = $1", episode_id)
        if asset_ids:
            await connection.execute(
                "DELETE FROM assets WHERE id = ANY($1::int[])", asset_ids
            )
        if project_ids:
            await connection.execute(
                "DELETE FROM projects WHERE id = ANY($1::int[])", project_ids
            )
        if style_id is not None:
            await connection.execute("DELETE FROM styles WHERE id = $1", style_id)
    finally:
        await connection.close()


def _assert_validation_response(response) -> None:
    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "validation_error",
            "message": "Request validation failed",
        }
    }


def test_c012_asset_name_contract_for_create_and_patch() -> None:
    style_id: int | None = None
    project_ids: list[int] = []
    asset_ids: list[int] = []
    episode_id = shot_id = clip_id = None
    try:
        with TestClient(app) as client:
            style_response = client.post(
                "/api/styles",
                json={
                    "name": "C012 Names Style " + uuid4().hex,
                    "prompt_fragment": "C012 names",
                },
            )
            assert style_response.status_code == 201
            style_id = style_response.json()["id"]

            for suffix in ("one", "two"):
                project_response = client.post(
                    "/api/projects",
                    json={
                        "name": f"C012 Names Project {suffix} " + uuid4().hex,
                        "style_id": style_id,
                    },
                )
                assert project_response.status_code == 201
                project_ids.append(project_response.json()["id"])

            first_response = client.post(
                f"/api/projects/{project_ids[0]}/assets",
                json={
                    "type": "character",
                    "name": "  Hero  ",
                    "description": "Hero description",
                },
            )
            assert first_response.status_code == 201
            first = first_response.json()
            asset_ids.append(first["id"])
            assert first["name"] == "Hero"
            assert first["revision"] == 1

            rows_before_duplicate = asyncio.run(_asset_rows(project_ids[0]))
            duplicate = client.post(
                f"/api/projects/{project_ids[0]}/assets",
                json={
                    "type": "scene",
                    "name": "Hero",
                    "description": "Duplicate scene",
                },
            )
            assert duplicate.status_code == 409
            assert duplicate.json() == {
                "detail": {"code": "conflict", "message": "资产名称已存在"}
            }
            assert asyncio.run(_asset_rows(project_ids[0])) == rows_before_duplicate

            other_project = client.post(
                f"/api/projects/{project_ids[1]}/assets",
                json={
                    "type": "scene",
                    "name": " Hero ",
                    "description": "Other project",
                },
            )
            assert other_project.status_code == 201
            asset_ids.append(other_project.json()["id"])
            assert other_project.json()["name"] == "Hero"

            lower_case = client.post(
                f"/api/projects/{project_ids[0]}/assets",
                json={
                    "type": "scene",
                    "name": "hero",
                    "description": "Lower case is distinct",
                },
            )
            assert lower_case.status_code == 201
            asset_ids.append(lower_case.json()["id"])

            internal_spaces = client.post(
                f"/api/projects/{project_ids[0]}/assets",
                json={
                    "type": "scene",
                    "name": "Hero  Name",
                    "description": "Internal spaces are preserved",
                },
            )
            assert internal_spaces.status_code == 201
            asset_ids.append(internal_spaces.json()["id"])
            assert internal_spaces.json()["name"] == "Hero  Name"

            second_response = client.post(
                f"/api/projects/{project_ids[0]}/assets",
                json={
                    "type": "character",
                    "name": "Second",
                    "description": "Second description",
                },
            )
            assert second_response.status_code == 201
            second = second_response.json()
            asset_ids.append(second["id"])
            episode_id, shot_id, clip_id = asyncio.run(
                _create_downstream(project_ids[0], second["id"])
            )
            downstream_before_rename = asyncio.run(
                _downstream_state(second["id"], episode_id, shot_id, clip_id)
            )

            rename_conflict = client.patch(
                f"/api/assets/{second['id']}", json={"name": " Hero "}
            )
            assert rename_conflict.status_code == 409
            assert rename_conflict.json() == {
                "detail": {"code": "conflict", "message": "资产名称已存在"}
            }
            assert asyncio.run(
                _downstream_state(second["id"], episode_id, shot_id, clip_id)
            ) == downstream_before_rename

            no_op = client.patch(
                f"/api/assets/{first['id']}", json={"name": "  Hero  "}
            )
            assert no_op.status_code == 200
            assert no_op.json()["name"] == "Hero"
            assert no_op.json()["revision"] == first["revision"]
            assert no_op.json()["updated_at"] == first["updated_at"]

            for invalid_name in ("   ", "bad\x00name", "x" * 2001):
                _assert_validation_response(
                    client.post(
                        f"/api/projects/{project_ids[0]}/assets",
                        json={
                            "type": "scene",
                            "name": invalid_name,
                            "description": "invalid name",
                        },
                    )
                )
                _assert_validation_response(
                    client.patch(
                        f"/api/assets/{second['id']}", json={"name": invalid_name}
                    )
                )
            assert asyncio.run(_asset_rows(project_ids[0]))[-1][1:] == (
                "Second",
                "Second description",
                1,
            )
    finally:
        asyncio.run(
            _cleanup(
                style_id,
                project_ids,
                asset_ids,
                episode_id,
                shot_id,
                clip_id,
            )
        )
