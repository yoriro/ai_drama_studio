from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import engine
from app.main import create_app


SEED = 9_001_116_167_303_358_020


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _seed_fixture() -> dict[str, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        suffix = uuid4().hex
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, 'seed contract style')
            RETURNING id
            """,
            f"C007 seed style {suffix}",
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            f"C007 seed project {suffix}",
            style_id,
        )
        asset_id = await connection.fetchval(
            """
            INSERT INTO assets
                (project_id, type, name, description, source, revision)
            VALUES ($1, 'character', 'Seed contract', 'seed contract asset', 'manual', 1)
            RETURNING id
            """,
            project_id,
        )
        await connection.execute(
            """
            INSERT INTO asset_images
                (asset_id, file_path, sha256, seed, source, is_current)
            VALUES ($1, 'generated.png', $2, $3, 'generated', true)
            """,
            asset_id,
            "a" * 64,
            SEED,
        )
        await connection.execute(
            """
            INSERT INTO asset_images
                (asset_id, file_path, sha256, seed, source, is_current)
            VALUES ($1, 'uploaded.png', $2, NULL, 'uploaded', false)
            """,
            asset_id,
            "b" * 64,
        )
        return {
            "style_id": int(style_id),
            "project_id": int(project_id),
            "asset_id": int(asset_id),
        }
    finally:
        await connection.close()


async def _cleanup_fixture(fixture: dict[str, int]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM asset_images WHERE asset_id = $1", fixture["asset_id"]
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
        update={"DATA_DIR": data_dir}
    )

    async def stop_worker() -> None:
        application.state.task_worker_stop.set()

    application.state.startup_prepare = stop_worker
    return application


def test_asset_image_seed_is_decimal_string_in_public_api(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_seed_fixture())
    try:
        with TestClient(_application(tmp_path)) as client:
            response = client.get(
                f"/api/assets/{fixture['asset_id']}/images"
            )

        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 2
        generated = next(row for row in rows if row["source"] == "generated")
        uploaded = next(row for row in rows if row["source"] == "uploaded")
        assert generated["seed"] == str(SEED)
        assert type(generated["seed"]) is str
        assert uploaded["seed"] is None
    finally:
        asyncio.run(_cleanup_fixture(fixture))
        asyncio.run(engine.dispose())
