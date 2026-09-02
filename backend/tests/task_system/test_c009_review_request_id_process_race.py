from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
from queue import Empty as QueueEmpty
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from starlette.requests import Request

from app.api.assets import generate_asset_image_route
from app.api.clips import generate_clip_video_route
from app.core.config import settings
from app.core.errors import handle_http_exception
from app.db.session import async_session_factory, engine
from app.integrations.workflow_binding import (
    load_binding_snapshot,
    load_minimax_binding_snapshot,
)
from app.main import create_app
from app.schemas.generation import (
    GenerateAssetImageRequest,
    GenerateClipVideoRequest,
)
from app.services.asset_files import asset_image_relative_path
from app.tasks.queue import REQUEST_ID_LOCK_NAMESPACE, TaskQueue


_MINIMAX_TEMPLATE = (
    "shots={{shots}}|references={{references}}|style={{style}}|"
    "duration={{requested_duration}}|note={{user_note}}"
)
_ZIMAGE_TEMPLATE = "asset={{asset}}|style={{style}}|note={{user_note}}"
_CONFLICT_MESSAGE = "request_id is already bound to a different task request"


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _request_for(application: Any, path: str) -> Request:
    encoded_path = path.encode("ascii")
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": encoded_path,
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 0),
            "server": ("127.0.0.1", 8000),
            "app": application,
        }
    )


async def _invoke_video_route(
    *,
    clip_id: int,
    user_note: str | None,
    user_note_provided: bool,
    request_id: str,
    application_name: str,
    ready_event: Any,
    ready_queue: Any,
    release_event: Any,
    result_queue: Any,
) -> None:
    application = create_app()
    application.state.task_queue = TaskQueue(async_session_factory)
    application.state.minimax_workflow_binding_snapshot = (
        load_minimax_binding_snapshot()
    )
    request = _request_for(
        application, f"/api/clips/{clip_id}/generate-video"
    )
    async with async_session_factory() as session:
        await session.execute(
            text("SELECT set_config('application_name', :name, false)"),
            {"name": application_name},
        )
        await session.commit()
        db_pid = await session.scalar(text("SELECT pg_backend_pid()"))
        await session.commit()
        assert isinstance(db_pid, int)
        ready_queue.put(
            {
                "pid": os.getpid(),
                "db_pid": db_pid,
                "application_name": application_name,
            }
        )
        ready_event.set()
        if not release_event.wait(30):
            raise TimeoutError(f"release event timed out for {application_name}")

        values: dict[str, object] = {"request_id": request_id}
        if user_note_provided:
            values["user_note"] = user_note
        payload = GenerateClipVideoRequest(**values)
        try:
            response = await generate_clip_video_route(
                clip_id,
                payload,
                request,
                session,
            )
        except HTTPException as exc:
            error_response = await handle_http_exception(request, exc)
            body = json.loads(error_response.body.decode("utf-8"))
            result_queue.put(
                {
                    "entry": "video",
                    "pid": os.getpid(),
                    "status_code": error_response.status_code,
                    "body": body,
                }
            )
        else:
            result_queue.put(
                {
                    "entry": "video",
                    "pid": os.getpid(),
                    "status_code": 202,
                    "body": response.model_dump(mode="json"),
                }
            )


async def _invoke_asset_route(
    *,
    asset_id: int,
    request_id: str,
    application_name: str,
    ready_event: Any,
    ready_queue: Any,
    release_event: Any,
    result_queue: Any,
) -> None:
    application = create_app()
    application.state.task_queue = TaskQueue(async_session_factory)
    application.state.workflow_binding_snapshot = load_binding_snapshot()
    request = _request_for(application, f"/api/assets/{asset_id}/generate-image")
    async with async_session_factory() as session:
        await session.execute(
            text("SELECT set_config('application_name', :name, false)"),
            {"name": application_name},
        )
        await session.commit()
        db_pid = await session.scalar(text("SELECT pg_backend_pid()"))
        await session.commit()
        assert isinstance(db_pid, int)
        ready_queue.put(
            {
                "pid": os.getpid(),
                "db_pid": db_pid,
                "application_name": application_name,
            }
        )
        ready_event.set()
        if not release_event.wait(30):
            raise TimeoutError(f"release event timed out for {application_name}")

        payload = GenerateAssetImageRequest(request_id=request_id)
        try:
            response = await generate_asset_image_route(
                asset_id,
                payload,
                request,
                session,
            )
        except HTTPException as exc:
            error_response = await handle_http_exception(request, exc)
            body = json.loads(error_response.body.decode("utf-8"))
            result_queue.put(
                {
                    "entry": "asset",
                    "pid": os.getpid(),
                    "status_code": error_response.status_code,
                    "body": body,
                }
            )
        else:
            result_queue.put(
                {
                    "entry": "asset",
                    "pid": os.getpid(),
                    "status_code": 202,
                    "body": response.model_dump(mode="json"),
                }
            )


async def _video_process_async(
    *,
    clip_id: int,
    user_note: str | None,
    user_note_provided: bool,
    request_id: str,
    application_name: str,
    ready_event: Any,
    ready_queue: Any,
    release_event: Any,
    result_queue: Any,
) -> None:
    try:
        await _invoke_video_route(
            clip_id=clip_id,
            user_note=user_note,
            user_note_provided=user_note_provided,
            request_id=request_id,
            application_name=application_name,
            ready_event=ready_event,
            ready_queue=ready_queue,
            release_event=release_event,
            result_queue=result_queue,
        )
    finally:
        await engine.dispose()


async def _asset_process_async(
    *,
    asset_id: int,
    request_id: str,
    application_name: str,
    ready_event: Any,
    ready_queue: Any,
    release_event: Any,
    result_queue: Any,
) -> None:
    try:
        await _invoke_asset_route(
            asset_id=asset_id,
            request_id=request_id,
            application_name=application_name,
            ready_event=ready_event,
            ready_queue=ready_queue,
            release_event=release_event,
            result_queue=result_queue,
        )
    finally:
        await engine.dispose()


def _close_child_queues(
    ready_queue: Any, result_queue: Any, done_event: Any
) -> None:
    try:
        ready_queue.close()
        ready_queue.join_thread()
    finally:
        try:
            result_queue.close()
            result_queue.join_thread()
        finally:
            done_event.set()


def _video_process(
    clip_id: int,
    user_note: str | None,
    user_note_provided: bool,
    request_id: str,
    application_name: str,
    ready_event: Any,
    ready_queue: Any,
    release_event: Any,
    done_event: Any,
    result_queue: Any,
) -> None:
    try:
        asyncio.run(
            _video_process_async(
                clip_id=clip_id,
                user_note=user_note,
                user_note_provided=user_note_provided,
                request_id=request_id,
                application_name=application_name,
                ready_event=ready_event,
                ready_queue=ready_queue,
                release_event=release_event,
                result_queue=result_queue,
            )
        )
    finally:
        _close_child_queues(ready_queue, result_queue, done_event)


def _asset_process(
    asset_id: int,
    request_id: str,
    application_name: str,
    ready_event: Any,
    ready_queue: Any,
    release_event: Any,
    done_event: Any,
    result_queue: Any,
) -> None:
    try:
        asyncio.run(
            _asset_process_async(
                asset_id=asset_id,
                request_id=request_id,
                application_name=application_name,
                ready_event=ready_event,
                ready_queue=ready_queue,
                release_event=release_event,
                result_queue=result_queue,
            )
        )
    finally:
        _close_child_queues(ready_queue, result_queue, done_event)


def _request_lock_process(
    request_id: str,
    application_name: str,
    locked_event: Any,
    release_event: Any,
    done_event: Any,
) -> None:
    async def run() -> None:
        connection = await asyncpg.connect(_database_url())
        transaction = connection.transaction()
        committed = False
        try:
            await connection.fetchval(
                "SELECT set_config('application_name', $1, false)",
                application_name,
            )
            await transaction.start()
            await connection.fetchval(
                "SELECT pg_advisory_xact_lock(hashtextextended($1 || $2, 0))",
                REQUEST_ID_LOCK_NAMESPACE,
                request_id,
            )
            locked_event.set()
            if not release_event.wait(30):
                raise TimeoutError("request-id lock release event timed out")
            await transaction.commit()
            committed = True
        finally:
            if not committed:
                await transaction.rollback()
            await connection.close()

    try:
        asyncio.run(run())
    finally:
        done_event.set()


async def _wait_for_event(event: Any, label: str) -> None:
    observed = await asyncio.to_thread(event.wait, 20)
    assert observed, f"{label} was not observed"


async def _wait_for_lock_waiter(application_name: str) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        for _ in range(200):
            row = await connection.fetchrow(
                """
                SELECT state, wait_event_type
                FROM pg_stat_activity
                WHERE application_name = $1
                  AND state = 'active'
                  AND wait_event_type = 'Lock'
                """,
                application_name,
            )
            if row is not None:
                assert row["state"] == "active"
                assert row["wait_event_type"] == "Lock"
                return
            await asyncio.sleep(0.01)
        raise AssertionError(
            f"request-id lock waiter was not visible for {application_name}"
        )
    finally:
        await connection.close()


async def _queue_get(queue: Any, label: str) -> dict[str, object]:
    try:
        value = await asyncio.to_thread(queue.get, True, 5)
    except QueueEmpty as exc:
        raise AssertionError(f"missing {label}") from exc
    assert isinstance(value, dict)
    return value


def _close_parent_queues(ready_queue: Any, result_queue: Any) -> None:
    try:
        ready_queue.close()
        ready_queue.join_thread()
    finally:
        result_queue.close()
        result_queue.join_thread()


async def _join_process(process: multiprocessing.Process) -> None:
    await asyncio.to_thread(process.join, 20)
    if process.is_alive():
        process.terminate()
        await asyncio.to_thread(process.join, 5)
    if process.is_alive():
        process.kill()
        await asyncio.to_thread(process.join, 5)
    assert not process.is_alive()


async def _run_locked_race(
    *,
    request_id: str,
    attempts: list[dict[str, object]],
) -> list[dict[str, object]]:
    assert len(attempts) >= 2
    context = multiprocessing.get_context("spawn")
    holder_locked = context.Event()
    holder_release = context.Event()
    holder_done = context.Event()
    ready_events = [context.Event() for _ in attempts]
    release_events = [context.Event() for _ in attempts]
    done_events = [context.Event() for _ in attempts]
    ready_queue = context.Queue()
    result_queue = context.Queue()
    holder = context.Process(
        target=_request_lock_process,
        args=(
            request_id.strip(),
            f"c009-t23-holder-{uuid4().hex[:8]}",
            holder_locked,
            holder_release,
            holder_done,
        ),
    )
    created_processes: list[multiprocessing.Process] = [holder]
    processes: list[multiprocessing.Process] = []
    started: list[multiprocessing.Process] = []
    application_names: list[str] = []
    try:
        try:
            holder.start()
            started.append(holder)
            await _wait_for_event(holder_locked, "request-id lock holder")

            for index, attempt in enumerate(attempts):
                entry = attempt["entry"]
                application_name = f"c009-t23-caller-{uuid4().hex[:8]}-{index}"
                application_names.append(application_name)
                if entry == "video":
                    process = context.Process(
                        target=_video_process,
                        args=(
                            int(attempt["target_id"]),
                            attempt["user_note"],
                            bool(attempt["user_note_provided"]),
                            request_id,
                            application_name,
                            ready_events[index],
                            ready_queue,
                            release_events[index],
                            done_events[index],
                            result_queue,
                        ),
                    )
                else:
                    assert entry == "asset"
                    process = context.Process(
                        target=_asset_process,
                        args=(
                            int(attempt["target_id"]),
                            request_id,
                            application_name,
                            ready_events[index],
                            ready_queue,
                            release_events[index],
                            done_events[index],
                            result_queue,
                        ),
                    )
                created_processes.append(process)
                process.start()
                started.append(process)
                processes.append(process)

            await asyncio.gather(
                *(
                    _wait_for_event(event, f"caller {index} ready")
                    for index, event in enumerate(ready_events)
                )
            )
            ready_records = [
                await _queue_get(ready_queue, f"caller {index} ready record")
                for index in range(len(attempts))
            ]
            assert {record["pid"] for record in ready_records} == {
                process.pid for process in processes
            }
            assert len({record["pid"] for record in ready_records}) == len(attempts)
            assert len({record["db_pid"] for record in ready_records}) == len(attempts)
            assert {
                record["application_name"] for record in ready_records
            } == set(application_names)

            for release_event in release_events:
                release_event.set()
            assert all(event.is_set() for event in release_events)
            await asyncio.gather(
                *(_wait_for_lock_waiter(name) for name in application_names)
            )
            print(
                "T23 release barrier reached before holder release: "
                f"request_id={request_id.strip()} "
                f"caller_pids={[record['pid'] for record in ready_records]} "
                f"db_pids={[record['db_pid'] for record in ready_records]}",
                flush=True,
            )
            holder_release.set()
            await _wait_for_event(holder_done, "request-id lock holder done")
            await asyncio.gather(
                *(
                    _wait_for_event(event, f"caller {index} done")
                    for index, event in enumerate(done_events)
                )
            )
        finally:
            holder_release.set()
            for release_event in release_events:
                release_event.set()
            for process in started:
                await _join_process(process)

        caller_pids = [process.pid for process in processes]
        caller_exitcodes = [process.exitcode for process in processes]
        holder_exitcode = holder.exitcode
        holder_exit_detail = (
            f"PID={holder.pid} exitcode={holder_exitcode}"
        )
        assert holder_exitcode == 0, (
            f"request-id lock holder process failed: {holder_exit_detail}"
        )
        caller_exit_details = ", ".join(
            f"PID={pid} exitcode={exitcode}"
            for pid, exitcode in zip(
                caller_pids, caller_exitcodes, strict=True
            )
        )
        assert all(exitcode == 0 for exitcode in caller_exitcodes), (
            f"caller process exitcodes: {caller_exit_details}"
        )
        records = [
            await _queue_get(result_queue, f"caller {index} result")
            for index in range(len(attempts))
        ]
        assert {record["pid"] for record in records} == set(caller_pids)
        return records
    finally:
        try:
            _close_parent_queues(ready_queue, result_queue)
        finally:
            for process in created_processes:
                assert not process.is_alive()
                process.close()


async def _run_single_attempt(attempt: dict[str, object]) -> dict[str, object]:
    context = multiprocessing.get_context("spawn")
    ready_event = context.Event()
    release_event = context.Event()
    done_event = context.Event()
    ready_queue = context.Queue()
    result_queue = context.Queue()
    application_name = f"c009-t23-single-{uuid4().hex[:8]}"
    request_id = str(attempt["request_id"])
    if attempt["entry"] == "video":
        process = context.Process(
            target=_video_process,
            args=(
                int(attempt["target_id"]),
                attempt["user_note"],
                bool(attempt["user_note_provided"]),
                request_id,
                application_name,
                ready_event,
                ready_queue,
                release_event,
                done_event,
                result_queue,
            ),
        )
    else:
        assert attempt["entry"] == "asset"
        process = context.Process(
            target=_asset_process,
            args=(
                int(attempt["target_id"]),
                request_id,
                application_name,
                ready_event,
                ready_queue,
                release_event,
                done_event,
                result_queue,
            ),
        )
    process_started = False
    try:
        try:
            process.start()
            process_started = True
            await _wait_for_event(ready_event, "single caller ready")
            ready_record = await _queue_get(
                ready_queue, "single caller ready record"
            )
            assert ready_record["pid"] == process.pid
            assert ready_record["application_name"] == application_name
            release_event.set()
            assert release_event.is_set()
            await _wait_for_event(done_event, "single caller done")
        finally:
            release_event.set()
            if process_started:
                await _join_process(process)

        process_pid = process.pid
        process_exitcode = process.exitcode
        assert process_exitcode == 0, (
            f"caller process failed: PID={process_pid} "
            f"exitcode={process_exitcode}"
        )
        record = await _queue_get(result_queue, "single caller result")
        assert record["pid"] == process_pid
        return record
    finally:
        try:
            _close_parent_queues(ready_queue, result_queue)
        finally:
            assert not process.is_alive()
            process.close()


async def _read_templates() -> dict[str, str]:
    connection = await asyncpg.connect(_database_url())
    try:
        rows = await connection.fetch(
            "SELECT key, content FROM prompt_templates ORDER BY key"
        )
        result = {str(row["key"]): str(row["content"]) for row in rows}
        assert set(result) == {"minimaxh3", "script2assets", "script2shots", "zimage"}
        return result
    finally:
        await connection.close()


async def _write_templates(templates: dict[str, str]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        for key in ("minimaxh3", "zimage"):
            await connection.execute(
                "UPDATE prompt_templates SET content = $1 WHERE key = $2",
                templates[key],
                key,
            )
    finally:
        await connection.close()


async def _create_video_fixture(data_dir: Path) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        suffix = uuid4().hex
        style_id = int(
            await connection.fetchval(
                """
                INSERT INTO styles (name, prompt_fragment)
                VALUES ($1, 'T23 电影写实')
                RETURNING id
                """,
                f"C009 T23 style {suffix}",
            )
        )
        project_id = int(
            await connection.fetchval(
                """
                INSERT INTO projects (name, style_id)
                VALUES ($1, $2)
                RETURNING id
                """,
                f"C009 T23 project {suffix}",
                style_id,
            )
        )
        episode_id = int(
            await connection.fetchval(
                """
                INSERT INTO episodes (project_id, seq, title, script_text)
                VALUES ($1, 1, 'T23 episode', 'T23')
                RETURNING id
                """,
                project_id,
            )
        )
        character_id = int(
            await connection.fetchval(
                """
                INSERT INTO assets (project_id, type, name, description, source)
                VALUES ($1, 'character', 'T23 角色', 'T23 描述', 'manual')
                RETURNING id
                """,
                project_id,
            )
        )
        scene_id = int(
            await connection.fetchval(
                """
                INSERT INTO assets (project_id, type, name, description, source)
                VALUES ($1, 'scene', 'T23 场景', 'T23 场景描述', 'manual')
                RETURNING id
                """,
                project_id,
            )
        )
        shot_ids: list[int] = []
        for order_index, description in ((1, "T23 等待"), (2, "T23 转身")):
            shot_id = int(
                await connection.fetchval(
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
            )
            shot_ids.append(shot_id)
            await connection.executemany(
                "INSERT INTO shot_assets (shot_id, asset_id) VALUES ($1, $2)",
                [(shot_id, character_id), (shot_id, scene_id)],
            )
        clip_id = int(
            await connection.fetchval(
                """
                INSERT INTO clips (episode_id, user_note, requested_duration)
                VALUES ($1, '原始意见', 5)
                RETURNING id
                """,
                episode_id,
            )
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
            VALUES ($1, 1, $2, 'T23 角色', 'character', true)
            """,
            clip_id,
            character_id,
        )
        image_id = int(
            await connection.fetchval(
                """
                INSERT INTO asset_images
                    (asset_id, file_path, sha256, source, is_current)
                VALUES ($1, 'pending', $2, 'uploaded', true)
                RETURNING id
                """,
                character_id,
                "0" * 64,
            )
        )
        image_relative_path = asset_image_relative_path(
            project_id, character_id, image_id, "png"
        )
        image_path = data_dir / image_relative_path
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_bytes = b"c009-t23-current-image"
        image_path.write_bytes(image_bytes)
        image_digest = hashlib.sha256(image_bytes).hexdigest()
        await connection.execute(
            "UPDATE asset_images SET file_path = $1, sha256 = $2 WHERE id = $3",
            image_relative_path.as_posix(),
            image_digest,
            image_id,
        )
        return {
            "style_id": style_id,
            "project_id": project_id,
            "episode_id": episode_id,
            "clip_id": clip_id,
            "character_id": character_id,
            "scene_id": scene_id,
            "shot_ids": shot_ids,
            "image_path": image_path,
        }
    finally:
        await connection.close()


async def _create_asset_fixture() -> dict[str, int]:
    connection = await asyncpg.connect(_database_url())
    try:
        suffix = uuid4().hex
        style_id = int(
            await connection.fetchval(
                """
                INSERT INTO styles (name, prompt_fragment)
                VALUES ($1, 'T23 资产风格')
                RETURNING id
                """,
                f"C009 T23 asset style {suffix}",
            )
        )
        project_id = int(
            await connection.fetchval(
                """
                INSERT INTO projects (name, style_id)
                VALUES ($1, $2)
                RETURNING id
                """,
                f"C009 T23 asset project {suffix}",
                style_id,
            )
        )
        asset_id = int(
            await connection.fetchval(
                """
                INSERT INTO assets
                    (project_id, type, name, description, source, revision)
                VALUES ($1, 'character', 'T23 图片资产', 'T23 资产描述', 'manual', 1)
                RETURNING id
                """,
                project_id,
            )
        )
        return {
            "style_id": style_id,
            "project_id": project_id,
            "asset_id": asset_id,
        }
    finally:
        await connection.close()


async def _read_request_rows(request_id: str) -> list[dict[str, object]]:
    connection = await asyncpg.connect(_database_url())
    try:
        rows = await connection.fetch(
            """
            SELECT id, type, target_id, request_id, status, progress,
                   started_at, finished_at, payload
            FROM tasks
            WHERE request_id = $1
            ORDER BY id
            """,
            request_id,
        )
        result: list[dict[str, object]] = []
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            assert isinstance(payload, dict)
            result.append(
                {
                    "id": int(row["id"]),
                    "type": row["type"],
                    "target_id": int(row["target_id"]),
                    "request_id": row["request_id"],
                    "status": row["status"],
                    "progress": float(row["progress"]),
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                    "payload": payload,
                }
            )
        return result
    finally:
        await connection.close()


async def _read_clip(clip_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            "SELECT user_note, revision, freshness, generation_state FROM clips WHERE id = $1",
            clip_id,
        )
        assert row is not None
        return dict(row)
    finally:
        await connection.close()


async def _mark_task_done(task_id: int) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            """
            UPDATE tasks
            SET status = 'done', progress = 1.0, finished_at = now()
            WHERE id = $1
            """,
            task_id,
        )
    finally:
        await connection.close()


async def _cleanup(
    request_id: str,
    video_fixtures: list[dict[str, object]],
    asset_fixtures: list[dict[str, int]],
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute("DELETE FROM tasks WHERE request_id = $1", request_id)
        for fixture in video_fixtures:
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
            await connection.execute(
                "DELETE FROM episodes WHERE id = $1", fixture["episode_id"]
            )
            await connection.execute(
                "DELETE FROM projects WHERE id = $1", fixture["project_id"]
            )
            await connection.execute(
                "DELETE FROM styles WHERE id = $1", fixture["style_id"]
            )
        for fixture in asset_fixtures:
            await connection.execute(
                "DELETE FROM asset_images WHERE asset_id = $1", fixture["asset_id"]
            )
            await connection.execute(
                "DELETE FROM assets WHERE id = $1", fixture["asset_id"]
            )
            await connection.execute(
                "DELETE FROM projects WHERE id = $1", fixture["project_id"]
            )
            await connection.execute(
                "DELETE FROM styles WHERE id = $1", fixture["style_id"]
            )
    finally:
        await connection.close()
    for fixture in video_fixtures:
        image_path = fixture["image_path"]
        assert isinstance(image_path, Path)
        image_path.unlink(missing_ok=True)


def _assert_accepted(record: dict[str, object], task_id: int) -> None:
    assert record["status_code"] == 202
    assert record["body"] == {"task_id": task_id}


def _assert_conflict(record: dict[str, object]) -> None:
    assert record["status_code"] == 409
    assert record["body"] == {
        "detail": {"code": "conflict", "message": _CONFLICT_MESSAGE}
    }


@pytest.mark.parametrize(
    (
        "case_name",
        "left_user_note_provided",
        "left_user_note",
        "right_user_note_provided",
        "right_user_note",
        "same_identity",
    ),
    [
        ("omitted", False, None, False, None, True),
        ("explicit-null", True, None, True, None, True),
        ("empty", True, "", True, "", True),
        ("whitespace", True, "  ", True, "  ", True),
        ("different-value", True, "T23 用户意见甲", True, "T23 用户意见乙", False),
    ],
)
def test_c009_request_id_same_identity_process_race(
    case_name: str,
    left_user_note_provided: bool,
    left_user_note: str | None,
    right_user_note_provided: bool,
    right_user_note: str | None,
    same_identity: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del case_name
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    async def run() -> None:
        original_templates = await _read_templates()
        fixture: dict[str, object] | None = None
        request_id = f" c009-t23-same-{uuid4().hex} "
        try:
            await _write_templates(
                original_templates
                | {"minimaxh3": _MINIMAX_TEMPLATE, "zimage": _ZIMAGE_TEMPLATE}
            )
            fixture = await _create_video_fixture(tmp_path)
            attempts = [
                {
                    "entry": "video",
                    "target_id": fixture["clip_id"],
                    "user_note": left_user_note,
                    "user_note_provided": left_user_note_provided,
                }
                ,
                {
                    "entry": "video",
                    "target_id": fixture["clip_id"],
                    "user_note": right_user_note,
                    "user_note_provided": right_user_note_provided,
                },
            ]
            records = await _run_locked_race(
                request_id=request_id,
                attempts=attempts,
            )
            rows = await _read_request_rows(request_id.strip())
            assert len(rows) == 1
            task_id = int(rows[0]["id"])
            assert rows[0]["type"] == "gen_clip_video"
            assert rows[0]["target_id"] == fixture["clip_id"]
            assert rows[0]["request_id"] == request_id.strip()
            assert rows[0]["status"] == "queued"
            snapshot = rows[0]["payload"]["input_snapshot"]
            if same_identity:
                for record in records:
                    _assert_accepted(record, task_id)
                assert snapshot["request_identity"] == {
                    "user_note_provided": left_user_note_provided,
                    "user_note": left_user_note
                    if left_user_note_provided
                    else "原始意见",
                }
                expected_note = (
                    left_user_note
                    if left_user_note_provided
                    else "原始意见"
                )
                changed = left_user_note_provided and left_user_note != "原始意见"
                clip = await _read_clip(int(fixture["clip_id"]))
                assert clip == {
                    "user_note": expected_note,
                    "revision": 2 if changed else 1,
                    "freshness": "stale" if changed else "fresh",
                    "generation_state": "queued",
                }
            else:
                assert sorted(record["status_code"] for record in records) == [
                    202,
                    409,
                ]
                _assert_accepted(
                    next(record for record in records if record["status_code"] == 202),
                    task_id,
                )
                _assert_conflict(
                    next(record for record in records if record["status_code"] == 409)
                )
                assert snapshot["request_identity"]["user_note_provided"] is True
                assert snapshot["request_identity"]["user_note"] in {
                    left_user_note,
                    right_user_note,
                }
                clip = await _read_clip(int(fixture["clip_id"]))
                assert clip["user_note"] in {left_user_note, right_user_note}
                assert clip["revision"] == 2
                assert clip["freshness"] == "stale"
                assert clip["generation_state"] == "queued"
        finally:
            if fixture is not None:
                await _cleanup(request_id.strip(), [fixture], [])
            await _write_templates(original_templates)
            await engine.dispose()

    asyncio.run(run())


def test_c009_request_id_different_clip_and_cross_type_process_race(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    async def run() -> None:
        original_templates = await _read_templates()
        first: dict[str, object] | None = None
        second: dict[str, object] | None = None
        asset: dict[str, int] | None = None
        different_clip_request: str | None = None
        cross_type_request: str | None = None
        try:
            await _write_templates(
                original_templates
                | {"minimaxh3": _MINIMAX_TEMPLATE, "zimage": _ZIMAGE_TEMPLATE}
            )
            first = await _create_video_fixture(tmp_path)
            second = await _create_video_fixture(tmp_path)
            different_clip_request = f" c009-t23-clip-{uuid4().hex} "
            clip_records = await _run_locked_race(
                request_id=different_clip_request,
                attempts=[
                    {
                        "entry": "video",
                        "target_id": first["clip_id"],
                        "user_note": None,
                        "user_note_provided": False,
                    },
                    {
                        "entry": "video",
                        "target_id": second["clip_id"],
                        "user_note": None,
                        "user_note_provided": False,
                    },
                ],
            )
            assert sorted(record["status_code"] for record in clip_records) == [
                202,
                409,
            ]
            winner_rows = await _read_request_rows(different_clip_request.strip())
            assert len(winner_rows) == 1
            _assert_accepted(
                next(record for record in clip_records if record["status_code"] == 202),
                int(winner_rows[0]["id"]),
            )
            _assert_conflict(
                next(record for record in clip_records if record["status_code"] == 409)
            )
            assert winner_rows[0]["type"] == "gen_clip_video"
            assert winner_rows[0]["target_id"] in {
                first["clip_id"],
                second["clip_id"],
            }
            first_clip = await _read_clip(int(first["clip_id"]))
            second_clip = await _read_clip(int(second["clip_id"]))
            assert sorted(
                [first_clip["generation_state"], second_clip["generation_state"]]
            ) == ["empty", "queued"]
            assert first_clip["user_note"] == "原始意见"
            assert second_clip["user_note"] == "原始意见"
            assert first_clip["revision"] == 1
            assert second_clip["revision"] == 1

            asset = await _create_asset_fixture()
            cross_type_request = f" c009-t23-cross-{uuid4().hex} "
            cross_records = await _run_locked_race(
                request_id=cross_type_request,
                attempts=[
                    {
                        "entry": "video",
                        "target_id": first["clip_id"],
                        "user_note": None,
                        "user_note_provided": False,
                    },
                    {
                        "entry": "asset",
                        "target_id": asset["asset_id"],
                    },
                ],
            )
            assert sorted(record["status_code"] for record in cross_records) == [
                202,
                409,
            ]
            cross_rows = await _read_request_rows(cross_type_request.strip())
            assert len(cross_rows) == 1
            winner = cross_rows[0]
            assert winner["type"] in {"gen_clip_video", "gen_asset_image"}
            assert winner["target_id"] in {
                first["clip_id"],
                asset["asset_id"],
            }
            _assert_accepted(
                next(record for record in cross_records if record["status_code"] == 202),
                int(winner["id"]),
            )
            _assert_conflict(
                next(record for record in cross_records if record["status_code"] == 409)
            )
        finally:
            if asset is not None and cross_type_request is not None:
                await _cleanup(
                    cross_type_request.strip(),
                    [fixture for fixture in (first,) if fixture is not None],
                    [asset],
                )
            if (
                first is not None
                and second is not None
                and different_clip_request is not None
            ):
                await _cleanup(
                    different_clip_request.strip(), [second, first], []
                )
            await _write_templates(original_templates)
            await engine.dispose()

    asyncio.run(run())


def test_c009_request_id_terminal_replay_process_preserves_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    async def run() -> None:
        original_templates = await _read_templates()
        fixture: dict[str, object] | None = None
        request_id = f" c009-t23-terminal-{uuid4().hex} "
        try:
            await _write_templates(
                original_templates
                | {"minimaxh3": _MINIMAX_TEMPLATE, "zimage": _ZIMAGE_TEMPLATE}
            )
            fixture = await _create_video_fixture(tmp_path)
            first = await _run_single_attempt(
                {
                    "entry": "video",
                    "target_id": fixture["clip_id"],
                    "user_note": None,
                    "user_note_provided": False,
                    "request_id": request_id,
                }
            )
            first_rows = await _read_request_rows(request_id.strip())
            assert len(first_rows) == 1
            first_task_id = int(first_rows[0]["id"])
            _assert_accepted(first, first_task_id)
            await _mark_task_done(first_task_id)
            terminal_rows = await _read_request_rows(request_id.strip())
            assert len(terminal_rows) == 1
            assert terminal_rows[0]["status"] == "done"
            assert terminal_rows[0]["payload"]["input_snapshot"]["seed"] == (
                first_rows[0]["payload"]["input_snapshot"]["seed"]
            )
            clip_before_replay = await _read_clip(int(fixture["clip_id"]))

            replay = await _run_single_attempt(
                {
                    "entry": "video",
                    "target_id": fixture["clip_id"],
                    "user_note": None,
                    "user_note_provided": False,
                    "request_id": request_id,
                }
            )
            _assert_accepted(replay, first_task_id)
            replay_rows = await _read_request_rows(request_id.strip())
            assert replay_rows == terminal_rows
            assert replay_rows[0]["payload"] == terminal_rows[0]["payload"]
            assert replay_rows[0]["payload"]["input_snapshot"]["seed"] == (
                terminal_rows[0]["payload"]["input_snapshot"]["seed"]
            )
            assert await _read_clip(int(fixture["clip_id"])) == clip_before_replay
        finally:
            if fixture is not None:
                await _cleanup(request_id.strip(), [fixture], [])
            await _write_templates(original_templates)
            await engine.dispose()

    asyncio.run(run())
