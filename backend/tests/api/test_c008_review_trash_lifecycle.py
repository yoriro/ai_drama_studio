from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from tests.api.test_c008_slot_overrides import (
    _cleanup_fixture,
    _image_bytes,
    _read_override_state,
    _relative_path,
    _reset_deleted_slot,
    _temp_files,
    _upload,
)
from tests.api.test_c008_slots import _create_fixture


async def _clip_slot_counts(fixture: dict[str, object]) -> tuple[int, int]:
    import os

    import asyncpg

    connection = await asyncpg.connect(
        os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)
    )
    try:
        return (
            int(
                await connection.fetchval(
                    "SELECT count(*) FROM clips WHERE id = $1",
                    fixture["clip_id"],
                )
            ),
            int(
                await connection.fetchval(
                    "SELECT count(*) FROM clip_ref_slots WHERE id = $1",
                    fixture["slot_ids"]["deleted"],
                )
            ),
        )
    finally:
        await connection.close()


def _stored_files(data_dir: Path) -> list[str]:
    return sorted(
        path.relative_to(data_dir).as_posix()
        for path in data_dir.rglob("*")
        if path.is_file()
    )


def _assert_latest_trash(
    data_dir: Path, relative_path: Path, expected_bytes: bytes
) -> None:
    formal_path = data_dir / relative_path
    trash_path = data_dir / "trash" / relative_path
    assert not formal_path.exists()
    assert trash_path.read_bytes() == expected_bytes
    assert _stored_files(data_dir) == [
        (Path("trash") / relative_path).as_posix()
    ]


def test_c008_same_format_replacement_then_clear_overwrites_canonical_trash(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture())
    asyncio.run(_reset_deleted_slot(fixture))
    try:
        first_bytes = _image_bytes("PNG", (255, 0, 0))
        second_bytes = _image_bytes("PNG", (0, 255, 0))
        relative_path = Path(_relative_path(fixture, "png"))
        with TestClient(app) as client:
            first = _upload(client, fixture, first_bytes, "image/png")
            assert first.status_code == 200
            second = _upload(client, fixture, second_bytes, "image/png")
            assert second.status_code == 200

            formal_path = tmp_path / relative_path
            trash_path = tmp_path / "trash" / relative_path
            assert formal_path.read_bytes() == second_bytes
            assert trash_path.read_bytes() == first_bytes
            assert asyncio.run(_read_override_state(fixture))[0] == relative_path.as_posix()

            cleared = client.patch(
                f"/api/clips/{fixture['clip_id']}/slots/4",
                files={"clear_override": (None, "true")},
            )
            assert cleared.status_code == 200
            assert cleared.json()["slot"]["image_source"] is None
            assert cleared.json()["slot"]["image_url"] is None

        assert asyncio.run(_read_override_state(fixture)) == (
            None,
            None,
            4,
            "stale",
            "empty",
        )
        _assert_latest_trash(tmp_path, relative_path, second_bytes)
        assert _temp_files(tmp_path) == []
    finally:
        asyncio.run(_cleanup_fixture(fixture))


def test_c008_same_format_replacement_then_clip_delete_overwrites_canonical_trash(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture())
    asyncio.run(_reset_deleted_slot(fixture))
    try:
        first_bytes = _image_bytes("PNG", (255, 0, 0))
        second_bytes = _image_bytes("PNG", (0, 255, 0))
        relative_path = Path(_relative_path(fixture, "png"))
        with TestClient(app) as client:
            first = _upload(client, fixture, first_bytes, "image/png")
            assert first.status_code == 200
            second = _upload(client, fixture, second_bytes, "image/png")
            assert second.status_code == 200
            assert (tmp_path / "trash" / relative_path).read_bytes() == first_bytes

            deleted = client.delete(f"/api/clips/{fixture['clip_id']}")
            assert deleted.status_code == 204
            assert deleted.content == b""

        assert asyncio.run(_clip_slot_counts(fixture)) == (0, 0)
        _assert_latest_trash(tmp_path, relative_path, second_bytes)
        assert _temp_files(tmp_path) == []
    finally:
        asyncio.run(_cleanup_fixture(fixture))
