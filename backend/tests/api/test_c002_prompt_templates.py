import asyncio
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient

from app.main import app
from tests.api.test_c002_script import (
    _cleanup,
    _create_downstream_rows,
    _snapshot_downstream,
)


async def _restore_prompt_template(content: str) -> None:
    connection = await asyncpg.connect(
        os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)
    )
    try:
        await connection.execute(
            "UPDATE prompt_templates SET content = $1 WHERE key = 'script2assets'",
            content,
        )
    finally:
        await connection.close()


def test_prompt_templates_and_edits_preserve_downstream_rows() -> None:
    style_id = project_id = episode_id = asset_id = shot_id = clip_id = None
    sentinel_fd, sentinel_name = tempfile.mkstemp(prefix="c002-template-")
    os.close(sentinel_fd)
    sentinel_path = Path(sentinel_name)
    sentinel_path.write_text("template-sentinel", encoding="utf-8")
    original_template_content: str | None = None

    try:
        with TestClient(app) as client:
            templates = client.get("/api/prompt-templates")
            assert templates.status_code == 200
            template_payload = templates.json()
            original_template_content = template_payload[0]["content"]
            assert [item["key"] for item in template_payload] == [
                "script2assets",
                "script2shots",
                "zimage",
                "minimaxh3",
            ]
            assert all(
                set(item) == {"id", "key", "content", "updated_at"}
                for item in template_payload
            )
            assert all(item["content"].startswith("[占位]") for item in template_payload)

            style_response = client.post(
                "/api/styles",
                json={
                    "name": "Template Test Style " + uuid4().hex,
                    "prompt_fragment": "before style",
                },
            )
            assert style_response.status_code == 201
            style_id = style_response.json()["id"]
            project_response = client.post(
                "/api/projects",
                json={
                    "name": "Template Test Project " + uuid4().hex,
                    "style_id": style_id,
                },
            )
            assert project_response.status_code == 201
            project_id = project_response.json()["id"]
            episode_response = client.post(
                f"/api/projects/{project_id}/episodes",
                json={"seq": 1, "title": "Template Episode"},
            )
            assert episode_response.status_code == 201
            episode_id = episode_response.json()["id"]

            asset_id, shot_id, clip_id = asyncio.run(
                _create_downstream_rows(project_id, episode_id, sentinel_path)
            )
            before = asyncio.run(_snapshot_downstream(project_id, episode_id))
            before_file = sentinel_path.read_text(encoding="utf-8")

            style_patch = client.patch(
                f"/api/styles/{style_id}",
                json={"prompt_fragment": "after style"},
            )
            assert style_patch.status_code == 200
            assert style_patch.json()["prompt_fragment"] == "after style"

            template_patch = client.patch(
                "/api/prompt-templates/script2assets",
                json={"content": "  [占位] edited template  "},
            )
            assert template_patch.status_code == 200
            assert template_patch.json()["content"] == "  [占位] edited template  "
            same_template = client.patch(
                "/api/prompt-templates/script2assets",
                json={"content": "  [占位] edited template  "},
            )
            assert same_template.status_code == 200
            assert same_template.json()["updated_at"] == template_patch.json()[
                "updated_at"
            ]

            refreshed = client.get("/api/prompt-templates")
            assert refreshed.status_code == 200
            assert refreshed.json()[0]["content"] == "  [占位] edited template  "
            assert "built_prompt" not in refreshed.text
            assert "input_snapshot" not in refreshed.text

            after = asyncio.run(_snapshot_downstream(project_id, episode_id))
            assert after == before
            assert sentinel_path.read_text(encoding="utf-8") == before_file
    finally:
        if original_template_content is not None:
            asyncio.run(_restore_prompt_template(original_template_content))
        asyncio.run(
            _cleanup(style_id, project_id, episode_id, asset_id, shot_id, clip_id)
        )
        sentinel_path.unlink(missing_ok=True)
