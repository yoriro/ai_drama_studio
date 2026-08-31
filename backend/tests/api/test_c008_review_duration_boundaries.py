from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from tests.api.test_c008_clip_create import _cleanup_fixture, _create_fixture


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _read_state(
    clip_id: int, shot_ids: list[int]
) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        clip = await connection.fetchrow(
            """
            SELECT requested_duration, revision, freshness
            FROM clips
            WHERE id = $1
            """,
            clip_id,
        )
        shots = await connection.fetch(
            """
            SELECT id, status, revision
            FROM shots
            WHERE id = ANY($1::int[])
            ORDER BY id
            """,
            shot_ids,
        )
        slots = await connection.fetch(
            """
            SELECT slot_no, asset_id, asset_name_snapshot, asset_type_snapshot,
                   enabled, override_image_path, override_sha256
            FROM clip_ref_slots
            WHERE clip_id = $1
            ORDER BY slot_no
            """,
            clip_id,
        )
        return {
            "clip": None if clip is None else dict(clip),
            "shots": [dict(row) for row in shots],
            "slots": [dict(row) for row in slots],
        }
    finally:
        await connection.close()


def _files(data_dir: Path) -> list[str]:
    return sorted(
        path.relative_to(data_dir).as_posix()
        for path in data_dir.rglob("*")
        if path.is_file()
    )


def test_c008_patch_accepts_exact_min_and_max_without_other_mutations(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    fixture = asyncio.run(_create_fixture())
    try:
        assert settings.CLIP_MIN_SECONDS < settings.CLIP_MAX_SECONDS
        with TestClient(app) as client:
            created = client.post(
                f"/api/episodes/{fixture['episode_id']}/clips",
                json={
                    "shot_ids": [
                        fixture["shots"]["first"],
                        fixture["shots"]["second"],
                    ],
                    "reference_asset_ids": [
                        fixture["assets"]["character_first"]
                    ],
                    "requested_duration": 8,
                },
            )
            assert created.status_code == 201
            clip_id = created.json()["id"]
            baseline = asyncio.run(
                _read_state(clip_id, [fixture["shots"]["first"], fixture["shots"]["second"]])
            )
            baseline_files = _files(tmp_path)

            minimum = client.patch(
                f"/api/clips/{clip_id}",
                json={"requested_duration": settings.CLIP_MIN_SECONDS},
            )
            assert minimum.status_code == 200
            assert minimum.json()["requested_duration"] == settings.CLIP_MIN_SECONDS
            assert minimum.json()["revision"] == 2
            assert minimum.json()["freshness"] == "stale"
            after_minimum = asyncio.run(
                _read_state(clip_id, [fixture["shots"]["first"], fixture["shots"]["second"]])
            )
            assert after_minimum["clip"] == {
                "requested_duration": settings.CLIP_MIN_SECONDS,
                "revision": 2,
                "freshness": "stale",
            }
            assert after_minimum["shots"] == baseline["shots"]
            assert after_minimum["slots"] == baseline["slots"]
            assert _files(tmp_path) == baseline_files

            maximum = client.patch(
                f"/api/clips/{clip_id}",
                json={"requested_duration": settings.CLIP_MAX_SECONDS},
            )
            assert maximum.status_code == 200
            assert maximum.json()["requested_duration"] == settings.CLIP_MAX_SECONDS
            assert maximum.json()["revision"] == 3
            assert maximum.json()["freshness"] == "stale"
            after_maximum = asyncio.run(
                _read_state(clip_id, [fixture["shots"]["first"], fixture["shots"]["second"]])
            )
            assert after_maximum["clip"] == {
                "requested_duration": settings.CLIP_MAX_SECONDS,
                "revision": 3,
                "freshness": "stale",
            }
            assert after_maximum["shots"] == baseline["shots"]
            assert after_maximum["slots"] == baseline["slots"]
            assert _files(tmp_path) == baseline_files
    finally:
        asyncio.run(_cleanup_fixture(fixture))
