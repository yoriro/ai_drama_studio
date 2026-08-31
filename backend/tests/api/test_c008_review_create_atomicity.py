from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.db.session import engine
from app.main import app
from tests.api.test_c008_clip_create import (
    _cleanup_fixture,
    _counts,
    _create_fixture,
)


@pytest.mark.parametrize(
    "failure_table",
    ["clips", "clip_shots", "clip_ref_slots"],
)
def test_c008_create_rolls_back_each_insert_stage(
    failure_table: str,
) -> None:
    fixture = asyncio.run(_create_fixture())
    hit_count = {"value": 0}

    def fail_target_insert(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        normalized = " ".join(statement.upper().split())
        if normalized.startswith(f"INSERT INTO {failure_table.upper()} "):
            hit_count["value"] += 1
            raise RuntimeError(f"C008 injected {failure_table} INSERT failure")

    event.listen(engine.sync_engine, "before_cursor_execute", fail_target_insert)
    try:
        before = asyncio.run(_counts(fixture["episode_id"]))
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
        assert hit_count["value"] == 1
        assert response.status_code == 500
        assert response.json() == {
            "detail": {
                "code": "internal_error",
                "message": "Internal server error",
            }
        }
        assert asyncio.run(_counts(fixture["episode_id"])) == before
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", fail_target_insert)
        asyncio.run(_cleanup_fixture(fixture))
