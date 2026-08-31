from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

import app.api.assets as assets_api
from app.main import create_app


class _HealthProbe:
    async def health(self) -> None:
        return None


def test_generate_asset_image_rejects_postgresql_int32_lower_bound_before_enqueue(
    monkeypatch,
) -> None:
    application: Any = None
    enqueue_calls: list[object] = []

    async def stop_worker() -> None:
        assert application is not None
        application.state.task_worker_stop.set()

    async def forbidden_enqueue(*args: object, **kwargs: object) -> None:
        del args, kwargs
        enqueue_calls.append(object())
        raise AssertionError("out-of-range asset_id reached task enqueue")

    application = create_app(
        startup_prepare=stop_worker,
        vllm_client_factory=lambda _base_url: _HealthProbe(),
        comfy_client_factory=lambda _base_url: _HealthProbe(),
    )
    monkeypatch.setattr(assets_api, "enqueue_generate_asset_image", forbidden_enqueue)

    with TestClient(application) as client:
        response = client.post(
            "/api/assets/-2147483649/generate-image",
            json={},
        )

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail"}
    assert set(body["detail"]) == {"code", "message"}
    assert body["detail"]["code"] == "validation_error"
    assert isinstance(body["detail"]["message"], str)
    assert body["detail"]["message"]
    assert enqueue_calls == []
