"""C012 B6: L4/L5 editing-operation lock-pair coverage.

The existing ``test_c012_lock_order.py`` covers the L4 structural operation
against video commit and the L5 replacement against a shot edit.  This module
lists every remaining §2.1 pair explicitly and exercises each pair in both
directions.  Each concurrent run is compared with a fresh fixture that ran
the same two operations serially in the same order.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import engine
from app.schemas.assets import AssetPatch
from app.schemas.clips import ClipCreateRequest, ClipSlotEnabledPatch
from app.schemas.shots import ShotPatch
from app.services.assets import update_asset
from app.services.clips import (
    create_clip,
    delete_clip,
    update_clip_slot_enabled,
)
from app.services.gen_shots import GeneratedShot, GeneratedShotsResponse
from app.services.shots import update_shot
from app.services.video_files import clip_video_paths
from app.tasks.gen_shots import _replace_episode
from app.tasks.queue import ClaimedTask, TaskQueue
from tests.api.test_c009_generate_video import (
    _cleanup_fixture as _cleanup_base_fixture,
    _create_fixture as _create_base_fixture,
)
from tests.task_system.test_c012_lock_order import (
    _cleanup_l5_fixture,
)


@dataclass(frozen=True)
class _Pair:
    layer: str
    structural: str
    edit: str
    existing_node: str


# §2.1 operation inventory.  The existing node is named for auditability; all
# rows below are the B6 gaps that this file closes.
PAIR_MATRIX = (
    _Pair(
        "L4",
        "create",
        "asset",
        "test_c012_lock_order.py::test_c012_lock_order[L4]",
    ),
    _Pair(
        "L4",
        "create",
        "shot",
        "test_c012_lock_order.py::test_c012_lock_order[L4]",
    ),
    _Pair(
        "L4",
        "slot",
        "asset",
        "test_c012_lock_order.py::test_c012_lock_order[L4]",
    ),
    _Pair(
        "L4",
        "slot",
        "shot",
        "test_c012_lock_order.py::test_c012_lock_order[L4]",
    ),
    _Pair(
        "L4",
        "delete",
        "asset",
        "test_c012_lock_order.py::test_c012_lock_order[L4]",
    ),
    _Pair(
        "L4",
        "delete",
        "shot",
        "test_c012_lock_order.py::test_c012_lock_order[L4]",
    ),
    _Pair(
        "L5",
        "replace",
        "asset",
        "test_c012_lock_order.py::test_c012_lock_order[L5]",
    ),
    _Pair(
        "L5",
        "replace",
        "shot",
        "test_c012_lock_order.py::test_c012_lock_order[L5]",
    ),
    _Pair(
        "L5",
        "replace",
        "create",
        "test_c012_lock_order.py::test_c012_lock_order[L5]",
    ),
    _Pair(
        "L5",
        "replace",
        "slot",
        "test_c012_lock_order.py::test_c012_lock_order[L5]",
    ),
    _Pair(
        "L5",
        "replace",
        "delete",
        "test_c012_lock_order.py::test_c012_lock_order[L5]",
    ),
)

_ALLOWED_OPERATION_ERRORS = (HTTPException, ValueError)


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


async def _open_operation_connection(label: str):
    if len(label) > 63:
        raise AssertionError(f"PostgreSQL application_name is too long: {label}")
    connection = await engine.connect()
    connection.sync_connection.info["c012_operation"] = label
    await connection.execute(
        text("SELECT set_config('application_name', :value, false)"),
        {"value": label},
    )
    await connection.execute(text("SET lock_timeout = '10s'"))
    await connection.commit()
    return connection


async def _read_lock_snapshot(prefix: str) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        activity = await connection.fetch(
            """
            SELECT pid, application_name, state, wait_event_type, wait_event,
                   pg_blocking_pids(pid) AS blockers, query
            FROM pg_stat_activity
            WHERE application_name LIKE $1
            ORDER BY pid
            """,
            f"{prefix}%",
        )
        pids = [int(row["pid"]) for row in activity]
        locks = []
        if pids:
            locks = await connection.fetch(
                """
                SELECT l.pid, n.nspname, c.relname, l.mode, l.granted
                FROM pg_locks AS l
                LEFT JOIN pg_class AS c ON c.oid = l.relation
                LEFT JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE l.pid = ANY($1::int[])
                ORDER BY l.pid, c.relname NULLS FIRST, l.mode
                """,
                pids,
            )
        return {
            "activity": [dict(row) for row in activity],
            "locks": [dict(row) for row in locks],
        }
    finally:
        await connection.close()


async def _wait_for_real_lock(
    prefix: str, label: str, allowed_blocker_pids: set[int]
) -> dict[str, object]:
    for _ in range(250):
        snapshot = await _read_lock_snapshot(prefix)
        for row in snapshot["activity"]:
            if row["application_name"] != label:
                continue
            if row["state"] != "active" or row["wait_event_type"] != "Lock":
                continue
            blockers = [int(pid) for pid in row["blockers"]]
            assert set(blockers) & allowed_blocker_pids, {
                "label": label,
                "allowed_blocker_pids": sorted(allowed_blocker_pids),
                "row": row,
                "snapshot": snapshot,
            }
            assert "for update" in str(row["query"]).lower(), row
            return snapshot
        await asyncio.sleep(0.02)
    snapshot = await _read_lock_snapshot(prefix)
    raise AssertionError(
        f"{label} did not reach a real FOR UPDATE lock wait: "
        f"{json.dumps(snapshot, ensure_ascii=False, default=str)}"
    )


def _waiting_pid(snapshot: dict[str, object], label: str) -> int:
    for row in snapshot["activity"]:
        if (
            row["application_name"] == label
            and row["state"] == "active"
            and row["wait_event_type"] == "Lock"
        ):
            return int(row["pid"])
    raise AssertionError(f"missing waiting operation pid for {label}: {snapshot}")


async def _open_clip_gate(
    fixture: dict[str, object], prefix: str
) -> tuple[asyncpg.Connection, int]:
    gate = await asyncpg.connect(
        _database_url(),
        server_settings={"application_name": f"{prefix}gate"},
    )
    await gate.execute("BEGIN")
    gate_pid = int(await gate.fetchval("SELECT pg_backend_pid()"))
    await gate.fetchval(
        "SELECT id FROM clips WHERE id = $1 FOR UPDATE", fixture["clip_id"]
    )
    return gate, gate_pid


async def _prepare_replacement_task(
    fixture: dict[str, object], data_dir: Path
) -> ClaimedTask:
    connection = await asyncpg.connect(_database_url())
    try:
        video_id = await connection.fetchval(
            """
            INSERT INTO clip_videos
                (clip_id, file_path, sha256, seed, requested_duration,
                 actual_duration, is_current, built_prompt, input_hash)
            VALUES ($1, 'pending', $2, 1, 5, 2.0, true,
                    'C012 L5 source', 'c012-l5')
            RETURNING id
            """,
            fixture["clip_id"],
            "0" * 64,
        )
        assert video_id is not None
        relative_path, formal_path, _trash_path = clip_video_paths(
            data_dir,
            int(fixture["project_id"]),
            int(fixture["episode_id"]),
            int(fixture["clip_id"]),
            int(video_id),
        )
        await connection.execute(
            "UPDATE clip_videos SET file_path = $1 WHERE id = $2",
            relative_path.as_posix(),
            video_id,
        )
        override_id = int(fixture["slot_ids"]["deleted"])
        payload = {
            "input_snapshot": {
                "episode_id": fixture["episode_id"],
                "project_id": fixture["project_id"],
                "script_revision": 2,
                "replacement_snapshot": {
                    "shots": [
                        {"id": shot_id, "revision": 1}
                        for shot_id in sorted(fixture["shot_ids"])
                    ],
                    "clips": [{"id": fixture["clip_id"], "revision": 1}],
                    "clip_video_ids": [int(video_id)],
                    "clip_media": [
                        {
                            "kind": "clip_video",
                            "id": int(video_id),
                            "path": relative_path.as_posix(),
                        },
                        {
                            "kind": "slot_override",
                            "id": override_id,
                            "path": fixture["override_relative_path"],
                        },
                    ],
                },
            },
            "input_hash": None,
            "source_revisions": {},
        }
        task_id = await connection.fetchval(
            """
            INSERT INTO tasks (type, target_id, payload, status, progress)
            VALUES ('gen_shots', $1, $2::jsonb, 'running', 0.2)
            RETURNING id
            """,
            fixture["episode_id"],
            json.dumps(payload),
        )
        assert task_id is not None
    finally:
        await connection.close()

    formal_path.parent.mkdir(parents=True, exist_ok=True)
    formal_path.write_bytes(b"c012-l5-source-media")
    fixture["video_id"] = int(video_id)
    fixture["video_path"] = relative_path.as_posix()
    fixture["gen_shots_task_id"] = int(task_id)
    return ClaimedTask(
        id=int(task_id),
        type="gen_shots",
        target_id=int(fixture["episode_id"]),
        request_id=None,
        payload=payload,
    )


def _replacement_output(fixture: dict[str, object]) -> GeneratedShotsResponse:
    return GeneratedShotsResponse(
        shots=[
            GeneratedShot(
                order=1,
                duration_est=2.0,
                shot_type="中景",
                camera="固定",
                description="C012 L5 replacement shot",
                dialogue="",
                asset_ids=[int(fixture["character_id"])],
            )
        ]
    )


async def _run_operation(
    fixture: dict[str, object],
    data_dir: Path,
    operation: str,
    label: str,
    replacement_task: ClaimedTask | None,
) -> object:
    connection = await _open_operation_connection(label)
    try:
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            if operation == "asset":
                return await update_asset(
                    session,
                    int(fixture["character_id"]),
                    AssetPatch(description="C012 pair asset edit"),
                )
            if operation == "shot":
                return await update_shot(
                    session,
                    int(fixture["shot_ids"][0]),
                    ShotPatch(description="C012 pair shot edit"),
                )
            if operation == "create":
                return await create_clip(
                    session,
                    int(fixture["episode_id"]),
                    ClipCreateRequest(
                        shot_ids=list(fixture["shot_ids"]),
                        reference_asset_ids=[int(fixture["character_id"])],
                        requested_duration=5,
                    ),
                )
            if operation == "slot":
                return await update_clip_slot_enabled(
                    session,
                    int(fixture["clip_id"]),
                    1,
                    ClipSlotEnabledPatch(enabled=False),
                )
            if operation == "delete":
                return await delete_clip(session, int(fixture["clip_id"]))
            if operation == "replace":
                if replacement_task is None:
                    raise AssertionError("replace operation has no task")
                moved: list[object] = []
                async with session.begin():
                    return await _replace_episode(
                        session,
                        TaskQueue(),
                        replacement_task,
                        _replacement_output(fixture),
                        moved,
                    )
    finally:
        await connection.close()
    raise AssertionError(f"unknown C012 operation: {operation}")


def _asset_role(fixture: dict[str, object], asset_id: int) -> str:
    if asset_id == int(fixture["character_id"]):
        return "character"
    if asset_id == int(fixture["scene_id"]):
        return "scene"
    return f"unknown:{asset_id}"


async def _read_state(
    fixture: dict[str, object], data_dir: Path
) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        asset_rows = await connection.fetch(
            """
            SELECT id, type, name, description, revision
            FROM assets WHERE id = ANY($1::int[]) ORDER BY id
            """,
            [fixture["character_id"], fixture["scene_id"]],
        )
        assets_by_id = {int(row["id"]): row for row in asset_rows}
        assets: list[dict[str, object]] = []
        for asset_id, role in (
            (int(fixture["character_id"]), "character"),
            (int(fixture["scene_id"]), "scene"),
        ):
            row = assets_by_id.get(asset_id)
            assets.append(
                {
                    "role": role,
                    "exists": row is not None,
                    "type": None if row is None else row["type"],
                    "name": None if row is None else row["name"],
                    "description": None if row is None else row["description"],
                    "revision": None if row is None else row["revision"],
                }
            )

        shot_rows = await connection.fetch(
            """
            SELECT id, order_index, revision, status, description
            FROM shots WHERE episode_id = $1 ORDER BY order_index, id
            """,
            fixture["episode_id"],
        )
        shot_order_by_id = {
            int(row["id"]): int(row["order_index"]) for row in shot_rows
        }
        shot_asset_rows = await connection.fetch(
            """
            SELECT sa.shot_id, sa.asset_id
            FROM shot_assets AS sa
            JOIN shots AS s ON s.id = sa.shot_id
            WHERE s.episode_id = $1
            ORDER BY sa.shot_id, sa.asset_id
            """,
            fixture["episode_id"],
        )
        shot_assets: dict[int, list[str]] = {}
        for row in shot_asset_rows:
            shot_assets.setdefault(int(row["shot_id"]), []).append(
                _asset_role(fixture, int(row["asset_id"]))
            )
        shots = [
            {
                "order": int(row["order_index"]),
                "revision": int(row["revision"]),
                "status": row["status"],
                "description": row["description"],
                "asset_roles": sorted(shot_assets.get(int(row["id"]), [])),
            }
            for row in shot_rows
        ]

        clip_rows = await connection.fetch(
            """
            SELECT id, revision, freshness
            FROM clips WHERE episode_id = $1 ORDER BY id
            """,
            fixture["episode_id"],
        )
        clip_role_by_id = {
            int(row["id"]): (
                "old" if int(row["id"]) == int(fixture["clip_id"]) else "new"
            )
            for row in clip_rows
        }
        clip_shot_rows = await connection.fetch(
            """
            SELECT cs.clip_id, cs.shot_id
            FROM clip_shots AS cs
            JOIN clips AS c ON c.id = cs.clip_id
            WHERE c.episode_id = $1
            ORDER BY cs.clip_id, cs.position, cs.shot_id
            """,
            fixture["episode_id"],
        )
        clip_shots: dict[int, list[object]] = {}
        for row in clip_shot_rows:
            shot_id = int(row["shot_id"])
            clip_shots.setdefault(int(row["clip_id"]), []).append(
                shot_order_by_id.get(shot_id, f"unknown:{shot_id}")
            )
        clips = [
            {
                "role": clip_role_by_id[int(row["id"])],
                "revision": int(row["revision"]),
                "freshness": row["freshness"],
                "shot_orders": clip_shots.get(int(row["id"]), []),
            }
            for row in clip_rows
        ]

        slot_rows = await connection.fetch(
            """
            SELECT clip_id, slot_no, asset_id, asset_name_snapshot,
                   asset_type_snapshot, enabled, override_image_path
            FROM clip_ref_slots
            WHERE clip_id IN (SELECT id FROM clips WHERE episode_id = $1)
            ORDER BY clip_id, slot_no, id
            """,
            fixture["episode_id"],
        )
        slots = [
            {
                "clip_role": clip_role_by_id[int(row["clip_id"])],
                "slot_no": int(row["slot_no"]),
                "asset_role": (
                    None
                    if row["asset_id"] is None
                    else _asset_role(fixture, int(row["asset_id"]))
                ),
                "asset_name_snapshot": row["asset_name_snapshot"],
                "asset_type_snapshot": row["asset_type_snapshot"],
                "enabled": bool(row["enabled"]),
                "has_override": row["override_image_path"] is not None,
            }
            for row in slot_rows
        ]

        video_rows = await connection.fetch(
            """
            SELECT cv.id, cv.clip_id, cv.file_path
            FROM clip_videos AS cv
            JOIN clips AS c ON c.id = cv.clip_id
            WHERE c.episode_id = $1 ORDER BY cv.id
            """,
            fixture["episode_id"],
        )
        videos = [
            {
                "clip_role": clip_role_by_id[int(row["clip_id"])],
                "file_role": "replacement_source"
                if "video_path" in fixture
                and row["file_path"] == fixture["video_path"]
                else "other",
            }
            for row in video_rows
        ]

        episode_marker = await connection.fetchval(
            "SELECT shots_generated_script_revision FROM episodes WHERE id = $1",
            fixture["episode_id"],
        )
        task_rows = await connection.fetch(
            """
            SELECT status, error_msg FROM tasks
            WHERE target_id = $1 AND type = 'gen_shots' ORDER BY id
            """,
            fixture["episode_id"],
        )
    finally:
        await connection.close()

    relative_paths: dict[str, str | None] = {
        "image": str(fixture["image_relative_path"]),
        "override": str(fixture["override_relative_path"]),
        "video": (
            str(fixture["video_path"]) if "video_path" in fixture else None
        ),
    }
    files: dict[str, object] = {}
    for name, relative_path in relative_paths.items():
        if relative_path is None:
            files[name] = None
            continue
        formal_path = data_dir / relative_path
        trash_path = data_dir / "trash" / relative_path
        files[name] = {
            "formal_exists": formal_path.is_file(),
            "formal_bytes": (
                formal_path.read_bytes() if formal_path.is_file() else None
            ),
            "trash_exists": trash_path.is_file(),
            "trash_bytes": (
                trash_path.read_bytes() if trash_path.is_file() else None
            ),
        }

    return {
        "marker": None if episode_marker is None else int(episode_marker),
        "assets": assets,
        "shots": shots,
        "clips": clips,
        "clip_shots": [
            {
                "clip_role": clip_role_by_id[int(row["clip_id"])],
                "shot_order": shot_order_by_id.get(
                    int(row["shot_id"]), f"unknown:{row['shot_id']}"
                ),
            }
            for row in clip_shot_rows
        ],
        "slots": slots,
        "videos": videos,
        "tasks": [dict(row) for row in task_rows],
        "files": files,
    }


def _display_state(state: dict[str, object]) -> dict[str, object]:
    def shorten(value: object) -> object:
        if isinstance(value, bytes):
            return {"length": len(value), "repr": repr(value)}
        if isinstance(value, dict):
            return {key: shorten(item) for key, item in value.items()}
        if isinstance(value, list):
            return [shorten(item) for item in value]
        return value

    return shorten(state)  # type: ignore[return-value]


def _result_signature(
    operation: str, result: object, fixture: dict[str, object]
) -> tuple[object, ...]:
    if isinstance(result, HTTPException):
        detail = str(result.detail)
        fixture_ids = [
            int(fixture["project_id"]),
            int(fixture["episode_id"]),
            int(fixture["character_id"]),
            int(fixture["scene_id"]),
            int(fixture["clip_id"]),
            *(int(shot_id) for shot_id in fixture["shot_ids"]),
            *(
                int(slot_id)
                for slot_id in fixture.get("slot_ids", {}).values()
            ),
        ]
        for fixture_id in sorted(set(fixture_ids), reverse=True):
            detail = re.sub(rf"\b{fixture_id}\b", "<id>", detail)
        return ("http", int(result.status_code), detail)
    if isinstance(result, ValueError):
        return ("value_error", str(result))
    if isinstance(result, BaseException):
        return ("unexpected_error", type(result).__name__, str(result))
    if operation == "asset":
        assert hasattr(result, "revision")
        return (
            "asset",
            int(result.revision),
            str(result.description),
        )
    if operation == "shot":
        assert isinstance(result, dict)
        return (
            "shot",
            int(result["revision"]),
            str(result["status"]),
            str(result["description"]),
            tuple(
                sorted(
                    _asset_role(fixture, int(asset_id))
                    for asset_id in result["asset_ids"]
                )
            ),
        )
    if operation == "slot":
        assert isinstance(result, dict)
        slot = result["slot"]
        return ("slot", int(slot["slot_no"]), bool(slot["enabled"]))
    if operation == "create":
        assert isinstance(result, dict)
        return ("create", int(result["id"]), tuple(result["shot_ids"]))
    return ("success",)


def _assert_no_unexpected_results(
    operations: tuple[str, str], results: list[object], context: str
) -> None:
    unexpected = [
        f"{operation}: {type(result).__name__}: {result}"
        for operation, result in zip(operations, results)
        if isinstance(result, BaseException)
        and not isinstance(result, _ALLOWED_OPERATION_ERRORS)
    ]
    assert not unexpected, f"{context}: {unexpected}"


def _result_for(
    operation: str, operations: tuple[str, str], results: list[object]
) -> object:
    return results[operations.index(operation)]


def _assert_l4_semantics(
    structural: str,
    edit: str,
    operations: tuple[str, str],
    results: list[object],
    state: dict[str, object],
) -> None:
    structural_result = _result_for(structural, operations, results)
    edit_result = _result_for(edit, operations, results)
    assert not isinstance(edit_result, BaseException), (edit, edit_result, state)

    if structural == "create":
        assert isinstance(structural_result, HTTPException)
        assert structural_result.status_code == 422
        assert len(state["clips"]) == 1
        assert state["clip_shots"] == [
            {"clip_role": "old", "shot_order": 1},
            {"clip_role": "old", "shot_order": 2},
        ]
        assert state["slots"]
        assert state["videos"] == []
    elif structural == "slot":
        assert not isinstance(structural_result, BaseException)
        assert state["clips"] == [
            {
                "role": "old",
                "revision": 2,
                "freshness": "stale",
                "shot_orders": [1, 2],
            }
        ]
        current_slot = next(
            slot for slot in state["slots"] if slot["slot_no"] == 1
        )
        assert current_slot["enabled"] is False
    else:
        assert structural == "delete"
        assert not isinstance(structural_result, BaseException)
        assert state["clips"] == []
        assert state["clip_shots"] == []
        assert state["slots"] == []
        assert state["videos"] == []
        assert len(state["shots"]) == 2
        assert state["files"]["override"]["formal_exists"] is False
        assert state["files"]["override"]["trash_exists"] is True

    character = next(asset for asset in state["assets"] if asset["role"] == "character")
    if edit == "asset":
        assert character["revision"] == 2
        assert character["description"] == "C012 pair asset edit"
    else:
        assert character["revision"] == 1
        assert character["description"] == "黑发白衬衫"
    assert state["files"]["image"]["formal_exists"] is True
    assert state["files"]["image"]["formal_bytes"] == b"c009-t9-current-image"
    if edit == "shot":
        first_shot = next(shot for shot in state["shots"] if shot["order"] == 1)
        assert first_shot["revision"] == 2
        assert first_shot["status"] == "changed"
        assert first_shot["description"] == "C012 pair shot edit"
    else:
        assert edit == "asset"


def _assert_l5_semantics(
    first: str,
    second: str,
    operations: tuple[str, str],
    results: list[object],
    state: dict[str, object],
) -> None:
    _assert_no_unexpected_results(operations, results, "L5")
    replace_result = _result_for("replace", operations, results)
    other = second if first == "replace" else first
    other_result = _result_for(other, operations, results)

    if first == "replace" or first == "create":
        assert not isinstance(replace_result, BaseException), (
            first,
            second,
            replace_result,
            state,
        )
        assert state["marker"] == 2
        replacement_revision = 2 if other == "asset" else 1
        replacement_status = "changed" if other == "asset" else "normal"
        assert state["shots"] == [
            {
                "order": 1,
                "revision": replacement_revision,
                "status": replacement_status,
                "description": "C012 L5 replacement shot",
                "asset_roles": ["character"],
            }
        ]
        assert state["clips"] == []
        assert state["clip_shots"] == []
        assert state["slots"] == []
        assert state["videos"] == []
        assert state["files"]["video"]["formal_exists"] is False
        assert state["files"]["video"]["trash_exists"] is True
        assert state["files"]["video"]["trash_bytes"] == b"c012-l5-source-media"
        assert state["files"]["override"]["formal_exists"] is False
        assert state["files"]["override"]["trash_exists"] is True
        assert state["files"]["override"]["trash_bytes"] == b"c009-t9-override-image"
        assert state["files"]["image"]["formal_bytes"] == b"c009-t9-current-image"
        if other == "asset":
            assert not isinstance(other_result, BaseException)
            character = next(
                asset for asset in state["assets"] if asset["role"] == "character"
            )
            assert character["revision"] == 2
            assert character["description"] == "C012 pair asset edit"
        else:
            expected_status = 422 if other == "create" else 404
            assert other in {"create", "shot", "slot", "delete"}
            assert isinstance(other_result, HTTPException)
            assert other_result.status_code == expected_status
        assert state["tasks"] == [{"status": "done", "error_msg": None}]
        return

    assert first in {"asset", "shot", "slot", "delete"}
    assert not isinstance(other_result, BaseException)
    assert isinstance(replace_result, ValueError)
    assert state["marker"] is None
    assert state["tasks"] == [{"status": "running", "error_msg": None}]
    assert state["files"]["image"]["formal_exists"] is True
    assert state["files"]["image"]["formal_bytes"] == b"c009-t9-current-image"

    if first == "asset":
        assert state["shots"] == [
            {
                "order": 1,
                "revision": 2,
                "status": "changed",
                "description": "街角等待",
                "asset_roles": ["character", "scene"],
            },
            {
                "order": 2,
                "revision": 2,
                "status": "changed",
                "description": "抬头望雨",
                "asset_roles": ["character", "scene"],
            },
        ]
        assert state["assets"][0]["revision"] == 2
        assert state["assets"][0]["description"] == "C012 pair asset edit"
        assert state["clips"] == [
            {
                "role": "old",
                "revision": 1,
                "freshness": "stale",
                "shot_orders": [1, 2],
            }
        ]
        assert state["files"]["video"]["formal_exists"] is True
        assert state["files"]["video"]["formal_bytes"] == b"c012-l5-source-media"
        assert state["files"]["override"]["formal_exists"] is True
        return

    if first == "shot":
        assert state["shots"] == [
            {
                "order": 1,
                "revision": 2,
                "status": "changed",
                "description": "C012 pair shot edit",
                "asset_roles": ["character", "scene"],
            },
            {
                "order": 2,
                "revision": 1,
                "status": "normal",
                "description": "抬头望雨",
                "asset_roles": ["character", "scene"],
            },
        ]
        assert state["clips"] == [
            {
                "role": "old",
                "revision": 1,
                "freshness": "stale",
                "shot_orders": [1, 2],
            }
        ]
        assert state["files"]["video"]["formal_exists"] is True
        assert state["files"]["video"]["formal_bytes"] == b"c012-l5-source-media"
        assert state["files"]["override"]["formal_exists"] is True
        return

    if first == "slot":
        assert state["shots"][0]["revision"] == 1
        assert state["clips"] == [
            {
                "role": "old",
                "revision": 2,
                "freshness": "stale",
                "shot_orders": [1, 2],
            }
        ]
        assert next(slot for slot in state["slots"] if slot["slot_no"] == 1)[
            "enabled"
        ] is False
        assert state["files"]["video"]["formal_exists"] is True
        assert state["files"]["override"]["formal_exists"] is True
        return

    assert first == "delete"
    assert state["shots"] == [
        {
            "order": 1,
            "revision": 1,
            "status": "normal",
            "description": "街角等待",
            "asset_roles": ["character", "scene"],
        },
        {
            "order": 2,
            "revision": 1,
            "status": "normal",
            "description": "抬头望雨",
            "asset_roles": ["character", "scene"],
        },
    ]
    assert state["clips"] == []
    assert state["clip_shots"] == []
    assert state["slots"] == []
    assert state["videos"] == []
    assert state["files"]["video"]["formal_exists"] is False
    assert state["files"]["video"]["trash_exists"] is True
    assert state["files"]["video"]["trash_bytes"] == b"c012-l5-source-media"
    assert state["files"]["override"]["formal_exists"] is False
    assert state["files"]["override"]["trash_exists"] is True


async def _cleanup_case(fixture: dict[str, object], data_dir: Path, layer: str) -> None:
    if layer == "L5":
        await _cleanup_l5_fixture(fixture, data_dir)
        return
    await _cleanup_base_fixture(fixture)


async def _run_serial(
    pair: _Pair,
    fixture: dict[str, object],
    data_dir: Path,
    first: str,
    second: str,
) -> tuple[list[object], dict[str, object]]:
    replacement_task = (
        await _prepare_replacement_task(fixture, data_dir)
        if pair.layer == "L5"
        else None
    )
    operations = (first, second)
    results: list[object] = []
    for index, operation in enumerate(operations):
        try:
            results.append(
                await _run_operation(
                    fixture,
                    data_dir,
                    operation,
                    f"c012-serial-{uuid4().hex[:10]}-{index}",
                    replacement_task,
                )
            )
        except HTTPException as exc:
            results.append(exc)
        except ValueError as exc:
            results.append(exc)
    state = await _read_state(fixture, data_dir)
    return results, state


async def _run_concurrent(
    pair: _Pair,
    fixture: dict[str, object],
    data_dir: Path,
    first: str,
    second: str,
) -> tuple[list[object], dict[str, object], dict[str, object]]:
    replacement_task = (
        await _prepare_replacement_task(fixture, data_dir)
        if pair.layer == "L5"
        else None
    )
    prefix = f"c012-edit-{uuid4().hex[:10]}-"
    first_label = f"{prefix}first"
    second_label = f"{prefix}second"
    gate, gate_pid = await _open_clip_gate(fixture, prefix)
    gate_released = False
    first_task: asyncio.Task[object] | None = None
    second_task: asyncio.Task[object] | None = None
    try:
        first_task = asyncio.create_task(
            _run_operation(
                fixture, data_dir, first, first_label, replacement_task
            )
        )
        first_wait = await _wait_for_real_lock(
            prefix, first_label, {gate_pid}
        )
        first_pid = _waiting_pid(first_wait, first_label)
        second_task = asyncio.create_task(
            _run_operation(
                fixture, data_dir, second, second_label, replacement_task
            )
        )
        second_wait = await _wait_for_real_lock(
            prefix, second_label, {gate_pid, first_pid}
        )
        await gate.execute("COMMIT")
        gate_released = True
        results = list(
            await asyncio.wait_for(
                asyncio.gather(
                    first_task, second_task, return_exceptions=True
                ),
                timeout=12,
            )
        )
        state = await _read_state(fixture, data_dir)
        return results, state, {
            "prefix": prefix,
            "gate_pid": gate_pid,
            "first_wait": first_wait,
            "second_wait": second_wait,
        }
    finally:
        if not gate_released:
            await gate.execute("ROLLBACK")
        await gate.close()
        pending = [task for task in (first_task, second_task) if task is not None]
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


async def _run_one_direction(
    pair: _Pair, data_dir: Path, first: str, second: str
) -> None:
    baseline_fixture = await _create_base_fixture(data_dir)
    try:
        serial_results, serial_state = await _run_serial(
            pair, baseline_fixture, data_dir, first, second
        )
        operations = (first, second)
        serial_signatures = [
            _result_signature(operation, result, baseline_fixture)
            for operation, result in zip(operations, serial_results)
        ]
    finally:
        await _cleanup_case(baseline_fixture, data_dir, pair.layer)

    concurrent_fixture = await _create_base_fixture(data_dir)
    try:
        concurrent_results, concurrent_state, lock_evidence = await _run_concurrent(
            pair, concurrent_fixture, data_dir, first, second
        )
        _assert_no_unexpected_results(
            operations, concurrent_results, f"{pair.layer} {first}->{second}"
        )
        concurrent_signatures = [
            _result_signature(operation, result, concurrent_fixture)
            for operation, result in zip(operations, concurrent_results)
        ]
        assert concurrent_signatures == serial_signatures, {
            "pair": pair,
            "order": operations,
            "serial": serial_signatures,
            "concurrent": concurrent_signatures,
            "lock_evidence": lock_evidence,
        }
        assert concurrent_state == serial_state, {
            "pair": pair,
            "order": operations,
            "serial_state": _display_state(serial_state),
            "concurrent_state": _display_state(concurrent_state),
            "lock_evidence": lock_evidence,
        }
        if pair.layer == "L4":
            _assert_l4_semantics(
                pair.structural,
                pair.edit,
                operations,
                concurrent_results,
                concurrent_state,
            )
        else:
            _assert_l5_semantics(
                first,
                second,
                operations,
                concurrent_results,
                concurrent_state,
            )
    finally:
        await _cleanup_case(concurrent_fixture, data_dir, pair.layer)


async def _run_matrix(data_dir: Path) -> None:
    try:
        for pair in PAIR_MATRIX:
            for first, second in (
                (pair.structural, pair.edit),
                (pair.edit, pair.structural),
            ):
                await _run_one_direction(pair, data_dir, first, second)
    finally:
        await engine.dispose()


def test_c012_lock_edit_pairs_are_serial_equivalent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    asyncio.run(_run_matrix(tmp_path))
