import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient

from app.main import app


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _task_payload(task_id: int) -> dict:
    connection = await asyncpg.connect(_database_url())
    try:
        payload = await connection.fetchval(
            "SELECT payload FROM tasks WHERE id = $1", task_id
        )
        assert payload is not None
        return json.loads(payload) if isinstance(payload, str) else payload
    finally:
        await connection.close()


async def _active_tasks(target_id: int) -> list[asyncpg.Record]:
    connection = await asyncpg.connect(_database_url())
    try:
        return await connection.fetch(
            """
            SELECT id, type, target_id, request_id, status, progress
            FROM tasks
            WHERE type = 'gen_assets' AND target_id = $1
              AND status IN ('queued', 'running')
            ORDER BY id
            """,
            target_id,
        )
    finally:
        await connection.close()


async def _mark_task_done(task_id: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            """
            UPDATE tasks
            SET status = 'done', progress = 1, finished_at = now()
            WHERE id = $1
            """,
            task_id,
        )
    finally:
        await connection.close()


async def _cleanup(
    task_ids: list[int],
    episode_ids: list[int],
    asset_ids: list[int],
    project_id: int | None,
    style_id: int | None,
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        if task_ids:
            await connection.execute(
                "DELETE FROM tasks WHERE id = ANY($1::int[])", task_ids
            )
        if asset_ids:
            await connection.execute(
                "DELETE FROM assets WHERE id = ANY($1::int[])", asset_ids
            )
        if episode_ids:
            await connection.execute(
                "DELETE FROM episodes WHERE id = ANY($1::int[])", episode_ids
            )
        if project_id is not None:
            await connection.execute("DELETE FROM projects WHERE id = $1", project_id)
        if style_id is not None:
            await connection.execute("DELETE FROM styles WHERE id = $1", style_id)
    finally:
        await connection.close()


def _assert_error(response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    assert set(response.json()) == {"detail"}
    assert set(response.json()["detail"]) == {"code", "message"}
    assert response.json()["detail"]["code"] == code


def test_generate_assets_enqueues_exact_snapshot_and_errors() -> None:
    original_template: str | None = None
    style_id = project_id = None
    episode_ids: list[int] = []
    asset_ids: list[int] = []
    task_ids: list[int] = []
    template = "prefix={{existing_assets}}|style={{style}}|script={{script}}|suffix"
    try:
        with TestClient(app) as client:
            app.state.task_worker_stop.set()
            templates = client.get("/api/prompt-templates")
            assert templates.status_code == 200
            original_template = templates.json()[0]["content"]
            patched = client.patch(
                "/api/prompt-templates/script2assets",
                json={"content": template},
            )
            assert patched.status_code == 200

            style_response = client.post(
                "/api/styles",
                json={
                    "name": "C005 API Style " + uuid4().hex,
                    "prompt_fragment": "视觉风格",
                },
            )
            assert style_response.status_code == 201
            style_id = style_response.json()["id"]
            project_response = client.post(
                "/api/projects",
                json={
                    "name": "C005 API Project " + uuid4().hex,
                    "style_id": style_id,
                },
            )
            assert project_response.status_code == 201
            project_id = project_response.json()["id"]

            first_episode = client.post(
                f"/api/projects/{project_id}/episodes",
                json={
                    "seq": 1,
                    "title": "Empty assets",
                    "script_text": "剧本 {{style}}",
                },
            )
            assert first_episode.status_code == 201
            first_episode_id = first_episode.json()["id"]
            episode_ids.append(first_episode_id)

            first = client.post(
                f"/api/episodes/{first_episode_id}/generate-assets"
            )
            assert first.status_code == 202
            assert set(first.json()) == {"task_id"}
            assert first.json()["task_id"] > 0
            task_ids.append(first.json()["task_id"])
            first_payload = asyncio.run(_task_payload(task_ids[-1]))
            assert set(first_payload) == {
                "input_snapshot",
                "input_hash",
                "source_revisions",
            }
            assert first_payload["input_hash"] is None
            assert set(first_payload["input_snapshot"]) == {
                "episode_id",
                "project_id",
                "script",
                "script_revision",
                "style",
                "template_key",
                "template_content",
                "existing_assets",
                "rendered_prompt",
                "model",
                "temperature",
            }
            assert first_payload["input_snapshot"]["existing_assets"] == []
            assert first_payload["input_snapshot"]["rendered_prompt"] == (
                "prefix=[]|style=视觉风格|script=剧本 {{style}}|suffix"
            )
            assert first_payload["source_revisions"]["assets"] == []
            assert first_payload["source_revisions"]["episode"] == {
                "id": first_episode_id,
                "script_revision": 1,
            }

            asset_response = client.post(
                f"/api/projects/{project_id}/assets",
                json={
                    "type": "character",
                    "name": "林夏",
                    "description": "短发，穿蓝色外套",
                },
            )
            assert asset_response.status_code == 201
            asset_ids.append(asset_response.json()["id"])
            second_episode = client.post(
                f"/api/projects/{project_id}/episodes",
                json={"seq": 2, "title": "Existing assets", "script_text": "第二集"},
            )
            assert second_episode.status_code == 201
            second_episode_id = second_episode.json()["id"]
            episode_ids.append(second_episode_id)
            second = client.post(
                f"/api/episodes/{second_episode_id}/generate-assets"
            )
            assert second.status_code == 202
            task_ids.append(second.json()["task_id"])
            second_payload = asyncio.run(_task_payload(task_ids[-1]))
            assert second_payload["input_snapshot"]["existing_assets"] == [
                {
                    "id": asset_ids[0],
                    "type": "character",
                    "name": "林夏",
                    "description": "短发，穿蓝色外套",
                }
            ]
            assert second_payload["source_revisions"]["assets"] == [
                {"id": asset_ids[0], "revision": 1}
            ]
            assert second_payload["input_snapshot"]["rendered_prompt"] == (
                'prefix=[{"id":%d,"type":"character","name":"林夏",'
                '"description":"短发，穿蓝色外套"}]|style=视觉风格|'
                "script=第二集|suffix" % asset_ids[0]
            )

            for body in (b"{}", b"null", b"text"):
                invalid = client.post(
                    f"/api/episodes/{first_episode_id}/generate-assets",
                    content=body,
                    headers={"content-type": "application/json"},
                )
                _assert_error(invalid, 422, "validation_error")

            missing = client.post("/api/episodes/2147483647/generate-assets")
            _assert_error(missing, 404, "not_found")

            invalid_template = client.patch(
                "/api/prompt-templates/script2assets",
                json={"content": "{{script}} {{style}}"},
            )
            assert invalid_template.status_code == 200
            third_episode = client.post(
                f"/api/projects/{project_id}/episodes",
                json={"seq": 3, "title": "Invalid template"},
            )
            assert third_episode.status_code == 201
            third_episode_id = third_episode.json()["id"]
            episode_ids.append(third_episode_id)
            invalid = client.post(
                f"/api/episodes/{third_episode_id}/generate-assets"
            )
            _assert_error(invalid, 409, "conflict")
    finally:
        if original_template is not None:
            asyncio.run(_restore_prompt_template(original_template))
        asyncio.run(
            _cleanup(task_ids, episode_ids, asset_ids, project_id, style_id)
        )


async def _restore_prompt_template(content: str) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE prompt_templates SET content = $1 WHERE key = 'script2assets'",
            content,
        )
    finally:
        await connection.close()


def test_generate_assets_active_conflict() -> None:
    original_template: str | None = None
    style_id = project_id = None
    episode_id: int | None = None
    task_ids: list[int] = []
    try:
        with TestClient(app) as client:
            app.state.task_worker_stop.set()
            templates = client.get("/api/prompt-templates")
            assert templates.status_code == 200
            original_template = templates.json()[0]["content"]
            patched = client.patch(
                "/api/prompt-templates/script2assets",
                json={
                    "content": "{{existing_assets}} {{style}} {{script}}"
                },
            )
            assert patched.status_code == 200
            style_response = client.post(
                "/api/styles",
                json={
                    "name": "C005 Conflict Style " + uuid4().hex,
                    "prompt_fragment": "style",
                },
            )
            assert style_response.status_code == 201
            style_id = style_response.json()["id"]
            project_response = client.post(
                "/api/projects",
                json={
                    "name": "C005 Conflict Project " + uuid4().hex,
                    "style_id": style_id,
                },
            )
            assert project_response.status_code == 201
            project_id = project_response.json()["id"]
            episode_response = client.post(
                f"/api/projects/{project_id}/episodes",
                json={"seq": 1, "title": "Conflict"},
            )
            assert episode_response.status_code == 201
            episode_id = episode_response.json()["id"]
            url = f"/api/episodes/{episode_id}/generate-assets"

            def post_generate():
                return client.post(url)

            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(lambda _: post_generate(), (1, 2)))
            statuses = sorted(response.status_code for response in responses)
            assert statuses == [202, 409]
            for response in responses:
                if response.status_code == 409:
                    _assert_error(response, 409, "conflict")
                else:
                    task_ids.append(response.json()["task_id"])
            assert len(task_ids) == 1
            active = asyncio.run(_active_tasks(episode_id))
            assert len(active) == 1
            assert active[0]["id"] == task_ids[0]
            assert active[0]["request_id"] is None
            assert active[0]["status"] == "queued"

            asyncio.run(_mark_task_done(task_ids[0]))
            after_terminal = client.post(url)
            assert after_terminal.status_code == 202
            task_ids.append(after_terminal.json()["task_id"])
            assert task_ids[-1] != task_ids[0]
    finally:
        if original_template is not None:
            asyncio.run(_restore_prompt_template(original_template))
        asyncio.run(
            _cleanup(task_ids, [episode_id] if episode_id is not None else [], [], project_id, style_id)
        )
