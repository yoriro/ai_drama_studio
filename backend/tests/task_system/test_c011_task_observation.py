from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import socket
from queue import Empty as QueueEmpty
from typing import Any
from urllib.parse import urlsplit

import asyncpg
import httpx
import uvicorn
from websockets.asyncio.client import connect

from app.db.session import async_session_factory, engine
from app.main import create_app
from app.tasks.queue import ClaimedTask, TaskQueue, WorkerContext


class _NoopHealthClient:
    async def health(self) -> None:
        return None


def _noop_health_client(_base_url: str) -> _NoopHealthClient:
    return _NoopHealthClient()


async def _startup_prepare() -> None:
    return None


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _database_name() -> str:
    name = urlsplit(_database_url()).path.lstrip("/")
    if not name:
        raise AssertionError("DATABASE_URL does not contain a database name")
    return name


def _payload(label: str) -> dict[str, object]:
    return {
        "input_snapshot": {"c011_t22_label": label},
        "input_hash": None,
        "source_revisions": {},
    }


async def _enqueue_task(
    task_queue: TaskQueue, *, label: str, target_id: int
) -> int:
    async with async_session_factory() as session:
        async with session.begin():
            result = await task_queue.enqueue(
                session,
                "gen_assets",
                target_id,
                _payload(label),
            )
            return int(result.task.id)


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _serve_process(
    port: int,
    handler_commands: Any,
    server_commands: Any,
    process_events: Any,
) -> None:
    async def controlled_handler(
        task: ClaimedTask, context: WorkerContext
    ) -> None:
        await context.heartbeat(progress=0.5)
        process_events.put(
            {
                "kind": "barrier_reached",
                "pid": os.getpid(),
                "task_id": task.id,
            }
        )
        command = await asyncio.to_thread(handler_commands.get)
        if not isinstance(command, dict):
            raise RuntimeError("T22 handler barrier command is not an object")
        if command.get("action") != "release":
            raise RuntimeError(
                f"T22 handler barrier action is invalid: {command!r}"
            )
        if command.get("task_id") != task.id:
            raise RuntimeError(
                "T22 handler barrier task mismatch: "
                f"expected {task.id}, received {command!r}"
            )
        process_events.put(
            {
                "kind": "barrier_released",
                "pid": os.getpid(),
                "task_id": task.id,
            }
        )

    async def run() -> None:
        application = create_app(
            task_handlers={"gen_assets": controlled_handler},
            startup_prepare=_startup_prepare,
            vllm_client_factory=_noop_health_client,
            comfy_client_factory=_noop_health_client,
        )
        server = uvicorn.Server(
            uvicorn.Config(
                application,
                host="127.0.0.1",
                port=port,
                log_level="error",
                access_log=False,
            )
        )
        server_task = asyncio.create_task(server.serve())
        while not server.started:
            if server_task.done():
                await server_task
                raise RuntimeError("T22 server stopped before becoming ready")
            await asyncio.sleep(0.01)

        process_events.put(
            {"kind": "ready", "pid": os.getpid(), "port": port}
        )
        command = await asyncio.to_thread(server_commands.get)
        if not isinstance(command, dict) or command.get("action") != "shutdown":
            raise RuntimeError(f"T22 server shutdown command is invalid: {command!r}")
        server.should_exit = True
        await server_task
        process_events.put({"kind": "stopped", "pid": os.getpid()})

    asyncio.run(run())


async def _wait_for_process_event(
    process_events: Any, predicate: Any, description: str
) -> dict[str, object]:
    try:
        record = await asyncio.to_thread(process_events.get, timeout=20)
    except QueueEmpty as exc:
        raise AssertionError(f"timeout waiting for {description}") from exc
    if not isinstance(record, dict):
        raise AssertionError(f"invalid process event for {description}: {record!r}")
    if predicate(record):
        return record
    raise AssertionError(
        f"unexpected process event while waiting for {description}: {record!r}"
    )


async def _receive_task_event(
    websocket: Any,
    observed_events: list[dict[str, object]],
    *,
    task_id: int,
    status: str,
    progress: float,
    message: str,
) -> dict[str, object]:
    try:
        raw_message = await asyncio.wait_for(websocket.recv(), timeout=20)
    except asyncio.TimeoutError as exc:
        raise AssertionError(
            f"timeout waiting for WS task_id={task_id} "
            f"status={status} message={message}"
        ) from exc
    raw_text = (
        raw_message.decode("utf-8")
        if isinstance(raw_message, bytes)
        else raw_message
    )
    event = json.loads(raw_text)
    if not isinstance(event, dict):
        raise AssertionError(f"WS event is not an object: {event!r}")
    if set(event) != {"task_id", "type", "status", "progress", "message"}:
        raise AssertionError(f"WS event shape changed: {event!r}")
    observed_events.append(event)
    if (
        event["task_id"] == task_id
        and event["status"] == status
        and event["progress"] == progress
        and event["message"] == message
    ):
        return event
    return await _receive_task_event(
        websocket,
        observed_events,
        task_id=task_id,
        status=status,
        progress=progress,
        message=message,
    )


async def _read_rest_task(client: httpx.AsyncClient, task_id: int) -> dict[str, Any]:
    response = await client.get(f"/api/tasks/{task_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == task_id
    return body


async def _read_db_task(task_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"
        )
        current_database = await connection.fetchval("SELECT current_database()")
        row = await connection.fetchrow(
            """
            SELECT id, status, progress, cancel_requested_at, finished_at
            FROM tasks
            WHERE id = $1
            """,
            task_id,
        )
    finally:
        await connection.close()
    assert current_database == _database_name()
    assert row is not None
    return {
        "current_database": current_database,
        "id": int(row["id"]),
        "status": row["status"],
        "progress": float(row["progress"]),
        "cancel_requested": row["cancel_requested_at"] is not None,
        "finished": row["finished_at"] is not None,
    }


async def _join_child(process: multiprocessing.Process) -> None:
    await asyncio.to_thread(process.join, 30)
    if process.is_alive():
        process.terminate()
        await asyncio.to_thread(process.join, 5)
    if process.is_alive():
        process.kill()
        await asyncio.to_thread(process.join, 5)
    assert not process.is_alive()


def _close_queue(value: Any) -> None:
    value.close()
    value.join_thread()


def test_c011_cross_process_cancel_observation_matches_rest_ws_and_db() -> None:
    async def run() -> None:
        context = multiprocessing.get_context("spawn")
        handler_commands = context.Queue()
        server_commands = context.Queue()
        process_events = context.Queue()
        port = _available_port()
        process = context.Process(
            target=_serve_process,
            args=(port, handler_commands, server_commands, process_events),
        )
        process.start()
        reached: list[int] = []
        released: set[int] = set()
        shutdown_requested = False
        observed_events: list[dict[str, object]] = []
        post_calls: list[int] = []
        observations: dict[str, object] = {
            "port": port,
            "handler": "create_app task_handlers gen_assets barrier",
            "external_clients": "injected health probes only",
            "barriers": {"reached": reached, "released": []},
            "post_calls": post_calls,
            "rest": {},
            "ws": observed_events,
            "db": {},
        }
        task_queue = TaskQueue(async_session_factory)
        base_target = 1_000_000 + (os.getpid() % 100_000) * 10
        websocket: Any = None
        try:
            ready = await _wait_for_process_event(
                process_events,
                lambda record: record.get("kind") == "ready",
                "backend process ready",
            )
            assert ready["pid"] == process.pid
            assert ready["port"] == port

            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}",
                timeout=20,
                trust_env=False,
            ) as client:
                websocket = await connect(
                    f"ws://127.0.0.1:{port}/ws/tasks",
                    open_timeout=20,
                    close_timeout=5,
                )
                first = await _enqueue_task(
                    task_queue,
                    label="running-then-done",
                    target_id=base_target + 1,
                )
                reached_event = await _wait_for_process_event(
                    process_events,
                    lambda record: record.get("kind") == "barrier_reached"
                    and record.get("task_id") == first,
                    f"task {first} barrier reached",
                )
                assert reached_event["pid"] == process.pid
                reached.append(first)
                await _receive_task_event(
                    websocket,
                    observed_events,
                    task_id=first,
                    status="running",
                    progress=0.0,
                    message="任务执行中",
                )
                await _receive_task_event(
                    websocket,
                    observed_events,
                    task_id=first,
                    status="running",
                    progress=0.5,
                    message="任务执行中",
                )
                first_running = await _read_rest_task(client, first)
                assert first_running["status"] == "running"
                assert first_running["progress"] == 0.5
                assert first_running["cancel_requested_at"] is None
                observations["rest"] = {"first_running": first_running}

                queued = await _enqueue_task(
                    task_queue,
                    label="queued-cancel",
                    target_id=base_target + 2,
                )
                queued_before = await _read_rest_task(client, queued)
                assert queued_before["status"] == "queued"
                post_calls.append(queued)
                queued_response = await client.post(
                    f"/api/tasks/{queued}/cancel"
                )
                assert queued_response.status_code == 200, queued_response.text
                queued_body = queued_response.json()
                assert queued_body["id"] == queued
                assert queued_body["status"] == "canceled"
                assert queued_body["cancel_requested_at"] is None
                await _receive_task_event(
                    websocket,
                    observed_events,
                    task_id=queued,
                    status="canceled",
                    progress=0.0,
                    message="任务已取消",
                )
                queued_after = await _read_rest_task(client, queued)
                assert queued_after["status"] == "canceled"
                assert queued_after["cancel_requested_at"] is None
                queued_db = await _read_db_task(queued)
                assert queued_db == {
                    "current_database": _database_name(),
                    "id": queued,
                    "status": "canceled",
                    "progress": 0.0,
                    "cancel_requested": False,
                    "finished": True,
                }
                observations["rest"]["queued_cancel"] = {
                    "before": queued_before,
                    "post": queued_body,
                    "after": queued_after,
                }
                observations["db"]["queued_cancel"] = queued_db

                handler_commands.put({"action": "release", "task_id": first})
                released.add(first)
                first_released = await _wait_for_process_event(
                    process_events,
                    lambda record: record.get("kind") == "barrier_released"
                    and record.get("task_id") == first,
                    f"task {first} barrier released",
                )
                assert first_released["pid"] == process.pid
                observations["barriers"]["released"].append(first)
                await _receive_task_event(
                    websocket,
                    observed_events,
                    task_id=first,
                    status="done",
                    progress=1.0,
                    message="任务完成",
                )
                first_done = await _read_rest_task(client, first)
                assert first_done["status"] == "done"
                assert first_done["progress"] == 1.0
                assert first_done["cancel_requested_at"] is None
                observations["rest"]["first_done"] = first_done

                running = await _enqueue_task(
                    task_queue,
                    label="running-cancel-safe-point",
                    target_id=base_target + 3,
                )
                running_reached = await _wait_for_process_event(
                    process_events,
                    lambda record: record.get("kind") == "barrier_reached"
                    and record.get("task_id") == running,
                    f"task {running} barrier reached",
                )
                assert running_reached["pid"] == process.pid
                reached.append(running)
                await _receive_task_event(
                    websocket,
                    observed_events,
                    task_id=running,
                    status="running",
                    progress=0.0,
                    message="任务执行中",
                )
                await _receive_task_event(
                    websocket,
                    observed_events,
                    task_id=running,
                    status="running",
                    progress=0.5,
                    message="任务执行中",
                )
                post_calls.append(running)
                running_response = await client.post(
                    f"/api/tasks/{running}/cancel"
                )
                assert running_response.status_code == 200, running_response.text
                running_body = running_response.json()
                assert running_body["id"] == running
                assert running_body["status"] == "running"
                assert running_body["cancel_requested_at"] is not None
                await _receive_task_event(
                    websocket,
                    observed_events,
                    task_id=running,
                    status="running",
                    progress=0.5,
                    message="已请求取消",
                )
                running_requested = await _read_rest_task(client, running)
                assert running_requested["status"] == "running"
                assert running_requested["cancel_requested_at"] is not None
                running_requested_db = await _read_db_task(running)
                assert running_requested_db == {
                    "current_database": _database_name(),
                    "id": running,
                    "status": "running",
                    "progress": 0.5,
                    "cancel_requested": True,
                    "finished": False,
                }
                observations["rest"]["running_requested"] = running_requested
                observations["db"]["running_requested"] = running_requested_db

                handler_commands.put({"action": "release", "task_id": running})
                released.add(running)
                running_released = await _wait_for_process_event(
                    process_events,
                    lambda record: record.get("kind") == "barrier_released"
                    and record.get("task_id") == running,
                    f"task {running} barrier released",
                )
                assert running_released["pid"] == process.pid
                observations["barriers"]["released"].append(running)
                await _receive_task_event(
                    websocket,
                    observed_events,
                    task_id=running,
                    status="canceled",
                    progress=0.5,
                    message="任务已取消",
                )
                running_canceled = await _read_rest_task(client, running)
                assert running_canceled["status"] == "canceled"
                assert running_canceled["cancel_requested_at"] is not None
                running_canceled_db = await _read_db_task(running)
                assert running_canceled_db == {
                    "current_database": _database_name(),
                    "id": running,
                    "status": "canceled",
                    "progress": 0.5,
                    "cancel_requested": True,
                    "finished": True,
                }
                observations["rest"]["running_canceled"] = running_canceled
                observations["db"]["running_canceled"] = running_canceled_db

                done_first = await _enqueue_task(
                    task_queue,
                    label="done-before-cancel",
                    target_id=base_target + 4,
                )
                done_reached = await _wait_for_process_event(
                    process_events,
                    lambda record: record.get("kind") == "barrier_reached"
                    and record.get("task_id") == done_first,
                    f"task {done_first} barrier reached",
                )
                assert done_reached["pid"] == process.pid
                reached.append(done_first)
                await _receive_task_event(
                    websocket,
                    observed_events,
                    task_id=done_first,
                    status="running",
                    progress=0.0,
                    message="任务执行中",
                )
                await _receive_task_event(
                    websocket,
                    observed_events,
                    task_id=done_first,
                    status="running",
                    progress=0.5,
                    message="任务执行中",
                )
                handler_commands.put(
                    {"action": "release", "task_id": done_first}
                )
                released.add(done_first)
                done_released = await _wait_for_process_event(
                    process_events,
                    lambda record: record.get("kind") == "barrier_released"
                    and record.get("task_id") == done_first,
                    f"task {done_first} barrier released",
                )
                assert done_released["pid"] == process.pid
                observations["barriers"]["released"].append(done_first)
                await _receive_task_event(
                    websocket,
                    observed_events,
                    task_id=done_first,
                    status="done",
                    progress=1.0,
                    message="任务完成",
                )
                done_body = await _read_rest_task(client, done_first)
                assert done_body["status"] == "done"
                done_db = await _read_db_task(done_first)
                assert done_db == {
                    "current_database": _database_name(),
                    "id": done_first,
                    "status": "done",
                    "progress": 1.0,
                    "cancel_requested": False,
                    "finished": True,
                }
                observations["rest"]["done_before_cancel"] = done_body
                observations["db"]["done_before_cancel"] = done_db

                post_calls.append(done_first)
                done_cancel_response = await client.post(
                    f"/api/tasks/{done_first}/cancel"
                )
                assert done_cancel_response.status_code == 409
                done_cancel_body = done_cancel_response.json()
                assert done_cancel_body == {
                    "detail": {
                        "code": "conflict",
                        "message": f"task {done_first} is already terminal",
                    }
                }
                done_after_conflict = await _read_rest_task(client, done_first)
                assert done_after_conflict["status"] == "done"
                done_after_conflict_db = await _read_db_task(done_first)
                assert done_after_conflict_db == done_db
                observations["rest"]["done_cancel_409"] = done_cancel_body
                observations["rest"]["done_after_conflict"] = done_after_conflict
                observations["db"]["done_after_conflict"] = done_after_conflict_db

                await websocket.close()
                websocket = None

            server_commands.put({"action": "shutdown"})
            shutdown_requested = True
            stopped = await _wait_for_process_event(
                process_events,
                lambda record: record.get("kind") == "stopped",
                "backend process stopped",
            )
            assert stopped["pid"] == process.pid
            await _join_child(process)
            assert process.exitcode == 0
            observations["process"] = {
                "pid": process.pid,
                "exitcode": process.exitcode,
                "alive": process.is_alive(),
            }

            task_ids = [first, queued, running, done_first]
            assert post_calls == [queued, running, done_first]
            assert reached == [first, running, done_first]
            assert observations["barriers"]["released"] == [
                first,
                running,
                done_first,
            ]
            by_task = {
                task_id: [event for event in observed_events if event["task_id"] == task_id]
                for task_id in task_ids
            }
            assert [event["status"] for event in by_task[first]] == [
                "running",
                "running",
                "done",
            ]
            assert [event["status"] for event in by_task[queued]] == ["canceled"]
            assert [event["status"] for event in by_task[running]] == [
                "running",
                "running",
                "running",
                "canceled",
            ]
            assert [event["status"] for event in by_task[done_first]] == [
                "running",
                "running",
                "done",
            ]
            assert sum(
                event["status"] == "running" and event["progress"] == 0.0
                for event in observed_events
            ) == 3
            print(
                "T22_OBSERVATION "
                + json.dumps(observations, ensure_ascii=False, sort_keys=True)
            )
        finally:
            if websocket is not None:
                await websocket.close()
            for task_id in reached:
                if task_id not in released:
                    handler_commands.put({"action": "release", "task_id": task_id})
            if process.is_alive() and not shutdown_requested:
                server_commands.put({"action": "shutdown"})
            await _join_child(process)
            await engine.dispose()
            _close_queue(handler_commands)
            _close_queue(server_commands)
            _close_queue(process_events)
            process.close()

    asyncio.run(run())
