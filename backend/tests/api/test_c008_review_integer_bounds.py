from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.db.session import engine
from app.main import app
from app.tasks.queue import TaskQueue


POSTGRES_INTEGER_MIN = -2_147_483_648
POSTGRES_INTEGER_MAX = 2_147_483_647


def _assert_error(response, status_code: int, code: str, message: str) -> None:
    assert response.status_code == status_code
    assert response.json() == {
        "detail": {
            "code": code,
            "message": message,
        }
    }


def test_c008_integer_bounds_are_checked_before_sql(monkeypatch) -> None:
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
    counter = {"sql": 0}

    def count_sql(*args) -> None:
        del args
        counter["sql"] += 1

    event.listen(engine.sync_engine, "before_cursor_execute", count_sql)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            path_requests: list[tuple[str, Callable[[], object]]] = []
            for value in (POSTGRES_INTEGER_MAX + 1, POSTGRES_INTEGER_MIN - 1):
                path_requests.extend(
                    [
                        (
                            f"clip_get_{value}",
                            lambda value=value: client.get(f"/api/clips/{value}"),
                        ),
                        (
                            f"clip_patch_{value}",
                            lambda value=value: client.patch(
                                f"/api/clips/{value}",
                                json={"user_note": "valid"},
                            ),
                        ),
                        (
                            f"clip_delete_{value}",
                            lambda value=value: client.delete(
                                f"/api/clips/{value}"
                            ),
                        ),
                        (
                            f"clip_slots_{value}",
                            lambda value=value: client.get(
                                f"/api/clips/{value}/slots"
                            ),
                        ),
                        (
                            f"clip_slot_mutation_{value}",
                            lambda value=value: client.patch(
                                f"/api/clips/{value}/slots/1",
                                json={"enabled": True},
                            ),
                        ),
                        (
                            f"episode_list_{value}",
                            lambda value=value: client.get(
                                f"/api/episodes/{value}/clips"
                            ),
                        ),
                        (
                            f"episode_preview_{value}",
                            lambda value=value: client.post(
                                f"/api/episodes/{value}/clips/preview",
                                json={"shot_ids": [1]},
                            ),
                        ),
                        (
                            f"episode_create_{value}",
                            lambda value=value: client.post(
                                f"/api/episodes/{value}/clips",
                                json={
                                    "shot_ids": [1],
                                    "reference_asset_ids": [1],
                                },
                            ),
                        ),
                        (
                            f"slot_media_{value}",
                            lambda value=value: client.get(
                                f"/media/slot-overrides/{value}"
                            ),
                        ),
                    ]
                )

            for name, request in path_requests:
                counter["sql"] = 0
                response = request()
                _assert_error(
                    response,
                    422,
                    "validation_error",
                    "Request validation failed",
                )
                assert counter["sql"] == 0, name

            body_requests = [
                (
                    "preview_shot_ids",
                    lambda: client.post(
                        f"/api/episodes/{POSTGRES_INTEGER_MAX}/clips/preview",
                        json={"shot_ids": [POSTGRES_INTEGER_MAX + 1]},
                    ),
                ),
                (
                    "create_shot_ids",
                    lambda: client.post(
                        f"/api/episodes/{POSTGRES_INTEGER_MAX}/clips",
                        json={
                            "shot_ids": [POSTGRES_INTEGER_MAX + 1],
                            "reference_asset_ids": [1],
                        },
                    ),
                ),
                (
                    "create_reference_asset_ids",
                    lambda: client.post(
                        f"/api/episodes/{POSTGRES_INTEGER_MAX}/clips",
                        json={
                            "shot_ids": [1],
                            "reference_asset_ids": [POSTGRES_INTEGER_MAX + 1],
                        },
                    ),
                ),
            ]
            for name, request in body_requests:
                counter["sql"] = 0
                response = request()
                _assert_error(
                    response,
                    422,
                    "validation_error",
                    "Request validation failed",
                )
                assert counter["sql"] == 0, name

            unknown_path_requests = [
                (
                    "clip_get",
                    lambda: client.get(f"/api/clips/{POSTGRES_INTEGER_MAX}"),
                    "Clip not found",
                ),
                (
                    "clip_patch",
                    lambda: client.patch(
                        f"/api/clips/{POSTGRES_INTEGER_MAX}",
                        json={"user_note": "valid"},
                    ),
                    "Clip not found",
                ),
                (
                    "clip_delete",
                    lambda: client.delete(
                        f"/api/clips/{POSTGRES_INTEGER_MAX}"
                    ),
                    "Clip not found",
                ),
                (
                    "clip_slots",
                    lambda: client.get(
                        f"/api/clips/{POSTGRES_INTEGER_MAX}/slots"
                    ),
                    "Clip not found",
                ),
                (
                    "clip_slot_mutation",
                    lambda: client.patch(
                        f"/api/clips/{POSTGRES_INTEGER_MAX}/slots/1",
                        json={"enabled": True},
                    ),
                    "Clip not found",
                ),
                (
                    "episode_list",
                    lambda: client.get(
                        f"/api/episodes/{POSTGRES_INTEGER_MAX}/clips"
                    ),
                    "Episode not found",
                ),
                (
                    "episode_preview",
                    lambda: client.post(
                        f"/api/episodes/{POSTGRES_INTEGER_MAX}/clips/preview",
                        json={"shot_ids": [1]},
                    ),
                    "Episode not found",
                ),
                (
                    "episode_create",
                    lambda: client.post(
                        f"/api/episodes/{POSTGRES_INTEGER_MAX}/clips",
                        json={
                            "shot_ids": [1],
                            "reference_asset_ids": [1],
                        },
                    ),
                    "Episode not found",
                ),
                (
                    "slot_media",
                    lambda: client.get(
                        f"/media/slot-overrides/{POSTGRES_INTEGER_MAX}"
                    ),
                    "Slot override not found",
                ),
            ]
            for name, request, message in unknown_path_requests:
                response = request()
                _assert_error(response, 404, "not_found", message)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_sql)
