from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import engine
from app.main import app
from app.tasks.queue import TaskQueue
from tests.api.test_c009_clip_videos import (
    _assert_error,
    _configure_app,
    _insert_video,
    _read_clip_projection,
    _read_video_rows,
)
from tests.api.test_c009_generate_video import (
    _cleanup_fixture,
    _create_fixture,
)


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _set_video_path(video_id: int, path: str) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE clip_videos SET file_path = $1 WHERE id = $2",
            path,
            video_id,
        )
    finally:
        await connection.close()


async def _set_video_hash(video_id: int, digest: str) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE clip_videos SET sha256 = $1 WHERE id = $2",
            digest,
            video_id,
        )
    finally:
        await connection.close()


def test_c009_clip_video_delete_current_noncurrent_and_same_name_trash(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        current_id, current_relative, current_bytes = asyncio.run(
            _insert_video(fixture, tmp_path, seed=1, is_current=True)
        )
        noncurrent_id, noncurrent_relative, noncurrent_bytes = asyncio.run(
            _insert_video(fixture, tmp_path, seed=2, is_current=False)
        )
        before_projection = asyncio.run(
            _read_clip_projection(int(fixture["clip_id"]))
        )
        existing_trash = tmp_path / "trash" / Path(noncurrent_relative)
        existing_trash.parent.mkdir(parents=True, exist_ok=True)
        existing_trash.write_bytes(b"old trash content")
        _configure_app(monkeypatch)

        with TestClient(app, raise_server_exceptions=False) as client:
            _assert_error(
                client.delete(f"/api/clip-videos/{current_id}"),
                409,
                "conflict",
                "Current clip video cannot be deleted directly",
            )
            deleted = client.delete(f"/api/clip-videos/{noncurrent_id}")
            assert deleted.status_code == 204
            assert deleted.content == b""
            _assert_error(
                client.get(f"/media/clip-videos/{noncurrent_id}"),
                404,
                "not_found",
                "Clip video not found",
            )

        rows = asyncio.run(_read_video_rows(int(fixture["clip_id"])))
        assert [row["id"] for row in rows] == [current_id]
        assert rows[0]["is_current"] is True
        assert rows[0]["file_path"] == current_relative
        assert (tmp_path / Path(current_relative)).read_bytes() == current_bytes
        assert not (tmp_path / Path(noncurrent_relative)).exists()
        assert existing_trash.read_bytes() == noncurrent_bytes
        assert asyncio.run(_read_clip_projection(int(fixture["clip_id"]))) == (
            before_projection
        )
    finally:
        asyncio.run(_cleanup_fixture(fixture))
        asyncio.run(engine.dispose())


def test_c009_clip_video_delete_rejects_path_hash_and_missing_file(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        video_id, relative, content = asyncio.run(
            _insert_video(fixture, tmp_path, seed=3, is_current=False)
        )
        before_rows = asyncio.run(_read_video_rows(int(fixture["clip_id"])))
        _configure_app(monkeypatch)

        with TestClient(app, raise_server_exceptions=False) as client:
            asyncio.run(_set_video_path(video_id, "../outside.mp4"))
            _assert_error(
                client.delete(f"/api/clip-videos/{video_id}"),
                500,
                "internal_error",
                "Clip video file is unavailable",
            )
            path_rows = asyncio.run(_read_video_rows(int(fixture["clip_id"])))
            assert path_rows[0]["file_path"] == "../outside.mp4"
            assert path_rows[0]["sha256"] == before_rows[0]["sha256"]
            assert (tmp_path / Path(relative)).is_file()

            asyncio.run(_set_video_path(video_id, relative))
            asyncio.run(_set_video_hash(video_id, "0" * 64))
            _assert_error(
                client.delete(f"/api/clip-videos/{video_id}"),
                500,
                "internal_error",
                "Clip video file is unavailable",
            )
            hash_rows = asyncio.run(_read_video_rows(int(fixture["clip_id"])))
            assert hash_rows[0]["file_path"] == relative
            assert hash_rows[0]["sha256"] == "0" * 64
            assert (tmp_path / Path(relative)).read_bytes() == content

            asyncio.run(_set_video_hash(video_id, before_rows[0]["sha256"]))
            (tmp_path / Path(relative)).unlink()
            _assert_error(
                client.delete(f"/api/clip-videos/{video_id}"),
                500,
                "internal_error",
                "Clip video file is unavailable",
            )
            missing_rows = asyncio.run(_read_video_rows(int(fixture["clip_id"])))
            assert missing_rows == before_rows
    finally:
        asyncio.run(_cleanup_fixture(fixture))
        asyncio.run(engine.dispose())


def test_c009_clip_video_delete_restores_after_database_failure(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    original_flush = AsyncSession.flush
    try:
        video_id, relative, content = asyncio.run(
            _insert_video(fixture, tmp_path, seed=4, is_current=False)
        )
        before_rows = asyncio.run(_read_video_rows(int(fixture["clip_id"])))

        async def failing_flush(self, *args, **kwargs):
            await original_flush(self, *args, **kwargs)
            raise RuntimeError("T15 database failure")

        monkeypatch.setattr(AsyncSession, "flush", failing_flush)
        _configure_app(monkeypatch)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.delete(f"/api/clip-videos/{video_id}")
            _assert_error(
                response,
                500,
                "internal_error",
                "Internal server error",
            )

        assert asyncio.run(_read_video_rows(int(fixture["clip_id"]))) == before_rows
        assert (tmp_path / Path(relative)).read_bytes() == content
        assert not (tmp_path / "trash" / Path(relative)).exists()
    finally:
        asyncio.run(_cleanup_fixture(fixture))
        asyncio.run(engine.dispose())


def test_c009_clip_video_delete_preserves_database_and_restore_failures(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    original_flush = AsyncSession.flush
    original_replace = Path.replace
    try:
        video_id, relative, content = asyncio.run(
            _insert_video(fixture, tmp_path, seed=5, is_current=False)
        )
        before_rows = asyncio.run(_read_video_rows(int(fixture["clip_id"])))
        formal = tmp_path / Path(relative)
        trash = tmp_path / "trash" / Path(relative)

        async def failing_flush(self, *args, **kwargs):
            await original_flush(self, *args, **kwargs)
            raise RuntimeError("T15 database failure")

        def failing_restore(self, target):
            if self == trash and Path(target) == formal:
                raise OSError("T15 restore failure")
            return original_replace(self, target)

        monkeypatch.setattr(AsyncSession, "flush", failing_flush)
        monkeypatch.setattr(Path, "replace", failing_restore)
        _configure_app(monkeypatch)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.delete(f"/api/clip-videos/{video_id}")
            _assert_error(
                response,
                500,
                "internal_error",
                "Internal server error",
            )

        assert "T15 database failure" in caplog.text
        assert "T15 restore failure" in caplog.text
        assert "clip video restore failed" in caplog.text
        assert asyncio.run(_read_video_rows(int(fixture["clip_id"]))) == before_rows
        assert not formal.exists()
        assert trash.read_bytes() == content
    finally:
        monkeypatch.setattr(Path, "replace", original_replace)
        monkeypatch.setattr(AsyncSession, "flush", original_flush)
        asyncio.run(_cleanup_fixture(fixture))
        asyncio.run(engine.dispose())


def test_c009_clip_video_media_uses_canonical_id_path_and_mp4(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture(tmp_path))
    try:
        video_id, relative, content = asyncio.run(
            _insert_video(fixture, tmp_path, seed=6, is_current=True)
        )
        _configure_app(monkeypatch)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(f"/media/clip-videos/{video_id}")
            assert response.status_code == 200
            assert response.headers["content-type"] == "video/mp4"
            assert response.content == content

            query_path = client.get(
                f"/media/clip-videos/{video_id}?path=../../outside.mp4&filename=x"
            )
            assert query_path.status_code == 200
            assert query_path.headers["content-type"] == "video/mp4"
            assert query_path.content == content

            _assert_error(
                client.get("/media/clip-videos/2147483647"),
                404,
                "not_found",
                "Clip video not found",
            )

            asyncio.run(_set_video_path(video_id, "../outside.mp4"))
            _assert_error(
                client.get(f"/media/clip-videos/{video_id}"),
                500,
                "internal_error",
                "Clip video media is unavailable",
            )

            asyncio.run(_set_video_path(video_id, relative))
            (tmp_path / Path(relative)).unlink()
            _assert_error(
                client.get(f"/media/clip-videos/{video_id}"),
                500,
                "internal_error",
                "Clip video media is unavailable",
            )
    finally:
        asyncio.run(_cleanup_fixture(fixture))
        asyncio.run(engine.dispose())
