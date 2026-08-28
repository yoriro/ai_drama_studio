import asyncio
import copy
import hashlib
import io
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from PIL import Image

from app.core.config import settings
from app.db.session import async_session_factory, engine
from app.services import asset_image_commit as commit_service
from app.tasks import gen_asset_image as image_task
from app.tasks.gen_asset_image import gen_asset_image_handler
from app.tasks.queue import TaskQueue


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _png_bytes() -> bytes:
    image = Image.new("RGB", (4, 4), (31, 47, 59))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


async def _create_fixture(*, cached_prompt: str | None = None) -> tuple[dict[str, int], dict[str, object]]:
    connection = await asyncpg.connect(_database_url())
    try:
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, '水墨写实')
            RETURNING id
            """,
            "C007 T8 style " + uuid4().hex,
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            "C007 T8 project " + uuid4().hex,
            style_id,
        )
        asset_id = await connection.fetchval(
            """
            INSERT INTO assets
                (project_id, type, name, description, source, revision)
            VALUES ($1, 'character', '林夏', '黑发白衬衫', 'manual', 1)
            RETURNING id
            """,
            project_id,
        )
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
        payload: dict[str, object] = {
            "input_snapshot": {
                "asset": {
                    "id": int(asset_id),
                    "project_id": int(project_id),
                    "type": "character",
                    "name": "林夏",
                    "description": "黑发白衬衫",
                    "revision": 1,
                },
                "style": "水墨写实",
                "template_key": "zimage",
                "template_content": "asset={{asset}}|style={{style}}|note={{user_note}}",
                "user_note": None,
                "rendered_prompt": "rendered prompt",
                "model": "test-model",
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
                    "hash": "workflow-hash",
                    "prompt_path": "6.inputs.text",
                    "seed_path": "3.inputs.seed",
                    "output_node": "9",
                    "definition": {
                        "3": {"inputs": {"seed": 11}},
                        "6": {"inputs": {"text": "original prompt"}},
                        "9": {"class_type": "SaveImage", "inputs": {}},
                    },
                },
                "seed": 123,
                "comfy_prompt_id": prompt_id,
                "cached_prompt": cached_prompt,
            },
            "input_hash": "input-hash",
            "source_revisions": {
                "asset": {"id": int(asset_id), "revision": 1}
            },
        }
        task_id = await connection.fetchval(
            """
            INSERT INTO tasks (type, target_id, payload, status, progress)
            VALUES ('gen_asset_image', $1, $2::jsonb, 'queued', 0.0)
            RETURNING id
            """,
            asset_id,
            json.dumps(payload, ensure_ascii=False),
        )
        fixture["task_id"] = int(task_id)
        if cached_prompt is not None:
            await connection.execute(
                """
                UPDATE assets
                SET image_prompt_cache = $1, image_prompt_hash = 'input-hash'
                WHERE id = $2
                """,
                cached_prompt,
                asset_id,
            )
        return fixture, payload
    finally:
        await connection.close()


async def _read_state(fixture: dict[str, int]) -> tuple[asyncpg.Record, list[asyncpg.Record]]:
    connection = await asyncpg.connect(_database_url())
    try:
        task = await connection.fetchrow(
            "SELECT status, progress, error_msg FROM tasks WHERE id = $1",
            fixture["task_id"],
        )
        asset = await connection.fetchrow(
            """
            SELECT revision, image_prompt_cache, image_prompt_hash
            FROM assets WHERE id = $1
            """,
            fixture["asset_id"],
        )
        images = await connection.fetch(
            """
            SELECT id, file_path, sha256, seed, source, is_current,
                   built_prompt, input_hash, input_snapshot, user_note
            FROM asset_images WHERE asset_id = $1 ORDER BY id
            """,
            fixture["asset_id"],
        )
        assert task is not None and asset is not None
        return (task, asset), list(images)
    finally:
        await connection.close()


async def _read_payload(fixture: dict[str, int]) -> dict[str, object]:
    connection = await asyncpg.connect(_database_url())
    try:
        raw = await connection.fetchval(
            "SELECT payload::text FROM tasks WHERE id = $1",
            fixture["task_id"],
        )
        assert isinstance(raw, str)
        return json.loads(raw)
    finally:
        await connection.close()


async def _cleanup_fixture(fixture: dict[str, int]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        await connection.execute(
            "DELETE FROM tasks WHERE id = $1", fixture["task_id"]
        )
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


class _FakeWebSocket:
    def __init__(self, records: list[tuple[str, object]], messages: list[object]) -> None:
        self._records = records
        self._messages = messages

    async def recv(self) -> object:
        self._records.append(("ws", "recv"))
        if not self._messages:
            raise RuntimeError("Comfy websocket exhausted")
        message = self._messages.pop(0)
        if isinstance(message, BaseException):
            raise message
        if isinstance(message, dict):
            return json.dumps(message)
        return message


class _FakeVLLM:
    def __init__(self, records: list[tuple[str, object]], mode: str) -> None:
        self._records = records
        self._mode = mode
        self.chat_requests: list[dict[str, object]] = []

    async def wake(self) -> None:
        self._records.append(("vllm", "wake"))

    async def sleep(self) -> None:
        self._records.append(("vllm", "sleep"))
        if self._mode == "sleep_error":
            raise RuntimeError("vLLM sleep failed")

    async def structured_chat(self, **request: object) -> dict[str, object]:
        self._records.append(("vllm", "chat"))
        self.chat_requests.append(copy.deepcopy(request))
        if self._mode == "chat_error":
            raise RuntimeError("vLLM chat failed")
        if self._mode == "schema_error":
            content = '{"prompt":"built","extra":1}'
        else:
            content = json.dumps({"prompt": "built prompt"})
        return {"choices": [{"message": {"content": content}}]}


class _FakeComfy:
    def __init__(
        self,
        records: list[tuple[str, object]],
        prompt_id: str,
        mode: str,
    ) -> None:
        self._records = records
        self._prompt_id = prompt_id
        self._mode = mode
        self.submit_count = 0
        self.free_count = 0
        self.submitted_workflow: dict[str, object] | None = None
        self.submitted_client_id: str | None = None
        self.submitted_prompt_id: str | None = None
        self.view_args: tuple[str, str, str] | None = None

    def _messages(self) -> list[object]:
        if self._mode == "ws_error" or self._mode == "ws_free_error":
            return [b"preview", RuntimeError("Comfy websocket failed")]
        if self._mode == "execution_error":
            return [
                {
                    "type": "execution_error",
                    "data": {
                        "prompt_id": self._prompt_id,
                        "node": "9",
                        "node_type": "SaveImage",
                        "exception_message": "node failed",
                    },
                }
            ]
        if self._mode == "interrupted":
            return [
                {
                    "type": "execution_interrupted",
                    "data": {"prompt_id": self._prompt_id},
                }
            ]
        return [
            b"preview",
            {
                "type": "progress",
                "data": {"prompt_id": str(uuid4()), "value": 99, "max": 99},
            },
            {
                "type": "executing",
                "data": {"prompt_id": self._prompt_id, "node": "6"},
            },
            {
                "type": "progress",
                "data": {"prompt_id": self._prompt_id, "value": 5, "max": 10},
            },
            {
                "type": "progress",
                "data": {"prompt_id": self._prompt_id, "value": 10, "max": 10},
            },
            {
                "type": "execution_success",
                "data": {"prompt_id": self._prompt_id},
            },
        ]

    @asynccontextmanager
    async def connect_ws(self, client_id: str):
        self._records.append(("comfy", "connect_ws"))
        yield _FakeWebSocket(self._records, self._messages())
        self._records.append(("comfy", "ws_close"))

    async def submit(
        self,
        *,
        prompt: dict[str, object],
        client_id: str,
        prompt_id: str,
    ) -> dict[str, object]:
        self._records.append(("comfy", "submit"))
        self.submit_count += 1
        self.submitted_workflow = copy.deepcopy(prompt)
        self.submitted_client_id = client_id
        self.submitted_prompt_id = prompt_id
        return {"prompt_id": prompt_id}

    async def history(self, prompt_id: str) -> dict[str, object]:
        self._records.append(("comfy", "history"))
        if self._mode == "history_error":
            raise RuntimeError("Comfy history failed")
        if self._mode == "wrong_output":
            outputs = {"other": {"images": [{"filename": "other.png"}]}}
        elif self._mode == "multiple_images":
            outputs = {
                "9": {
                    "images": [
                        {"filename": "first.png", "subfolder": "", "type": "output"},
                        {"filename": "second.png", "subfolder": "", "type": "output"},
                    ]
                }
            }
        else:
            outputs = {
                "9": {
                    "images": [
                        {"filename": "generated.png", "subfolder": "sub", "type": "output"}
                    ]
                }
            }
        return {
            prompt_id: {
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
    ):
        self._records.append(("comfy", "view"))
        self.view_args = (filename, subfolder, media_type)
        if self._mode == "view_error":
            raise RuntimeError("Comfy view failed")
        if self._mode == "png_error":
            yield b"not a png"
            return
        png = _png_bytes()
        for offset in range(0, len(png), 11):
            yield png[offset : offset + 11]

    async def free(self) -> None:
        self._records.append(("comfy", "free"))
        self.free_count += 1
        if self._mode in {"free_error", "ws_free_error"}:
            raise RuntimeError("Comfy free failed")


def _patch_transports(monkeypatch, records: list[tuple[str, object]], mode: str, prompt_id: str):
    vllm = _FakeVLLM(records, mode)
    comfy = _FakeComfy(records, prompt_id, mode)
    monkeypatch.setattr(image_task, "VLLMClient", lambda _base_url: vllm)
    monkeypatch.setattr(image_task, "ComfyClient", lambda _base_url: comfy)
    return vllm, comfy


def test_gen_asset_image_cache_miss_runs_ordered_pipeline_and_commits(
    tmp_path: Path, monkeypatch
) -> None:
    async def run() -> None:
        fixture, payload = await _create_fixture()
        records: list[tuple[str, object]] = []
        events: list[dict[str, object]] = []
        vllm, comfy = _patch_transports(
            monkeypatch,
            records,
            "success",
            payload["input_snapshot"]["comfy_prompt_id"],  # type: ignore[index]
        )
        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
        original_commit = commit_service.commit_generated_asset_image

        async def tracked_commit(*args, **kwargs):
            records.append(("db", "commit"))
            return await original_commit(*args, **kwargs)

        monkeypatch.setattr(image_task, "commit_generated_asset_image", tracked_commit)

        async def publish(event) -> None:
            events.append(
                {
                    "status": event.status,
                    "progress": event.progress,
                    "message": event.message,
                }
            )

        try:
            queue = TaskQueue(async_session_factory, publisher=publish)
            await queue.run_worker(
                handlers={"gen_asset_image": gen_asset_image_handler},
                poll_interval=0,
                stop_when_idle=True,
            )
            state, images = await _read_state(fixture)
            assert state[0]["status"] == "done", state[0]
            assert state[0]["progress"] == 1
            assert state[0]["error_msg"] is None
            assert state[1]["revision"] == 2
            assert state[1]["image_prompt_cache"] == "built prompt"
            assert state[1]["image_prompt_hash"] == "input-hash"
            assert len(images) == 1
            assert images[0]["source"] == "generated"
            assert images[0]["is_current"] is True
            assert images[0]["built_prompt"] == "built prompt"
            assert images[0]["input_hash"] == "input-hash"
            assert images[0]["sha256"] == hashlib.sha256(_png_bytes()).hexdigest()
            formal_path = tmp_path / images[0]["file_path"]
            assert formal_path.is_file()
            assert formal_path.read_bytes() == _png_bytes()
            assert not list((tmp_path / "tmp" / "asset-images").glob("*.upload"))
            assert await _read_payload(fixture) == payload

            assert [record for record in records if record[0] == "vllm"] == [
                ("vllm", "wake"),
                ("vllm", "chat"),
                ("vllm", "sleep"),
            ]
            assert vllm.chat_requests[0]["messages"] == [
                {"role": "user", "content": "rendered prompt"}
            ]
            assert vllm.chat_requests[0]["model"] == "test-model"
            assert vllm.chat_requests[0]["temperature"] == 0.2
            assert vllm.chat_requests[0]["schema_name"] == "zimage"
            assert vllm.chat_requests[0]["schema"] == payload["input_snapshot"]["guided_json_schema"]["json_schema"]["schema"]  # type: ignore[index]
            assert comfy.submit_count == 1
            assert comfy.free_count == 1
            assert comfy.submitted_client_id == payload["input_snapshot"]["comfy_prompt_id"]  # type: ignore[index]
            assert comfy.submitted_prompt_id == comfy.submitted_client_id
            assert comfy.submitted_workflow is not None
            assert comfy.submitted_workflow["6"]["inputs"]["text"] == "built prompt"  # type: ignore[index]
            assert comfy.submitted_workflow["3"]["inputs"]["seed"] == 123  # type: ignore[index]
            assert comfy.view_args == ("generated.png", "sub", "output")
            assert records.index(("comfy", "free")) < records.index(("db", "commit"))
            progress = [
                float(event["progress"])
                for event in events
                if event["message"] == "任务执行中"
                and float(event["progress"]) > 0
            ]
            assert progress == sorted(progress)
            assert min(progress) >= 0.25
            assert max(progress) <= 0.90
            assert progress[-3:] == pytest.approx([0.25, 0.575, 0.9])
        finally:
            await _cleanup_fixture(fixture)
            await engine.dispose()

    asyncio.run(run())


def test_gen_asset_image_cache_hit_skips_llm_but_sleeps_and_commits(
    tmp_path: Path, monkeypatch
) -> None:
    async def run() -> None:
        fixture, payload = await _create_fixture(cached_prompt="cached prompt")
        records: list[tuple[str, object]] = []
        vllm, comfy = _patch_transports(
            monkeypatch,
            records,
            "success",
            payload["input_snapshot"]["comfy_prompt_id"],  # type: ignore[index]
        )
        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
        try:
            await TaskQueue(async_session_factory).run_worker(
                handlers={"gen_asset_image": gen_asset_image_handler},
                poll_interval=0,
                stop_when_idle=True,
            )
            state, images = await _read_state(fixture)
            assert state[0]["status"] == "done", state[0]
            assert state[1]["revision"] == 2
            assert state[1]["image_prompt_cache"] == "cached prompt"
            assert state[1]["image_prompt_hash"] == "input-hash"
            assert len(images) == 1
            assert images[0]["built_prompt"] == "cached prompt"
            assert [record for record in records if record[0] == "vllm"] == [
                ("vllm", "sleep")
            ]
            assert vllm.chat_requests == []
            assert comfy.free_count == 1
            assert comfy.submitted_workflow is not None
            assert comfy.submitted_workflow["6"]["inputs"]["text"] == "cached prompt"  # type: ignore[index]
        finally:
            await _cleanup_fixture(fixture)
            await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("mode", "error_text", "submit_count", "free_count"),
    [
        ("chat_error", "vLLM chat failed", 0, 0),
        ("schema_error", "zimage response", 0, 0),
        ("sleep_error", "vLLM sleep failed", 0, 0),
        ("ws_error", "Comfy websocket failed", 1, 1),
        ("execution_error", "node=9 type=SaveImage exception=node failed", 1, 1),
        ("interrupted", "without cancellation intent", 1, 1),
        ("history_error", "Comfy history failed", 1, 1),
        ("view_error", "Comfy view failed", 1, 1),
        ("png_error", "not a complete PNG", 1, 1),
        ("free_error", "Comfy free error: Comfy free failed", 1, 1),
    ],
)
def test_gen_asset_image_external_failures_fail_once_without_business_writes(
    mode: str,
    error_text: str,
    submit_count: int,
    free_count: int,
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def run() -> None:
        fixture, payload = await _create_fixture()
        records: list[tuple[str, object]] = []
        _vllm, comfy = _patch_transports(
            monkeypatch,
            records,
            mode,
            payload["input_snapshot"]["comfy_prompt_id"],  # type: ignore[index]
        )
        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
        try:
            await TaskQueue(async_session_factory).run_worker(
                handlers={"gen_asset_image": gen_asset_image_handler},
                poll_interval=0,
                stop_when_idle=True,
            )
            state, images = await _read_state(fixture)
            assert state[0]["status"] == "failed"
            assert error_text in state[0]["error_msg"]
            assert state[1]["image_prompt_cache"] is None
            assert state[1]["image_prompt_hash"] is None
            assert images == []
            assert comfy.submit_count == submit_count
            assert comfy.free_count == free_count
            assert not list((tmp_path / "tmp" / "asset-images").glob("*.upload"))
        finally:
            await _cleanup_fixture(fixture)
            await engine.dispose()

    asyncio.run(run())


def test_gen_asset_image_preserves_primary_and_free_errors(
    tmp_path: Path, monkeypatch
) -> None:
    async def run() -> None:
        fixture, payload = await _create_fixture()
        records: list[tuple[str, object]] = []
        _vllm, comfy = _patch_transports(
            monkeypatch,
            records,
            "ws_free_error",
            payload["input_snapshot"]["comfy_prompt_id"],  # type: ignore[index]
        )
        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
        try:
            await TaskQueue(async_session_factory).run_worker(
                handlers={"gen_asset_image": gen_asset_image_handler},
                poll_interval=0,
                stop_when_idle=True,
            )
            state, images = await _read_state(fixture)
            assert state[0]["status"] == "failed"
            assert "Comfy websocket failed" in state[0]["error_msg"]
            assert "Comfy free failed" in state[0]["error_msg"]
            assert state[1]["image_prompt_cache"] is None
            assert images == []
            assert comfy.submit_count == 1
            assert comfy.free_count == 1
            assert not list((tmp_path / "tmp" / "asset-images").glob("*.upload"))
        finally:
            await _cleanup_fixture(fixture)
            await engine.dispose()

    asyncio.run(run())
