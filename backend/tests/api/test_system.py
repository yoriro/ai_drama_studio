import socket

from fastapi.testclient import TestClient

from app.main import app


MINIMAX_WORKFLOW_HASH = "bfa1fbfffecf1665309b01234621bc32cd29f86fd3dfa40f12605cbf3eb3f780"


class _HealthyClient:
    def __init__(self) -> None:
        self.health_calls = 0

    async def health(self) -> None:
        self.health_calls += 1


def test_infrastructure_smoke(monkeypatch) -> None:
    def fail_external_connection(*args, **kwargs):
        raise AssertionError("health must not open an external connection")

    monkeypatch.setattr(socket, "create_connection", fail_external_connection)
    vllm_client = _HealthyClient()
    comfy_client = _HealthyClient()
    monkeypatch.setattr(
        app.state, "vllm_client_factory", lambda _base_url: vllm_client
    )
    monkeypatch.setattr(
        app.state, "comfy_client_factory", lambda _base_url: comfy_client
    )

    with TestClient(app) as client:
        docs_response = client.get("/docs")
        openapi_response = client.get("/openapi.json")
        health_response = client.get("/api/system/health")
        missing_response = client.get("/api/not-found")

    assert docs_response.status_code == 200
    assert openapi_response.status_code == 200
    assert health_response.status_code == 200
    assert health_response.json() == {
        "vllm": {"status": "healthy", "message": None},
        "comfy": {"status": "healthy", "message": None},
        "workflow_bindings": {
            "status": "valid",
            "message": None,
            "hashes": {
                "zimage": "e9790bece3462691ebaf63d849bf1940beec62f9149fb6d475be859c47e41eaa",
                "minimaxh3": MINIMAX_WORKFLOW_HASH,
            },
        },
    }
    assert vllm_client.health_calls == 2
    assert comfy_client.health_calls == 2
    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "detail": {"code": "not_found", "message": "Not Found"}
    }
