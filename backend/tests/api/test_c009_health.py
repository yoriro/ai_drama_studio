from __future__ import annotations

import asyncio
import json
from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.integrations.workflow_binding import WorkflowBindingError
from app.main import create_app


ZIMAGE_WORKFLOW_HASH = "e9790bece3462691ebaf63d849bf1940beec62f9149fb6d475be859c47e41eaa"
MINIMAX_WORKFLOW_HASH = "4f078c121b8ec0d9023e775e0b052036407a5f75bf626d13ea223ebf3d5b4772"


class _ProbeClient:
    def __init__(self) -> None:
        self.calls = 0

    async def health(self) -> None:
        self.calls += 1


def _database_url() -> str:
    return settings.DATABASE_URL.get_secret_value().replace("+asyncpg", "", 1)


async def _insert_queued_task(target_id: int) -> int:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            INSERT INTO tasks(type, target_id, payload, status, progress)
            VALUES ('gen_asset_image', $1, $2, 'queued', 0)
            RETURNING id
            """,
            target_id,
            json.dumps(
                {
                    "input_snapshot": {},
                    "input_hash": None,
                    "source_revisions": {},
                }
            ),
        )
        assert row is not None
        return int(row["id"])
    finally:
        await connection.close()


async def _task_status(task_id: int) -> str:
    connection = await asyncpg.connect(_database_url())
    try:
        status = await connection.fetchval(
            "SELECT status FROM tasks WHERE id = $1", task_id
        )
        assert status is not None
        return str(status)
    finally:
        await connection.close()


async def _delete_task(task_id: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute("DELETE FROM tasks WHERE id = $1", task_id)
    finally:
        await connection.close()


def test_c009_health_exposes_two_workflow_hashes() -> None:
    vllm_client = _ProbeClient()
    comfy_client = _ProbeClient()
    application = create_app(
        vllm_client_factory=lambda _base_url: vllm_client,
        comfy_client_factory=lambda _base_url: comfy_client,
    )

    with TestClient(application) as client:
        response = client.get("/api/system/health")

        assert response.status_code == 200
        assert response.json() == {
            "vllm": {"status": "healthy", "message": None},
            "comfy": {"status": "healthy", "message": None},
            "workflow_bindings": {
                "status": "valid",
                "message": None,
                "hashes": {
                    "zimage": ZIMAGE_WORKFLOW_HASH,
                    "minimaxh3": MINIMAX_WORKFLOW_HASH,
                },
            },
        }

    assert application.state.workflow_binding_snapshot.name == "zimage"
    assert (
        application.state.minimax_workflow_binding_snapshot.name == "minimaxh3"
    )
    assert vllm_client.calls == 2
    assert comfy_client.calls == 2


def test_c009_invalid_minimax_binding_rejects_startup_before_worker_claim(
    tmp_path: Path,
) -> None:
    workflow_path = tmp_path / "workflows" / "bad.json"
    workflow_path.parent.mkdir()
    workflow_path.write_text(
        json.dumps({"nodes": [], "links": []}), encoding="utf-8"
    )
    binding_path = tmp_path / "minimaxh3.toml"
    binding_path.write_text(
        """
[comfy.minimaxh3]
workflow = "workflows/bad.json"
prompt_path = "138.inputs.value"
seed_path = "129.inputs.noise_seed"
duration_path = "132.inputs.value"
ref_image_paths = [
  "137.inputs.image",
  "139.inputs.image",
  "146.inputs.image",
  "400.inputs.image",
  "401.inputs.image",
  "402.inputs.image",
  "403.inputs.image",
  "404.inputs.image",
  "405.inputs.image",
]
ref_consumer_paths = [
  "186.inputs.ref_images.ref_image_0",
  "186.inputs.ref_images.ref_image_1",
  "186.inputs.ref_images.ref_image_2",
  "186.inputs.ref_images.ref_image_3",
  "186.inputs.ref_images.ref_image_4",
  "186.inputs.ref_images.ref_image_5",
  "186.inputs.ref_images.ref_image_6",
  "186.inputs.ref_images.ref_image_7",
  "186.inputs.ref_images.ref_image_8",
]
optional_refs = false
output_node = "168"
""".lstrip(),
        encoding="utf-8",
    )
    target_id = 9_009_001
    task_id = asyncio.run(_insert_queued_task(target_id))
    claimed = False

    async def handler(_task, _context) -> None:
        nonlocal claimed
        claimed = True

    application = create_app(
        minimax_binding_path=binding_path,
        minimax_binding_root=tmp_path,
        task_handlers={"gen_asset_image": handler},
    )
    try:
        with pytest.raises(WorkflowBindingError, match="UI graph"):
            with TestClient(application):
                pass
        assert not claimed
        assert asyncio.run(_task_status(task_id)) == "queued"
    finally:
        asyncio.run(_delete_task(task_id))
