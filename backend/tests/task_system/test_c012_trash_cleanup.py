from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from app.services import trash
from app.services.trash import cleanup_expired_trash, run_trash_cleanup_loop


def test_c012_trash_cleanup_deletes_strictly_older_and_preserves_other_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    trash_dir = data_dir / "trash" / "nested"
    trash_dir.mkdir(parents=True)
    outside = data_dir / "media" / "valid.mp4"
    outside.parent.mkdir()
    outside.write_bytes(b"outside-media")
    old = trash_dir / "old.bin"
    exact = trash_dir / "exact.bin"
    recent = trash_dir / "recent.bin"
    old.write_bytes(b"old")
    exact.write_bytes(b"exact")
    recent.write_bytes(b"recent")

    fixed_now = 10_000.0
    monkeypatch.setattr(trash.time, "time", lambda: fixed_now)
    os.utime(old, (fixed_now - 3_601, fixed_now - 3_601))
    os.utime(exact, (fixed_now - 3_600, fixed_now - 3_600))
    os.utime(recent, (fixed_now - 3_599, fixed_now - 3_599))

    cleanup_expired_trash(data_dir, retention_hours=1)

    assert not old.exists()
    assert exact.read_bytes() == b"exact"
    assert recent.read_bytes() == b"recent"
    assert outside.read_bytes() == b"outside-media"
    print(
        "C012 trash observations "
        f"old_deleted={not old.exists()} exact_bytes={exact.stat().st_size} "
        f"recent_bytes={recent.stat().st_size} outside_bytes={outside.stat().st_size}"
    )


def test_c012_trash_cleanup_surfaces_invalid_root(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "trash").write_bytes(b"not-a-directory")

    with pytest.raises(NotADirectoryError):
        cleanup_expired_trash(data_dir, retention_hours=1)

    print("C012 trash failure observation invalid_root=NotADirectoryError")


def test_c012_trash_cleanup_loop_runs_production_path_before_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    trash_dir = data_dir / "trash"
    trash_dir.mkdir(parents=True)
    expired = trash_dir / "expired.bin"
    expired.write_bytes(b"expired")
    now = time.time()
    os.utime(expired, (now - 7_201, now - 7_201))
    sleeps = 0

    async def controlled_sleep(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 1:
            return
        raise asyncio.CancelledError

    monkeypatch.setattr(trash.asyncio, "sleep", controlled_sleep)

    async def run() -> None:
        with pytest.raises(asyncio.CancelledError):
            await run_trash_cleanup_loop(data_dir, retention_hours=1)

    asyncio.run(run())
    assert sleeps == 2
    assert not expired.exists()
    print(
        "C012 scheduled trash observations "
        f"cleanup_calls={sleeps - 1} expired_deleted={not expired.exists()} "
        "shutdown=CancelledError"
    )
