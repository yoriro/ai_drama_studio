import asyncio
import os
from uuid import uuid4

import asyncpg
import httpx
import pytest

from app.db.session import dispose_engine
from app.main import app
from app.services import clips as clip_service


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _create_fixture() -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, 'C008 concurrency style')
            RETURNING id
            """,
            "C008 concurrency style " + uuid4().hex,
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C008 concurrency project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, 'Concurrency episode', 'concurrency')
            RETURNING id
            """,
            project_id,
        )
        asset_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source)
            VALUES ($1, 'character', '人物', '人物描述', 'manual')
            RETURNING id
            """,
            project_id,
        )
        shots: list[int] = []
        for order_index in range(1, 4):
            shot_id = await connection.fetchval(
                """
                INSERT INTO shots
                    (episode_id, order_index, duration_est, shot_type, camera,
                     description, dialogue, status, revision)
                VALUES ($1, $2, 2, '中景', '固定', $3, '', 'normal', 1)
                RETURNING id
                """,
                episode_id,
                order_index,
                f"shot {order_index}",
            )
            shots.append(int(shot_id))
            await connection.execute(
                "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
                shot_id,
                asset_id,
            )
    finally:
        await connection.close()
    return {
        "style_id": style_id,
        "project_id": project_id,
        "episode_id": episode_id,
        "asset_id": asset_id,
        "shots": shots,
    }


async def _read_counts(fixture: dict[str, object]) -> tuple[int, int, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        return (
            int(
                await connection.fetchval(
                    "SELECT count(*) FROM clips WHERE episode_id = $1",
                    fixture["episode_id"],
                )
            ),
            int(
                await connection.fetchval(
                    """
                    SELECT count(*)
                    FROM clip_shots
                    WHERE clip_id IN (SELECT id FROM clips WHERE episode_id = $1)
                    """,
                    fixture["episode_id"],
                )
            ),
            int(
                await connection.fetchval(
                    """
                    SELECT count(*)
                    FROM clip_ref_slots
                    WHERE clip_id IN (SELECT id FROM clips WHERE episode_id = $1)
                    """,
                    fixture["episode_id"],
                )
            ),
        )
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


async def _run_concurrent_requests(
    fixture: dict[str, object],
    first_shot_ids: list[int],
    second_shot_ids: list[int],
    monkeypatch: pytest.MonkeyPatch,
) -> list[httpx.Response]:
    ready = asyncio.Event()
    arrived = 0
    original_load = clip_service._load_selection

    async def gated_load(*args, **kwargs):
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            ready.set()
        await ready.wait()
        return await original_load(*args, **kwargs)

    monkeypatch.setattr(clip_service, "_load_selection", gated_load)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return list(
                await asyncio.gather(
                    client.post(
                        f"/api/episodes/{fixture['episode_id']}/clips",
                        json={
                            "shot_ids": first_shot_ids,
                            "reference_asset_ids": [fixture["asset_id"]],
                        },
                    ),
                    client.post(
                        f"/api/episodes/{fixture['episode_id']}/clips",
                        json={
                            "shot_ids": second_shot_ids,
                            "reference_asset_ids": [fixture["asset_id"]],
                        },
                    ),
                )
            )
    finally:
        await dispose_engine()


@pytest.mark.parametrize(
    ("first_indexes", "second_indexes"),
    [((0, 1), (0, 1)), ((0, 1), (1, 2))],
)
def test_concurrent_clip_creates_have_one_winner_and_no_orphans(
    monkeypatch: pytest.MonkeyPatch,
    first_indexes: tuple[int, int],
    second_indexes: tuple[int, int],
) -> None:
    fixture = asyncio.run(_create_fixture())
    try:
        first_shots = [fixture["shots"][index] for index in first_indexes]
        second_shots = [fixture["shots"][index] for index in second_indexes]
        responses = asyncio.run(
            _run_concurrent_requests(
                fixture,
                first_shots,
                second_shots,
                monkeypatch,
            )
        )
        assert sorted(response.status_code for response in responses) == [201, 422]
        loser = next(response for response in responses if response.status_code == 422)
        assert loser.json()["detail"]["code"] == "validation_error"
        assert loser.json()["detail"]["message"]

        counts = asyncio.run(_read_counts(fixture))
        winner = next(response for response in responses if response.status_code == 201)
        assert counts == (1, len(winner.json()["shot_ids"]), 1)
    finally:
        asyncio.run(_cleanup_fixture(fixture))
