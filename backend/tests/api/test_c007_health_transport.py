from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import cast

import pytest
from fastapi.testclient import TestClient

from app.db.session import engine
from app.integrations.comfy import ComfyClient
from app.main import create_app
from app.services.vllm import VLLMClient


class _HealthServer(ThreadingHTTPServer):
    case: str
    paths: list[str]

    def __init__(self, case: str) -> None:
        super().__init__(("127.0.0.1", 0), _HealthHandler)
        self.case = case
        self.paths = []


class _HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def do_GET(self) -> None:
        server = cast(_HealthServer, self.server)
        server.paths.append(self.path)
        if self.path == "/health":
            if server.case == "vllm_non_2xx":
                status = 503
                body = b"down"
            elif server.case == "vllm_non_json_body":
                status = 200
                body = b"not-json"
            else:
                status = 200
                body = b""
        elif self.path == "/system_stats":
            if server.case == "comfy_malformed_json":
                status = 200
                body = b"not-json"
            else:
                status = 200
                body = b'{"system":"ready"}'
        else:
            status = 404
            body = b"not found"
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.mark.parametrize(
    "case",
    [
        pytest.param("vllm_empty_body", id="vllm_empty_body"),
        pytest.param("vllm_non_json_body", id="vllm_non_json_body"),
        pytest.param("vllm_non_2xx", id="vllm_non_2xx"),
        pytest.param("comfy_malformed_json", id="comfy_malformed_json"),
    ],
)
def test_health_follows_upstream_protocol_contracts(case: str) -> None:
    server = _HealthServer(case)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    application = create_app(
        startup_prepare=lambda: _stop_worker(application),
        vllm_client_factory=lambda _base_url: VLLMClient(base_url),
        comfy_client_factory=lambda _base_url: ComfyClient(base_url),
    )
    try:
        with TestClient(application) as client:
            response = client.get("/api/system/health")

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"vllm", "comfy", "workflow_bindings"}
        if case in {"vllm_empty_body", "vllm_non_json_body"}:
            assert body["vllm"] == {"status": "healthy", "message": None}
        elif case == "vllm_non_2xx":
            assert body["vllm"] == {
                "status": "unhealthy",
                "message": "vLLM health returned HTTP 503",
            }
        else:
            assert body["comfy"] == {
                "status": "unhealthy",
                "message": "ComfyUI health response was invalid",
            }
        if case != "comfy_malformed_json":
            assert body["comfy"] == {"status": "healthy", "message": None}
        if case not in {"vllm_non_2xx", "comfy_malformed_json"}:
            assert body["vllm"] == {"status": "healthy", "message": None}
        assert body["workflow_bindings"]["status"] == "valid"
        assert set(body["workflow_bindings"]["hashes"]) == {
            "zimage",
            "minimaxh3",
        }
        assert server.paths.count("/health") == 2
        assert server.paths.count("/system_stats") == 2
        assert all(
            path in {"/health", "/system_stats"} for path in server.paths
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        asyncio.run(engine.dispose())


async def _stop_worker(application) -> None:
    application.state.task_worker_stop.set()
