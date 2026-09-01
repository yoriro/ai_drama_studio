from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import engine
from app.main import app
from tests.api.test_c009_clip_videos import (
    _assert_base_item,
    _configure_app,
    _insert_video,
    _read_stored_snapshot,
)
from tests.api.test_c009_generate_video import (
    _cleanup_fixture,
    _create_fixture,
)


def test_c009_clip_video_seed_and_debug_payload_contract(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "DEBUG_PROMPTS", False)
    fixture = asyncio.run(_create_fixture(tmp_path))
    maximum_seed = 9_223_372_036_854_775_807
    try:
        first_id, _, first_bytes = asyncio.run(
            _insert_video(
                fixture,
                tmp_path,
                seed=maximum_seed,
                is_current=True,
            )
        )
        second_id, _, second_bytes = asyncio.run(
            _insert_video(fixture, tmp_path, seed=17, is_current=False)
        )
        _configure_app(monkeypatch)

        first_digest = hashlib.sha256(first_bytes).hexdigest()
        second_digest = hashlib.sha256(second_bytes).hexdigest()
        base_keys = {
            "id",
            "clip_id",
            "sha256",
            "seed",
            "requested_duration",
            "actual_duration",
            "is_current",
            "media_url",
            "created_at",
        }
        debug_keys = base_keys | {"built_prompt", "input_snapshot"}

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(f"/api/clips/{fixture['clip_id']}/videos")
            assert response.status_code == 200
            items = response.json()
            assert [item["id"] for item in items] == [first_id, second_id]
            assert set(items[0]) == base_keys
            assert set(items[1]) == base_keys
            _assert_base_item(items[0], seed=maximum_seed, digest=first_digest)
            _assert_base_item(items[1], seed=17, digest=second_digest)
            assert type(items[0]["seed"]) is str
            assert type(items[1]["seed"]) is str
            assert all(
                field not in response.text
                for field in (
                    "built_prompt",
                    "input_snapshot",
                    "file_path",
                    "input_hash",
                    "prompt",
                )
            )
            assert all(
                isinstance(item["created_at"], str)
                and datetime.fromisoformat(
                    item["created_at"].replace("Z", "+00:00")
                )
                for item in items
            )

            monkeypatch.setattr(settings, "DEBUG_PROMPTS", True)
            debug_response = client.get(
                f"/api/clips/{fixture['clip_id']}/videos"
            )
            assert debug_response.status_code == 200
            debug_items = debug_response.json()
            assert [item["id"] for item in debug_items] == [first_id, second_id]
            assert set(debug_items[0]) == debug_keys
            assert set(debug_items[1]) == debug_keys
            _assert_base_item(
                {key: debug_items[0][key] for key in base_keys},
                seed=maximum_seed,
                digest=first_digest,
            )
            _assert_base_item(
                {key: debug_items[1][key] for key in base_keys},
                seed=17,
                digest=second_digest,
            )
            assert debug_items[0]["built_prompt"] == (
                "built-9223372036854775807"
            )
            assert debug_items[1]["built_prompt"] == "built-17"
            assert debug_items[0]["input_snapshot"] == {
                "seed": "9223372036854775807",
                "marker": "snapshot-9223372036854775807",
            }
            assert debug_items[1]["input_snapshot"] == {
                "seed": "17",
                "marker": "snapshot-17",
            }
            assert type(debug_items[0]["seed"]) is str
            assert type(debug_items[0]["input_snapshot"]["seed"]) is str
            assert type(debug_items[1]["seed"]) is str
            assert type(debug_items[1]["input_snapshot"]["seed"]) is str

        first_snapshot = asyncio.run(_read_stored_snapshot(first_id))
        second_snapshot = asyncio.run(_read_stored_snapshot(second_id))
        if isinstance(first_snapshot, str):
            first_snapshot = json.loads(first_snapshot)
        if isinstance(second_snapshot, str):
            second_snapshot = json.loads(second_snapshot)
        assert first_snapshot == {
            "seed": maximum_seed,
            "marker": "snapshot-9223372036854775807",
        }
        assert second_snapshot == {"seed": 17, "marker": "snapshot-17"}
        assert type(first_snapshot["seed"]) is int
        assert type(second_snapshot["seed"]) is int
    finally:
        asyncio.run(_cleanup_fixture(fixture))
        asyncio.run(engine.dispose())
