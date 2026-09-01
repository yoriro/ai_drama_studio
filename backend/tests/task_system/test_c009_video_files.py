from __future__ import annotations

import asyncio
import hashlib
import io
import math
from pathlib import Path
from types import SimpleNamespace

import av
import pytest

from app.services import video_files
from app.services.video_files import (
    cleanup_clip_video_temp,
    clip_video_paths,
    probe_clip_video_duration,
    sha256_file,
    validated_clip_media_move,
    write_clip_video,
)


def _video_bytes() -> bytes:
    output = io.BytesIO()
    container = av.open(output, mode="w", format="mp4")
    stream = container.add_stream("mpeg4", rate=24)
    stream.width = 16
    stream.height = 16
    stream.pix_fmt = "yuv420p"
    for _ in range(3):
        frame = av.VideoFrame(16, 16, "yuv420p")
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return output.getvalue()


def _audio_only_bytes() -> bytes:
    output = io.BytesIO()
    container = av.open(output, mode="w", format="mp4")
    stream = container.add_stream("aac", rate=48000)
    stream.layout = "mono"
    for _ in range(2):
        frame = av.AudioFrame(format="fltp", layout="mono", samples=1024)
        frame.sample_rate = 48000
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return output.getvalue()


async def _chunks(value: bytes):
    for start in range(0, len(value), 137):
        yield value[start : start + 137]


def test_video_temp_stream_probe_hash_and_cleanup_without_ffprobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _video_bytes()
    monkeypatch.setenv("PATH", "")

    temp_path = asyncio.run(
        write_clip_video(_chunks(raw), data_dir=tmp_path, task_id=77)
    )
    assert temp_path == tmp_path.resolve() / "tmp" / "clip-videos" / "77.mp4"
    assert temp_path.read_bytes() == raw
    assert probe_clip_video_duration(temp_path) == pytest.approx(0.125)
    assert sha256_file(temp_path) == hashlib.sha256(raw).hexdigest()

    cleanup_clip_video_temp(temp_path)
    assert not temp_path.exists()


def test_clip_video_paths_and_c008_media_move_validation_share_canonical_layout(
    tmp_path: Path,
) -> None:
    relative, formal, trash = clip_video_paths(tmp_path, 4, 5, 6, 7)
    assert relative.as_posix() == "projects/4/episodes/5/clips/6/7.mp4"
    assert formal == tmp_path.resolve() / relative
    assert trash == tmp_path.resolve() / "trash" / relative

    formal.parent.mkdir(parents=True)
    formal.write_bytes(b"video")
    assert validated_clip_media_move(
        tmp_path, relative.as_posix(), relative
    ) == (formal, trash)
    with pytest.raises(ValueError, match="canonical"):
        validated_clip_media_move(
            tmp_path, "projects/4/episodes/5/clips/6/7.avi", relative
        )

    missing_relative = relative.with_name("8.mp4")
    with pytest.raises(ValueError, match="does not exist"):
        validated_clip_media_move(
            tmp_path, missing_relative.as_posix(), missing_relative
        )


def test_stream_failure_removes_partial_clip_video_temp(
    tmp_path: Path,
) -> None:
    async def broken_chunks():
        yield b"partial"
        raise RuntimeError("stream failed")

    with pytest.raises(RuntimeError, match="stream failed"):
        asyncio.run(write_clip_video(broken_chunks(), data_dir=tmp_path, task_id=78))
    assert not (
        tmp_path.resolve() / "tmp" / "clip-videos" / "78.mp4"
    ).exists()


def test_probe_rejects_corrupt_and_audio_only_files(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"not an mp4")
    with pytest.raises(ValueError, match="container"):
        probe_clip_video_duration(corrupt)

    audio_only = tmp_path / "audio-only.mp4"
    audio_only.write_bytes(_audio_only_bytes())
    with pytest.raises(ValueError, match="video stream"):
        probe_clip_video_duration(audio_only)


@pytest.mark.parametrize(
    ("duration", "message"),
    [
        (None, "missing"),
        (0, "finite and positive"),
        (-1, "finite and positive"),
        (float("nan"), "finite and positive"),
        (float("inf"), "finite and positive"),
    ],
    ids=["missing", "zero", "negative", "nan", "infinite"],
)
def test_probe_rejects_missing_or_invalid_container_duration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    duration: object,
    message: str,
) -> None:
    class _FakeContainer:
        streams = [SimpleNamespace(type="video")]

        def __init__(self, value: object) -> None:
            self.duration = value

        def __enter__(self) -> "_FakeContainer":
            return self

        def __exit__(self, *args: object) -> None:
            del args

    monkeypatch.setattr(
        video_files.av,
        "open",
        lambda *args, **kwargs: _FakeContainer(duration),
    )
    with pytest.raises(ValueError, match=message):
        probe_clip_video_duration(tmp_path / "fake.mp4")


@pytest.mark.parametrize(
    ("project_id", "episode_id", "clip_id", "video_id"),
    [
        (0, 1, 1, 1),
        (1, 0, 1, 1),
        (1, 1, 0, 1),
        (1, 1, 1, 0),
    ],
)
def test_clip_video_paths_require_positive_identifiers(
    tmp_path: Path,
    project_id: int,
    episode_id: int,
    clip_id: int,
    video_id: int,
) -> None:
    with pytest.raises(ValueError, match="positive"):
        clip_video_paths(tmp_path, project_id, episode_id, clip_id, video_id)
