from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.db.session import engine
from app.main import app
from app.tasks.queue import TaskQueue
from tests.api.test_c008_clip_create import _cleanup_fixture, _create_fixture


def _assert_validation_error(response) -> None:
    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "validation_error",
            "message": "Request validation failed",
        }
    }


async def _read_user_note(clip_id: int) -> str | None:
    import os

    import asyncpg

    connection = await asyncpg.connect(
        os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)
    )
    try:
        return await connection.fetchval(
            "SELECT user_note FROM clips WHERE id = $1", clip_id
        )
    finally:
        await connection.close()


def test_c008_user_note_nul_is_rejected_before_sql_and_empty_is_preserved(
    monkeypatch,
) -> None:
    async def idle_worker(
        self,
        *,
        handlers,
        stop_event=None,
        poll_interval=0.5,
        stop_when_idle=False,
    ) -> None:
        del self, handlers, poll_interval, stop_when_idle
        assert stop_event is not None
        await stop_event.wait()

    monkeypatch.setattr(TaskQueue, "run_worker", idle_worker)
    fixture = asyncio.run(_create_fixture())
    counter = {"sql": 0}

    def count_sql(*args) -> None:
        del args
        counter["sql"] += 1

    event.listen(engine.sync_engine, "before_cursor_execute", count_sql)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            create_before = asyncio.run(_counts(fixture["episode_id"]))
            counter["sql"] = 0
            invalid_create = client.post(
                f"/api/episodes/{fixture['episode_id']}/clips",
                json={
                    "shot_ids": [fixture["shots"]["first"]],
                    "reference_asset_ids": [fixture["assets"]["character_first"]],
                    "user_note": "before\x00after",
                },
            )
            _assert_validation_error(invalid_create)
            assert counter["sql"] == 0
            assert asyncio.run(_counts(fixture["episode_id"])) == create_before

            patch_before = asyncio.run(_counts(fixture["episode_id"]))
            counter["sql"] = 0
            invalid_patch = client.patch(
                f"/api/clips/{fixture['occupied_clip_id']}",
                json={"user_note": "before\x00after"},
            )
            _assert_validation_error(invalid_patch)
            assert counter["sql"] == 0
            assert asyncio.run(_counts(fixture["episode_id"])) == patch_before

            empty_create = client.post(
                f"/api/episodes/{fixture['episode_id']}/clips",
                json={
                    "shot_ids": [fixture["shots"]["first"]],
                    "reference_asset_ids": [fixture["assets"]["character_first"]],
                    "user_note": "",
                },
            )
            assert empty_create.status_code == 201
            assert empty_create.json()["user_note"] == ""
            assert asyncio.run(_read_user_note(empty_create.json()["id"])) == ""
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_sql)
        asyncio.run(_cleanup_fixture(fixture))


async def _counts(episode_id: int) -> tuple[int, int, int]:
    import os

    import asyncpg

    connection = await asyncpg.connect(
        os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)
    )
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
