from __future__ import annotations

import asyncio
import copy
import io
import json
import multiprocessing
import os
import queue
import threading
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from websockets.asyncio.server import ServerConnection, serve

import app.api.assets as assets_api
from app.core.config import settings
from app.db.session import async_session_factory, engine
from app.integrations.comfy import ComfyClient
from app.integrations.workflow_binding import load_binding_snapshot
from app.main import create_app
from app.services.generate_asset_image import enqueue_generate_asset_image
from app.services.vllm import VLLMClient
from app.tasks import gen_asset_image as image_task
from app.tasks.gen_asset_image import gen_asset_image_handler
from app.tasks.queue import TaskQueue


def _database_url() -> str:
    return settings.DATABASE_URL.get_secret_value().replace("+asyncpg", "", 1)


def _png_bytes() -> bytes:
    image = Image.new("RGB", (4, 4), (31, 47, 59))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


async def _create_handler_fixture(
    *, with_task: bool = True
) -> tuple[dict[str, int], dict[str, Any]]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C007 review style " + uuid4().hex,
            "入队前风格",
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C007 review project " + uuid4().hex,
            style_id,
        )
        asset_id = await connection.fetchval(
            """
            INSERT INTO assets
                (project_id, type, name, description, source, revision)
            VALUES ($1, 'character', $2, $3, 'manual', 1)
            RETURNING id
            """,
            project_id,
            "入队前角色",
            "入队前描述",
        )
        assert style_id is not None
        assert project_id is not None
        assert asset_id is not None
        fixture = {
            "style_id": int(style_id),
            "project_id": int(project_id),
            "asset_id": int(asset_id),
        }
        prompt_id = str(uuid4())
        schema = {
            "type": "object",
            "properties": {"prompt": {"type": "string"}},
            "required": ["prompt"],
            "additionalProperties": False,
        }
        payload: dict[str, Any] = {
            "input_snapshot": {
                "asset": {
                    "id": fixture["asset_id"],
                    "project_id": fixture["project_id"],
                    "type": "character",
                    "name": "入队前角色",
                    "description": "入队前描述",
                    "revision": 1,
                },
                "style": "入队前风格",
                "template_key": "zimage",
                "template_content": "asset={{asset}}|style={{style}}|note={{user_note}}",
                "user_note": None,
                "rendered_prompt": "入队前提示词",
                "model": "review-model",
                "temperature": 0.2,
                "guided_json_schema": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "zimage",
                        "strict": True,
                        "schema": schema,
                    },
                },
                "workflow": {
                    "name": "zimage.json",
                    "hash": "review-workflow-hash",
                    "prompt_path": "6.inputs.text",
                    "seed_path": "3.inputs.seed",
                    "output_node": "9",
                    "definition": {
                        "3": {
                            "class_type": "KSampler",
                            "inputs": {"seed": 11},
                        },
                        "6": {
                            "class_type": "CLIPTextEncode",
                            "inputs": {"text": "original prompt"},
                        },
                        "9": {
                            "class_type": "SaveImage",
                            "inputs": {},
                        },
                    },
                },
                "seed": 123,
                "comfy_prompt_id": prompt_id,
                "cached_prompt": None,
            },
            "input_hash": "review-input-hash",
            "source_revisions": {
                "asset": {"id": fixture["asset_id"], "revision": 1}
            },
        }
        if with_task:
            task_id = await connection.fetchval(
                """
                INSERT INTO tasks (type, target_id, payload, status, progress)
                VALUES ('gen_asset_image', $1, $2::jsonb, 'queued', 0.0)
                RETURNING id
                """,
                fixture["asset_id"],
                json.dumps(payload, ensure_ascii=False),
            )
            assert task_id is not None
            fixture["task_id"] = int(task_id)
        return fixture, payload
    finally:
        await connection.close()


async def _read_handler_state(
    fixture: dict[str, int],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    connection = await asyncpg.connect(_database_url())
    try:
        task = await connection.fetchrow(
            "SELECT status, progress, error_msg FROM tasks WHERE id = $1",
            fixture["task_id"],
        )
        asset = await connection.fetchrow(
            """
            SELECT image_prompt_cache, image_prompt_hash
            FROM assets
            WHERE id = $1
            """,
            fixture["asset_id"],
        )
        images = await connection.fetch(
            """
            SELECT id, file_path, is_current, built_prompt
            FROM asset_images
            WHERE asset_id = $1
            ORDER BY id
            """,
            fixture["asset_id"],
        )
        assert task is not None
        assert asset is not None
        return (
            dict(task),
            dict(asset),
            [dict(image) for image in images],
        )
    finally:
        await connection.close()


async def _cleanup_handler_fixture(fixture: dict[str, int]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM asset_images WHERE asset_id = $1",
            fixture["asset_id"],
        )
        await connection.execute(
            "DELETE FROM tasks WHERE id = $1",
            fixture["task_id"],
        )
        await connection.execute(
            "DELETE FROM assets WHERE id = $1",
            fixture["asset_id"],
        )
        await connection.execute(
            "DELETE FROM projects WHERE id = $1",
            fixture["project_id"],
        )
        await connection.execute(
            "DELETE FROM styles WHERE id = $1",
            fixture["style_id"],
        )
    finally:
        await connection.close()


class _FakeVLLM:
    def __init__(self, mode: str = "valid") -> None:
        self.mode = mode
        self.wake_calls = 0
        self.chat_calls = 0
        self.sleep_calls = 0

    async def wake(self) -> None:
        self.wake_calls += 1

    async def sleep(self) -> None:
        self.sleep_calls += 1

    async def structured_chat(self, **request: object) -> dict[str, object]:
        del request
        self.chat_calls += 1
        if self.mode == "blank":
            content = json.dumps({"prompt": "   "})
        elif self.mode == "invalid_json":
            content = "not-json"
        else:
            content = json.dumps({"prompt": "worker built prompt"})
        return {"choices": [{"message": {"content": content}}]}


class _FakeWebSocket:
    def __init__(self, messages: list[object]) -> None:
        self._messages = messages

    async def recv(self) -> object:
        if not self._messages:
            raise AssertionError("fake Comfy websocket was exhausted")
        message = self._messages.pop(0)
        if isinstance(message, BaseException):
            raise message
        if isinstance(message, dict):
            return json.dumps(message)
        return message


class _FakeComfy:
    def __init__(self, mode: str, prompt_id: str) -> None:
        self.mode = mode
        self.prompt_id = prompt_id
        self.submit_calls = 0
        self.free_calls = 0
        self.view_calls = 0

    @asynccontextmanager
    async def connect_ws(self, client_id: str) -> AsyncIterator[_FakeWebSocket]:
        assert client_id == self.prompt_id
        yield _FakeWebSocket(
            [
                {
                    "type": "execution_success",
                    "data": {"prompt_id": self.prompt_id},
                }
            ]
        )

    async def submit(
        self,
        *,
        prompt: Mapping[str, Any],
        client_id: str,
        prompt_id: str,
    ) -> Mapping[str, Any]:
        del prompt
        assert client_id == self.prompt_id
        assert prompt_id == self.prompt_id
        self.submit_calls += 1
        return {"prompt_id": self.prompt_id}

    async def history(self, prompt_id: str) -> Mapping[str, Any]:
        assert prompt_id == self.prompt_id
        if self.mode == "zero_images":
            images: list[dict[str, str]] = []
            outputs: dict[str, Any] = {"9": {"images": images}}
        elif self.mode == "two_images":
            images = [
                {"filename": "first.png", "subfolder": "", "type": "output"},
                {"filename": "second.png", "subfolder": "", "type": "output"},
            ]
            outputs = {"9": {"images": images}}
        elif self.mode == "wrong_output_node":
            outputs = {
                "8": {
                    "images": [
                        {"filename": "wrong.png", "subfolder": "", "type": "output"}
                    ]
                }
            }
        else:
            outputs = {
                "9": {
                    "images": [
                        {
                            "filename": "generated.png",
                            "subfolder": "",
                            "type": "output",
                        }
                    ]
                }
            }
        return {
            self.prompt_id: {
                "status": {"status_str": "success"},
                "outputs": outputs,
            }
        }

    async def view_stream(
        self,
        *,
        filename: str,
        subfolder: str,
        media_type: str,
    ) -> AsyncIterator[bytes]:
        del filename, subfolder, media_type
        self.view_calls += 1
        yield _png_bytes()

    async def free(self) -> None:
        self.free_calls += 1


def test_generate_asset_image_rejects_int32_overflow_and_nul_before_enqueue(
    monkeypatch,
) -> None:
    calls: list[object] = []
    application: Any = None

    async def stop_worker() -> None:
        assert application is not None
        application.state.task_worker_stop.set()

    async def forbidden_enqueue(*args: object, **kwargs: object) -> None:
        del args, kwargs
        calls.append(object())
        raise AssertionError("invalid request reached task enqueue")

    application = create_app(
        startup_prepare=stop_worker,
        vllm_client_factory=lambda _base_url: _HealthOnlyProbe(),
        comfy_client_factory=lambda _base_url: _HealthOnlyProbe(),
    )
    monkeypatch.setattr(assets_api, "enqueue_generate_asset_image", forbidden_enqueue)
    with TestClient(application) as client:
        cases = [
            ("/api/assets/2147483648/generate-image", {}),
            ("/api/assets/1/generate-image", {"request_id": "bad\x00id"}),
            ("/api/assets/1/generate-image", {"user_note": "bad\x00note"}),
        ]
        for path, body in cases:
            response = client.post(path, json=body)
            assert response.status_code == 422
            response_body = response.json()
            assert set(response_body) == {"detail"}
            assert set(response_body["detail"]) == {"code", "message"}
            assert response_body["detail"]["code"] == "validation_error"
            assert response_body["detail"]["message"]
    assert calls == []


class _HealthOnlyProbe:
    async def health(self) -> None:
        return None


@pytest.mark.parametrize(
    ("mode", "expected_error"),
    [
        pytest.param(
            "blank",
            "zimage response prompt must be non-empty",
            id="blank_prompt",
        ),
        pytest.param(
            "invalid_json",
            "vLLM response is not valid zimage JSON",
            id="invalid_json",
        ),
    ],
)
def test_gen_asset_image_handler_rejects_blank_or_invalid_json_without_side_effects(
    mode: str,
    expected_error: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def run() -> None:
        fixture, payload = await _create_handler_fixture()
        vllm = _FakeVLLM(mode)
        comfy = _FakeComfy("valid", payload["input_snapshot"]["comfy_prompt_id"])
        monkeypatch.setattr(image_task, "VLLMClient", lambda _base_url: vllm)
        monkeypatch.setattr(image_task, "ComfyClient", lambda _base_url: comfy)
        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
        try:
            await TaskQueue(async_session_factory).run_worker(
                handlers={"gen_asset_image": gen_asset_image_handler},
                poll_interval=0,
                stop_when_idle=True,
            )
            task, asset, images = await _read_handler_state(fixture)
            assert task["status"] == "failed"
            assert expected_error in task["error_msg"]
            assert vllm.wake_calls == 1
            assert vllm.chat_calls == 1
            assert vllm.sleep_calls == 0
            assert comfy.submit_calls == 0
            assert comfy.free_calls == 0
            assert comfy.view_calls == 0
            assert asset["image_prompt_cache"] is None
            assert asset["image_prompt_hash"] is None
            assert images == []
            assert not [path for path in tmp_path.rglob("*") if path.is_file()]
        finally:
            await _cleanup_handler_fixture(fixture)
            await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("mode", "expected_error"),
    [
        pytest.param("zero_images", "exactly one image", id="zero_images"),
        pytest.param("two_images", "exactly one image", id="two_images"),
        pytest.param("wrong_output_node", "bound output node", id="wrong_output_node"),
    ],
)
def test_gen_asset_image_handler_fails_invalid_comfy_image_outputs_without_side_effects(
    mode: str,
    expected_error: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def run() -> None:
        fixture, payload = await _create_handler_fixture()
        vllm = _FakeVLLM()
        comfy = _FakeComfy(mode, payload["input_snapshot"]["comfy_prompt_id"])
        monkeypatch.setattr(image_task, "VLLMClient", lambda _base_url: vllm)
        monkeypatch.setattr(image_task, "ComfyClient", lambda _base_url: comfy)
        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
        try:
            await TaskQueue(async_session_factory).run_worker(
                handlers={"gen_asset_image": gen_asset_image_handler},
                poll_interval=0,
                stop_when_idle=True,
            )
            task, asset, images = await _read_handler_state(fixture)
            assert task["status"] == "failed"
            assert expected_error in task["error_msg"]
            assert vllm.wake_calls == 1
            assert vllm.chat_calls == 1
            assert vllm.sleep_calls == 1
            assert comfy.submit_calls == 1
            assert comfy.free_calls == 1
            assert comfy.view_calls == 0
            assert asset["image_prompt_cache"] is None
            assert asset["image_prompt_hash"] is None
            assert images == []
            assert not [path for path in tmp_path.rglob("*") if path.is_file()]
        finally:
            await _cleanup_handler_fixture(fixture)
            await engine.dispose()

    asyncio.run(run())


async def _read_zimage_template() -> str:
    connection = await asyncpg.connect(_database_url())
    try:
        content = await connection.fetchval(
            "SELECT content FROM prompt_templates WHERE key = 'zimage'"
        )
        assert isinstance(content, str)
        return content
    finally:
        await connection.close()


async def _write_zimage_template(content: str) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "UPDATE prompt_templates SET content = $1 WHERE key = 'zimage'",
            content,
        )
    finally:
        await connection.close()


async def _source_state(fixture: dict[str, int]) -> dict[str, Any]:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT name, description, revision
            FROM assets
            WHERE id = $1
            """,
            fixture["asset_id"],
        )
        assert row is not None
        return dict(row)
    finally:
        await connection.close()


async def _enqueue_asset_image_request(
    fixture: dict[str, int],
    binding: object,
    queue_instance: TaskQueue,
) -> object:
    async with async_session_factory() as session:
        return await enqueue_generate_asset_image(
            session,
            queue_instance,
            fixture["asset_id"],
            user_note=None,
            request_id=None,
            workflow_binding=binding,
        )


async def _cleanup_enqueue_fixture(
    fixture: dict[str, int], task_id: int | None,
) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        if task_id is not None:
            await connection.execute("DELETE FROM tasks WHERE id = $1", task_id)
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


def test_enqueue_snapshot_wins_concurrent_source_edit_and_worker_uses_copy() -> None:
    async def run() -> None:
        original_template = await _read_zimage_template()
        fixture, _ = await _create_handler_fixture(with_task=False)
        binding = load_binding_snapshot()
        queue_instance = TaskQueue(async_session_factory)
        task_id: int | None = None
        snapshot_built = asyncio.Event()
        editor_started = asyncio.Event()
        editor_task: asyncio.Task[None] | None = None
        template = "asset={{asset}}|style={{style}}|note={{user_note}}"
        try:
            await _write_zimage_template(template)
            original_enqueue = queue_instance.enqueue

            async def delayed_enqueue(
                session: Any,
                task_type: str,
                target_id: int,
                payload: Mapping[str, Any],
                request_id: str | None = None,
            ) -> object:
                snapshot_built.set()
                await asyncio.sleep(0.1)
                return await original_enqueue(
                    session,
                    task_type,
                    target_id,
                    payload,
                    request_id=request_id,
                )

            queue_instance.enqueue = delayed_enqueue  # type: ignore[method-assign]

            async def edit_sources() -> None:
                editor_started.set()
                await snapshot_built.wait()
                connection = await asyncpg.connect(_database_url())
                try:
                    await connection.execute(
                        """
                        UPDATE assets
                        SET name = '入队后角色', description = '入队后描述', revision = 2
                        WHERE id = $1
                        """,
                        fixture["asset_id"],
                    )
                    await connection.execute(
                        "UPDATE styles SET prompt_fragment = '入队后风格' WHERE id = $1",
                        fixture["style_id"],
                    )
                    await connection.execute(
                        "UPDATE prompt_templates SET content = $1 WHERE key = 'zimage'",
                        "asset={{asset}}|style={{style}}|note={{user_note}}|after",
                    )
                finally:
                    await connection.close()

            editor_task = asyncio.create_task(edit_sources())
            assert not editor_started.is_set()
            enqueue_task = asyncio.create_task(
                _enqueue_asset_image_request(fixture, binding, queue_instance)
            )
            await editor_started.wait()
            await snapshot_built.wait()
            await asyncio.sleep(0.05)
            assert not editor_task.done()

            result = await enqueue_task
            await editor_task
            editor_task = None
            task_id = int(result.task.id)  # type: ignore[union-attr]
            enqueued_payload = copy.deepcopy(result.task.payload)  # type: ignore[union-attr]

            source = await _source_state(fixture)
            assert source == {
                "name": "入队后角色",
                "description": "入队后描述",
                "revision": 2,
            }
            snapshot = enqueued_payload["input_snapshot"]
            assert snapshot["asset"] == {
                "id": fixture["asset_id"],
                "project_id": fixture["project_id"],
                "type": "character",
                "name": "入队前角色",
                "description": "入队前描述",
                "revision": 1,
            }
            assert snapshot["style"] == "入队前风格"
            assert snapshot["template_content"] == template
            assert snapshot["rendered_prompt"] == (
                'asset={"type":"character","name":"入队前角色","description":"入队前描述"}'
                "|style=入队前风格|note="
            )

            captured: list[dict[str, Any]] = []

            async def capture_worker(task: object, context: object) -> None:
                del context
                captured.append(copy.deepcopy(task.payload))  # type: ignore[union-attr]

            await queue_instance.run_worker(
                handlers={"gen_asset_image": capture_worker},
                poll_interval=0,
                stop_when_idle=True,
            )
            assert captured == [enqueued_payload]
        finally:
            if editor_task is not None and not editor_task.done():
                editor_task.cancel()
                await TaskQueue._await_cancelled_task(editor_task)
            await _write_zimage_template(original_template)
            await _cleanup_enqueue_fixture(fixture, task_id)
            await engine.dispose()

    asyncio.run(run())


_lifecycle_records: Any = None
_lifecycle_submit_event: threading.Event | None = None


def _lifecycle_record(label: str, payload: object = None) -> None:
    if _lifecycle_records is None:
        raise RuntimeError("lifecycle protocol record queue is not configured")
    _lifecycle_records.put((label, time.monotonic(), payload))


class _LifecycleHTTPHandler(BaseHTTPRequestHandler):
    server_version = "C007LifecycleServer/1.0"

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _read_json(self) -> object:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if not raw:
            return None
        return json.loads(raw)

    def _send_json(self, status: int, value: object) -> None:
        raw = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith("/history/"):
            prompt_id = unquote(path.rsplit("/", 1)[1])
            _lifecycle_record("comfy_history", prompt_id)
            self._send_json(
                200,
                {
                    prompt_id: {
                        "status": {"status_str": "success"},
                        "outputs": {
                            "9": {
                                "images": [
                                    {
                                        "filename": "generated.png",
                                        "subfolder": "",
                                        "type": "output",
                                    }
                                ]
                            }
                        },
                    }
                },
            )
            return
        if path == "/view":
            _lifecycle_record("comfy_view", self.path)
            raw = _png_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        body = self._read_json()
        path = urlsplit(self.path).path
        if path == "/wake_up":
            _lifecycle_record("vllm_wake", body)
            self._send_json(200, {})
            return
        if path == "/sleep":
            _lifecycle_record("vllm_sleep", body)
            self._send_json(200, {})
            return
        if path == "/v1/chat/completions":
            _lifecycle_record("vllm_chat", body)
            _lifecycle_record("vllm_active_start")
            time.sleep(0.02)
            _lifecycle_record("vllm_active_end")
            self._send_json(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"prompt": "process-built prompt"}
                                )
                            }
                        }
                    ]
                },
            )
            return
        if path == "/prompt":
            assert isinstance(body, dict)
            prompt_id = body.get("prompt_id")
            _lifecycle_record("comfy_submit", body)
            _lifecycle_record("comfy_active_start")
            assert _lifecycle_submit_event is not None
            _lifecycle_submit_event.set()
            self._send_json(200, {"prompt_id": prompt_id, "number": 1})
            return
        if path == "/free":
            _lifecycle_record("comfy_free", body)
            _lifecycle_record("comfy_active_end")
            self._send_json(200, {})
            return
        self._send_json(404, {"error": "not found"})


async def _lifecycle_websocket_handler(connection: ServerConnection) -> None:
    query = parse_qs(urlsplit(connection.request.path).query)
    client_ids = query.get("clientId")
    if not client_ids:
        raise ValueError("lifecycle websocket clientId is required")
    prompt_id = client_ids[0]
    _lifecycle_record("comfy_ws_open", prompt_id)
    assert _lifecycle_submit_event is not None
    while not _lifecycle_submit_event.is_set():
        await asyncio.sleep(0.005)
    _lifecycle_record("comfy_progress", prompt_id)
    await connection.send(
        json.dumps(
            {
                "type": "progress",
                "data": {"prompt_id": prompt_id, "value": 1, "max": 1},
            }
        )
    )
    await connection.send(
        json.dumps(
            {"type": "execution_success", "data": {"prompt_id": prompt_id}}
        )
    )
    await connection.wait_closed()


def _run_lifecycle_server(ready: Any, records: Any) -> None:
    global _lifecycle_records, _lifecycle_submit_event
    _lifecycle_records = records
    _lifecycle_submit_event = threading.Event()
    http_server = ThreadingHTTPServer(("127.0.0.1", 0), _LifecycleHTTPHandler)
    http_thread = threading.Thread(
        target=http_server.serve_forever,
        name="c007-lifecycle-http",
        daemon=True,
    )
    http_thread.start()

    async def run_websocket_server() -> None:
        websocket_server = await serve(
            _lifecycle_websocket_handler,
            "127.0.0.1",
            0,
        )
        websocket_port = websocket_server.sockets[0].getsockname()[1]
        ready.put((http_server.server_port, websocket_port))
        await asyncio.Future()

    try:
        asyncio.run(run_websocket_server())
    finally:
        http_server.shutdown()
        http_server.server_close()
        http_thread.join(timeout=5)


def _start_lifecycle_server() -> tuple[multiprocessing.Process, Any, int, int]:
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    records = context.Queue()
    process = context.Process(
        target=_run_lifecycle_server,
        args=(ready, records),
    )
    process.start()
    try:
        http_port, websocket_port = ready.get(timeout=10)
    except queue.Empty:
        process.terminate()
        process.join(timeout=5)
        raise AssertionError("lifecycle server did not start")
    return process, records, int(http_port), int(websocket_port)


def _stop_lifecycle_server(process: multiprocessing.Process) -> None:
    if process.is_alive():
        process.terminate()
    process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)


def _drain_lifecycle_records(records: Any) -> list[tuple[str, float, object]]:
    observed: list[tuple[str, float, object]] = []
    while True:
        try:
            observed.append(records.get(timeout=0.5))
        except queue.Empty:
            return observed


class _SplitComfy:
    def __init__(self, http_base_url: str, websocket_base_url: str) -> None:
        self._http = ComfyClient(http_base_url)
        self._websocket = ComfyClient(websocket_base_url)

    @asynccontextmanager
    async def connect_ws(self, client_id: str) -> AsyncIterator[Any]:
        async with self._websocket.connect_ws(client_id) as websocket:
            yield websocket

    async def submit(
        self,
        *,
        prompt: Mapping[str, Any],
        client_id: str,
        prompt_id: str,
    ) -> Mapping[str, Any]:
        return await self._http.submit(
            prompt=prompt,
            client_id=client_id,
            prompt_id=prompt_id,
        )

    async def history(self, prompt_id: str) -> Mapping[str, Any]:
        return await self._http.history(prompt_id)

    async def view_stream(
        self,
        *,
        filename: str,
        subfolder: str,
        media_type: str,
    ) -> AsyncIterator[bytes]:
        async for chunk in self._http.view_stream(
            filename=filename,
            subfolder=subfolder,
            media_type=media_type,
        ):
            yield chunk

    async def free(self) -> None:
        await self._http.free()


def test_gen_asset_image_handler_process_lifecycle_has_non_overlapping_inference_intervals(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def run() -> None:
        fixture, _ = await _create_handler_fixture()
        process, records, http_port, websocket_port = _start_lifecycle_server()
        task_id = fixture["task_id"]
        try:
            http_base_url = f"http://127.0.0.1:{http_port}"
            websocket_base_url = f"http://127.0.0.1:{websocket_port}"
            monkeypatch.setattr(settings, "VLLM_BASE_URL", http_base_url)
            monkeypatch.setattr(settings, "COMFY_BASE_URL", http_base_url)
            monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
            monkeypatch.setattr(
                image_task,
                "ComfyClient",
                lambda _base_url: _SplitComfy(http_base_url, websocket_base_url),
            )

            await TaskQueue(async_session_factory).run_worker(
                handlers={"gen_asset_image": gen_asset_image_handler},
                poll_interval=0,
                stop_when_idle=True,
            )
            task, _asset, images = await _read_handler_state(fixture)
            assert task["status"] == "done"
            assert len(images) == 1
            assert (tmp_path / images[0]["file_path"]).is_file()

            _stop_lifecycle_server(process)
            observed = _drain_lifecycle_records(records)
            labels = [record[0] for record in observed]
            for label in (
                "vllm_wake",
                "vllm_chat",
                "vllm_active_start",
                "vllm_active_end",
                "vllm_sleep",
                "comfy_ws_open",
                "comfy_submit",
                "comfy_progress",
                "comfy_history",
                "comfy_view",
                "comfy_free",
                "comfy_active_start",
                "comfy_active_end",
            ):
                assert labels.count(label) == 1, (label, labels)
            assert labels.index("vllm_wake") < labels.index("vllm_chat")
            assert labels.index("vllm_chat") < labels.index("vllm_sleep")
            assert labels.index("vllm_sleep") < labels.index("comfy_submit")
            assert labels.index("comfy_submit") < labels.index("comfy_progress")
            assert labels.index("comfy_progress") < labels.index("comfy_history")
            assert labels.index("comfy_history") < labels.index("comfy_view")
            assert labels.index("comfy_view") < labels.index("comfy_free")
            vllm_end = next(
                timestamp
                for label, timestamp, _payload in observed
                if label == "vllm_active_end"
            )
            comfy_start = next(
                timestamp
                for label, timestamp, _payload in observed
                if label == "comfy_active_start"
            )
            assert vllm_end <= comfy_start
        finally:
            _stop_lifecycle_server(process)
            await _cleanup_handler_fixture(fixture)
            await engine.dispose()

    asyncio.run(run())
