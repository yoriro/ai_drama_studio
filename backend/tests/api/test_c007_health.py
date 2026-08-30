import asyncio
import json
from pathlib import Path

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.integrations.workflow_binding import WorkflowBindingError
from app.main import create_app


WORKFLOW_HASH = "e9790bece3462691ebaf63d849bf1940beec62f9149fb6d475be859c47e41eaa"


class _ProbeClient:
    def __init__(self, error: BaseException | None = None) -> None:
        self.calls = 0
        self._error = error

    async def health(self) -> None:
        self.calls += 1
        if self._error is not None:
            raise self._error


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


def test_health_returns_exact_schema_and_probes_once_per_lifecycle() -> None:
    vllm_client = _ProbeClient()
    comfy_client = _ProbeClient()
    application = create_app(
        vllm_client_factory=lambda _base_url: vllm_client,
        comfy_client_factory=lambda _base_url: comfy_client,
    )

    with TestClient(application) as client:
        first = client.get("/api/system/health")
        second = client.get("/api/system/health")

        expected = {
            "vllm": {"status": "healthy", "message": None},
            "comfy": {"status": "healthy", "message": None},
            "workflow_bindings": {
                "status": "valid",
                "message": None,
                "hashes": {"zimage": WORKFLOW_HASH},
            },
        }
        assert first.status_code == 200
        assert first.json() == expected
        assert second.status_code == 200
        assert second.json() == expected

    assert vllm_client.calls == 3
    assert comfy_client.calls == 3


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "http://health.test/health")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"unexpected {status_code}", request=request, response=response
    )


@pytest.mark.parametrize(
    ("component", "error", "expected_message"),
    [
        (
            "vllm",
            httpx.ConnectError("offline"),
            "vLLM health connection failed",
        ),
        (
            "comfy",
            _http_status_error(503),
            "ComfyUI health returned HTTP 503",
        ),
        (
            "comfy",
            ValueError("invalid JSON"),
            "ComfyUI health response was invalid",
        ),
    ],
)
def test_health_reports_expected_component_failures(
    component: str, error: BaseException, expected_message: str
) -> None:
    vllm_client = _ProbeClient(error if component == "vllm" else None)
    comfy_client = _ProbeClient(error if component == "comfy" else None)
    application = create_app(
        vllm_client_factory=lambda _base_url: vllm_client,
        comfy_client_factory=lambda _base_url: comfy_client,
    )

    with TestClient(application) as client:
        response = client.get("/api/system/health")

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"vllm", "comfy", "workflow_bindings"}
    assert body[component] == {
        "status": "unhealthy",
        "message": expected_message,
    }
    other_component = "comfy" if component == "vllm" else "vllm"
    assert body[other_component] == {"status": "healthy", "message": None}
    assert body["workflow_bindings"] == {
        "status": "valid",
        "message": None,
        "hashes": {"zimage": WORKFLOW_HASH},
    }
    assert vllm_client.calls == 2
    assert comfy_client.calls == 2


def test_invalid_binding_rejects_startup_before_worker_claim(tmp_path: Path) -> None:
    workflow_path = tmp_path / "workflows" / "bad.json"
    workflow_path.parent.mkdir()
    workflow_path.write_text(
        json.dumps({"nodes": [], "links": []}), encoding="utf-8"
    )
    binding_path = tmp_path / "bindings.toml"
    binding_path.write_text(
        """
[comfy.zimage]
workflow = "workflows/bad.json"
prompt_path = "6.inputs.text"
seed_path = "3.inputs.seed"
output_node = "9"
""".lstrip(),
        encoding="utf-8",
    )
    target_id = 7_007_001
    task_id = asyncio.run(_insert_queued_task(target_id))
    claimed = False

    async def handler(_task, _context) -> None:
        nonlocal claimed
        claimed = True

    application = create_app(
        binding_path=binding_path,
        binding_root=tmp_path,
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
