from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
import queue
import socket
import threading
import time
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import asyncpg
import httpx
import pytest
from websockets.asyncio.server import ServerConnection, serve

from app.core.config import settings
from app.db.session import async_session_factory, engine
from app.integrations.workflow_binding import load_minimax_binding_snapshot
from app.services.clip_video_inputs import build_minimaxh3_response_format
from app.services.generate_clip_video import enqueue_generate_clip_video
from app.tasks import gen_clip_video as video_task
from app.tasks.queue import TaskQueue
from tests.api.test_c009_generate_video import _cleanup_fixture, _create_fixture


_stub_mode = "wake"
_stub_records: Any = None
_stub_prompt_submitted: threading.Event | None = None


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _record(record: dict[str, object]) -> None:
    if _stub_records is None:
        raise RuntimeError("T25 stub record queue is not configured")
    _stub_records.put(record)


def _multipart_body(body: bytes, content_type: str) -> dict[str, object]:
    message = BytesParser(policy=default).parsebytes(
        b"Content-Type: "
        + content_type.encode("ascii")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + body
    )
    fields: dict[str, str] = {}
    image: dict[str, object] | None = None
    for part in message.iter_parts():
        field_name = part.get_param("name", header="content-disposition")
        if field_name == "image":
            filename = part.get_filename()
            content = part.get_payload(decode=True)
            if not isinstance(filename, str) or not isinstance(content, bytes):
                raise ValueError("T25 upload image part is invalid")
            image = {"filename": filename, "content": content}
            continue
        value = part.get_payload(decode=True)
        if not isinstance(field_name, str) or not isinstance(value, bytes):
            raise ValueError("T25 upload form part is invalid")
        fields[field_name] = value.decode("utf-8")
    if image is None:
        raise ValueError("T25 upload image part is missing")
    return {"fields": fields, "image": image}


def _request_body(path: str, body: bytes, content_type: str | None) -> object:
    if not body:
        return None
    if path == "/upload/image":
        if not isinstance(content_type, str):
            raise ValueError("T25 upload content type is missing")
        return _multipart_body(body, content_type)
    return json.loads(body)


class _WorkerFailureHTTPHandler(BaseHTTPRequestHandler):
    server_version = "C009WorkerFailureStub/1.0"

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _body(self) -> bytes:
        content_length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(content_length)

    def _send_json(self, status: int, payload: object) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:
        path_with_query = self.path
        path = urlsplit(path_with_query).path
        body = self._body()
        content_type = self.headers.get("Content-Type")
        started = time.perf_counter_ns()

        if path == "/wake_up":
            status = 503 if _stub_mode == "wake" else 200
            self._send_json(status, {} if status == 200 else {"error": "T25 wake failure"})
        elif path == "/v1/chat/completions":
            status = 200
            self._send_json(
                status,
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"prompt": "T25 built prompt"}
                                )
                            }
                        }
                    ]
                },
            )
        elif path == "/sleep":
            status = 503 if _stub_mode == "sleep" else 200
            self._send_json(status, {} if status == 200 else {"error": "T25 sleep failure"})
        elif path == "/upload/image":
            status = 200
            parsed = _multipart_body(body, content_type or "")
            fields = parsed["fields"]
            image = parsed["image"]
            if not isinstance(fields, dict) or not isinstance(image, dict):
                raise ValueError("T25 parsed upload body is invalid")
            filename = image.get("filename")
            subfolder = fields.get("subfolder")
            if not isinstance(filename, str) or not isinstance(subfolder, str):
                raise ValueError("T25 upload identity is invalid")
            self._send_json(
                status,
                {
                    "name": filename,
                    "subfolder": subfolder,
                    "type": "input",
                },
            )
        elif path == "/prompt":
            status = 200
            request = json.loads(body)
            prompt_id = request["prompt_id"]
            if not isinstance(prompt_id, str):
                raise ValueError("T25 prompt id is invalid")
            if _stub_prompt_submitted is None:
                raise RuntimeError("T25 submit barrier is not configured")
            _stub_prompt_submitted.set()
            self._send_json(status, {"prompt_id": prompt_id})
        elif path == "/free":
            status = 200
            self._send_json(status, {})
        else:
            status = 404
            self._send_json(status, {"error": "not found"})

        _record(
            {
                "kind": "http",
                "method": "POST",
                "path": path_with_query,
                "body": _request_body(path, body, content_type),
                "status": status,
                "raw_body_sha256": hashlib.sha256(body).hexdigest(),
                "raw_body_length": len(body),
                "start_ns": started,
                "end_ns": time.perf_counter_ns(),
            }
        )


async def _worker_failure_websocket(connection: ServerConnection) -> None:
    if _stub_prompt_submitted is None:
        raise RuntimeError("T25 websocket barrier is not configured")
    request_path = connection.request.path
    prompt_ids = parse_qs(urlsplit(request_path).query).get("clientId", [])
    if len(prompt_ids) != 1 or not isinstance(prompt_ids[0], str):
        raise RuntimeError("T25 websocket clientId is invalid")
    prompt_id = prompt_ids[0]
    submitted = await asyncio.to_thread(_stub_prompt_submitted.wait, 15)
    if not submitted:
        raise RuntimeError("T25 websocket submit barrier timed out")

    ignored_message = {
        "type": "execution_error",
        "data": {
            "prompt_id": "unrelated-prompt-id",
            "node": None,
            "node_type": None,
            "exception_message": None,
        },
    }
    ignored_started = time.perf_counter_ns()
    await connection.send(json.dumps(ignored_message, ensure_ascii=False))
    _record(
        {
            "kind": "ws_ignored",
            "method": "WS",
            "path": request_path,
            "body": ignored_message,
            "start_ns": ignored_started,
            "end_ns": time.perf_counter_ns(),
        }
    )

    message = {
        "type": "execution_error",
        "data": {
            "prompt_id": prompt_id,
            "node": "168",
            "node_type": "T25StubNode",
            "exception_message": "T25 WS stage failure",
        },
    }
    started = time.perf_counter_ns()
    await connection.send(json.dumps(message, ensure_ascii=False))
    _record(
        {
            "kind": "ws",
            "method": "WS",
            "path": request_path,
            "body": message,
            "start_ns": started,
            "end_ns": time.perf_counter_ns(),
        }
    )


def _run_worker_failure_stub(
    mode: str, ready: Any, records: Any, stop_event: Any
) -> None:
    global _stub_mode, _stub_records, _stub_prompt_submitted
    _stub_mode = mode
    _stub_records = records
    _stub_prompt_submitted = threading.Event()
    _record({"kind": "lifecycle", "event": "started", "pid": os.getpid()})

    http_server = ThreadingHTTPServer(
        ("127.0.0.1", 0), _WorkerFailureHTTPHandler
    )
    http_thread = threading.Thread(
        target=http_server.serve_forever,
        name="c009-worker-failure-http",
        daemon=True,
    )
    http_thread.start()

    async def run() -> None:
        websocket_server = await serve(
            _worker_failure_websocket,
            "127.0.0.1",
            0,
        )
        websocket_port = websocket_server.sockets[0].getsockname()[1]
        ready.put(
            {
                "http_port": http_server.server_port,
                "websocket_port": websocket_port,
            }
        )
        ready.close()
        ready.join_thread()
        await asyncio.to_thread(stop_event.wait)
        websocket_server.close()
        await websocket_server.wait_closed()

    try:
        asyncio.run(run())
    finally:
        http_server.shutdown()
        http_server.server_close()
        http_thread.join()
        _record({"kind": "lifecycle", "event": "stopped", "pid": os.getpid()})
        records.close()
        records.join_thread()


def _close_queue(value: Any) -> None:
    value.close()
    value.join_thread()


def _terminate_process(process: Any, stop_event: Any) -> None:
    stop_event.set()
    process.join(timeout=15)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)


def _start_worker_failure_stub(
    mode: str,
) -> tuple[Any, Any, Any, Any, int, int]:
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    records = context.Queue()
    stop_event = context.Event()
    process = context.Process(
        target=_run_worker_failure_stub,
        args=(mode, ready, records, stop_event),
    )
    process.start()
    try:
        ports = ready.get(timeout=15)
    except queue.Empty as exc:
        _terminate_process(process, stop_event)
        _close_queue(ready)
        _close_queue(records)
        process.close()
        raise AssertionError("T25 worker failure stub did not start") from exc

    if not isinstance(ports, dict):
        _terminate_process(process, stop_event)
        _close_queue(ready)
        _close_queue(records)
        process.close()
        raise AssertionError("T25 worker failure stub ports are invalid")
    http_port = ports.get("http_port")
    websocket_port = ports.get("websocket_port")
    if not isinstance(http_port, int) or not isinstance(websocket_port, int):
        _terminate_process(process, stop_event)
        _close_queue(ready)
        _close_queue(records)
        process.close()
        raise AssertionError("T25 worker failure stub ports are invalid")
    return process, stop_event, ready, records, http_port, websocket_port


def _drain_worker_failure_records(records: Any) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    while True:
        try:
            value = records.get(timeout=5)
        except queue.Empty:
            return values
        if not isinstance(value, dict):
            raise AssertionError("T25 worker failure stub record is invalid")
        values.append(value)
        if value.get("kind") == "lifecycle" and value.get("event") == "stopped":
            return values


def _stop_worker_failure_stub(
    process: Any,
    stop_event: Any,
    ready: Any,
    records: Any,
) -> dict[str, object]:
    _terminate_process(process, stop_event)
    pid = process.pid
    exit_code = process.exitcode
    alive = process.is_alive()
    try:
        events = _drain_worker_failure_records(records)
    finally:
        _close_queue(ready)
        _close_queue(records)
        process.close()
    return {"pid": pid, "exitcode": exit_code, "alive": alive, "events": events}


def _assert_port_closed(port: int) -> None:
    with pytest.raises(OSError):
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            pass


def _real_comfy_factory(websocket_port: int):
    from app.integrations.comfy import ComfyClient

    def factory(base_url: str) -> ComfyClient:
        client = ComfyClient(base_url)
        client._websocket_base_url = f"ws://127.0.0.1:{websocket_port}"
        return client

    return factory


def _inventory(data_dir: Path) -> list[str]:
    if not data_dir.exists():
        return []
    return sorted(
        path.relative_to(data_dir).as_posix()
        for path in data_dir.rglob("*")
        if path.is_file()
    )


async def _run_failure_scenario(data_dir: Path) -> dict[str, object]:
    fixture: dict[str, object] | None = None
    try:
        fixture = await _create_fixture(data_dir)
        before_clip = await _read_clip_state(int(fixture["clip_id"]))
        before_inventory = _inventory(data_dir)
        task_id = await _enqueue_and_run(fixture)
        state = await _read_failure_state(task_id, int(fixture["clip_id"]))
        return {
            "fixture": fixture,
            "before_clip": before_clip,
            "before_inventory": before_inventory,
            "task_id": task_id,
            "state": state,
        }
    finally:
        try:
            if fixture is not None:
                await _cleanup_fixture(fixture)
        finally:
            await engine.dispose()


async def _enqueue_and_run(fixture: dict[str, object]) -> int:
    binding = load_minimax_binding_snapshot()
    queue_service = TaskQueue(async_session_factory)
    async with async_session_factory() as session:
        result = await enqueue_generate_clip_video(
            session,
            queue_service,
            int(fixture["clip_id"]),
            user_note=None,
            user_note_provided=False,
            request_id=None,
            workflow_binding=binding,
        )
        assert result.created is True
        task_id = int(result.task.id)
    await queue_service.run_worker(
        handlers={"gen_clip_video": video_task.gen_clip_video_task_handler},
        poll_interval=0,
        stop_when_idle=True,
    )
    return task_id


async def _read_clip_state(clip_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT user_note, revision, freshness, generation_state,
                   prompt_cache, prompt_input_hash
            FROM clips
            WHERE id = $1
            """,
            clip_id,
        )
        if row is None:
            raise AssertionError("T25 Clip row is missing")
        return dict(row)
    finally:
        await connection.close()


async def _read_failure_state(task_id: int, clip_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        task = await connection.fetchrow(
            """
            SELECT id, type, target_id, status, progress, error_msg,
                   started_at, finished_at, payload
            FROM tasks
            WHERE id = $1
            """,
            task_id,
        )
        clip = await connection.fetchrow(
            """
            SELECT user_note, revision, freshness, generation_state,
                   prompt_cache, prompt_input_hash
            FROM clips
            WHERE id = $1
            """,
            clip_id,
        )
        counts = await connection.fetchrow(
            """
            SELECT count(*)::int AS total,
                   count(*) FILTER (WHERE status = 'queued')::int AS queued,
                   count(*) FILTER (WHERE status = 'running')::int AS running,
                   count(*) FILTER (WHERE status = 'done')::int AS done,
                   count(*) FILTER (WHERE status = 'failed')::int AS failed
            FROM tasks
            WHERE target_id = $1 AND type = 'gen_clip_video'
            """,
            clip_id,
        )
        video_count = await connection.fetchval(
            "SELECT count(*) FROM clip_videos WHERE clip_id = $1", clip_id
        )
        if task is None or clip is None or counts is None:
            raise AssertionError("T25 failure state row is missing")
        task_value = dict(task)
        payload_value = task_value["payload"]
        payload = json.loads(payload_value) if isinstance(payload_value, str) else payload_value
        if not isinstance(payload, dict):
            raise AssertionError("T25 task payload must decode to a JSON object")
        task_value["payload"] = payload
        return {
            "task": task_value,
            "clip": dict(clip),
            "counts": dict(counts),
            "video_count": int(video_count),
        }
    finally:
        await connection.close()


def _expected_http_error(url: str) -> str:
    response = httpx.Response(503, request=httpx.Request("POST", url))
    with pytest.raises(httpx.HTTPStatusError) as raised:
        response.raise_for_status()
    return str(raised.value)


def _assert_failure_error(
    error_msg: object,
    *,
    mode: str,
    http_port: int,
) -> None:
    assert isinstance(error_msg, str)
    assert error_msg.startswith("Traceback (most recent call last):\n")
    if mode == "wake":
        expected = _expected_http_error(
            f"http://127.0.0.1:{http_port}/wake_up"
        )
        assert error_msg.endswith(f"httpx.HTTPStatusError: {expected}\n")
    elif mode == "sleep":
        expected = _expected_http_error(
            f"http://127.0.0.1:{http_port}/sleep?level=1"
        )
        assert error_msg.endswith(f"httpx.HTTPStatusError: {expected}\n")
    else:
        assert error_msg.splitlines()[-1] == (
            "RuntimeError: Comfy execution_error "
            "node=168 type=T25StubNode exception=T25 WS stage failure"
        )


def _assert_http_event(
    event: dict[str, object],
    *,
    method: str,
    path: str,
    body: object,
    status: int,
) -> None:
    assert event["kind"] == "http"
    assert event["method"] == method
    assert event["path"] == path
    assert event["body"] == body
    assert event["status"] == status
    assert isinstance(event["raw_body_sha256"], str)
    assert len(event["raw_body_sha256"]) == 64
    assert int(event["end_ns"]) >= int(event["start_ns"])


def _chat_body(snapshot: dict[str, object]) -> dict[str, object]:
    return {
        "model": snapshot["model"],
        "messages": [{"role": "user", "content": snapshot["rendered_prompt"]}],
        "temperature": snapshot["temperature"],
        "response_format": build_minimaxh3_response_format(),
    }


@pytest.mark.parametrize("mode", ["wake", "sleep", "ws"])
def test_c009_review_worker_failures_preserve_resources_and_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    data_dir = tmp_path / mode
    monkeypatch.setattr(settings, "DATA_DIR", data_dir)
    process: Any = None
    stop_event: Any = None
    ready: Any = None
    records_queue: Any = None
    http_port: int | None = None
    websocket_port: int | None = None
    stub_result: dict[str, object] | None = None
    state: dict[str, object] | None = None
    before_clip: dict[str, object] | None = None
    before_inventory: list[str] = []
    task_id: int | None = None
    fixture: dict[str, object] | None = None

    try:
        (
            process,
            stop_event,
            ready,
            records_queue,
            http_port,
            websocket_port,
        ) = _start_worker_failure_stub(mode)
        base_url = f"http://127.0.0.1:{http_port}"
        monkeypatch.setattr(settings, "VLLM_BASE_URL", base_url)
        monkeypatch.setattr(settings, "COMFY_BASE_URL", base_url)
        if mode == "ws":
            monkeypatch.setattr(
                video_task,
                "ComfyClient",
                _real_comfy_factory(websocket_port),
            )

        scenario = asyncio.run(_run_failure_scenario(data_dir))
        fixture_value = scenario["fixture"]
        before_clip_value = scenario["before_clip"]
        before_inventory_value = scenario["before_inventory"]
        task_id_value = scenario["task_id"]
        state_value = scenario["state"]
        if (
            not isinstance(fixture_value, dict)
            or not isinstance(before_clip_value, dict)
            or not isinstance(before_inventory_value, list)
            or not isinstance(task_id_value, int)
            or not isinstance(state_value, dict)
        ):
            raise AssertionError("T25 database scenario result is invalid")
        fixture = fixture_value
        before_clip = before_clip_value
        before_inventory = before_inventory_value
        task_id = task_id_value
        state = state_value
    finally:
        if process is not None:
            assert stop_event is not None
            assert ready is not None
            assert records_queue is not None
            stub_result = _stop_worker_failure_stub(
                process,
                stop_event,
                ready,
                records_queue,
            )

    assert stub_result is not None
    assert stub_result["exitcode"] == 0
    assert stub_result["alive"] is False
    records = stub_result["events"]
    assert isinstance(records, list)
    lifecycle = [record for record in records if record.get("kind") == "lifecycle"]
    assert [record.get("event") for record in lifecycle] == ["started", "stopped"]
    assert lifecycle[0]["pid"] == lifecycle[1]["pid"] == stub_result["pid"]
    assert http_port is not None
    assert websocket_port is not None
    _assert_port_closed(http_port)
    _assert_port_closed(websocket_port)

    request_records = sorted(
        [record for record in records if record.get("kind") in {"http", "ws"}],
        key=lambda record: int(record["start_ns"]),
    )
    assert state is not None
    assert before_clip is not None
    task = state["task"]
    clip = state["clip"]
    counts = state["counts"]
    assert isinstance(task, dict)
    assert isinstance(clip, dict)
    assert isinstance(counts, dict)
    assert task["id"] == task_id
    assert task["type"] == "gen_clip_video"
    assert task["target_id"] == fixture["clip_id"]
    assert task["status"] == "failed"
    assert task["progress"] == 0
    assert task["started_at"] is not None
    assert task["finished_at"] is not None
    _assert_failure_error(task["error_msg"], mode=mode, http_port=http_port)
    assert counts == {
        "total": 1,
        "queued": 0,
        "running": 0,
        "done": 0,
        "failed": 1,
    }
    assert state["video_count"] == 0
    assert clip["user_note"] == before_clip["user_note"]
    assert clip["revision"] == before_clip["revision"]
    assert clip["freshness"] == before_clip["freshness"]
    assert clip["generation_state"] == "failed"
    assert clip["prompt_cache"] is None
    assert clip["prompt_input_hash"] is None
    assert _inventory(data_dir) == before_inventory
    assert not (data_dir / "tmp" / "clip-videos" / f"{task_id}.mp4").exists()

    if mode == "wake":
        assert len(request_records) == 2
        _assert_http_event(
            request_records[0],
            method="POST",
            path="/wake_up",
            body=None,
            status=503,
        )
        _assert_http_event(
            request_records[1],
            method="POST",
            path="/free",
            body={"unload_models": True, "free_memory": True},
            status=200,
        )
    elif mode == "sleep":
        assert len(request_records) == 4
        snapshot = task["payload"]["input_snapshot"]
        assert isinstance(snapshot, dict)
        _assert_http_event(
            request_records[0],
            method="POST",
            path="/wake_up",
            body=None,
            status=200,
        )
        _assert_http_event(
            request_records[1],
            method="POST",
            path="/v1/chat/completions",
            body=_chat_body(snapshot),
            status=200,
        )
        _assert_http_event(
            request_records[2],
            method="POST",
            path="/sleep?level=1",
            body=None,
            status=503,
        )
        _assert_http_event(
            request_records[3],
            method="POST",
            path="/free",
            body={"unload_models": True, "free_memory": True},
            status=200,
        )
    else:
        assert len(request_records) == 8
        snapshot = task["payload"]["input_snapshot"]
        assert isinstance(snapshot, dict)
        _assert_http_event(
            request_records[0],
            method="POST",
            path="/wake_up",
            body=None,
            status=200,
        )
        _assert_http_event(
            request_records[1],
            method="POST",
            path="/v1/chat/completions",
            body=_chat_body(snapshot),
            status=200,
        )
        _assert_http_event(
            request_records[2],
            method="POST",
            path="/sleep?level=1",
            body=None,
            status=200,
        )
        expected_uploads = [
            (
                "subject1.png",
                b"c009-t9-current-image",
            ),
            (
                "subject2.png",
                b"c009-t9-override-image",
            ),
        ]
        for record, (filename, content) in zip(
            request_records[3:5], expected_uploads, strict=True
        ):
            assert record["kind"] == "http"
            assert record["method"] == "POST"
            assert record["path"] == "/upload/image"
            assert record["status"] == 200
            body = record["body"]
            assert isinstance(body, dict)
            assert body["fields"] == {
                "overwrite": "true",
                "type": "input",
                "subfolder": f"c009/task-{task_id}",
            }
            assert body["image"] == {"filename": filename, "content": content}
            assert int(record["end_ns"]) >= int(record["start_ns"])

        prompt_event = request_records[5]
        assert prompt_event["kind"] == "http"
        assert prompt_event["method"] == "POST"
        assert prompt_event["path"] == "/prompt"
        assert prompt_event["status"] == 200
        prompt_body = prompt_event["body"]
        assert isinstance(prompt_body, dict)
        assert set(prompt_body) == {"prompt", "client_id", "prompt_id"}
        prompt_id = prompt_body["prompt_id"]
        assert isinstance(prompt_id, str)
        assert prompt_body["client_id"] == prompt_id
        assert [(record["kind"], record["path"]) for record in request_records] == [
            ("http", "/wake_up"),
            ("http", "/v1/chat/completions"),
            ("http", "/sleep?level=1"),
            ("http", "/upload/image"),
            ("http", "/upload/image"),
            ("http", "/prompt"),
            ("ws", f"/ws?clientId={prompt_id}"),
            ("http", "/free"),
        ]
        prompt = prompt_body["prompt"]
        assert isinstance(prompt, dict)
        assert prompt["138"]["inputs"]["value"] == "T25 built prompt"
        assert prompt["129"]["inputs"]["noise_seed"] == snapshot["seed"]
        assert prompt["132"]["inputs"]["value"] == snapshot["requested_duration"]
        assert prompt["137"]["inputs"]["image"] == (
            f"c009/task-{task_id}/subject1.png"
        )
        assert prompt["139"]["inputs"]["image"] == (
            f"c009/task-{task_id}/subject2.png"
        )
        assert int(prompt_event["end_ns"]) >= int(prompt_event["start_ns"])

        ignored_events = [
            record for record in records if record.get("kind") == "ws_ignored"
        ]
        assert len(ignored_events) == 1
        ignored_event = ignored_events[0]
        assert ignored_event["method"] == "WS"
        assert ignored_event["path"] == f"/ws?clientId={prompt_id}"
        assert ignored_event["body"] == {
            "type": "execution_error",
            "data": {
                "prompt_id": "unrelated-prompt-id",
                "node": None,
                "node_type": None,
                "exception_message": None,
            },
        }
        assert int(ignored_event["end_ns"]) >= int(ignored_event["start_ns"])

        ws_event = request_records[6]
        assert ws_event["kind"] == "ws"
        assert ws_event["method"] == "WS"
        assert ws_event["path"] == f"/ws?clientId={prompt_id}"
        assert ws_event["body"] == {
            "type": "execution_error",
            "data": {
                "prompt_id": prompt_id,
                "node": "168",
                "node_type": "T25StubNode",
                "exception_message": "T25 WS stage failure",
            },
        }
        assert int(ws_event["end_ns"]) >= int(ws_event["start_ns"])

        _assert_http_event(
            request_records[7],
            method="POST",
            path="/free",
            body={"unload_models": True, "free_memory": True},
            status=200,
        )
        assert ws_event["path"] == f"/ws?clientId={prompt_id}"
        assert ws_event["body"]["data"]["prompt_id"] == prompt_id
        assert int(prompt_event["start_ns"]) <= int(ignored_event["start_ns"])
        assert int(ignored_event["end_ns"]) <= int(ws_event["start_ns"])
        assert request_records[5]["start_ns"] <= ws_event["start_ns"]
        assert ws_event["end_ns"] <= request_records[7]["start_ns"]
