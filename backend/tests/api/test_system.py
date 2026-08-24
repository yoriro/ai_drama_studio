import socket

from fastapi.testclient import TestClient

from app.main import app


def test_infrastructure_smoke(monkeypatch) -> None:
    def fail_external_connection(*args, **kwargs):
        raise AssertionError("health must not open an external connection")

    monkeypatch.setattr(socket, "create_connection", fail_external_connection)

    with TestClient(app) as client:
        docs_response = client.get("/docs")
        openapi_response = client.get("/openapi.json")
        health_response = client.get("/api/system/health")
        missing_response = client.get("/api/not-found")

    assert docs_response.status_code == 200
    assert openapi_response.status_code == 200
    assert health_response.status_code == 200
    assert health_response.json() == {
        "vllm": {"status": "not_checked"},
        "comfy": {"status": "not_checked"},
        "workflow_bindings": {"status": "not_checked", "hashes": {}},
    }
    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "detail": {"code": "not_found", "message": "Not Found"}
    }
