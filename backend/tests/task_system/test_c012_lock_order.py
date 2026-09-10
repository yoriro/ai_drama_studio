from __future__ import annotations

import asyncio
import hashlib
import io
import json
from pathlib import Path
from uuid import uuid4

import asyncpg
import av
import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import engine
from app.integrations.workflow_binding import load_minimax_binding_snapshot
from app.services.asset_files import asset_image_relative_path
from app.schemas.assets import AssetPatch
from app.schemas.clips import ClipCreateRequest, ClipSlotEnabledPatch
from app.schemas.shots import ShotPatch
from app.services.clip_video_commit import commit_generated_clip_video
from app.services.assets import delete_asset, set_current_asset_image, update_asset
from app.services.clips import (
    create_clip,
    delete_clip,
    update_clip_slot_enabled,
)
from app.services.generate_clip_video import enqueue_generate_clip_video
from app.services.shots import update_shot
from app.services.video_files import temporary_clip_video_path
from app.tasks.gen_clip_video import GeneratedClipVideo
from app.tasks.queue import ClaimedTask, TaskQueue


LOCK_CASES = ("L1", "L2", "L3", "L4", "L5")


def _database_url() -> str:
    return __import__("os").environ["DATABASE_URL"].replace("+asyncpg", "", 1)


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


async def _create_fixture(data_dir: Path) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        suffix = uuid4().hex
        original_template = await connection.fetchval(
            "SELECT content FROM prompt_templates WHERE key = 'minimaxh3'"
        )
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, '电影写实')
            RETURNING id
            """,
            f"C012 lock style {suffix}",
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            f"C012 lock project {suffix}",
            style_id,
        )
        episode_id = await connection.fetchval(
            """
            INSERT INTO episodes (project_id, seq, title, script_text)
            VALUES ($1, 1, 'C012 lock episode', 'C012')
            RETURNING id
            """,
            project_id,
        )
        character_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source)
            VALUES ($1, 'character', '锁测人物', '用于锁顺序探针', 'manual')
            RETURNING id
            """,
            project_id,
        )
        scene_id = await connection.fetchval(
            """
            INSERT INTO assets (project_id, type, name, description, source)
            VALUES ($1, 'scene', '锁测场景', '用于锁顺序探针', 'manual')
            RETURNING id
            """,
            project_id,
        )
        shot_ids: list[int] = []
        for order_index, description in ((1, "锁测入门"), (2, "锁测停留")):
            shot_id = await connection.fetchval(
                """
                INSERT INTO shots
                    (episode_id, order_index, duration_est, shot_type, camera,
                     description, dialogue, status, revision)
                VALUES ($1, $2, 2, '中景', '固定', $3, '', 'normal', 1)
                RETURNING id
                """,
                episode_id,
                order_index,
                description,
            )
            shot_ids.append(int(shot_id))
            await connection.executemany(
                "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
                [(shot_id, character_id), (shot_id, scene_id)],
            )

        clip_id = await connection.fetchval(
            """
            INSERT INTO clips (episode_id, requested_duration)
            VALUES ($1, 5)
            RETURNING id
            """,
            episode_id,
        )
        await connection.executemany(
            "INSERT INTO clip_shots (clip_id, shot_id, position) VALUES ($1, $2, $3)",
            [(clip_id, shot_ids[0], 1), (clip_id, shot_ids[1], 2)],
        )
        await connection.execute(
            """
            INSERT INTO clip_ref_slots
                (clip_id, slot_no, asset_id, asset_name_snapshot,
                 asset_type_snapshot, enabled)
            VALUES ($1, 1, $2, '锁测人物', 'character', true)
            """,
            clip_id,
            character_id,
        )

        image_id = await connection.fetchval(
            """
            INSERT INTO asset_images
                (asset_id, file_path, sha256, source, is_current)
            VALUES ($1, 'pending', $2, 'uploaded', true)
            RETURNING id
            """,
            character_id,
            "0" * 64,
        )
        image_relative_path = asset_image_relative_path(
            int(project_id), int(character_id), int(image_id), "png"
        )
        image_path = data_dir / image_relative_path
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_bytes = b"c012-lock-current-image"
        image_path.write_bytes(image_bytes)
        await connection.execute(
            """
            UPDATE asset_images
            SET file_path = $1, sha256 = $2
            WHERE id = $3
            """,
            image_relative_path.as_posix(),
            hashlib.sha256(image_bytes).hexdigest(),
            image_id,
        )
        await connection.execute(
            """
            UPDATE prompt_templates
            SET content = $1
            WHERE key = 'minimaxh3'
            """,
            "shots={{shots}}|references={{references}}|style={{style}}|"
            "duration={{requested_duration}}|note={{user_note}}",
        )
    finally:
        await connection.close()
    return {
        "style_id": int(style_id),
        "project_id": int(project_id),
        "episode_id": int(episode_id),
        "character_id": int(character_id),
        "scene_id": int(scene_id),
        "shot_ids": shot_ids,
        "clip_id": int(clip_id),
        "image_id": int(image_id),
        "original_template": original_template,
    }


async def _cleanup_fixture(fixture: dict[str, object]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE prompt_templates SET content = $1 WHERE key = 'minimaxh3'",
            fixture["original_template"],
        )
        await connection.execute(
            "DELETE FROM tasks WHERE target_id = $1 AND type = 'gen_clip_video'",
            fixture["clip_id"],
        )
        await connection.execute(
            "DELETE FROM clip_videos WHERE clip_id = $1", fixture["clip_id"]
        )
        await connection.execute(
            "DELETE FROM clip_ref_slots WHERE clip_id = $1", fixture["clip_id"]
        )
        await connection.execute(
            "DELETE FROM clip_shots WHERE clip_id = $1", fixture["clip_id"]
        )
        await connection.execute(
            "DELETE FROM asset_images WHERE asset_id = ANY($1::int[])",
            [fixture["character_id"], fixture["scene_id"]],
        )
        await connection.execute(
            "DELETE FROM shot_assets WHERE shot_id = ANY($1::int[])",
            fixture["shot_ids"],
        )
        await connection.execute("DELETE FROM clips WHERE id = $1", fixture["clip_id"])
        await connection.execute(
            "DELETE FROM shots WHERE id = ANY($1::int[])", fixture["shot_ids"]
        )
        await connection.execute(
            "DELETE FROM assets WHERE id = ANY($1::int[])",
            [fixture["character_id"], fixture["scene_id"]],
        )
        await connection.execute("DELETE FROM episodes WHERE id = $1", fixture["episode_id"])
        await connection.execute("DELETE FROM projects WHERE id = $1", fixture["project_id"])
        await connection.execute("DELETE FROM styles WHERE id = $1", fixture["style_id"])
    finally:
        await connection.close()


async def _insert_commit_task(fixture: dict[str, object]) -> ClaimedTask:
    payload = {
        "input_snapshot": {
            "clip": {
                "id": fixture["clip_id"],
                "episode_id": fixture["episode_id"],
                "revision": 1,
            },
            "requested_duration": 5,
            "seed": 123,
            "cached_prompt": None,
        },
        "input_hash": "c012-lock-order-input",
        "source_revisions": {
            "clip": {"id": fixture["clip_id"], "revision": 1},
            "shots": [
                {"id": shot_id, "revision": 1}
                for shot_id in fixture["shot_ids"]
            ],
            "assets": [
                {"id": fixture["character_id"], "revision": 1},
                {"id": fixture["scene_id"], "revision": 1},
            ],
        },
    }
    connection = await asyncpg.connect(_database_url())
    try:
        task_id = await connection.fetchval(
            """
            INSERT INTO tasks
                (type, target_id, payload, status, progress)
            VALUES ('gen_clip_video', $1, $2::jsonb, 'running', 0.2)
            RETURNING id
            """,
            fixture["clip_id"],
            json.dumps(payload),
        )
    finally:
        await connection.close()
    return ClaimedTask(
        id=int(task_id),
        type="gen_clip_video",
        target_id=int(fixture["clip_id"]),
        request_id=None,
        payload=payload,
    )


async def _open_operation_connection(label: str):
    connection = await engine.connect()
    connection.sync_connection.info["c012_operation"] = label
    await connection.execute(
        text("SELECT set_config('application_name', :value, false)"),
        {"value": label},
    )
    await connection.execute(text("SET lock_timeout = '1500ms'"))
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


async def _run_direction(
    fixture: dict[str, object], data_dir: Path, *, first: str
) -> tuple[list[object], dict[str, object], dict[str, object]]:
    task = await _insert_commit_task(fixture)
    temp_path = temporary_clip_video_path(data_dir, task.id)
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_bytes(_video_bytes())

    prefix = f"c012-lock-{uuid4().hex[:12]}-"
    commit_label = f"{prefix}commit"
    enqueue_label = f"{prefix}enqueue"
    commit_source_seen = asyncio.Event()
    enqueue_source_seen = asyncio.Event()
    enqueue_asset_attempted = asyncio.Event()
    loop = asyncio.get_running_loop()
    seen: dict[str, bool] = {commit_label: False, enqueue_label: False}
    observed: list[tuple[object, str]] = []

    def observe_source_lock(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        operation = _conn.info.get("c012_operation")
        normalized = " ".join(str(statement).lower().split())
        if operation in seen:
            observed.append((operation, normalized[:240]))
        if operation not in seen or seen[operation]:
            return
        if " for update" not in normalized:
            return
        if not any(
            f" from {table}" in normalized
            for table in ("episodes", "assets", "shots", "clips")
        ):
            return
        if operation == enqueue_label and " from assets" in normalized:
            loop.call_soon_threadsafe(enqueue_asset_attempted.set)
        seen[operation] = True
        target = commit_source_seen if operation == commit_label else enqueue_source_seen
        loop.call_soon_threadsafe(target.set)

    event.listen(engine.sync_engine, "before_cursor_execute", observe_source_lock)
    gate_connection = None
    results: list[object] = []
    try:
        async def wait_for_source(event_to_wait: asyncio.Event, label: str) -> None:
            try:
                await asyncio.wait_for(event_to_wait.wait(), timeout=5)
            except asyncio.TimeoutError as exc:
                snapshot = await _read_lock_snapshot(prefix)
                raise AssertionError(
                    f"C012 {label} source lock was not observed; "
                    f"observed={observed}; snapshot={snapshot}"
                ) from exc

        async def commit_worker() -> object:
            connection = await _open_operation_connection(commit_label)
            try:
                session = AsyncSession(bind=connection, expire_on_commit=False)
                try:
                    return await commit_generated_clip_video(
                        session,
                        TaskQueue(),
                        task,
                        GeneratedClipVideo(temp_path, "C012 lock probe prompt"),
                        data_dir=data_dir,
                    )
                finally:
                    await session.close()
            finally:
                await connection.close()

        async def enqueue_worker() -> object:
            connection = await _open_operation_connection(enqueue_label)
            try:
                session = AsyncSession(bind=connection, expire_on_commit=False)
                try:
                    return await enqueue_generate_clip_video(
                        session,
                        TaskQueue(),
                        int(fixture["clip_id"]),
                        user_note=None,
                        user_note_provided=False,
                        request_id=None,
                        workflow_binding=load_minimax_binding_snapshot(),
                    )
                finally:
                    await session.close()
            finally:
                await connection.close()

        commit_task: asyncio.Task[object] | None = None
        enqueue_task: asyncio.Task[object] | None = None
        if first == "commit":
            gate_connection = await _open_operation_connection(f"{prefix}gate")
            await gate_connection.execute(
                text("SELECT id FROM shots WHERE id = :shot_id FOR UPDATE"),
                {"shot_id": fixture["shot_ids"][0]},
            )
            commit_task = asyncio.create_task(commit_worker())
            await wait_for_source(commit_source_seen, "commit")
            enqueue_task = asyncio.create_task(enqueue_worker())
            await asyncio.wait_for(enqueue_asset_attempted.wait(), timeout=5)
            await gate_connection.commit()
        else:
            enqueue_task = asyncio.create_task(enqueue_worker())
            await wait_for_source(enqueue_source_seen, "enqueue")
            commit_task = asyncio.create_task(commit_worker())
            await wait_for_source(commit_source_seen, "commit")

        live_snapshot = await _read_lock_snapshot(prefix)
        results = list(
            await asyncio.wait_for(
                asyncio.gather(
                    commit_task, enqueue_task, return_exceptions=True
                ),
                timeout=8,
            )
        )
        snapshot = {
            "while_running": live_snapshot,
            "after_completion": await _read_lock_snapshot(prefix),
        }
        state_connection = await asyncpg.connect(_database_url())
        try:
            state = {
                "tasks": [
                    dict(row)
                    for row in await state_connection.fetch(
                        """
                        SELECT id, status, error_msg
                        FROM tasks
                        WHERE target_id = $1 AND type = 'gen_clip_video'
                        ORDER BY id
                        """,
                        fixture["clip_id"],
                    )
                ],
                "videos": [
                    dict(row)
                    for row in await state_connection.fetch(
                        """
                        SELECT id, file_path, is_current
                        FROM clip_videos WHERE clip_id = $1 ORDER BY id
                        """,
                        fixture["clip_id"],
                    )
                ],
            }
        finally:
            await state_connection.close()
        return results, snapshot, state
    finally:
        if gate_connection is not None:
            await gate_connection.rollback()
            await gate_connection.close()
        event.remove(engine.sync_engine, "before_cursor_execute", observe_source_lock)
        for task_to_cancel in (
            locals().get("commit_task"),
            locals().get("enqueue_task"),
        ):
            if isinstance(task_to_cancel, asyncio.Task) and not task_to_cancel.done():
                task_to_cancel.cancel()
        pending = [
            task_to_cancel
            for task_to_cancel in (
                locals().get("commit_task"),
                locals().get("enqueue_task"),
            )
            if isinstance(task_to_cancel, asyncio.Task)
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


async def _assert_direction(
    fixture: dict[str, object], data_dir: Path, *, first: str
) -> None:
    results, snapshot, state = await _run_direction(fixture, data_dir, first=first)
    errors = [repr(result) for result in results if isinstance(result, BaseException)]
    if errors:
        pytest.fail(
            "C012 L1 lock-order probe failed for "
            f"{first}-first: errors={errors}; "
            f"pg_observation={json.dumps(snapshot, ensure_ascii=False, default=str)}; "
            f"state={json.dumps(state, ensure_ascii=False, default=str)}"
        )
    assert len(state["videos"]) == 1
    assert len([task for task in state["tasks"] if task["status"] == "done"]) == 1
    assert len([task for task in state["tasks"] if task["status"] == "queued"]) == 1
    assert state["videos"][0]["is_current"] is True


async def _prepare_l2_variant(
    fixture: dict[str, object], *, operation: str, slot_only: bool
) -> int | None:
    connection = await asyncpg.connect(_database_url())
    try:
        if slot_only:
            await connection.execute(
                "DELETE FROM shot_assets WHERE asset_id = $1 AND shot_id = ANY($2::int[])",
                fixture["character_id"],
                fixture["shot_ids"],
            )
        if operation != "current":
            return None
        image_id = await connection.fetchval(
            """
            INSERT INTO asset_images
                (asset_id, file_path, sha256, source, is_current)
            VALUES ($1, 'non-current.png', $2, 'uploaded', false)
            RETURNING id
            """,
            fixture["character_id"],
            "0" * 64,
        )
        assert image_id is not None
        return int(image_id)
    finally:
        await connection.close()


async def _read_l2_state(fixture: dict[str, object]) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        asset = await connection.fetchrow(
            "SELECT name, revision FROM assets WHERE id = $1",
            fixture["character_id"],
        )
        shot = await connection.fetchrow(
            "SELECT status, revision FROM shots WHERE id = $1",
            fixture["shot_ids"][0],
        )
        clip = await connection.fetchrow(
            "SELECT freshness FROM clips WHERE id = $1", fixture["clip_id"]
        )
        slot = await connection.fetchrow(
            "SELECT asset_id FROM clip_ref_slots WHERE clip_id = $1 AND slot_no = 1",
            fixture["clip_id"],
        )
        videos = await connection.fetch(
            "SELECT id, is_current FROM clip_videos WHERE clip_id = $1",
            fixture["clip_id"],
        )
        tasks = await connection.fetch(
            "SELECT status FROM tasks WHERE target_id = $1 AND type = 'gen_clip_video'",
            fixture["clip_id"],
        )
        assert shot is not None and clip is not None and slot is not None
        return {
            "asset": None if asset is None else dict(asset),
            "shot": dict(shot),
            "clip": dict(clip),
            "slot": dict(slot),
            "videos": [dict(video) for video in videos],
            "tasks": [dict(task) for task in tasks],
        }
    finally:
        await connection.close()


async def _run_l2_variant(
    fixture: dict[str, object],
    data_dir: Path,
    *,
    operation: str,
    slot_only: bool,
    first: str,
) -> None:
    second_image_id = await _prepare_l2_variant(
        fixture, operation=operation, slot_only=slot_only
    )
    task = await _insert_commit_task(fixture)
    temp_path = temporary_clip_video_path(data_dir, task.id)
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_bytes(_video_bytes())
    label = f"c012-l2-{uuid4().hex[:12]}"

    async def commit_worker() -> object:
        connection = await _open_operation_connection(f"{label}-commit")
        try:
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                return await commit_generated_clip_video(
                    session,
                    TaskQueue(),
                    task,
                    GeneratedClipVideo(temp_path, "C012 L2 prompt"),
                    data_dir=data_dir,
                )
        finally:
            await connection.close()

    async def mutation_worker() -> object:
        connection = await _open_operation_connection(f"{label}-mutation")
        try:
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                if operation == "patch":
                    return await update_asset(
                        session,
                        int(fixture["character_id"]),
                        AssetPatch(name=f"L2改名{uuid4().hex[:6]}"),
                    )
                if operation == "current":
                    assert second_image_id is not None
                    return await set_current_asset_image(
                        session,
                        int(fixture["character_id"]),
                        second_image_id,
                    )
                await delete_asset(session, int(fixture["character_id"]))
                return None
        finally:
            await connection.close()

    if first == "mutation":
        mutation_task = asyncio.create_task(mutation_worker())
        await asyncio.sleep(0)
        commit_task = asyncio.create_task(commit_worker())
    else:
        commit_task = asyncio.create_task(commit_worker())
        await asyncio.sleep(0)
        mutation_task = asyncio.create_task(mutation_worker())
    results = await asyncio.wait_for(
        asyncio.gather(commit_task, mutation_task, return_exceptions=True),
        timeout=10,
    )
    errors = [repr(result) for result in results if isinstance(result, BaseException)]
    state = await _read_l2_state(fixture)
    if errors:
        pytest.fail(
            f"C012 L2 {operation}/{slot_only}/{first} failed: "
            f"errors={errors}; state={json.dumps(state, ensure_ascii=False, default=str)}"
        )
    assert len(state["videos"]) == 1
    assert state["tasks"] == [{"status": "done"}]
    assert state["clip"]["freshness"] == "stale"
    assert state["shot"]["status"] == ("normal" if slot_only else "changed")
    assert state["shot"]["revision"] == (1 if slot_only else 2)
    if operation == "delete":
        assert state["asset"] is None
        assert state["slot"]["asset_id"] is None
    else:
        assert state["asset"]["revision"] == 2


async def _assert_l2(data_dir: Path) -> None:
    for operation in ("patch", "current", "delete"):
        for slot_only in (False, True):
            for first in ("mutation", "commit"):
                fixture = await _create_fixture(data_dir)
                try:
                    await _run_l2_variant(
                        fixture,
                        data_dir,
                        operation=operation,
                        slot_only=slot_only,
                        first=first,
                    )
                finally:
                    await _cleanup_fixture(fixture)


async def _read_l3_state(fixture: dict[str, object]) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        shot = await connection.fetchrow(
            "SELECT status, revision, description FROM shots WHERE id = $1",
            fixture["shot_ids"][0],
        )
        assets = await connection.fetch(
            "SELECT asset_id FROM shot_assets WHERE shot_id = $1 ORDER BY asset_id",
            fixture["shot_ids"][0],
        )
        clip = await connection.fetchrow(
            "SELECT freshness FROM clips WHERE id = $1", fixture["clip_id"]
        )
        videos = await connection.fetch(
            "SELECT id, is_current FROM clip_videos WHERE clip_id = $1",
            fixture["clip_id"],
        )
        tasks = await connection.fetch(
            "SELECT status FROM tasks WHERE target_id = $1 AND type = 'gen_clip_video'",
            fixture["clip_id"],
        )
        assert shot is not None and clip is not None
        return {
            "shot": dict(shot),
            "assets": [int(row[0]) for row in assets],
            "clip": dict(clip),
            "videos": [dict(video) for video in videos],
            "tasks": [dict(task) for task in tasks],
        }
    finally:
        await connection.close()


async def _run_l3_variant(
    fixture: dict[str, object],
    data_dir: Path,
    *,
    operation: str,
    first: str,
) -> None:
    task = await _insert_commit_task(fixture)
    temp_path = temporary_clip_video_path(data_dir, task.id)
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_bytes(_video_bytes())
    label = f"c012-l3-{uuid4().hex[:12]}"

    async def commit_worker() -> object:
        connection = await _open_operation_connection(f"{label}-commit")
        try:
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                return await commit_generated_clip_video(
                    session,
                    TaskQueue(),
                    task,
                    GeneratedClipVideo(temp_path, "C012 L3 prompt"),
                    data_dir=data_dir,
                )
        finally:
            await connection.close()

    async def mutation_worker() -> object:
        connection = await _open_operation_connection(f"{label}-mutation")
        try:
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                if operation == "text":
                    return await update_shot(
                        session,
                        int(fixture["shot_ids"][0]),
                        ShotPatch(description="C012 L3 文本修改"),
                    )
                return await update_shot(
                    session,
                    int(fixture["shot_ids"][0]),
                    ShotPatch(asset_ids=[int(fixture["scene_id"])]),
                )
        finally:
            await connection.close()

    if first == "mutation":
        mutation_task = asyncio.create_task(mutation_worker())
        await asyncio.sleep(0)
        commit_task = asyncio.create_task(commit_worker())
    else:
        commit_task = asyncio.create_task(commit_worker())
        await asyncio.sleep(0)
        mutation_task = asyncio.create_task(mutation_worker())
    results = await asyncio.wait_for(
        asyncio.gather(commit_task, mutation_task, return_exceptions=True),
        timeout=10,
    )
    errors = [repr(result) for result in results if isinstance(result, BaseException)]
    state = await _read_l3_state(fixture)
    if errors:
        pytest.fail(
            f"C012 L3 {operation}/{first} failed: errors={errors}; "
            f"state={json.dumps(state, ensure_ascii=False, default=str)}"
        )
    assert state["shot"]["revision"] == 2
    assert state["shot"]["status"] == "changed"
    assert state["shot"]["description"] == (
        "C012 L3 文本修改" if operation == "text" else "锁测入门"
    )
    assert state["assets"] == (
        [int(fixture["character_id"]), int(fixture["scene_id"])]
        if operation == "text"
        else [int(fixture["scene_id"])]
    )
    assert state["clip"]["freshness"] == "stale"
    assert len(state["videos"]) == 1
    assert state["tasks"] == [{"status": "done"}]


async def _assert_l3(data_dir: Path) -> None:
    for operation in ("text", "binding"):
        for first in ("mutation", "commit"):
            fixture = await _create_fixture(data_dir)
            try:
                await _run_l3_variant(
                    fixture,
                    data_dir,
                    operation=operation,
                    first=first,
                )
            finally:
                await _cleanup_fixture(fixture)


async def _read_l4_state(
    fixture: dict[str, object], data_dir: Path
) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        clips = await connection.fetch(
            "SELECT id, revision, freshness FROM clips WHERE episode_id = $1 ORDER BY id",
            fixture["episode_id"],
        )
        clip_shots = await connection.fetch(
            "SELECT clip_id, shot_id FROM clip_shots WHERE clip_id = $1 ORDER BY shot_id",
            fixture["clip_id"],
        )
        slots = await connection.fetch(
            "SELECT clip_id, slot_no, asset_id, enabled FROM clip_ref_slots "
            "WHERE clip_id = $1 ORDER BY slot_no",
            fixture["clip_id"],
        )
        videos = await connection.fetch(
            "SELECT id, file_path, is_current FROM clip_videos WHERE clip_id = $1 ORDER BY id",
            fixture["clip_id"],
        )
        tasks = await connection.fetch(
            "SELECT status, error_msg FROM tasks WHERE target_id = $1 "
            "AND type = 'gen_clip_video' ORDER BY id",
            fixture["clip_id"],
        )
        shots = await connection.fetch(
            "SELECT id FROM shots WHERE id = ANY($1::int[]) ORDER BY id",
            fixture["shot_ids"],
        )
        trash_files = sorted(
            path.relative_to(data_dir).as_posix()
            for path in (data_dir / "trash").rglob("*")
            if path.is_file()
        ) if (data_dir / "trash").exists() else []
        return {
            "clips": [dict(row) for row in clips],
            "clip_shots": [dict(row) for row in clip_shots],
            "slots": [dict(row) for row in slots],
            "videos": [dict(row) for row in videos],
            "tasks": [dict(row) for row in tasks],
            "shots": [int(row[0]) for row in shots],
            "trash_files": trash_files,
        }
    finally:
        await connection.close()


async def _run_l4_variant(
    fixture: dict[str, object],
    data_dir: Path,
    *,
    operation: str,
    first: str,
) -> None:
    task = await _insert_commit_task(fixture)
    temp_path = temporary_clip_video_path(data_dir, task.id)
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_bytes(_video_bytes())
    label = f"c012-l4-{uuid4().hex[:12]}"

    async def commit_worker() -> object:
        connection = await _open_operation_connection(f"{label}-commit")
        try:
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                return await commit_generated_clip_video(
                    session,
                    TaskQueue(),
                    task,
                    GeneratedClipVideo(temp_path, "C012 L4 prompt"),
                    data_dir=data_dir,
                )
        finally:
            await connection.close()

    async def mutation_worker() -> object:
        connection = await _open_operation_connection(f"{label}-mutation")
        try:
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
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
                return await delete_clip(session, int(fixture["clip_id"]))
        finally:
            await connection.close()

    if first == "mutation":
        mutation_task = asyncio.create_task(mutation_worker())
        await asyncio.sleep(0)
        commit_task = asyncio.create_task(commit_worker())
    else:
        commit_task = asyncio.create_task(commit_worker())
        await asyncio.sleep(0)
        mutation_task = asyncio.create_task(mutation_worker())
    results = await asyncio.wait_for(
        asyncio.gather(commit_task, mutation_task, return_exceptions=True),
        timeout=10,
    )
    state = await _read_l4_state(fixture, data_dir)

    if operation == "create":
        mutation_result = results[1]
        unexpected = [
            result
            for result in results
            if isinstance(result, BaseException)
            and not isinstance(result, HTTPException)
        ]
        if unexpected or not isinstance(mutation_result, HTTPException):
            pytest.fail(
                f"C012 L4 create/{first} failed: results={results}; "
                f"state={json.dumps(state, ensure_ascii=False, default=str)}"
            )
        assert mutation_result.status_code == 422
        assert state["clips"] == [
            {
                "id": fixture["clip_id"],
                "revision": 1,
                "freshness": "fresh",
            }
        ]
        assert state["tasks"] == [{"status": "done", "error_msg": None}]
        assert len(state["videos"]) == 1
        assert state["clip_shots"] == [
            {"clip_id": fixture["clip_id"], "shot_id": shot_id}
            for shot_id in sorted(fixture["shot_ids"])
        ]
        return

    if operation == "slot":
        errors = [repr(result) for result in results if isinstance(result, BaseException)]
        if errors:
            pytest.fail(
                f"C012 L4 slot/{first} failed: errors={errors}; "
                f"state={json.dumps(state, ensure_ascii=False, default=str)}"
            )
        assert state["clips"] == [
            {
                "id": fixture["clip_id"],
                "revision": 2,
                "freshness": "stale",
            }
        ]
        assert state["slots"] == [
            {
                "clip_id": fixture["clip_id"],
                "slot_no": 1,
                "asset_id": fixture["character_id"],
                "enabled": False,
            }
        ]
        assert state["tasks"] == [{"status": "done", "error_msg": None}]
        assert len(state["videos"]) == 1
        return

    delete_errors = [
        result
        for result in results
        if isinstance(result, BaseException) and not isinstance(result, ValueError)
    ]
    if delete_errors:
        pytest.fail(
            f"C012 L4 delete/{first} failed: results={results}; "
            f"state={json.dumps(state, ensure_ascii=False, default=str)}"
        )
    assert state["clips"] == []
    assert state["clip_shots"] == []
    assert state["slots"] == []
    assert state["videos"] == []
    assert state["shots"] == sorted(fixture["shot_ids"])
    assert len(state["tasks"]) == 1
    current_trash_files = [
        path
        for path in state["trash_files"]
        if f"/clips/{fixture['clip_id']}/" in f"/{path}"
    ]
    if current_trash_files:
        assert results[0] is not None
        assert len(current_trash_files) == 1
        assert state["tasks"] in (
            [{"status": "done", "error_msg": None}],
            [{"status": "running", "error_msg": None}],
        )
    else:
        assert isinstance(results[0], ValueError)
        assert state["tasks"] == [{"status": "running", "error_msg": None}]
        assert current_trash_files == []


async def _assert_l4(data_dir: Path) -> None:
    for operation in ("create", "slot", "delete"):
        for first in ("mutation", "commit"):
            fixture = await _create_fixture(data_dir)
            try:
                await _run_l4_variant(
                    fixture,
                    data_dir,
                    operation=operation,
                    first=first,
                )
            finally:
                await _cleanup_fixture(fixture)


@pytest.mark.parametrize("lock_case", LOCK_CASES, ids=LOCK_CASES)
def test_c012_lock_order(
    lock_case: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    async def run() -> None:
        if lock_case == "L2":
            await _assert_l2(tmp_path)
            return
        if lock_case == "L3":
            await _assert_l3(tmp_path)
            return
        if lock_case == "L4":
            await _assert_l4(tmp_path)
            return
        fixture = await _create_fixture(tmp_path)
        try:
            if lock_case != "L1":
                pytest.fail(
                    f"C012 {lock_case} probe is scheduled for its lock-order task"
                )
            await _assert_direction(fixture, tmp_path, first="commit")
        finally:
            await _cleanup_fixture(fixture)

        fixture = await _create_fixture(tmp_path)
        try:
            if lock_case != "L1":
                pytest.fail(
                    f"C012 {lock_case} probe is scheduled for its lock-order task"
                )
            await _assert_direction(fixture, tmp_path, first="enqueue")
        finally:
            await _cleanup_fixture(fixture)

    asyncio.run(run())
