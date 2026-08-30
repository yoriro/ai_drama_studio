from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.vllm import VLLMClient


class _TimeoutHandler(BaseHTTPRequestHandler):
    server_version = "C007HealthTimeoutServer/1.0"

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def do_GET(self) -> None:
        time.sleep(0.2)
        raw = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except BrokenPipeError:
            return


class _TimeoutVLLM(VLLMClient):
    def __init__(self, base_url: str) -> None:
        super().__init__(base_url, timeout=0.03)
        self.mutation_calls: list[str] = []

    async def wake(self) -> None:
        self.mutation_calls.append("wake")

    async def sleep(self) -> None:
        self.mutation_calls.append("sleep")


class _NoMutationComfy:
    def __init__(self) -> None:
        self.mutation_calls: list[str] = []

    async def health(self) -> dict[str, str]:
        return {"system": "ready"}

    async def free(self) -> None:
        self.mutation_calls.append("free")


def test_health_timeout_is_unhealthy_without_gpu_mutation() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TimeoutHandler)
    server.daemon_threads = True
    thread = threading.Thread(
        target=server.serve_forever,
        name="c007-health-timeout-server",
        daemon=True,
    )
    thread.start()
    vllm_client: _TimeoutVLLM | None = None
    comfy_client = _NoMutationComfy()
    application: Any = None

    def build_vllm(base_url: str) -> _TimeoutVLLM:
        nonlocal vllm_client
        vllm_client = _TimeoutVLLM(base_url)
        return vllm_client

    async def stop_worker() -> None:
        assert application is not None
        application.state.task_worker_stop.set()

    try:
        application = create_app(
            startup_prepare=stop_worker,
            vllm_client_factory=build_vllm,
            comfy_client_factory=lambda _base_url: comfy_client,
        )
        with TestClient(application) as client:
            response = client.get("/api/system/health")

        assert vllm_client is not None
        assert response.status_code == 200
        body = response.json()
        assert body["vllm"] == {
            "status": "unhealthy",
            "message": "vLLM health probe timed out",
        }
        assert body["comfy"] == {"status": "healthy", "message": None}
        assert body["workflow_bindings"]["status"] == "valid"
        assert vllm_client.mutation_calls == []
        assert comfy_client.mutation_calls == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
