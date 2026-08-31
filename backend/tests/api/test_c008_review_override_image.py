from __future__ import annotations

import asyncio
import struct
import zlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from tests.api.test_c008_slot_overrides import (
    _cleanup_fixture,
    _read_override_state,
    _relative_path,
    _reset_deleted_slot,
    _temp_files,
)
from tests.api.test_c008_slots import _create_fixture


def _decompression_bomb_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 20_000, 10_000, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def test_c008_override_decompression_bomb_is_validation_error_without_side_effects(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture())
    asyncio.run(_reset_deleted_slot(fixture))
    try:
        before = asyncio.run(_read_override_state(fixture))
        relative_path = Path(_relative_path(fixture, "png"))
        formal_path = tmp_path / relative_path
        trash_path = tmp_path / "trash" / relative_path
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.patch(
                f"/api/clips/{fixture['clip_id']}/slots/4",
                files={
                    "file": (
                        "hostile.png",
                        _decompression_bomb_png(),
                        "image/png",
                    )
                },
            )

        assert response.status_code == 422
        assert response.json() == {
            "detail": {
                "code": "validation_error",
                "message": "file is not a complete PNG, JPEG, or WebP image",
            }
        }
        assert asyncio.run(_read_override_state(fixture)) == before
        assert not formal_path.exists()
        assert not trash_path.exists()
        assert _temp_files(tmp_path) == []
    finally:
        asyncio.run(_cleanup_fixture(fixture))
