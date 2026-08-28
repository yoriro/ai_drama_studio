from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.db.session import engine
from app.main import create_app


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _png_bytes() -> bytes:
    image = Image.new("RGB", (4, 4), (31, 47, 59))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


async def _seed_fixture(data_dir: Path) -> dict[str, int | str]:
    connection = await asyncpg.connect(_database_url())
    try:
        suffix = uuid4().hex
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, '水墨写实')
            RETURNING id
            """,
            f"C007 T10 style {suffix}",
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            f"C007 T10 project {suffix}",
            style_id,
        )
        asset_id = await connection.fetchval(
            """
            INSERT INTO assets
                (project_id, type, name, description, source, revision)
            VALUES ($1, 'character', '林夏', '黑发白衬衫', 'manual', 2)
            RETURNING id
            """,
            project_id,
        )
        generated_id = await connection.fetchval(
            """
            INSERT INTO asset_images
                (asset_id, file_path, sha256, seed, source, is_current,
                 built_prompt, input_hash, input_snapshot, user_note)
            VALUES ($1, 'pending', $2, 123, 'generated', true,
                    'built prompt', 'secret-input-hash', $3::jsonb, 'private note')
            RETURNING id
            """,
            asset_id,
            hashlib.sha256(_png_bytes()).hexdigest(),
            json.dumps(
                {"asset": {"id": int(asset_id)}, "workflow": {"secret": True}},
                ensure_ascii=False,
            ),
        )
        generated_path = (
            f"projects/{project_id}/assets/{asset_id}/{generated_id}.png"
        )
        await connection.execute(
            "UPDATE asset_images SET file_path = $1 WHERE id = $2",
            generated_path,
            generated_id,
        )
        uploaded_id = await connection.fetchval(
            """
            INSERT INTO asset_images
                (asset_id, file_path, sha256, seed, source, is_current,
                 built_prompt, input_hash, input_snapshot, user_note)
            VALUES ($1, 'pending', $2, NULL, 'uploaded', false,
                    NULL, NULL, NULL, NULL)
            RETURNING id
            """,
            asset_id,
            hashlib.sha256(_png_bytes()).hexdigest(),
        )
        uploaded_path = f"projects/{project_id}/assets/{asset_id}/{uploaded_id}.png"
        await connection.execute(
            "UPDATE asset_images SET file_path = $1 WHERE id = $2",
            uploaded_path,
            uploaded_id,
        )
        task_id = await connection.fetchval(
            """
            INSERT INTO tasks (type, target_id, payload, status, progress)
            VALUES ('gen_asset_image', $1, $2::jsonb, 'done', 1)
            RETURNING id
            """,
            asset_id,
            json.dumps(
                {
                    "input_snapshot": {"task_secret": "not an image field"},
                    "input_hash": "task-secret",
                    "source_revisions": {},
                }
            ),
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, 'T10 episode', 'T10 script')
            RETURNING id
            """,
            project_id,
        )
    finally:
        await connection.close()

    for image_id in (generated_id, uploaded_id):
        path = data_dir / f"projects/{project_id}/assets/{asset_id}/{image_id}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_png_bytes())
    return {
        "style_id": int(style_id),
        "project_id": int(project_id),
        "asset_id": int(asset_id),
        "generated_id": int(generated_id),
        "uploaded_id": int(uploaded_id),
        "task_id": int(task_id),
        "episode_id": int(episode_id),
    }


async def _cleanup_fixture(fixture: dict[str, int | str]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM tasks WHERE id = $1", fixture["task_id"]
        )
        await connection.execute(
            "DELETE FROM episodes WHERE id = $1", fixture["episode_id"]
        )
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


def _application(*, debug_prompts: bool, data_dir: Path):
    probe = _HealthProbe()
    application = create_app(
        vllm_client_factory=lambda _base_url: probe,
        comfy_client_factory=lambda _base_url: probe,
    )
    application.state.settings = settings.model_copy(
        update={"DEBUG_PROMPTS": debug_prompts, "DATA_DIR": data_dir}
    )

    async def stop_worker() -> None:
        application.state.task_worker_stop.set()

    application.state.startup_prepare = stop_worker
    return application


def test_asset_image_debug_fields_follow_app_setting_and_do_not_leak(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_seed_fixture(tmp_path))
    base_keys = {
        "id",
        "asset_id",
        "sha256",
        "seed",
        "source",
        "is_current",
        "created_at",
    }
    debug_keys = base_keys | {"built_prompt", "input_snapshot"}
    try:
        with TestClient(
            _application(debug_prompts=False, data_dir=tmp_path)
        ) as client:
            response = client.get(
                f"/api/assets/{fixture['asset_id']}/images"
            )
            assert response.status_code == 200
            rows = response.json()
            assert len(rows) == 2
            assert {key for key in rows[0]} == base_keys
            assert {key for key in rows[1]} == base_keys
            assert all(
                field not in response.text
                for field in (
                    "built_prompt",
                    "input_snapshot",
                    "file_path",
                    "input_hash",
                    "user_note",
                )
            )

        with TestClient(
            _application(debug_prompts=True, data_dir=tmp_path)
        ) as client:
            response = client.get(
                f"/api/assets/{fixture['asset_id']}/images"
            )
            assert response.status_code == 200
            rows = response.json()
            assert {key for key in rows[0]} == debug_keys
            assert {key for key in rows[1]} == debug_keys
            generated = next(
                row for row in rows if row["source"] == "generated"
            )
            uploaded = next(row for row in rows if row["source"] == "uploaded")
            assert generated["built_prompt"] == "built prompt"
            assert generated["input_snapshot"] == {
                "asset": {"id": fixture["asset_id"]},
                "workflow": {"secret": True},
            }
            assert uploaded["built_prompt"] is None
            assert uploaded["input_snapshot"] is None
            assert all(
                field not in response.text
                for field in ("file_path", "input_hash", "user_note")
            )

            other_paths = [
                f"/api/assets/{fixture['asset_id']}",
                f"/api/projects/{fixture['project_id']}",
                f"/api/projects/{fixture['project_id']}/assets",
                f"/api/projects/{fixture['project_id']}/episodes",
                "/api/tasks",
                "/api/system/health",
            ]
            for path in other_paths:
                other = client.get(path)
                assert other.status_code == 200
                assert all(
                    field not in other.text
                    for field in (
                        "built_prompt",
                        "input_snapshot",
                        "file_path",
                        "input_hash",
                        "user_note",
                    )
                ), path

            media = client.get(
                f"/media/asset-images/{fixture['generated_id']}"
            )
            assert media.status_code == 200
            assert media.headers["content-type"].startswith("image/png")
            assert b"built prompt" not in media.content
    finally:
        asyncio.run(_cleanup_fixture(fixture))
        asyncio.run(engine.dispose())
