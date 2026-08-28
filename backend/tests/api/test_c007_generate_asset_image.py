import asyncio
import hashlib
import json
import os
from collections.abc import Mapping
from uuid import uuid4

import asyncpg
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _task_row(task_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT id, type, target_id, request_id, payload, status, progress
            FROM tasks
            WHERE id = $1
            """,
            task_id,
        )
        assert row is not None
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        assert isinstance(payload, dict)
        return {
            "id": row["id"],
            "type": row["type"],
            "target_id": row["target_id"],
            "request_id": row["request_id"],
            "payload": payload,
            "status": row["status"],
            "progress": row["progress"],
        }
    finally:
        await connection.close()


async def _update_asset_cache(
    asset_id: int, input_hash: str | None, cached_prompt: str | None
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            """
            UPDATE assets
            SET image_prompt_hash = $1, image_prompt_cache = $2
            WHERE id = $3
            """,
            input_hash,
            cached_prompt,
            asset_id,
        )
    finally:
        await connection.close()


async def _cleanup_fixture(
    task_ids: list[int], asset_id: int | None, project_id: int | None, style_id: int | None
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        if task_ids:
            await connection.execute(
                "DELETE FROM tasks WHERE id = ANY($1::int[])", task_ids
            )
        if asset_id is not None:
            await connection.execute("DELETE FROM assets WHERE id = $1", asset_id)
        if project_id is not None:
            await connection.execute("DELETE FROM projects WHERE id = $1", project_id)
        if style_id is not None:
            await connection.execute("DELETE FROM styles WHERE id = $1", style_id)
    finally:
        await connection.close()


def _assert_error(response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"detail"}
    assert set(body["detail"]) == {"code", "message"}
    assert body["detail"]["code"] == code
    assert isinstance(body["detail"]["message"], str)
    assert body["detail"]["message"]


def _create_asset_fixture(client: TestClient) -> dict[str, int]:
    style_response = client.post(
        "/api/styles",
        json={
            "name": "C007 T5 style " + uuid4().hex,
            "prompt_fragment": "水墨写实",
        },
    )
    assert style_response.status_code == 201
    style_id = style_response.json()["id"]

    project_response = client.post(
        "/api/projects",
        json={
            "name": "C007 T5 project " + uuid4().hex,
            "style_id": style_id,
        },
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    asset_response = client.post(
        f"/api/projects/{project_id}/assets",
        json={
            "type": "character",
            "name": "林夏",
            "description": "黑发白衬衫",
        },
    )
    assert asset_response.status_code == 201
    asset_id = asset_response.json()["id"]
    return {
        "style_id": style_id,
        "project_id": project_id,
        "asset_id": asset_id,
    }


def _expected_input_hash(
    *,
    asset_name: str,
    asset_description: str,
    asset_revision: int,
    style_prompt_fragment: str,
    template_content: str,
    user_note: str | None,
    workflow_hash: str,
) -> str:
    serialized = json.dumps(
        [
            asset_name,
            asset_description,
            asset_revision,
            style_prompt_fragment,
            template_content,
            user_note,
            settings.VLLM_MODEL,
            workflow_hash,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


class _HealthProbe:
    def __init__(self) -> None:
        self.calls = 0

    async def health(self) -> None:
        self.calls += 1


def test_generate_asset_image_request_contract(monkeypatch) -> None:
    vllm_probe = _HealthProbe()
    comfy_probe = _HealthProbe()
    monkeypatch.setattr(
        app.state, "vllm_client_factory", lambda _base_url: vllm_probe
    )
    monkeypatch.setattr(
        app.state, "comfy_client_factory", lambda _base_url: comfy_probe
    )

    async def stop_worker() -> None:
        app.state.task_worker_stop.set()

    monkeypatch.setattr(app.state, "startup_prepare", stop_worker)

    original_template: str | None = None
    fixture: dict[str, int] | None = None
    task_ids: list[int] = []
    template = "asset={{asset}}|style={{style}}|note={{user_note}}"
    try:
        with TestClient(app) as client:
            templates_response = client.get("/api/prompt-templates")
            assert templates_response.status_code == 200
            original_template = next(
                item["content"]
                for item in templates_response.json()
                if item["key"] == "zimage"
            )
            assert client.patch(
                "/api/prompt-templates/zimage", json={"content": template}
            ).status_code == 200
            fixture = _create_asset_fixture(client)
            asset_id = fixture["asset_id"]

            startup_probe_calls = (vllm_probe.calls, comfy_probe.calls)

            empty_body = client.post(f"/api/assets/{asset_id}/generate-image", json={})
            assert empty_body.status_code == 202
            assert set(empty_body.json()) == {"task_id"}
            task_ids.append(empty_body.json()["task_id"])

            null_fields = client.post(
                f"/api/assets/{asset_id}/generate-image",
                json={"user_note": None, "request_id": None},
            )
            assert null_fields.status_code == 202
            task_ids.append(null_fields.json()["task_id"])

            fixed = client.post(
                f"/api/assets/{asset_id}/generate-image",
                json={"user_note": "备注", "request_id": " abc "},
            )
            assert fixed.status_code == 202
            assert set(fixed.json()) == {"task_id"}
            fixed_task_id = fixed.json()["task_id"]
            task_ids.append(fixed_task_id)

            fixed_task = asyncio.run(_task_row(fixed_task_id))
            assert fixed_task["type"] == "gen_asset_image"
            assert fixed_task["target_id"] == asset_id
            assert fixed_task["request_id"] == "abc"
            assert fixed_task["status"] == "queued"
            assert fixed_task["progress"] == 0

            payload = fixed_task["payload"]
            assert isinstance(payload, dict)
            assert set(payload) == {
                "input_snapshot",
                "input_hash",
                "source_revisions",
            }
            snapshot = payload["input_snapshot"]
            assert isinstance(snapshot, dict)
            assert set(snapshot) == {
                "asset",
                "style",
                "template_key",
                "template_content",
                "user_note",
                "rendered_prompt",
                "model",
                "temperature",
                "guided_json_schema",
                "workflow",
                "seed",
                "comfy_prompt_id",
                "cached_prompt",
            }
            assert snapshot["asset"] == {
                "id": asset_id,
                "project_id": fixture["project_id"],
                "type": "character",
                "name": "林夏",
                "description": "黑发白衬衫",
                "revision": 1,
            }
            assert snapshot["style"] == "水墨写实"
            assert snapshot["template_key"] == "zimage"
            assert snapshot["template_content"] == template
            assert snapshot["user_note"] == "备注"
            assert snapshot["rendered_prompt"] == (
                'asset={"type":"character","name":"林夏","description":"黑发白衬衫"}'
                "|style=水墨写实|note=备注"
            )
            assert snapshot["model"] == settings.VLLM_MODEL
            assert snapshot["temperature"] == settings.VLLM_TEMPERATURE
            assert snapshot["guided_json_schema"] == {
                "type": "json_schema",
                "json_schema": {
                    "name": "zimage",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"prompt": {"type": "string"}},
                        "required": ["prompt"],
                        "additionalProperties": False,
                    },
                },
            }
            binding_snapshot = app.state.workflow_binding_snapshot
            assert snapshot["workflow"] == binding_snapshot.workflow_payload()
            assert snapshot["seed"] == 1782929867419795085
            assert snapshot["comfy_prompt_id"] == (
                "f0faf273-5fe9-5726-98be-3d449efdbe8d"
            )
            assert snapshot["cached_prompt"] is None
            expected_hash = _expected_input_hash(
                asset_name="林夏",
                asset_description="黑发白衬衫",
                asset_revision=1,
                style_prompt_fragment="水墨写实",
                template_content=template,
                user_note="备注",
                workflow_hash=binding_snapshot.workflow_hash,
            )
            assert payload["input_hash"] == expected_hash
            assert payload["source_revisions"] == {
                "asset": {"id": asset_id, "revision": 1}
            }
            assert (vllm_probe.calls, comfy_probe.calls) == startup_probe_calls

            invalid_requests = [
                (client.post(f"/api/assets/{asset_id}/generate-image"), 422),
                (
                    client.post(
                        f"/api/assets/{asset_id}/generate-image",
                        content="null",
                        headers={"content-type": "application/json"},
                    ),
                    422,
                ),
                (
                    client.post(
                        f"/api/assets/{asset_id}/generate-image",
                        content="[]",
                        headers={"content-type": "application/json"},
                    ),
                    422,
                ),
                (
                    client.post(
                        f"/api/assets/{asset_id}/generate-image",
                        json={"unknown": "field"},
                    ),
                    422,
                ),
                (
                    client.post(
                        f"/api/assets/{asset_id}/generate-image",
                        json={"user_note": 3},
                    ),
                    422,
                ),
                (
                    client.post(
                        f"/api/assets/{asset_id}/generate-image",
                        json={"request_id": 3},
                    ),
                    422,
                ),
                (
                    client.post(
                        f"/api/assets/{asset_id}/generate-image",
                        json={"request_id": "   "},
                    ),
                    422,
                ),
                (
                    client.post(
                        f"/api/assets/{asset_id}/generate-image",
                        json={"request_id": "a" * 129},
                    ),
                    422,
                ),
            ]
            for response, status_code in invalid_requests:
                _assert_error(response, status_code, "validation_error")
            assert (vllm_probe.calls, comfy_probe.calls) == startup_probe_calls

            _assert_error(
                client.post("/api/assets/999999999/generate-image", json={}),
                404,
                "not_found",
            )
    finally:
        if original_template is not None:
            with TestClient(app) as client:
                restored = client.patch(
                    "/api/prompt-templates/zimage",
                    json={"content": original_template},
                )
                assert restored.status_code == 200
        if fixture is not None:
            asyncio.run(
                _cleanup_fixture(
                    task_ids,
                    fixture["asset_id"],
                    fixture["project_id"],
                    fixture["style_id"],
                )
            )


def test_generate_asset_image_request_contract_rejects_prerequisite_failures(
    monkeypatch,
) -> None:
    monkeypatch.setattr(app.state, "vllm_client_factory", lambda _base_url: _HealthProbe())
    monkeypatch.setattr(app.state, "comfy_client_factory", lambda _base_url: _HealthProbe())

    async def stop_worker() -> None:
        app.state.task_worker_stop.set()

    monkeypatch.setattr(app.state, "startup_prepare", stop_worker)

    original_template: str | None = None
    fixture: dict[str, int] | None = None
    template = "asset={{asset}}|style={{style}}|note={{user_note}}"
    try:
        with TestClient(app) as client:
            templates_response = client.get("/api/prompt-templates")
            assert templates_response.status_code == 200
            original_template = next(
                item["content"]
                for item in templates_response.json()
                if item["key"] == "zimage"
            )
            assert client.patch(
                "/api/prompt-templates/zimage", json={"content": template}
            ).status_code == 200
            fixture = _create_asset_fixture(client)
            asset_id = fixture["asset_id"]
            binding_snapshot = app.state.workflow_binding_snapshot

            invalid_template = client.patch(
                "/api/prompt-templates/zimage",
                json={"content": "missing placeholders"},
            )
            assert invalid_template.status_code == 200
            _assert_error(
                client.post(f"/api/assets/{asset_id}/generate-image", json={}),
                409,
                "conflict",
            )
            assert client.patch(
                "/api/prompt-templates/zimage", json={"content": template}
            ).status_code == 200

            expected_hash = _expected_input_hash(
                asset_name="林夏",
                asset_description="黑发白衬衫",
                asset_revision=1,
                style_prompt_fragment="水墨写实",
                template_content=template,
                user_note=None,
                workflow_hash=binding_snapshot.workflow_hash,
            )
            asyncio.run(_update_asset_cache(asset_id, expected_hash, None))
            _assert_error(
                client.post(f"/api/assets/{asset_id}/generate-image", json={}),
                500,
                "internal_error",
            )
            asyncio.run(_update_asset_cache(asset_id, None, None))
    finally:
        if original_template is not None:
            with TestClient(app) as client:
                restored = client.patch(
                    "/api/prompt-templates/zimage",
                    json={"content": original_template},
                )
                assert restored.status_code == 200
        if fixture is not None:
            asyncio.run(
                _cleanup_fixture(
                    [],
                    fixture["asset_id"],
                    fixture["project_id"],
                    fixture["style_id"],
                )
            )
