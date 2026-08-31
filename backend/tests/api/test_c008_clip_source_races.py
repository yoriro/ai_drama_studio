import asyncio
import os
from uuid import uuid4

import asyncpg
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import dispose_engine
from app.main import app


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _create_fixture() -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, 'C008 race style')
            RETURNING id
            """,
            "C008 race style " + uuid4().hex,
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C008 race project " + uuid4().hex,
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, 'Race episode', 'race')
            RETURNING id
            """,
            project_id,
        )
        target_asset_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source)
            VALUES ($1, 'character', '旧人物', '旧描述', 'manual')
            RETURNING id
            """,
            project_id,
        )
        replacement_asset_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source)
            VALUES ($1, 'character', '新人物', '新描述', 'manual')
            RETURNING id
            """,
            project_id,
        )
        shot_id = await connection.fetchval(
            """
            INSERT INTO shots
                (episode_id, order_index, duration_est, shot_type, camera,
                 description, dialogue, status, revision)
            VALUES ($1, 1, 2, '中景', '固定', 'race shot', '', 'normal', 1)
            RETURNING id
            """,
            episode_id,
        )
        await connection.execute(
            "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
            shot_id,
            target_asset_id,
        )
    finally:
        await connection.close()
    return {
        "style_id": style_id,
        "project_id": project_id,
        "episode_id": episode_id,
        "target_asset_id": target_asset_id,
        "replacement_asset_id": replacement_asset_id,
        "shot_id": shot_id,
    }


async def _read_state(fixture: dict[str, object]) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        shot = await connection.fetchrow(
            """
            SELECT revision, status
            FROM shots
            WHERE id = $1
            """,
            fixture["shot_id"],
        )
        shot_assets = await connection.fetch(
            """
            SELECT asset_id
            FROM shot_assets
            WHERE shot_id = $1
            ORDER BY asset_id
            """,
            fixture["shot_id"],
        )
        clips = await connection.fetch(
            """
            SELECT c.id, c.revision, c.freshness, c.generation_state,
                   s.asset_id, s.asset_name_snapshot, s.slot_no
            FROM clips AS c
            LEFT JOIN clip_ref_slots AS s ON s.clip_id = c.id
            WHERE c.episode_id = $1
            ORDER BY c.id, s.slot_no
            """,
            fixture["episode_id"],
        )
        return {
            "shot": (int(shot["revision"]), str(shot["status"])),
            "shot_assets": [int(row["asset_id"]) for row in shot_assets],
            "clips": [dict(row) for row in clips],
        }
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
            "DELETE FROM clips WHERE episode_id = $1", fixture["episode_id"]
        )
        await connection.execute(
            "DELETE FROM shot_assets WHERE shot_id = $1", fixture["shot_id"]
        )
        await connection.execute(
            "DELETE FROM shots WHERE id = $1", fixture["shot_id"]
        )
        await connection.execute(
            "DELETE FROM assets WHERE project_id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM episodes WHERE id = $1", fixture["episode_id"]
        )
        await connection.execute(
            "DELETE FROM projects WHERE id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM styles WHERE id = $1", fixture["style_id"]
        )
    finally:
        await connection.close()


async def _run_race(
    fixture: dict[str, object],
    *,
    mutation: str,
    mutation_first: bool,
    monkeypatch,
) -> tuple[httpx.Response, httpx.Response]:
    from app.api import assets as assets_api
    from app.api import clips as clips_api
    from app.api import shots as shots_api

    create_started = asyncio.Event()
    mutation_started = asyncio.Event()
    transaction_paused = asyncio.Event()
    release_transaction = asyncio.Event()
    original_create = clips_api.create_clip
    original_update_shot = shots_api.update_shot
    original_delete_asset = assets_api.delete_asset
    original_flush = AsyncSession.flush

    async def wrapped_create(session, episode_id, payload):
        create_started.set()
        session.info["c008_race_phase"] = "create"
        return await original_create(session, episode_id, payload)

    async def wrapped_update_shot(session, shot_id, payload):
        mutation_started.set()
        session.info["c008_race_phase"] = "shot"
        return await original_update_shot(session, shot_id, payload)

    async def wrapped_delete_asset(session, asset_id):
        mutation_started.set()
        session.info["c008_race_phase"] = "asset"
        return await original_delete_asset(session, asset_id)

    async def controlled_flush(self, *args, **kwargs):
        result = await original_flush(self, *args, **kwargs)
        phase = self.info.get("c008_race_phase")
        flush_count = int(self.info.get("c008_flush_count", 0)) + 1
        self.info["c008_flush_count"] = flush_count
        should_pause = phase == "create" and flush_count == 2
        if phase in {"shot", "asset"} and flush_count == 1:
            should_pause = True
        if should_pause:
            transaction_paused.set()
            await release_transaction.wait()
        return result

    monkeypatch.setattr(AsyncSession, "flush", controlled_flush)
    monkeypatch.setattr(clips_api, "create_clip", wrapped_create)
    if mutation == "shot":
        monkeypatch.setattr(shots_api, "update_shot", wrapped_update_shot)
    else:
        monkeypatch.setattr(assets_api, "delete_asset", wrapped_delete_asset)

    create_payload = {
        "shot_ids": [fixture["shot_id"]],
        "reference_asset_ids": [fixture["target_asset_id"]],
    }
    if mutation == "shot":
        mutation_request = (
            "patch",
            f"/api/shots/{fixture['shot_id']}",
            {"asset_ids": [fixture["replacement_asset_id"]]},
        )
    else:
        mutation_request = (
            "delete",
            f"/api/assets/{fixture['target_asset_id']}",
            None,
        )

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            if mutation_first:
                mutation_task = asyncio.create_task(
                    getattr(client, mutation_request[0])(
                        mutation_request[1],
                        **({"json": mutation_request[2]} if mutation_request[2] else {}),
                    )
                )
                await asyncio.wait_for(transaction_paused.wait(), 5)
                create_task = asyncio.create_task(
                    client.post(
                        f"/api/episodes/{fixture['episode_id']}/clips",
                        json=create_payload,
                    )
                )
                await asyncio.wait_for(create_started.wait(), 5)
            else:
                create_task = asyncio.create_task(
                    client.post(
                        f"/api/episodes/{fixture['episode_id']}/clips",
                        json=create_payload,
                    )
                )
                await asyncio.wait_for(transaction_paused.wait(), 5)
                mutation_task = asyncio.create_task(
                    getattr(client, mutation_request[0])(
                        mutation_request[1],
                        **({"json": mutation_request[2]} if mutation_request[2] else {}),
                    )
                )
                await asyncio.wait_for(mutation_started.wait(), 5)
            release_transaction.set()
            create_response, mutation_response = await asyncio.gather(
                create_task, mutation_task
            )
            return create_response, mutation_response
    finally:
        release_transaction.set()
        await dispose_engine()


@pytest.mark.parametrize("mutation", ["shot", "asset"])
@pytest.mark.parametrize("mutation_first", [True, False])
def test_create_source_races_reconcile_to_committed_shot_or_asset_truth(
    mutation: str, mutation_first: bool, monkeypatch
) -> None:
    fixture = asyncio.run(_create_fixture())
    try:
        create_response, mutation_response = asyncio.run(
            _run_race(
                fixture,
                mutation=mutation,
                mutation_first=mutation_first,
                monkeypatch=monkeypatch,
            )
        )
        assert mutation_response.status_code == (200 if mutation == "shot" else 204)
        if mutation_first:
            assert create_response.status_code == 422
            assert create_response.json()["detail"]["code"] == "validation_error"
            assert asyncio.run(_read_state(fixture))["clips"] == []
        else:
            assert create_response.status_code == 201
            state = asyncio.run(_read_state(fixture))
            assert state["shot_assets"] == (
                [fixture["replacement_asset_id"]] if mutation == "shot" else []
            )
            assert len(state["clips"]) == 1
            clip = state["clips"][0]
            if mutation == "shot":
                assert clip["asset_id"] == fixture["target_asset_id"]
                assert clip["freshness"] == "stale"
            else:
                assert clip["asset_id"] is None
                assert clip["freshness"] == "stale"
    finally:
        asyncio.run(_cleanup_fixture(fixture))
