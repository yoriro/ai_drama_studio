from __future__ import annotations

import math
from collections.abc import AsyncIterable
from pathlib import Path

import av

from app.services.asset_files import resolve_data_path, sha256_file


def clip_video_relative_path(
    project_id: int, episode_id: int, clip_id: int, video_id: int
) -> Path:
    if min(project_id, episode_id, clip_id, video_id) <= 0:
        raise ValueError("clip video identifiers must be positive")
    return Path(
        "projects",
        str(project_id),
        "episodes",
        str(episode_id),
        "clips",
        str(clip_id),
        f"{video_id}.mp4",
    )


def clip_video_paths(
    data_dir: Path,
    project_id: int,
    episode_id: int,
    clip_id: int,
    video_id: int,
) -> tuple[Path, Path, Path]:
    relative_path = clip_video_relative_path(
        project_id, episode_id, clip_id, video_id
    )
    formal_path = resolve_data_path(data_dir, relative_path)
    trash_path = resolve_data_path(data_dir, Path("trash") / relative_path)
    return relative_path, formal_path, trash_path


def validated_clip_media_move(
    data_dir: Path,
    relative_path_value: str,
    expected_relative_path: Path,
) -> tuple[Path, Path]:
    relative_path = Path(relative_path_value)
    if relative_path.as_posix() != expected_relative_path.as_posix():
        raise ValueError("clip media path does not match its canonical path")
    formal_path = resolve_data_path(data_dir, relative_path)
    if not formal_path.is_file():
        raise ValueError("clip media file does not exist")
    trash_path = resolve_data_path(data_dir, Path("trash") / relative_path)
    return formal_path, trash_path


def temporary_clip_video_path(data_dir: Path, task_id: int) -> Path:
    if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id <= 0:
        raise ValueError("clip video task id must be positive")
    return data_dir.resolve() / "tmp" / "clip-videos" / f"{task_id}.mp4"


async def write_clip_video(
    chunks: AsyncIterable[bytes], *, data_dir: Path, task_id: int
) -> Path:
    temp_path = temporary_clip_video_path(data_dir, task_id)
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    completed = False
    try:
        with temp_path.open("wb") as file_handle:
            async for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise TypeError("clip video stream must yield bytes")
                file_handle.write(chunk)
        completed = True
        return temp_path
    finally:
        if not completed and temp_path.exists():
            temp_path.unlink()


def cleanup_clip_video_temp(temp_path: Path) -> None:
    if temp_path.exists():
        temp_path.unlink()


def probe_clip_video_duration(video_path: Path) -> float:
    try:
        with av.open(str(video_path), mode="r") as container:
            has_video_stream = any(
                stream.type == "video" for stream in container.streams
            )
            duration = container.duration
    except (av.error.FFmpegError, OSError, ValueError) as exc:
        raise ValueError("clip video container cannot be parsed") from exc
    if not has_video_stream:
        raise ValueError("clip video must contain a video stream")
    if duration is None:
        raise ValueError("clip video container duration is missing")
    seconds = float(duration) / float(av.time_base)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("clip video container duration must be finite and positive")
    return seconds
