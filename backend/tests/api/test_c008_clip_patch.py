import asyncio
import os

import asyncpg
import httpx
from fastapi.testclient import TestClient

from app.db.session import dispose_engine
from app.main import app
from tests.api.test_c008_clip_create import _cleanup_fixture, _create_fixture


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _create_clip(client: TestClient, fixture: dict[str, object]) -> dict[str, object]:
    response = client.post(
        f"/api/episodes/{fixture['episode_id']}/clips",
        json={
            "shot_ids": [fixture["shots"]["first"], fixture["shots"]["second"]],
            "reference_asset_ids": [fixture["assets"]["character_first"]],
            "requested_duration": 8,
            "user_note": "初始意见",
        },
    )
    assert response.status_code == 201
    return response.json()


async def _read_shot_state(shot_id: int) -> tuple[int, str, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            "SELECT revision, status, order_index FROM shots WHERE id = $1",
            shot_id,
        )
        return int(row["revision"]), str(row["status"]), int(row["order_index"])
    finally:
        await connection.close()


async def _read_clip_state(clip_id: int) -> tuple[int, str | None, int, str, str]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT revision, user_note, requested_duration,
                   freshness, generation_state
            FROM clips
            WHERE id = $1
            """,
            clip_id,
        )
        return (
            int(row["revision"]),
            row["user_note"],
            int(row["requested_duration"]),
            str(row["freshness"]),
            str(row["generation_state"]),
        )
    finally:
        await connection.close()


async def _read_slot_state(clip_id: int) -> list[tuple[int, int, bool]]:
    connection = await asyncpg.connect(_database_url())
    try:
        rows = await connection.fetch(
            """
            SELECT slot_no, asset_id, enabled
            FROM clip_ref_slots
            WHERE clip_id = $1
            ORDER BY slot_no
            """,
            clip_id,
        )
        return [
            (int(row["slot_no"]), int(row["asset_id"]), bool(row["enabled"]))
            for row in rows
        ]
    finally:
        await connection.close()


async def _run_concurrent_patches(clip_id: int) -> list[httpx.Response]:
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return list(
                await asyncio.gather(
                    client.patch(
                        f"/api/clips/{clip_id}",
                        json={"user_note": "并发意见"},
                    ),
                    client.patch(
                        f"/api/clips/{clip_id}",
                        json={"requested_duration": 9},
                    ),
                )
            )
    finally:
        await dispose_engine()


def _assert_error(response, status_code: int) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert body["detail"]["code"]
    assert body["detail"]["message"]


def test_clip_patch_supports_noop_clear_and_single_revision_change() -> None:
    fixture = asyncio.run(_create_fixture())
    try:
        with TestClient(app) as client:
            created = _create_clip(client, fixture)
            clip_id = created["id"]
            shot_state = asyncio.run(_read_shot_state(fixture["shots"]["first"]))
            slot_state = asyncio.run(_read_slot_state(clip_id))

            noop = client.patch(
                f"/api/clips/{clip_id}",
                json={"user_note": "初始意见", "requested_duration": 8},
            )
            assert noop.status_code == 200
            assert noop.json() == created

            changed = client.patch(
                f"/api/clips/{clip_id}",
                json={"user_note": None, "requested_duration": 9},
            )
            assert changed.status_code == 200
            changed_body = changed.json()
            assert changed_body["user_note"] is None
            assert changed_body["requested_duration"] == 9
            assert changed_body["revision"] == 2
            assert changed_body["freshness"] == "stale"
            assert changed_body["generation_state"] == "empty"
            assert changed_body["shot_ids"] == created["shot_ids"]
            assert changed_body["enabled_slot_count"] == 1
            assert changed_body["updated_at"] != created["updated_at"]

            note_only = client.patch(
                f"/api/clips/{clip_id}", json={"user_note": "新意见"}
            )
            assert note_only.status_code == 200
            assert note_only.json()["revision"] == 3
            assert note_only.json()["requested_duration"] == 9

            for body in (
                {},
                {"unknown": True},
                {"requested_duration": None},
                {"requested_duration": True},
                {"requested_duration": 5.5},
                {"requested_duration": "9"},
                {"requested_duration": 4},
                {"requested_duration": 16},
                {"user_note": 3},
            ):
                _assert_error(client.patch(f"/api/clips/{clip_id}", json=body), 422)
            _assert_error(client.patch("/api/clips/2147483647", json={"user_note": "x"}), 404)

        assert asyncio.run(_read_shot_state(fixture["shots"]["first"])) == shot_state
        assert asyncio.run(_read_slot_state(clip_id)) == slot_state
        assert asyncio.run(_read_clip_state(clip_id)) == (
            3,
            "新意见",
            9,
            "stale",
            "empty",
        )
    finally:
        asyncio.run(_cleanup_fixture(fixture))


def test_clip_patch_concurrent_requests_serialize_on_current_values() -> None:
    fixture = asyncio.run(_create_fixture())
    try:
        with TestClient(app) as client:
            created = _create_clip(client, fixture)
        responses = asyncio.run(_run_concurrent_patches(created["id"]))
        assert [response.status_code for response in responses] == [200, 200]
        assert asyncio.run(_read_clip_state(created["id"])) == (
            3,
            "并发意见",
            9,
            "stale",
            "empty",
        )
    finally:
        asyncio.run(_cleanup_fixture(fixture))
