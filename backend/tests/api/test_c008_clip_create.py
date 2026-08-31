import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _create_fixture() -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, 'C008 create style')
            RETURNING id
            """,
            "C008 create style " + uuid4().hex,
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C008 create project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, 'Create episode', 'create')
            RETURNING id
            """,
            project_id,
        )

        assets: dict[str, int] = {}
        for key, asset_type, name in (
            ("character_first", "character", "先出现人物"),
            ("character_second", "character", "后出现人物"),
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

        overflow_asset_ids: list[int] = []
        for index in range(10):
            overflow_asset_ids.append(
                await connection.fetchval(
                    """
                    INSERT INTO assets (project_id, type, name, description, source)
                    VALUES ($1, 'character', $2, $3, 'manual')
                    RETURNING id
                    """,
                    project_id,
                    f"超限人物{index}",
                    f"超限人物{index}描述",
                )
            )

        shots: dict[str, int] = {}
        for key, order_index, duration, asset_keys in (
            (
                "first",
                1,
                2.0,
                ("character_first", "scene_first"),
            ),
            (
                "second",
                2,
                3.0,
                ("character_second", "scene_first"),
            ),
            ("third", 3, 1.0, ("character_first",)),
            (
                "double_scene",
                4,
                1.0,
                ("character_first", "scene_first", "scene_second"),
            ),
            ("overflow", 5, 2.0, ("character_first",)),
            ("no_assets", 6, 1.0, ()),
        ):
            shots[key] = await connection.fetchval(
                """
                INSERT INTO shots
                    (episode_id, order_index, duration_est, shot_type, camera,
                     description, dialogue, status, revision)
                VALUES ($1, $2, $3, '中景', '固定', $4, '', 'normal', 1)
                RETURNING id
                """,
                episode_id,
                order_index,
                duration,
                "shot " + key,
            )
            ids = [assets[key_name] for key_name in asset_keys]
            if key == "overflow":
                ids.extend(overflow_asset_ids)
            await connection.executemany(
                "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
                [(shots[key], asset_id) for asset_id in ids],
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
            shots["third"],
        )
    finally:
        await connection.close()
    return {
        "style_id": style_id,
        "project_id": project_id,
        "episode_id": episode_id,
        "occupied_clip_id": occupied_clip_id,
        "assets": assets,
        "overflow_asset_ids": overflow_asset_ids,
        "shots": shots,
    }


async def _counts(episode_id: int) -> tuple[int, int, int]:
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
            values.append(int(await connection.fetchval(query, episode_id)))
        return values[0], values[1], values[2]
    finally:
        await connection.close()


async def _cleanup_fixture(fixture: dict[str, object]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM clip_shots WHERE clip_id IN "
            "(SELECT id FROM clips WHERE episode_id = $1)",
            fixture["episode_id"],
        )
        await connection.execute(
            "DELETE FROM clip_ref_slots WHERE clip_id IN "
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
            "DELETE FROM shot_assets WHERE shot_id IN "
            "(SELECT id FROM shots WHERE episode_id = $1)",
            fixture["episode_id"],
        )
        await connection.execute(
            "DELETE FROM shots WHERE episode_id = $1", fixture["episode_id"]
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


def test_clip_create_persists_sorted_relations_and_stable_list_detail() -> None:
    fixture = asyncio.run(_create_fixture())
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/episodes/{fixture['episode_id']}/clips",
                json={
                    "shot_ids": [
                        fixture["shots"]["second"],
                        fixture["shots"]["first"],
                    ],
                    "reference_asset_ids": [
                        fixture["assets"]["scene_first"],
                        fixture["assets"]["character_second"],
                    ],
                    "requested_duration": 8,
                    "user_note": "节奏紧凑",
                },
            )
            assert response.status_code == 201
            created = response.json()
            clip_id = created["id"]
            assert set(created) == {
                "id",
                "episode_id",
                "generation_mode",
                "user_note",
                "requested_duration",
                "generation_state",
                "freshness",
                "revision",
                "shot_ids",
                "start_order_index",
                "end_order_index",
                "enabled_slot_count",
                "warnings",
                "created_at",
                "updated_at",
            }
            assert created["episode_id"] == fixture["episode_id"]
            assert created["generation_mode"] == "ref2v"
            assert created["user_note"] == "节奏紧凑"
            assert created["requested_duration"] == 8
            assert created["generation_state"] == "empty"
            assert created["freshness"] == "fresh"
            assert created["revision"] == 1
            assert created["shot_ids"] == [
                fixture["shots"]["first"],
                fixture["shots"]["second"],
            ]
            assert created["start_order_index"] == 1
            assert created["end_order_index"] == 2
            assert created["enabled_slot_count"] == 2
            assert created["warnings"] == []
            assert "prompt_cache" not in created
            assert "prompt_input_hash" not in created
            assert "file_path" not in created

            slots = asyncio.run(_read_slots(clip_id))
            assert slots == [
                (
                    1,
                    fixture["assets"]["character_second"],
                    "后出现人物",
                    "character",
                ),
                (2, fixture["assets"]["scene_first"], "第一场景", "scene"),
            ]

            detail = client.get(f"/api/clips/{clip_id}")
            assert detail.status_code == 200
            assert detail.json() == created

            second = client.post(
                f"/api/episodes/{fixture['episode_id']}/clips",
                json={
                    "shot_ids": [fixture["shots"]["overflow"]],
                    "reference_asset_ids": [fixture["overflow_asset_ids"][9]],
                },
            )
            assert second.status_code == 201
            assert second.json()["requested_duration"] == 5
            assert second.json()["shot_ids"] == [fixture["shots"]["overflow"]]

            listed = client.get(f"/api/episodes/{fixture['episode_id']}/clips")
            assert listed.status_code == 200
            listed_rows = listed.json()
            assert [row["start_order_index"] for row in listed_rows] == [1, 3, 5]
            assert [row["id"] for row in listed_rows] == [
                clip_id,
                fixture["occupied_clip_id"],
                second.json()["id"],
            ]
        assert asyncio.run(_counts(fixture["episode_id"])) == (3, 4, 3)
    finally:
        asyncio.run(_cleanup_fixture(fixture))


async def _read_slots(clip_id: int) -> list[tuple[int, int, str, str]]:
    connection = await asyncpg.connect(_database_url())
    try:
        rows = await connection.fetch(
            """
            SELECT slot_no, asset_id, asset_name_snapshot, asset_type_snapshot
            FROM clip_ref_slots
            WHERE clip_id = $1
            ORDER BY slot_no
            """,
            clip_id,
        )
        return [
            (
                int(row["slot_no"]),
                int(row["asset_id"]),
                str(row["asset_name_snapshot"]),
                str(row["asset_type_snapshot"]),
            )
            for row in rows
        ]
    finally:
        await connection.close()


def test_clip_create_accepts_legal_subset_of_overflow_candidates() -> None:
    fixture = asyncio.run(_create_fixture())
    try:
        before = asyncio.run(_counts(fixture["episode_id"]))
        with TestClient(app) as client:
            response = client.post(
                f"/api/episodes/{fixture['episode_id']}/clips",
                json={
                    "shot_ids": [fixture["shots"]["overflow"]],
                    "reference_asset_ids": [fixture["overflow_asset_ids"][0]],
                },
            )
        assert response.status_code == 201
        assert response.json()["enabled_slot_count"] == 1
        assert asyncio.run(_counts(fixture["episode_id"])) == (
            before[0] + 1,
            before[1] + 1,
            before[2] + 1,
        )
    finally:
        asyncio.run(_cleanup_fixture(fixture))


def test_clip_create_rejects_rules_and_body_errors_without_partial_rows() -> None:
    fixture = asyncio.run(_create_fixture())
    try:
        before = asyncio.run(_counts(fixture["episode_id"]))
        with TestClient(app) as client:
            invalid_bodies = (
                {
                    "shot_ids": [
                        fixture["shots"]["first"],
                        fixture["shots"]["overflow"],
                    ],
                    "reference_asset_ids": [fixture["assets"]["character_first"]],
                },
                {
                    "shot_ids": [fixture["shots"]["first"]],
                    "reference_asset_ids": [fixture["assets"]["scene_second"]],
                },
                {
                    "shot_ids": [fixture["shots"]["first"]],
                    "reference_asset_ids": [fixture["assets"]["character_first"]],
                    "requested_duration": None,
                },
                {
                    "shot_ids": [fixture["shots"]["first"]],
                    "reference_asset_ids": [fixture["assets"]["character_first"]],
                    "requested_duration": 5.5,
                },
                {
                    "shot_ids": [fixture["shots"]["first"]],
                    "reference_asset_ids": [fixture["assets"]["character_first"]],
                    "unexpected": True,
                },
            )
            for body in invalid_bodies:
                _assert_error(
                    client.post(
                        f"/api/episodes/{fixture['episode_id']}/clips",
                        json=body,
                    ),
                    422,
                )
            _assert_error(
                client.post(
                    "/api/2147483647/clips",
                    json={
                        "shot_ids": [fixture["shots"]["first"]],
                        "reference_asset_ids": [
                            fixture["assets"]["character_first"]
                        ],
                    },
                ),
                404,
            )
        assert asyncio.run(_counts(fixture["episode_id"])) == before
    finally:
        asyncio.run(_cleanup_fixture(fixture))


@pytest.mark.parametrize("fail_after_flush", [1, 2])
def test_clip_create_rolls_back_when_a_write_flush_fails(
    monkeypatch: pytest.MonkeyPatch, fail_after_flush: int
) -> None:
    fixture = asyncio.run(_create_fixture())
    try:
        before = asyncio.run(_counts(fixture["episode_id"]))
        flush_count = 0
        original_flush = AsyncSession.flush

        async def failing_flush(self, *args, **kwargs):
            nonlocal flush_count
            await original_flush(self, *args, **kwargs)
            flush_count += 1
            if flush_count == fail_after_flush:
                raise RuntimeError("C008 injected database flush failure")

        monkeypatch.setattr(AsyncSession, "flush", failing_flush)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                f"/api/episodes/{fixture['episode_id']}/clips",
                json={
                    "shot_ids": [
                        fixture["shots"]["first"],
                        fixture["shots"]["second"],
                    ],
                    "reference_asset_ids": [
                        fixture["assets"]["character_first"]
                    ],
                },
            )
        assert response.status_code == 500
        assert response.json()["detail"]["code"] == "internal_error"
        assert asyncio.run(_counts(fixture["episode_id"])) == before
    finally:
        asyncio.run(_cleanup_fixture(fixture))
