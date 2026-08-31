import asyncio
import os

import asyncpg
from fastapi.testclient import TestClient

from app.main import app
from tests.api.test_c008_slots import _cleanup_fixture, _create_fixture


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _read_state(fixture: dict[str, object]) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        clip = await connection.fetchrow(
            """
            SELECT revision, freshness, generation_state
            FROM clips
            WHERE id = $1
            """,
            fixture["clip_id"],
        )
        slots = await connection.fetch(
            """
            SELECT slot_no, enabled
            FROM clip_ref_slots
            WHERE clip_id = $1
            ORDER BY slot_no
            """,
            fixture["clip_id"],
        )
        shot = await connection.fetchrow(
            """
            SELECT revision, status, order_index
            FROM shots
            WHERE id = $1
            """,
            fixture["shot_id"],
        )
        return {
            "clip": (
                int(clip["revision"]),
                str(clip["freshness"]),
                str(clip["generation_state"]),
            ),
            "slots": [
                (int(slot["slot_no"]), bool(slot["enabled"])) for slot in slots
            ],
            "shot": (
                int(shot["revision"]),
                str(shot["status"]),
                int(shot["order_index"]),
            ),
        }
    finally:
        await connection.close()


def _assert_error(response, status_code: int) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"detail"}
    assert body["detail"]["code"]
    assert body["detail"]["message"]


def test_slot_enabled_mutation_is_strict_and_serializes_clip_state() -> None:
    fixture = asyncio.run(_create_fixture())
    try:
        with TestClient(app) as client:
            initial = client.get(f"/api/clips/{fixture['clip_id']}/slots")
            assert initial.status_code == 200
            assert [item["enabled"] for item in initial.json()["items"]] == [
                True,
                True,
                False,
                True,
                True,
                False,
            ]
            assert initial.json()["warnings"] == []

            disable_first = client.patch(
                f"/api/clips/{fixture['clip_id']}/slots/1",
                json={"enabled": False},
            )
            assert disable_first.status_code == 200
            assert set(disable_first.json()) == {"slot", "warnings"}
            assert set(disable_first.json()["slot"]) == {
                "id",
                "clip_id",
                "slot_no",
                "asset_id",
                "asset_name_snapshot",
                "asset_type_snapshot",
                "asset_deleted",
                "enabled",
                "image_source",
                "image_url",
            }
            assert disable_first.json()["slot"]["slot_no"] == 1
            assert disable_first.json()["slot"]["enabled"] is False
            assert disable_first.json()["warnings"] == []
            assert asyncio.run(_read_state(fixture)) == {
                "clip": (2, "stale", "empty"),
                "slots": [
                    (1, False),
                    (2, True),
                    (3, False),
                    (4, True),
                    (5, True),
                    (6, False),
                ],
                "shot": (1, "normal", 1),
            }

            noop = client.patch(
                f"/api/clips/{fixture['clip_id']}/slots/1",
                json={"enabled": False},
            )
            assert noop.status_code == 200
            assert noop.json() == disable_first.json()
            assert asyncio.run(_read_state(fixture))["clip"] == (
                2,
                "stale",
                "empty",
            )

            enable_last = client.patch(
                f"/api/clips/{fixture['clip_id']}/slots/6",
                json={"enabled": True},
            )
            assert enable_last.status_code == 200
            assert enable_last.json()["slot"]["enabled"] is True
            assert enable_last.json()["warnings"] == []

            enable_first = client.patch(
                f"/api/clips/{fixture['clip_id']}/slots/1",
                json={"enabled": True},
            )
            assert enable_first.status_code == 200
            assert [item["code"] for item in enable_first.json()["warnings"]] == [
                "enabled_slots_exceed_recommendation"
            ]
            assert "建议 4 张以内" in enable_first.json()["warnings"][0]["message"]
            assert asyncio.run(_read_state(fixture))["clip"] == (
                4,
                "stale",
                "empty",
            )

            disable_last = client.patch(
                f"/api/clips/{fixture['clip_id']}/slots/6",
                json={"enabled": False},
            )
            assert disable_last.status_code == 200
            assert disable_last.json()["warnings"] == []
            assert asyncio.run(_read_state(fixture))["clip"] == (
                5,
                "stale",
                "empty",
            )

            for body in (
                {},
                {"enabled": 1},
                {"enabled": "true"},
                {"enabled": True, "unknown": False},
                {"enabled": True, "override": "x"},
            ):
                _assert_error(
                    client.patch(
                        f"/api/clips/{fixture['clip_id']}/slots/1", json=body
                    ),
                    422,
                )
            _assert_error(
                client.patch(
                    f"/api/clips/{fixture['clip_id']}/slots/1",
                    files={"file": ("override.png", b"not-an-image", "image/png")},
                    data={"enabled": "true"},
                ),
                422,
            )
            _assert_error(
                client.patch(
                    f"/api/clips/{fixture['clip_id']}/slots/0",
                    json={"enabled": True},
                ),
                422,
            )
            _assert_error(
                client.patch(
                    f"/api/clips/{fixture['clip_id']}/slots/10",
                    json={"enabled": True},
                ),
                422,
            )
            _assert_error(
                client.patch(
                    f"/api/clips/{fixture['clip_id']}/slots/9",
                    json={"enabled": True},
                ),
                404,
            )
            _assert_error(
                client.patch(
                    "/api/clips/2147483647/slots/1", json={"enabled": True}
                ),
                404,
            )

        assert asyncio.run(_read_state(fixture))["slots"] == [
            (1, True),
            (2, True),
            (3, False),
            (4, True),
            (5, True),
            (6, False),
        ]
        assert asyncio.run(_read_state(fixture))["shot"] == (1, "normal", 1)
    finally:
        asyncio.run(_cleanup_fixture(fixture))
