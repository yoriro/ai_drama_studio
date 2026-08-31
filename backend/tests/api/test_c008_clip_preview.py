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
            VALUES ($1, 'C008 preview style')
            RETURNING id
            """,
            "C008 preview style " + uuid4().hex,
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C008 preview project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, 'Preview episode', 'preview')
            RETURNING id
            """,
            project_id,
        )
        other_episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 2, 'Other episode', 'other')
            RETURNING id
            """,
            project_id,
        )

        assets: dict[str, int] = {}
        for key, asset_type, name in (
            ("character_first", "character", "先出现的人物"),
            ("character_second", "character", "后出现的人物"),
            ("scene_first", "scene", "第一场景"),
            ("scene_second", "scene", "第二场景"),
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
                name + "描述",
            )

        shots: dict[str, int] = {}
        shot_specs = (
            ("first", episode_id, 1, 2.0, ("character_first", "scene_first")),
            ("second", episode_id, 2, 3.0, ("character_second", "scene_first")),
            ("occupied", episode_id, 3, 1.0, ("character_first",)),
            (
                "double_scene",
                episode_id,
                4,
                1.0,
                ("character_first", "scene_first", "scene_second"),
            ),
            ("long_one", episode_id, 5, 5.0, ("character_first",)),
            ("long_two", episode_id, 6, 5.0, ("character_first",)),
            ("long_three", episode_id, 7, 5.0, ("character_first",)),
            ("long_four", episode_id, 8, 5.0, ("character_first",)),
            ("no_assets", episode_id, 9, 1.0, ()),
            ("foreign", other_episode_id, 1, 2.0, ("character_first",)),
        )
        for key, shot_episode_id, order_index, duration, asset_keys in shot_specs:
            shots[key] = await connection.fetchval(
                """
                INSERT INTO shots
                    (episode_id, order_index, duration_est, shot_type, camera,
                     description, dialogue, status, revision)
                VALUES ($1, $2, $3, '中景', '固定', $4, '', 'normal', 1)
                RETURNING id
                """,
                shot_episode_id,
                order_index,
                duration,
                "shot " + key,
            )
            await connection.executemany(
                "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
                [(shots[key], assets[asset_key]) for asset_key in asset_keys],
            )

        occupied_clip_id = await connection.fetchval(
            """
            INSERT INTO clips (episode_id, requested_duration)
            VALUES ($1, 5)
            RETURNING id
            """,
            episode_id,
        )
        await connection.execute(
            """
            INSERT INTO clip_shots (clip_id, shot_id, position)
            VALUES ($1, $2, 1)
            """,
            occupied_clip_id,
            shots["occupied"],
        )
    finally:
        await connection.close()
    return {
        "style_id": style_id,
        "project_id": project_id,
        "episode_id": episode_id,
        "other_episode_id": other_episode_id,
        "occupied_clip_id": occupied_clip_id,
        "assets": assets,
        "shots": shots,
    }


async def _row_counts(episode_id: int) -> tuple[int, int, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        counts: list[int] = []
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
            counts.append(int(await connection.fetchval(query, episode_id)))
        return counts[0], counts[1], counts[2]
    finally:
        await connection.close()


async def _cleanup_fixture(fixture: dict[str, object]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM clip_shots WHERE clip_id = $1",
            fixture["occupied_clip_id"],
        )
        await connection.execute(
            "DELETE FROM clips WHERE id = $1", fixture["occupied_clip_id"]
        )
        await connection.execute(
            "DELETE FROM shot_assets WHERE shot_id IN "
            "(SELECT id FROM shots WHERE episode_id IN ($1, $2))",
            fixture["episode_id"],
            fixture["other_episode_id"],
        )
        await connection.execute(
            "DELETE FROM shots WHERE episode_id IN ($1, $2)",
            fixture["episode_id"],
            fixture["other_episode_id"],
        )
        await connection.execute(
            "DELETE FROM episodes WHERE id IN ($1, $2)",
            fixture["episode_id"],
            fixture["other_episode_id"],
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


def test_clip_preview_returns_exact_sorted_rules_without_writes() -> None:
    fixture = asyncio.run(_create_fixture())
    try:
        before = asyncio.run(_row_counts(fixture["episode_id"]))
        with TestClient(app) as client:
            response = client.post(
                f"/api/episodes/{fixture['episode_id']}/clips/preview",
                json={
                    "shot_ids": [
                        fixture["shots"]["second"],
                        fixture["shots"]["first"],
                        fixture["shots"]["occupied"],
                    ]
                },
            )
        assert response.status_code == 200
        assert response.json() == {
            "episode_id": fixture["episode_id"],
            "shot_ids": [
                fixture["shots"]["first"],
                fixture["shots"]["second"],
                fixture["shots"]["occupied"],
            ],
            "duration_est_total": 6.0,
            "suggested_requested_duration": 6,
            "reference_candidates": [
                {
                    "asset_id": fixture["assets"]["character_first"],
                    "asset_type": "character",
                    "asset_name": "先出现的人物",
                    "first_shot_id": fixture["shots"]["first"],
                    "first_order_index": 1,
                    "selected_by_default": True,
                },
                {
                    "asset_id": fixture["assets"]["character_second"],
                    "asset_type": "character",
                    "asset_name": "后出现的人物",
                    "first_shot_id": fixture["shots"]["second"],
                    "first_order_index": 2,
                    "selected_by_default": True,
                },
                {
                    "asset_id": fixture["assets"]["scene_first"],
                    "asset_type": "scene",
                    "asset_name": "第一场景",
                    "first_shot_id": fixture["shots"]["first"],
                    "first_order_index": 1,
                    "selected_by_default": True,
                },
            ],
            "default_reference_asset_ids": [
                fixture["assets"]["character_first"],
                fixture["assets"]["character_second"],
                fixture["assets"]["scene_first"],
            ],
            "violations": [
                {
                    "code": "shot_already_in_clip",
                    "message": (
                        "Shots already belong to a clip: "
                        f"{fixture['shots']['occupied']}."
                    ),
                }
            ],
            "warnings": [],
        }
        assert asyncio.run(_row_counts(fixture["episode_id"])) == before
    finally:
        asyncio.run(_cleanup_fixture(fixture))


def test_clip_preview_returns_rule_violations_as_200_and_preserves_rows() -> None:
    fixture = asyncio.run(_create_fixture())
    try:
        before = asyncio.run(_row_counts(fixture["episode_id"]))
        with TestClient(app) as client:
            discontinuous = client.post(
                f"/api/episodes/{fixture['episode_id']}/clips/preview",
                json={
                    "shot_ids": [
                        fixture["shots"]["first"],
                        fixture["shots"]["double_scene"],
                    ]
                },
            )
            assert discontinuous.status_code == 200
            assert [
                item["code"] for item in discontinuous.json()["violations"]
            ] == [
                "shots_not_contiguous",
                "shot_has_multiple_scenes",
                "multiple_scenes",
            ]

            too_long = client.post(
                f"/api/episodes/{fixture['episode_id']}/clips/preview",
                json={
                    "shot_ids": [
                        fixture["shots"]["long_one"],
                        fixture["shots"]["long_two"],
                        fixture["shots"]["long_three"],
                        fixture["shots"]["long_four"],
                    ]
                },
            )
            assert too_long.status_code == 200
            assert [item["code"] for item in too_long.json()["violations"]] == [
                "duration_exceeds_max"
            ]

            no_assets = client.post(
                f"/api/episodes/{fixture['episode_id']}/clips/preview",
                json={"shot_ids": [fixture["shots"]["no_assets"]]},
            )
            assert no_assets.status_code == 200
            assert [item["code"] for item in no_assets.json()["violations"]] == [
                "no_reference_candidates"
            ]
            assert [item["code"] for item in no_assets.json()["warnings"]] == [
                "duration_below_min"
            ]
        assert asyncio.run(_row_counts(fixture["episode_id"])) == before
    finally:
        asyncio.run(_cleanup_fixture(fixture))


def test_clip_preview_rejects_unknown_or_invalid_shot_selection() -> None:
    fixture = asyncio.run(_create_fixture())
    try:
        with TestClient(app) as client:
            _assert_error(
                client.post(
                    "/api/episodes/2147483647/clips/preview",
                    json={"shot_ids": [fixture["shots"]["first"]]},
                ),
                404,
            )
            for body in (
                {"shot_ids": []},
                {"shot_ids": [fixture["shots"]["first"], fixture["shots"]["first"]]},
                {"shot_ids": [True]},
                {"shot_ids": [1.5]},
                {"shot_ids": ["1"]},
                {"shot_ids": [fixture["shots"]["foreign"]]},
                {"shot_ids": [fixture["shots"]["first"]], "extra": True},
            ):
                _assert_error(
                    client.post(
                        f"/api/episodes/{fixture['episode_id']}/clips/preview",
                        json=body,
                    ),
                    422,
                )
    finally:
        asyncio.run(_cleanup_fixture(fixture))
