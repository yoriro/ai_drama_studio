from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.config import settings
from app.db.session import engine
from app.main import app
from tests.api.test_c009_clip_videos import (
    _assert_error as _assert_clip_error,
    _configure_app,
    _insert_video,
)
from tests.api.test_c009_generate_video import (
    _cleanup_fixture,
    _create_fixture,
)


def _assert_validation_error(response) -> None:
    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "validation_error",
            "message": "Request validation failed",
        }
    }


def _assert_not_found(response, message: str) -> None:
    _assert_clip_error(response, 404, "not_found", message)


def test_c009_api_boundaries_reject_before_sql_and_preserve_error_contract(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        video_id, relative_path, _ = asyncio.run(
            _insert_video(fixture, tmp_path, seed=31, is_current=True)
        )
        _configure_app(monkeypatch)

        with TestClient(app, raise_server_exceptions=False) as client:
            sql_count = {"value": 0}

            def count_sql(*args) -> None:
                del args
                sql_count["value"] += 1

            event.listen(engine.sync_engine, "before_cursor_execute", count_sql)
            try:
                invalid_requests = [
                    client.post(
                        f"/api/clips/{fixture['clip_id']}/generate-video"
                    ),
                    client.post(
                        f"/api/clips/{fixture['clip_id']}/generate-video",
                        content=b"null",
                        headers={"content-type": "application/json"},
                    ),
                    client.post(
                        f"/api/clips/{fixture['clip_id']}/generate-video",
                        json=[],
                    ),
                    client.post(
                        f"/api/clips/{fixture['clip_id']}/generate-video",
                        json={"unknown": True},
                    ),
                    client.post(
                        f"/api/clips/{fixture['clip_id']}/generate-video",
                        json={"user_note": 1.0},
                    ),
                    client.post(
                        f"/api/clips/{fixture['clip_id']}/generate-video",
                        json={"request_id": True},
                    ),
                    client.post(
                        f"/api/clips/{fixture['clip_id']}/generate-video",
                        json={"request_id": "   "},
                    ),
                    client.post(
                        f"/api/clips/{fixture['clip_id']}/generate-video",
                        json={"request_id": "a" * 129},
                    ),
                    client.post(
                        f"/api/clips/{fixture['clip_id']}/generate-video",
                        json={"request_id": "bad\x00id"},
                    ),
                    client.post(
                        f"/api/clips/{fixture['clip_id']}/generate-video",
                        json={"user_note": "bad\x00note"},
                    ),
                    client.post(
                        f"/api/clips/{fixture['clip_id']}/generate-video",
                        content=b"{}",
                        headers={"content-type": "text/plain"},
                    ),
                    client.post(
                        f"/api/assets/{fixture['character_id']}/generate-image",
                        json={"request_id": "   "},
                    ),
                    client.post(
                        f"/api/assets/{fixture['character_id']}/generate-image",
                        json={"request_id": "a" * 129},
                    ),
                    client.post(
                        f"/api/assets/{fixture['character_id']}/generate-image",
                        json={"request_id": "bad\x00id"},
                    ),
                    client.post(
                        f"/api/assets/{fixture['character_id']}/generate-image",
                        content=b"{}",
                        headers={"content-type": "text/plain"},
                    ),
                    client.put(
                        f"/api/clips/{fixture['clip_id']}/current-video",
                        json={},
                    ),
                    client.put(
                        f"/api/clips/{fixture['clip_id']}/current-video",
                        json=None,
                    ),
                    client.put(
                        f"/api/clips/{fixture['clip_id']}/current-video",
                        json=[],
                    ),
                    client.put(
                        f"/api/clips/{fixture['clip_id']}/current-video",
                        json={"video_id": True},
                    ),
                    client.put(
                        f"/api/clips/{fixture['clip_id']}/current-video",
                        json={"video_id": 1.0},
                    ),
                    client.put(
                        f"/api/clips/{fixture['clip_id']}/current-video",
                        json={"video_id": str(video_id)},
                    ),
                    client.put(
                        f"/api/clips/{fixture['clip_id']}/current-video",
                        json={"video_id": 0},
                    ),
                    client.put(
                        f"/api/clips/{fixture['clip_id']}/current-video",
                        json={"video_id": 2_147_483_648},
                    ),
                    client.put(
                        f"/api/clips/{fixture['clip_id']}/current-video",
                        json={"video_id": video_id, "extra": True},
                    ),
                ]
                for response in invalid_requests:
                    _assert_validation_error(response)

                path_boundary_requests = [
                    client.post("/api/clips/2147483648/generate-video", json={}),
                    client.post("/api/clips/-2147483649/generate-video", json={}),
                    client.post("/api/clips/not-an-integer/generate-video", json={}),
                    client.post("/api/assets/2147483648/generate-image", json={}),
                    client.get("/api/clips/2147483648/videos"),
                    client.get("/api/clips/-2147483649/videos"),
                    client.get("/api/clips/not-an-integer/videos"),
                    client.put(
                        "/api/clips/2147483648/current-video",
                        json={"video_id": video_id},
                    ),
                    client.put(
                        "/api/clips/-2147483649/current-video",
                        json={"video_id": video_id},
                    ),
                    client.put(
                        "/api/clips/not-an-integer/current-video",
                        json={"video_id": video_id},
                    ),
                    client.delete("/api/clip-videos/2147483648"),
                    client.delete("/api/clip-videos/-2147483649"),
                    client.delete("/api/clip-videos/not-an-integer"),
                    client.get("/media/clip-videos/2147483648"),
                    client.get("/media/clip-videos/-2147483649"),
                    client.get("/media/clip-videos/not-an-integer"),
                ]
                for response in path_boundary_requests:
                    _assert_validation_error(response)

                assert sql_count["value"] == 0
            finally:
                event.remove(
                    engine.sync_engine, "before_cursor_execute", count_sql
                )

            _assert_not_found(
                client.post("/api/clips/2147483647/generate-video", json={}),
                "Clip not found",
            )
            _assert_not_found(
                client.get("/api/clips/2147483647/videos"),
                "Clip not found",
            )
            _assert_not_found(
                client.put(
                    "/api/clips/2147483647/current-video",
                    json={"video_id": video_id},
                ),
                "Clip not found",
            )
            _assert_not_found(
                client.delete("/api/clip-videos/2147483647"),
                "Clip video not found",
            )
            _assert_not_found(
                client.get("/media/clip-videos/2147483647"),
                "Clip video not found",
            )

            (tmp_path / Path(relative_path)).unlink()
            _assert_clip_error(
                client.get(f"/media/clip-videos/{video_id}"),
                500,
                "internal_error",
                "Clip video media is unavailable",
            )
    finally:
        asyncio.run(_cleanup_fixture(fixture))
        asyncio.run(engine.dispose())
