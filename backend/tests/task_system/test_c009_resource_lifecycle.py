from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import multiprocessing
import re
import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from websockets.asyncio.server import ServerConnection, serve

from app.core.config import settings
from app.integrations.comfy import ComfyClient
from app.integrations.workflow_binding import load_minimax_binding_snapshot
from app.services.clip_video_inputs import build_minimaxh3_response_format
from app.tasks import gen_clip_video as video_task
from app.tasks.queue import ClaimedTask


_stub_records: Any = None
_stub_mode = "success"
_stub_current_task: int | None = None
_stub_prompt_submitted: threading.Event | None = None


def _record(
    component: str,
    operation: str,
    start_ns: int,
    *,
    task_id: int | None = None,
    detail: object | None = None,
) -> None:
    if _stub_records is None:
        raise RuntimeError("stub record queue is not configured")
    record: dict[str, object] = {
        "component": component,
        "operation": operation,
        "start_ns": start_ns,
        "end_ns": time.perf_counter_ns(),
        "task_id": task_id,
    }
    if detail is not None:
        record["detail"] = detail
    _stub_records.put(record)


class _LifecycleHTTPHandler(BaseHTTPRequestHandler):
    server_version = "C009LifecycleStub/1.0"

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _send_json(self, status: int, payload: object) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_bytes(self, status: int, content_type: str, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _body(self) -> bytes:
        content_length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(content_length)

    def do_POST(self) -> None:
        global _stub_current_task
        path = urlsplit(self.path).path
        body = self._body()
        operation: str | None = None
        component: str | None = None
        task_id: int | None = _stub_current_task
        detail: object | None = None
        prompt_response_sent = False
        started = time.perf_counter_ns()
        try:
            if path == "/wake_up":
                component, operation = "vllm", "wake"
                self._send_json(200, {})
            elif path == "/sleep":
                component, operation = "vllm", "sleep"
                self._send_json(200, {})
            elif path == "/v1/chat/completions":
                component, operation = "vllm", "chat"
                request = json.loads(body)
                detail = {
                    "messages": copy.deepcopy(request.get("messages")),
                    "schema_name": request.get("response_format", {})
                    .get("json_schema", {})
                    .get("name"),
                }
                self._send_json(
                    200,
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {"prompt": "stub built prompt"}
                                    )
                                }
                            }
                        ]
                    },
                )
            elif path == "/upload/image":
                component, operation = "comfy", "upload"
                decoded = body.decode("latin1")
                match = re.search(r"c009/task-(\d+)", decoded)
                if match is not None:
                    task_id = int(match.group(1))
                    _stub_current_task = task_id
                filename_match = re.search(r'filename="([^"]+)"', decoded)
                filename = "subject1.png" if filename_match is None else filename_match.group(1)
                detail = {"filename": filename, "task_id": task_id}
                self._send_json(
                    200,
                    {
                        "name": filename,
                        "subfolder": f"c009/task-{task_id}",
                        "type": "input",
                        "fullpath": "must-not-be-read",
                    },
                )
            elif path == "/prompt":
                component, operation = "comfy", "submit"
                request = json.loads(body)
                prompt_id = request["prompt_id"]
                match = re.fullmatch(r"prompt-(\d+)", prompt_id)
                if match is not None:
                    task_id = int(match.group(1))
                    _stub_current_task = task_id
                detail = {"prompt_id": prompt_id}
                if _stub_prompt_submitted is None:
                    raise RuntimeError("stub submit barrier is not configured")
                self._send_json(200, {"prompt_id": prompt_id})
                prompt_response_sent = True
            elif path == "/interrupt":
                component, operation = "comfy", "interrupt"
                self._send_json(200, {})
            elif path == "/free":
                component, operation = "comfy", "free"
                self._send_json(200, {})
            else:
                self._send_json(404, {"error": "not found"})
        finally:
            if component is not None and operation is not None:
                _record(
                    component,
                    operation,
                    started,
                    task_id=task_id,
                    detail=detail,
                )
                if path == "/prompt" and prompt_response_sent:
                    _stub_prompt_submitted.set()

    def do_GET(self) -> None:
        global _stub_current_task
        path = urlsplit(self.path).path
        operation: str | None = None
        task_id: int | None = _stub_current_task
        detail: object | None = None
        started = time.perf_counter_ns()
        try:
            if path.startswith("/history/"):
                operation = "history"
                component = "comfy"
                prompt_id = unquote(path.rsplit("/", 1)[1])
                match = re.fullmatch(r"prompt-(\d+)", prompt_id)
                if match is not None:
                    task_id = int(match.group(1))
                    _stub_current_task = task_id
                detail = {"prompt_id": prompt_id}
                self._send_json(
                    200,
                    {
                        prompt_id: {
                            "status": {"status_str": "success"},
                            "outputs": {
                                "168": {
                                    "gifs": [
                                        {
                                            "filename": "clip.mp4",
                                            "subfolder": "output",
                                            "type": "output",
                                            "format": "video/h264-mp4",
                                            "fullpath": "must-not-be-read",
                                        }
                                    ]
                                }
                            },
                        }
                    },
                )
            elif path == "/view":
                operation = "view"
                component = "comfy"
                if _stub_mode == "view_failure":
                    self._send_json(503, {"error": "view unavailable"})
                else:
                    self._send_bytes(200, "video/mp4", b"stub video bytes")
            else:
                component = None
                self._send_json(404, {"error": "not found"})
        finally:
            if component is not None and operation is not None:
                _record(
                    component,
                    operation,
                    started,
                    task_id=task_id,
                    detail=detail,
                )


async def _lifecycle_websocket(connection: ServerConnection) -> None:
    if _stub_prompt_submitted is None:
        raise RuntimeError("stub submit barrier is not configured")
    query = parse_qs(urlsplit(connection.request.path).query)
    prompt_id = query.get("clientId", [None])[0]
    if not isinstance(prompt_id, str):
        raise RuntimeError("stub websocket clientId is missing")
    await asyncio.to_thread(_stub_prompt_submitted.wait, 10)
    match = re.fullmatch(r"prompt-(\d+)", prompt_id)
    task_id = None if match is None else int(match.group(1))
    started = time.perf_counter_ns()
    for message in (
        {
            "type": "progress",
            "data": {"prompt_id": prompt_id, "value": 1, "max": 2},
        },
        {
            "type": "executing",
            "data": {"prompt_id": prompt_id, "node": "168"},
        },
        {
            "type": "progress",
            "data": {"prompt_id": prompt_id, "value": 2, "max": 2},
        },
        {
            "type": "execution_success",
            "data": {"prompt_id": prompt_id},
        },
    ):
        await connection.send(json.dumps(message))
    _record("comfy", "ws", started, task_id=task_id)


def _run_lifecycle_stub(
    mode: str,
    ready: Any,
    records: Any,
    stop_event: Any,
) -> None:
    global _stub_current_task, _stub_mode, _stub_prompt_submitted, _stub_records
    _stub_records = records
    _stub_mode = mode
    _stub_current_task = None
    _stub_prompt_submitted = threading.Event()
    http_server = ThreadingHTTPServer(("127.0.0.1", 0), _LifecycleHTTPHandler)
    http_thread = threading.Thread(
        target=http_server.serve_forever,
        name="c009-lifecycle-http",
        daemon=True,
    )
    http_thread.start()

    async def run() -> None:
        websocket_server = await serve(
            _lifecycle_websocket,
            "127.0.0.1",
            0,
        )
        websocket_port = websocket_server.sockets[0].getsockname()[1]
        ready.put((http_server.server_port, websocket_port))
        try:
            while not stop_event.is_set():
                await asyncio.sleep(0.02)
        finally:
            websocket_server.close()
            await websocket_server.wait_closed()

    try:
        asyncio.run(run())
    finally:
        http_server.shutdown()
        http_server.server_close()
        http_thread.join(timeout=5)


def _start_lifecycle_stub(mode: str) -> tuple[Any, Any, Any, int, int]:
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    records = context.Queue()
    stop_event = context.Event()
    process = context.Process(
        target=_run_lifecycle_stub,
        args=(mode, ready, records, stop_event),
    )
    process.start()
    try:
        http_port, websocket_port = ready.get(timeout=15)
    except Exception:
        process.terminate()
        process.join(timeout=5)
        raise AssertionError("lifecycle stub did not start")
    return process, stop_event, records, http_port, websocket_port


def _stop_lifecycle_stub(process: Any, stop_event: Any) -> None:
    stop_event.set()
    process.join(timeout=15)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)


def _drain_records(records: Any) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    while True:
        try:
            values.append(records.get_nowait())
        except Exception:
            return values


def _assert_port_closed(port: int) -> None:
    with pytest.raises(OSError):
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            pass


def _task_fixture(
    data_dir: Path, *, task_id: int, cached_prompt: str | None
) -> ClaimedTask:
    binding = load_minimax_binding_snapshot()
    relative_path = Path("projects", "1", "assets", str(task_id), "1.png")
    content = f"reference-{task_id}".encode()
    media_path = data_dir / relative_path
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(content)
    snapshot = {
        "clip": {
            "id": 7,
            "episode_id": 3,
            "revision": 2,
            "generation_mode": "ref2v",
        },
        "rendered_prompt": "rendered prompt from snapshot",
        "model": "model-from-snapshot",
        "temperature": 0.2,
        "guided_json_schema": build_minimaxh3_response_format(),
        "seed": 12345,
        "requested_duration": 3,
        "comfy_prompt_id": f"prompt-{task_id}",
        "workflow": binding.workflow_payload(),
        "shots": [],
        "references": [
            {
                "slot_no": 1,
                "reference_name": "subject1",
                "asset_type": "character",
                "asset_name": "subject",
                "asset_description": "description",
                "image_source": "asset_current",
                "image_id": 1,
                "override_sha256": None,
            }
        ],
        "reference_media": [
            {
                "file_path": relative_path.as_posix(),
                "extension": "png",
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
        "cached_prompt": cached_prompt,
    }
    return ClaimedTask(
        id=task_id,
        type="gen_clip_video",
        target_id=7,
        request_id=None,
        payload={
            "input_snapshot": snapshot,
            "input_hash": f"hash-{task_id}",
            "source_revisions": {},
        },
    )


class _RunningContext:
    def __init__(self) -> None:
        self.heartbeats: list[float] = []
        self.safe_point_calls = 0

    async def cancel_safe_point(self) -> SimpleNamespace:
        self.safe_point_calls += 1
        return SimpleNamespace(task=SimpleNamespace(status="running"))

    async def heartbeat(self, progress: float) -> None:
        self.heartbeats.append(progress)

    async def cancel_requested(self) -> bool:
        return False


def _real_comfy_factory(websocket_port: int):
    def factory(base_url: str) -> ComfyClient:
        client = ComfyClient(base_url)
        client._websocket_base_url = f"ws://127.0.0.1:{websocket_port}"
        return client

    return factory


def _assert_vllm_comfy_intervals_do_not_overlap(
    records: list[dict[str, object]],
) -> None:
    intervals = sorted(records, key=lambda record: int(record["start_ns"]))
    for index, left in enumerate(intervals):
        left_start = int(left["start_ns"])
        left_end = int(left["end_ns"])
        assert left_end >= left_start
        for right in intervals[index + 1 :]:
            right_start = int(right["start_ns"])
            right_end = int(right["end_ns"])
            if not (
                (left["component"] == "vllm" and right["component"] == "comfy")
                or (left["component"] == "comfy" and right["component"] == "vllm")
            ):
                continue
            assert not (
                left_start < right_end and right_start < left_end
            ), (left, right)


def test_c009_resource_lifecycle_cross_process_cache_miss_uses_real_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process, stop_event, records_queue, http_port, websocket_port = (
        _start_lifecycle_stub("success")
    )
    data_dir = tmp_path / "cache-miss"
    try:
        monkeypatch.setattr(settings, "DATA_DIR", data_dir)
        base_url = f"http://127.0.0.1:{http_port}"
        monkeypatch.setattr(settings, "VLLM_BASE_URL", base_url)
        monkeypatch.setattr(settings, "COMFY_BASE_URL", base_url)
        monkeypatch.setattr(
            video_task,
            "ComfyClient",
            _real_comfy_factory(websocket_port),
        )
        result = asyncio.run(
            video_task.gen_clip_video_handler(
                _task_fixture(data_dir, task_id=42, cached_prompt=None),
                _RunningContext(),
            )
        )
        assert result is not None
        assert result.built_prompt == "stub built prompt"
        assert result.temp_path.read_bytes() == b"stub video bytes"
        result.temp_path.unlink()
    finally:
        _stop_lifecycle_stub(process, stop_event)

    assert not process.is_alive()
    _assert_port_closed(http_port)
    _assert_port_closed(websocket_port)
    records = _drain_records(records_queue)
    assert [record["operation"] for record in records] == [
        "wake",
        "chat",
        "sleep",
        "upload",
        "submit",
        "ws",
        "history",
        "view",
        "free",
    ]
    assert [record["component"] for record in records[:3]] == [
        "vllm",
        "vllm",
        "vllm",
    ]
    assert [record["component"] for record in records[3:]] == [
        "comfy",
        "comfy",
        "comfy",
        "comfy",
        "comfy",
        "comfy",
    ]
    _assert_vllm_comfy_intervals_do_not_overlap(records)
    chat_detail = records[1]["detail"]
    assert chat_detail == {
        "messages": [
            {
                "role": "user",
                "content": "rendered prompt from snapshot",
            }
        ],
        "schema_name": "minimaxh3",
    }
    assert records[3]["detail"] == {
        "filename": "subject1.png",
        "task_id": 42,
    }
    assert records[4]["detail"] == {"prompt_id": "prompt-42"}
    assert records[-1]["operation"] == "free"
    assert records[-1]["task_id"] == 42


def test_c009_resource_lifecycle_cross_process_cache_hit_skips_chat_and_frees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process, stop_event, records_queue, http_port, websocket_port = (
        _start_lifecycle_stub("success")
    )
    data_dir = tmp_path / "cache-hit"
    try:
        monkeypatch.setattr(settings, "DATA_DIR", data_dir)
        base_url = f"http://127.0.0.1:{http_port}"
        monkeypatch.setattr(settings, "VLLM_BASE_URL", base_url)
        monkeypatch.setattr(settings, "COMFY_BASE_URL", base_url)
        monkeypatch.setattr(
            video_task,
            "ComfyClient",
            _real_comfy_factory(websocket_port),
        )
        result = asyncio.run(
            video_task.gen_clip_video_handler(
                _task_fixture(
                    data_dir,
                    task_id=43,
                    cached_prompt="cached prompt from snapshot",
                ),
                _RunningContext(),
            )
        )
        assert result is not None
        assert result.built_prompt == "cached prompt from snapshot"
        result.temp_path.unlink()
    finally:
        _stop_lifecycle_stub(process, stop_event)

    assert not process.is_alive()
    _assert_port_closed(http_port)
    _assert_port_closed(websocket_port)
    records = _drain_records(records_queue)
    assert [record["operation"] for record in records] == [
        "sleep",
        "upload",
        "submit",
        "ws",
        "history",
        "view",
        "free",
    ]
    assert all(record["operation"] != "chat" for record in records)
    _assert_vllm_comfy_intervals_do_not_overlap(records)
    assert records[-1]["operation"] == "free"
    assert records[-1]["task_id"] == 43


def test_c009_resource_lifecycle_cross_process_transport_failure_still_frees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process, stop_event, records_queue, http_port, websocket_port = (
        _start_lifecycle_stub("view_failure")
    )
    data_dir = tmp_path / "transport-failure"
    try:
        monkeypatch.setattr(settings, "DATA_DIR", data_dir)
        base_url = f"http://127.0.0.1:{http_port}"
        monkeypatch.setattr(settings, "VLLM_BASE_URL", base_url)
        monkeypatch.setattr(settings, "COMFY_BASE_URL", base_url)
        monkeypatch.setattr(
            video_task,
            "ComfyClient",
            _real_comfy_factory(websocket_port),
        )
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(
                video_task.gen_clip_video_handler(
                    _task_fixture(
                        data_dir,
                        task_id=44,
                        cached_prompt="cached prompt from snapshot",
                    ),
                    _RunningContext(),
                )
            )
    finally:
        _stop_lifecycle_stub(process, stop_event)

    assert not process.is_alive()
    _assert_port_closed(http_port)
    _assert_port_closed(websocket_port)
    records = _drain_records(records_queue)
    assert [record["operation"] for record in records] == [
        "sleep",
        "upload",
        "submit",
        "ws",
        "history",
        "view",
        "free",
    ]
    assert records[-1]["operation"] == "free"
    assert records[-1]["task_id"] == 44
    assert not (data_dir / "tmp" / "clip-videos" / "44.mp4").exists()
    _assert_vllm_comfy_intervals_do_not_overlap(records)
