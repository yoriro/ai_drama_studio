import asyncio
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.main import app
from tests.api.test_c008_slots import _cleanup_fixture, _create_fixture


def _database_url() -> str:
    import os

    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _image_bytes(image_format: str, color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (3, 2), color).save(output, format=image_format)
    return output.getvalue()


def _slot_url(fixture: dict[str, object]) -> str:
    return f"/api/clips/{fixture['clip_id']}/slots/4"


def _media_url(fixture: dict[str, object]) -> str:
    return f"/media/slot-overrides/{fixture['slot_ids']['deleted']}"


def _relative_path(fixture: dict[str, object], extension: str) -> str:
    return (
        f"projects/{fixture['project_id']}/episodes/{fixture['episode_id']}"
        f"/clips/{fixture['clip_id']}/slots/{fixture['slot_ids']['deleted']}.{extension}"
    )


async def _reset_deleted_slot(fixture: dict[str, object]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            """
            UPDATE clip_ref_slots
            SET override_image_path = NULL, override_sha256 = NULL
            WHERE id = $1
            """,
            fixture["slot_ids"]["deleted"],
        )
    finally:
        await connection.close()


async def _read_override_state(
    fixture: dict[str, object],
) -> tuple[str | None, str | None, int, str, str]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT s.override_image_path, s.override_sha256,
                   c.revision, c.freshness, c.generation_state
            FROM clip_ref_slots AS s
            JOIN clips AS c ON c.id = s.clip_id
            WHERE s.id = $1
            """,
            fixture["slot_ids"]["deleted"],
        )
        return (
            row["override_image_path"],
            row["override_sha256"],
            int(row["revision"]),
            str(row["freshness"]),
            str(row["generation_state"]),
        )
    finally:
        await connection.close()


async def _set_override_row(
    fixture: dict[str, object], path: str, digest: str
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            """
            UPDATE clip_ref_slots
            SET override_image_path = $1, override_sha256 = $2
            WHERE id = $3
            """,
            path,
            digest,
            fixture["slot_ids"]["deleted"],
        )
    finally:
        await connection.close()


def _temp_files(data_dir: Path) -> list[Path]:
    return list((data_dir / "tmp" / "slot-overrides").glob("*"))


def _assert_error(response, status_code: int) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"detail"}
    assert body["detail"]["code"]
    assert body["detail"]["message"]


def _upload(client: TestClient, fixture: dict[str, object], data: bytes, mime: str):
    return client.patch(
        _slot_url(fixture),
        files={"file": ("user supplied name", data, mime)},
    )


def test_slot_override_upload_replace_clear_and_media(tmp_path, monkeypatch) -> None:
    fixture = asyncio.run(_create_fixture())
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    asyncio.run(_reset_deleted_slot(fixture))
    try:
        png = _image_bytes("PNG", (255, 0, 0))
        jpeg = _image_bytes("JPEG", (0, 255, 0))
        webp = _image_bytes("WEBP", (0, 0, 255))
        with TestClient(app) as client:
            uploaded = _upload(client, fixture, png, "image/png")
            assert uploaded.status_code == 200
            body = uploaded.json()
            assert set(body) == {"slot", "warnings"}
            assert body["slot"]["slot_no"] == 4
            assert body["slot"]["asset_id"] is None
            assert body["slot"]["asset_deleted"] is True
            assert body["slot"]["image_source"] == "override"
            assert body["slot"]["image_url"] == (
                f"/media/slot-overrides/{fixture['slot_ids']['deleted']}"
            )
            png_path = _relative_path(fixture, "png")
            assert asyncio.run(_read_override_state(fixture)) == (
                png_path,
                sha256(png).hexdigest(),
                2,
                "stale",
                "empty",
            )
            assert (tmp_path / Path(png_path)).read_bytes() == png
            assert _temp_files(tmp_path) == []

            media = client.get(_media_url(fixture))
            assert media.status_code == 200
            assert media.headers["content-type"].startswith("image/png")
            assert media.content == png

            same = _upload(client, fixture, png, "image/png")
            assert same.status_code == 200
            assert asyncio.run(_read_override_state(fixture))[2:] == (
                2,
                "stale",
                "empty",
            )
            assert not (tmp_path / "trash" / Path(png_path)).exists()

            replaced = _upload(client, fixture, jpeg, "image/jpeg")
            assert replaced.status_code == 200
            jpg_path = _relative_path(fixture, "jpg")
            assert asyncio.run(_read_override_state(fixture)) == (
                jpg_path,
                sha256(jpeg).hexdigest(),
                3,
                "stale",
                "empty",
            )
            assert not (tmp_path / Path(png_path)).exists()
            assert (tmp_path / "trash" / Path(png_path)).read_bytes() == png
            assert (tmp_path / Path(jpg_path)).read_bytes() == jpeg
            media = client.get(_media_url(fixture))
            assert media.status_code == 200
            assert media.headers["content-type"].startswith("image/jpeg")
            assert media.content == jpeg

            replaced = _upload(client, fixture, webp, "image/webp")
            assert replaced.status_code == 200
            webp_path = _relative_path(fixture, "webp")
            assert asyncio.run(_read_override_state(fixture)) == (
                webp_path,
                sha256(webp).hexdigest(),
                4,
                "stale",
                "empty",
            )
            assert not (tmp_path / Path(jpg_path)).exists()
            assert (tmp_path / "trash" / Path(jpg_path)).read_bytes() == jpeg
            media = client.get(_media_url(fixture))
            assert media.status_code == 200
            assert media.headers["content-type"].startswith("image/webp")
            assert media.content == webp

            cleared = client.patch(
                _slot_url(fixture),
                files={"clear_override": (None, "true")},
            )
            assert cleared.status_code == 200
            assert cleared.json()["slot"]["image_source"] is None
            assert cleared.json()["slot"]["image_url"] is None
            assert asyncio.run(_read_override_state(fixture)) == (
                None,
                None,
                5,
                "stale",
                "empty",
            )
            assert not (tmp_path / Path(webp_path)).exists()
            assert (tmp_path / "trash" / Path(webp_path)).read_bytes() == webp
            _assert_error(client.get(_media_url(fixture)), 404)

            clear_noop = client.patch(
                _slot_url(fixture),
                files={"clear_override": (None, "true")},
            )
            assert clear_noop.status_code == 200
            assert asyncio.run(_read_override_state(fixture))[2:] == (
                5,
                "stale",
                "empty",
            )

            asyncio.run(
                _set_override_row(
                    fixture,
                    "../outside.png",
                    sha256(png).hexdigest(),
                )
            )
            _assert_error(client.get(_media_url(fixture)), 500)
            asyncio.run(
                _set_override_row(
                    fixture,
                    _relative_path(fixture, "gif"),
                    sha256(png).hexdigest(),
                )
            )
            _assert_error(client.get(_media_url(fixture)), 500)
            asyncio.run(
                _set_override_row(
                    fixture,
                    _relative_path(fixture, "png"),
                    sha256(png).hexdigest(),
                )
            )
            _assert_error(client.get(_media_url(fixture)), 500)
    finally:
        asyncio.run(_cleanup_fixture(fixture))


def test_slot_override_rejects_multipart_and_content_errors(
    tmp_path, monkeypatch
) -> None:
    fixture = asyncio.run(_create_fixture())
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    asyncio.run(_reset_deleted_slot(fixture))
    try:
        png = _image_bytes("PNG", (10, 20, 30))
        with TestClient(app) as client:
            invalid_requests = [
                {"files": {"other": (None, "value")}},
                {"files": {"clear_override": (None, "false")}},
                {
                    "files": {
                        "file": ("bad.gif", png, "image/gif"),
                    }
                },
                {
                    "files": {
                        "file": ("wrong.jpg", png, "image/jpeg"),
                    }
                },
                {
                    "files": {
                        "file": ("broken.png", b"not an image", "image/png"),
                    }
                },
                {"files": {"file": ("empty.png", b"", "image/png")}},
                {
                    "files": [
                        ("file", ("one.png", png, "image/png")),
                        ("file", ("two.png", png, "image/png")),
                    ]
                },
                {
                    "files": [
                        ("file", ("one.png", png, "image/png")),
                        ("clear_override", (None, "true")),
                    ]
                },
                {
                    "files": [
                        ("file", ("one.png", png, "image/png")),
                        ("enabled", (None, "false")),
                    ]
                },
            ]
            for request in invalid_requests:
                _assert_error(client.patch(_slot_url(fixture), **request), 422)
            empty_multipart = client.patch(
                _slot_url(fixture),
                content=b"--c008-boundary--\r\n",
                headers={
                    "content-type": "multipart/form-data; "
                    "boundary=c008-boundary"
                },
            )
            _assert_error(empty_multipart, 422)

            monkeypatch.setattr(settings, "UPLOAD_MAX_MB", 1)
            oversized = client.patch(
                _slot_url(fixture),
                files={
                    "file": (
                        "large.png",
                        b"x" * (1024 * 1024 + 1),
                        "image/png",
                    )
                },
            )
            _assert_error(oversized, 422)

            assert asyncio.run(_read_override_state(fixture)) == (
                None,
                None,
                1,
                "fresh",
                "empty",
            )
            assert _temp_files(tmp_path) == []
            assert not (tmp_path / "projects").exists()
    finally:
        asyncio.run(_cleanup_fixture(fixture))


def test_slot_override_compensates_database_failure_and_reports_restore_failure(
    tmp_path, monkeypatch, caplog
) -> None:
    fixture = asyncio.run(_create_fixture())
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    asyncio.run(_reset_deleted_slot(fixture))
    original_flush = AsyncSession.flush
    original_replace = Path.replace
    try:
        png = _image_bytes("PNG", (100, 10, 10))
        jpeg = _image_bytes("JPEG", (10, 100, 10))
        webp = _image_bytes("WEBP", (10, 10, 100))
        with TestClient(app, raise_server_exceptions=False) as client:
            async def failing_flush(self, *args, **kwargs):
                await original_flush(self, *args, **kwargs)
                raise RuntimeError("C008 injected override database failure")

            monkeypatch.setattr(AsyncSession, "flush", failing_flush)
            first_failure = _upload(client, fixture, png, "image/png")
            _assert_error(first_failure, 500)
            png_path = _relative_path(fixture, "png")
            assert asyncio.run(_read_override_state(fixture)) == (
                None,
                None,
                1,
                "fresh",
                "empty",
            )
            assert not (tmp_path / Path(png_path)).exists()
            assert (tmp_path / "trash" / Path(png_path)).read_bytes() == png
            assert _temp_files(tmp_path) == []

            monkeypatch.setattr(AsyncSession, "flush", original_flush)
            base = _upload(client, fixture, png, "image/png")
            assert base.status_code == 200
            base_state = asyncio.run(_read_override_state(fixture))
            base_formal = tmp_path / Path(base_state[0])
            base_trash = tmp_path / "trash" / Path(base_state[0])
            assert base_formal.read_bytes() == png

            monkeypatch.setattr(AsyncSession, "flush", failing_flush)
            replacement_failure = _upload(client, fixture, jpeg, "image/jpeg")
            _assert_error(replacement_failure, 500)
            assert asyncio.run(_read_override_state(fixture)) == base_state
            assert base_formal.read_bytes() == png
            assert not base_trash.exists()
            jpg_path = _relative_path(fixture, "jpg")
            assert not (tmp_path / Path(jpg_path)).exists()
            assert (tmp_path / "trash" / Path(jpg_path)).read_bytes() == jpeg
            assert _temp_files(tmp_path) == []

            monkeypatch.setattr(AsyncSession, "flush", original_flush)
            caplog.clear()

            def fail_restore(self, target):
                if self == tmp_path / "trash" / Path(base_state[0]):
                    raise OSError("C008 injected old override restore failure")
                return original_replace(self, target)

            monkeypatch.setattr(Path, "replace", fail_restore)
            monkeypatch.setattr(AsyncSession, "flush", failing_flush)
            restore_failure = _upload(client, fixture, webp, "image/webp")
            _assert_error(restore_failure, 500)
            assert "C008 injected override database failure" in caplog.text
            assert "old override restore failed" in caplog.text
            assert asyncio.run(_read_override_state(fixture)) == base_state
            assert not base_formal.exists()
            assert base_trash.read_bytes() == png
            webp_path = _relative_path(fixture, "webp")
            assert (tmp_path / "trash" / Path(webp_path)).read_bytes() == webp
            assert _temp_files(tmp_path) == []
    finally:
        monkeypatch.setattr(AsyncSession, "flush", original_flush)
        monkeypatch.setattr(Path, "replace", original_replace)
        asyncio.run(_cleanup_fixture(fixture))
