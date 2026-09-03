from __future__ import annotations

import hashlib
import multiprocessing
import os
from pathlib import Path
from typing import Any

import pytest

from app.core.config import settings
from app.tasks import gen_clip_video as video_task


def _restore_reference_file(
    target_path: str,
    content: bytes,
    read_event: Any,
    restored_event: Any,
) -> None:
    if not read_event.wait(15):
        raise TimeoutError("reference reader did not reach the race boundary")
    target = Path(target_path)
    replacement = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    replacement.write_bytes(content)
    os.replace(replacement, target)
    restored_event.set()


def _join_writer(process: multiprocessing.Process) -> None:
    process.join(timeout=15)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)
    exitcode = process.exitcode
    assert exitcode == 0, f"writer PID={process.pid} exitcode={exitcode}"


def test_c009_reference_media_upload_bytes_share_snapshot_hash_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    relative_path = Path("projects", "1", "assets", "1", "1.png")
    media_path = data_dir / relative_path
    media_path.parent.mkdir(parents=True)
    snapshot_bytes = b"reference-bytes-matching-snapshot"
    first_read_bytes = b"reference-bytes-read-before-atomic-restore"
    media_path.write_bytes(first_read_bytes)
    snapshot_digest = hashlib.sha256(snapshot_bytes).hexdigest()
    snapshot = {
        "references": [{"reference_name": "subject1"}],
        "reference_media": [
            {
                "file_path": relative_path.as_posix(),
                "extension": "png",
                "sha256": snapshot_digest,
            }
        ],
    }
    monkeypatch.setattr(settings, "DATA_DIR", data_dir)

    context = multiprocessing.get_context("spawn")
    read_event = context.Event()
    restored_event = context.Event()
    writer = context.Process(
        target=_restore_reference_file,
        args=(str(media_path), snapshot_bytes, read_event, restored_event),
    )
    writer.start()

    original_read_bytes = Path.read_bytes
    first_read_seen = False

    def gated_read_bytes(path: Path) -> bytes:
        nonlocal first_read_seen
        content = original_read_bytes(path)
        if not first_read_seen:
            first_read_seen = True
            read_event.set()
            if not restored_event.wait(15):
                raise TimeoutError("writer did not atomically restore reference A")
        return content

    try:
        with monkeypatch.context() as boundary_patch:
            boundary_patch.setattr(Path, "read_bytes", gated_read_bytes)
            with pytest.raises(ValueError) as error:
                video_task._reference_media(snapshot)
        assert str(error.value) == (
            "gen_clip_video reference_media[0] hash does not match"
        )
    finally:
        try:
            _join_writer(writer)
        finally:
            writer.close()

    assert original_read_bytes(media_path) == snapshot_bytes
    _, uploads = video_task._reference_media(snapshot)
    assert len(uploads) == 1
    assert hashlib.sha256(uploads[0][2]).hexdigest() == snapshot_digest
    assert uploads[0] == ("subject1.png", "png", snapshot_bytes)
