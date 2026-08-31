from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import engine
from app.main import create_app


SEED = 1_782_929_867_419_795_085


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _seed_fixture() -> dict[str, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        suffix = uuid4().hex
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, 'debug seed style')
            RETURNING id
            """,
            f"C007 debug seed style {suffix}",
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            f"C007 debug seed project {suffix}",
            style_id,
        )
        asset_id = await connection.fetchval(
            """
            INSERT INTO assets
                (project_id, type, name, description, source, revision)
            VALUES ($1, 'character', 'Debug seed', 'debug seed asset', 'manual', 1)
            RETURNING id
            """,
            project_id,
        )
        image_id = await connection.fetchval(
            """
            INSERT INTO asset_images
                (asset_id, file_path, sha256, seed, source, is_current,
                 input_snapshot)
            VALUES ($1, 'debug-seed.png', $2, $3, 'generated', true, $4::jsonb)
            RETURNING id
            """,
            asset_id,
            "a" * 64,
            SEED,
            json.dumps(
                {
                    "seed": SEED,
                    "rendered_prompt": "debug seed prompt",
                }
            ),
        )
        assert style_id is not None
        assert project_id is not None
        assert asset_id is not None
        assert image_id is not None
        return {
            "style_id": int(style_id),
            "project_id": int(project_id),
            "asset_id": int(asset_id),
            "image_id": int(image_id),
        }
    finally:
        await connection.close()


async def _read_internal_seed(fixture: dict[str, int]) -> tuple[object, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            "SELECT seed, input_snapshot FROM asset_images WHERE id = $1",
            fixture["image_id"],
        )
        assert row is not None
        snapshot = row["input_snapshot"]
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        return row["seed"], snapshot["seed"]
    finally:
        await connection.close()


async def _cleanup_fixture(fixture: dict[str, int]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM asset_images WHERE id = $1", fixture["image_id"]
        )
        await connection.execute(
            "DELETE FROM assets WHERE id = $1", fixture["asset_id"]
        )
        await connection.execute(
            "DELETE FROM projects WHERE id = $1", fixture["project_id"]
        )
        await connection.execute(
            "DELETE FROM styles WHERE id = $1", fixture["style_id"]
        )
    finally:
        await connection.close()


class _HealthProbe:
    async def health(self) -> None:
        return None


def _application(data_dir: Path):
    probe = _HealthProbe()
    application = create_app(
        vllm_client_factory=lambda _base_url: probe,
        comfy_client_factory=lambda _base_url: probe,
    )
    application.state.settings = settings.model_copy(
        update={"DEBUG_PROMPTS": True, "DATA_DIR": data_dir}
    )

    async def stop_worker() -> None:
        application.state.task_worker_stop.set()

    application.state.startup_prepare = stop_worker
    return application


def test_debug_asset_image_input_snapshot_seed_is_decimal_string(
    tmp_path: Path,
) -> None:
    fixture = asyncio.run(_seed_fixture())
    try:
        with TestClient(_application(tmp_path)) as client:
            response = client.get(
                f"/api/assets/{fixture['asset_id']}/images"
            )

        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["seed"] == str(SEED)
        assert type(row["seed"]) is str
        assert row["input_snapshot"]["seed"] == str(SEED)
        assert type(row["input_snapshot"]["seed"]) is str

        database_seed, snapshot_seed = asyncio.run(_read_internal_seed(fixture))
        assert database_seed == SEED
        assert type(database_seed) is int
        assert snapshot_seed == SEED
        assert type(snapshot_seed) is int
    finally:
        asyncio.run(_cleanup_fixture(fixture))
        asyncio.run(engine.dispose())
