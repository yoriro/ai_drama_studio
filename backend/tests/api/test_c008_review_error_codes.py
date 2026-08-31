from __future__ import annotations

import asyncio
from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.config import settings
from app.db.session import engine
from app.main import app
from app.tasks.queue import TaskQueue
from tests.api.test_c008_slots import _cleanup_fixture, _create_fixture


def _assert_error(response, status_code: int, code: str, message: str) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"detail"}
    assert set(body["detail"]) == {"code", "message"}
    assert body["detail"]["code"] == code
    assert body["detail"]["message"] == message
    assert isinstance(body["detail"]["message"], str)
    assert body["detail"]["message"]


def test_c008_review_error_codes_and_boundary_sql(monkeypatch, tmp_path) -> None:
    async def idle_worker(
        self,
        *,
        handlers,
        stop_event=None,
        poll_interval=0.5,
        stop_when_idle=False,
    ) -> None:
        del self, handlers, poll_interval, stop_when_idle
        assert stop_event is not None
        await stop_event.wait()

    monkeypatch.setattr(TaskQueue, "run_worker", idle_worker)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture())
    counter = {"sql": 0}

    def count_sql(*args) -> None:
        del args
        counter["sql"] += 1

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            event.listen(engine.sync_engine, "before_cursor_execute", count_sql)
            try:
                boundary_requests: list[tuple[str, Callable[[], object]]] = [
                    (
                        "preview_unknown_field",
                        lambda: client.post(
                            f"/api/episodes/{fixture['episode_id']}/clips/preview",
                            json={
                                "shot_ids": [fixture["shot_id"]],
                                "unknown": True,
                            },
                        ),
                    ),
                    (
                        "create_unknown_field",
                        lambda: client.post(
                            f"/api/episodes/{fixture['episode_id']}/clips",
                            json={
                                "shot_ids": [fixture["shot_id"]],
                                "reference_asset_ids": [
                                    fixture["asset_ids"]["first"]
                                ],
                                "unknown": True,
                            },
                        ),
                    ),
                    (
                        "patch_unknown_field",
                        lambda: client.patch(
                            f"/api/clips/{fixture['clip_id']}",
                            json={"unknown": True},
                        ),
                    ),
                    (
                        "slot_unknown_field",
                        lambda: client.patch(
                            f"/api/clips/{fixture['clip_id']}/slots/1",
                            json={"enabled": True, "unknown": True},
                        ),
                    ),
                    (
                        "slot_wrong_content_type",
                        lambda: client.patch(
                            f"/api/clips/{fixture['clip_id']}/slots/1",
                            content=b"enabled=true",
                            headers={"content-type": "text/plain"},
                        ),
                    ),
                ]
                expected_boundary_error = (
                    422,
                    "validation_error",
                    "Request validation failed",
                )
                expected_slot_error = (
                    422,
                    "validation_error",
                    "JSON slot mutation must be exactly {enabled: boolean}",
                )
                expected_content_type_error = (
                    422,
                    "validation_error",
                    "slot mutation must use application/json or multipart/form-data",
                )
                expected_errors = {
                    "preview_unknown_field": expected_boundary_error,
                    "create_unknown_field": expected_boundary_error,
                    "patch_unknown_field": expected_boundary_error,
                    "slot_unknown_field": expected_slot_error,
                    "slot_wrong_content_type": expected_content_type_error,
                }
                for name, request in boundary_requests:
                    counter["sql"] = 0
                    response = request()
                    _assert_error(response, *expected_errors[name])
                    assert counter["sql"] == 0, name

                counter["sql"] = 0
                no_override = client.get(
                    f"/media/slot-overrides/{fixture['slot_ids']['missing']}"
                )
                _assert_error(
                    no_override,
                    404,
                    "not_found",
                    "Slot override not found",
                )
                assert counter["sql"] == 1

                counter["sql"] = 0
                missing_file = client.get(
                    f"/media/slot-overrides/{fixture['slot_ids']['deleted']}"
                )
                _assert_error(
                    missing_file,
                    500,
                    "internal_error",
                    "Slot override media is unavailable",
                )
                assert counter["sql"] == 3
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", count_sql)
    finally:
        asyncio.run(_cleanup_fixture(fixture))
