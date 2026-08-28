from __future__ import annotations

import asyncio
import io
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.db.session import engine
from app.main import create_app
from app.tasks import gen_asset_image as image_task
from app.tasks import queue as queue_module


def _database_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)


def _png_bytes() -> bytes:
    image = Image.new("RGB", (4, 4), (31, 47, 59))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _payload(
    *, asset_id: int, project_id: int, prompt_id: str, cached_prompt: str | None
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {"prompt": {"type": "string"}},
        "required": ["prompt"],
        "additionalProperties": False,
    }
    return {
        "input_snapshot": {
            "asset": {
                "id": asset_id,
                "project_id": project_id,
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
                "name": "zimage",
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
        "source_revisions": {"asset": {"id": asset_id, "revision": 1}},
    }


async def _create_asset_task(
    *, status: str = "queued", cached_prompt: str | None = "cached prompt"
) -> dict[str, Any]:
    connection = await asyncpg.connect(_database_url())
    try:
        suffix = uuid4().hex
        style_id = await connection.fetchval(
            """
            INSERT INTO styles (name, prompt_fragment)
            VALUES ($1, '水墨写实')
            RETURNING id
            """,
            f"C007 T9 style {suffix}",
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO projects (name, style_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            f"C007 T9 project {suffix}",
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
        prompt_id = str(uuid4())
        payload = _payload(
            asset_id=int(asset_id),
            project_id=int(project_id),
            prompt_id=prompt_id,
            cached_prompt=cached_prompt,
        )
        task_id = await connection.fetchval(
            """
            INSERT INTO tasks
                (type, target_id, payload, status, progress,
                 heartbeat_at, started_at, cancel_requested_at, finished_at)
            VALUES (
                'gen_asset_image', $1, $2::jsonb, $3, 0.2,
                CASE WHEN $4 THEN now() ELSE NULL END,
                CASE WHEN $4 THEN now() ELSE NULL END,
                NULL, NULL
            )
            RETURNING id
            """,
            asset_id,
            json.dumps(payload, ensure_ascii=False),
            status,
            status == "running",
        )
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
        return {
            "style_id": int(style_id),
            "project_id": int(project_id),
            "asset_id": int(asset_id),
            "task_id": int(task_id),
            "prompt_id": prompt_id,
            "payload": payload,
        }
    finally:
        await connection.close()


async def _create_task_matrix() -> dict[str, dict[str, Any]]:
    matrix: dict[str, dict[str, Any]] = {}
    matrix["queued"] = await _create_asset_task()
    matrix["running"] = await _create_asset_task(status="running")
    matrix["canceled"] = await _create_asset_task(status="canceled")

    connection = await asyncpg.connect(_database_url())
    try:
        payload = json.dumps(
            {"input_snapshot": {}, "input_hash": None, "source_revisions": {}}
        )
        other_id = await connection.fetchval(
            """
            INSERT INTO tasks (type, target_id, payload, status, progress)
            VALUES ('gen_assets', $1, $2::jsonb, 'running', 0.2)
            RETURNING id
            """,
            9_000_001 + int(uuid4().int % 100_000),
            payload,
        )
        matrix["other"] = {"task_id": int(other_id)}
        for key, status in (("done", "done"), ("failed", "failed")):
            terminal_id = await connection.fetchval(
                """
                INSERT INTO tasks (type, target_id, payload, status, progress)
                VALUES ('gen_asset_image', $1, $2::jsonb, $3, $4)
                RETURNING id
                """,
                9_100_001 + int(uuid4().int % 100_000),
                payload,
                status,
                1 if status == "done" else 0,
            )
            matrix[key] = {"task_id": int(terminal_id)}
        return matrix
    finally:
        await connection.close()


async def _read_task(task_id: int) -> asyncpg.Record:
    connection = await asyncpg.connect(_database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT status, progress, cancel_requested_at, error_msg
            FROM tasks WHERE id = $1
            """,
            task_id,
        )
        assert row is not None
        return row
    finally:
        await connection.close()


async def _read_asset_state(fixture: dict[str, Any]) -> tuple[asyncpg.Record, list[asyncpg.Record]]:
    connection = await asyncpg.connect(_database_url())
    try:
        asset = await connection.fetchrow(
            """
            SELECT revision, image_prompt_cache, image_prompt_hash
            FROM assets WHERE id = $1
            """,
            fixture["asset_id"],
        )
        images = await connection.fetch(
            """
            SELECT id, file_path, is_current, built_prompt, input_hash
            FROM asset_images WHERE asset_id = $1 ORDER BY id
            """,
            fixture["asset_id"],
        )
        assert asset is not None
        return asset, list(images)
    finally:
        await connection.close()


async def _cleanup_fixtures(fixtures: list[dict[str, Any]]) -> None:
    connection = await asyncpg.connect(_database_url())
    try:
        for fixture in fixtures:
            if "task_id" in fixture:
                await connection.execute(
                    "DELETE FROM tasks WHERE id = $1", fixture["task_id"]
                )
            if "asset_id" in fixture:
                await connection.execute(
                    "DELETE FROM asset_images WHERE asset_id = $1",
                    fixture["asset_id"],
                )
                await connection.execute(
                    "DELETE FROM assets WHERE id = $1", fixture["asset_id"]
                )
            if "project_id" in fixture:
                await connection.execute(
                    "DELETE FROM projects WHERE id = $1", fixture["project_id"]
                )
            if "style_id" in fixture:
                await connection.execute(
                    "DELETE FROM styles WHERE id = $1", fixture["style_id"]
                )
            if "other_task_ids" in fixture:
                await connection.execute(
                    "DELETE FROM tasks WHERE id = ANY($1::int[])",
                    fixture["other_task_ids"],
                )
    finally:
        await connection.close()


def _wait_for_status(task_id: int, expected: str, *, timeout: float = 10.0) -> asyncpg.Record:
    deadline = time.monotonic() + timeout
    last: asyncpg.Record | None = None
    while time.monotonic() < deadline:
        last = asyncio.run(_read_task(task_id))
        if last["status"] == expected:
            return last
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} status did not become {expected}: {last}")


class _FakeVLLM:
    def __init__(self) -> None:
        self.sleep_count = 0

    async def health(self) -> None:
        return None

    async def wake(self) -> None:
        raise AssertionError("T9 cache-hit race must not wake vLLM")

    async def sleep(self) -> None:
        self.sleep_count += 1

    async def structured_chat(self, **_request: object) -> dict[str, object]:
        raise AssertionError("T9 cache-hit race must not call vLLM chat")


class _BarrierWebSocket:
    def __init__(self, comfy: "_BarrierComfy", prompt_id: str) -> None:
        self._comfy = comfy
        self._prompt_id = prompt_id

    async def recv(self) -> str:
        if self._comfy.mode == "interrupt":
            opened = await asyncio.to_thread(
                self._comfy.allow_terminal.wait, 10
            )
            if not opened:
                raise RuntimeError("T9 interrupt barrier timed out")
            return json.dumps(
                {
                    "type": "execution_interrupted",
                    "data": {"prompt_id": self._prompt_id},
                }
            )
        return json.dumps(
            {
                "type": "execution_success",
                "data": {"prompt_id": self._prompt_id},
            }
        )


class _BarrierComfy:
    def __init__(self, *, mode: str = "success", interrupt_error: BaseException | None = None) -> None:
        self.mode = mode
        self.interrupt_error = interrupt_error
        self.submitted = threading.Event()
        self.allow_terminal = threading.Event()
        self.interrupt_calls: list[str] = []
        self.free_count = 0
        self.submit_count = 0

    async def health(self) -> None:
        return None

    async def interrupt(self, prompt_id: str) -> None:
        self.interrupt_calls.append(prompt_id)
        if self.interrupt_error is not None:
            raise self.interrupt_error
        self.allow_terminal.set()

    @asynccontextmanager
    async def connect_ws(self, client_id: str):
        yield _BarrierWebSocket(self, client_id)

    async def submit(
        self,
        *,
        prompt: dict[str, object],
        client_id: str,
        prompt_id: str,
    ) -> dict[str, object]:
        del prompt
        assert client_id == prompt_id
        self.submit_count += 1
        self.submitted.set()
        return {"prompt_id": prompt_id}

    async def history(self, prompt_id: str) -> dict[str, object]:
        return {
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
        }

    async def view_stream(
        self, *, filename: str, subfolder: str, media_type: str
    ):
        assert (filename, subfolder, media_type) == (
            "generated.png",
            "",
            "output",
        )
        yield _png_bytes()

    async def free(self) -> None:
        self.free_count += 1


def _application(
    *, comfy: _BarrierComfy, vllm: _FakeVLLM, stop_worker: bool = False
):
    application = create_app(
        vllm_client_factory=lambda _base_url: vllm,
        comfy_client_factory=lambda _base_url: comfy,
    )
    if stop_worker:

        async def stop() -> None:
            application.state.task_worker_stop.set()

        application.state.startup_prepare = stop
    return application


def test_cancel_route_interrupts_only_first_running_asset_image() -> None:
    async def seed() -> dict[str, dict[str, Any]]:
        matrix = await _create_task_matrix()
        matrix["other"]["other_task_ids"] = [matrix["other"]["task_id"]]
        matrix["done"]["other_task_ids"] = [matrix["done"]["task_id"]]
        matrix["failed"]["other_task_ids"] = [matrix["failed"]["task_id"]]
        return matrix

    comfy = _BarrierComfy()
    vllm = _FakeVLLM()
    application = _application(comfy=comfy, vllm=vllm, stop_worker=True)
    fixtures: list[dict[str, Any]] = []
    try:
        with TestClient(application) as client:
            matrix = asyncio.run(seed())
            fixtures.extend(
                fixture
                for key, fixture in matrix.items()
                if key in {"queued", "running", "canceled"}
            )
            fixtures.extend(matrix[key] for key in ("other", "done", "failed"))

            queued = client.post(
                f"/api/tasks/{matrix['queued']['task_id']}/cancel"
            )
            assert queued.status_code == 200
            assert queued.json()["status"] == "canceled"
            assert comfy.interrupt_calls == []

            running = client.post(
                f"/api/tasks/{matrix['running']['task_id']}/cancel"
            )
            assert running.status_code == 200
            assert running.json()["status"] == "running"
            assert running.json()["cancel_requested_at"] is not None
            assert comfy.interrupt_calls == [matrix["running"]["prompt_id"]]

            repeated = client.post(
                f"/api/tasks/{matrix['running']['task_id']}/cancel"
            )
            assert repeated.status_code == 200
            assert repeated.json()["status"] == "running"
            assert comfy.interrupt_calls == [matrix["running"]["prompt_id"]]

            canceled = client.post(
                f"/api/tasks/{matrix['canceled']['task_id']}/cancel"
            )
            assert canceled.status_code == 200
            assert canceled.json()["status"] == "canceled"
            assert comfy.interrupt_calls == [matrix["running"]["prompt_id"]]

            other = client.post(
                f"/api/tasks/{matrix['other']['task_id']}/cancel"
            )
            assert other.status_code == 200
            assert other.json()["status"] == "running"
            assert comfy.interrupt_calls == [matrix["running"]["prompt_id"]]

            for key in ("done", "failed"):
                terminal = client.post(
                    f"/api/tasks/{matrix[key]['task_id']}/cancel"
                )
                assert terminal.status_code == 409
                assert terminal.json()["detail"]["code"] == "conflict"
                assert comfy.interrupt_calls == [matrix["running"]["prompt_id"]]
    finally:
        asyncio.run(_cleanup_fixtures(fixtures))
        asyncio.run(engine.dispose())


def test_cancel_route_keeps_committed_intent_when_interrupt_fails(caplog) -> None:
    error = httpx.ConnectError(
        "Comfy connection failed",
        request=httpx.Request("POST", "http://comfy/interrupt"),
    )
    comfy = _BarrierComfy(interrupt_error=error)
    vllm = _FakeVLLM()
    application = _application(comfy=comfy, vllm=vllm, stop_worker=True)
    fixture: dict[str, Any] | None = None
    try:
        with TestClient(application) as client:
            fixture = asyncio.run(_create_asset_task(status="running"))
            response = client.post(f"/api/tasks/{fixture['task_id']}/cancel")
            assert response.status_code == 200
            assert response.json()["status"] == "running"
            assert response.json()["cancel_requested_at"] is not None
            assert comfy.interrupt_calls == [fixture["prompt_id"]]
            row = asyncio.run(_read_task(fixture["task_id"]))
            assert row["status"] == "running"
            assert row["cancel_requested_at"] is not None
        warning_messages = [record.getMessage() for record in caplog.records]
        assert any(
            str(fixture["task_id"]) in message
            and fixture["prompt_id"] in message
            and "interrupt" in message
            for message in warning_messages
        )
    finally:
        asyncio.run(_cleanup_fixtures([] if fixture is None else [fixture]))
        asyncio.run(engine.dispose())


def test_running_comfy_cancel_wins_and_cleans_generated_state(
    tmp_path: Path, monkeypatch
) -> None:
    comfy = _BarrierComfy(mode="interrupt")
    vllm = _FakeVLLM()
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(image_task, "VLLMClient", lambda _base_url: vllm)
    monkeypatch.setattr(image_task, "ComfyClient", lambda _base_url: comfy)
    application = _application(comfy=comfy, vllm=vllm)
    fixture = asyncio.run(_create_asset_task())
    try:
        with TestClient(application) as client:
            assert comfy.submitted.wait(10), "worker did not submit Comfy prompt"
            response = client.post(f"/api/tasks/{fixture['task_id']}/cancel")
            assert response.status_code == 200
            assert response.json()["status"] == "running"
            assert response.json()["cancel_requested_at"] is not None
            assert comfy.interrupt_calls == [fixture["prompt_id"]]
            row = _wait_for_status(fixture["task_id"], "canceled")
            assert row["error_msg"] is None
            assert comfy.submit_count == 1
            assert comfy.free_count == 1
            asset, images = asyncio.run(_read_asset_state(fixture))
            assert asset["image_prompt_cache"] is not None
            assert images == []
            assert not list((tmp_path / "tmp" / "asset-images").glob("*.upload"))
    finally:
        asyncio.run(_cleanup_fixtures([fixture]))
        asyncio.run(engine.dispose())


def test_cancel_after_comfy_before_final_commit_wins(
    tmp_path: Path, monkeypatch
) -> None:
    comfy = _BarrierComfy(mode="success")
    vllm = _FakeVLLM()
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(image_task, "VLLMClient", lambda _base_url: vllm)
    monkeypatch.setattr(image_task, "ComfyClient", lambda _base_url: comfy)
    final_safe_point_passed = threading.Event()
    allow_commit = threading.Event()
    original_safe_point = queue_module.WorkerContext.cancel_safe_point
    safe_point_calls = 0

    async def gated_safe_point(context):
        nonlocal safe_point_calls
        safe_point_calls += 1
        result = await original_safe_point(context)
        if safe_point_calls == 3:
            final_safe_point_passed.set()
            opened = await asyncio.to_thread(allow_commit.wait, 10)
            if not opened:
                raise RuntimeError("T9 final-commit barrier timed out")
        return result

    monkeypatch.setattr(
        queue_module.WorkerContext, "cancel_safe_point", gated_safe_point
    )
    application = _application(comfy=comfy, vllm=vllm)
    fixture = asyncio.run(_create_asset_task())
    try:
        with TestClient(application) as client:
            assert final_safe_point_passed.wait(10), (
                "worker did not reach final cancellation safe point"
            )
            response = client.post(f"/api/tasks/{fixture['task_id']}/cancel")
            assert response.status_code == 200
            assert response.json()["status"] == "running"
            assert comfy.interrupt_calls == [fixture["prompt_id"]]
            allow_commit.set()
            row = _wait_for_status(fixture["task_id"], "canceled")
            assert row["error_msg"] is None
            assert comfy.free_count == 1
            asset, images = asyncio.run(_read_asset_state(fixture))
            assert asset["image_prompt_cache"] == "cached prompt"
            assert asset["image_prompt_hash"] == "input-hash"
            assert images == []
            assert not list(tmp_path.rglob("*.png"))
    finally:
        allow_commit.set()
        asyncio.run(_cleanup_fixtures([fixture]))
        asyncio.run(engine.dispose())


def test_final_commit_wins_before_cancel_request(
    tmp_path: Path, monkeypatch
) -> None:
    comfy = _BarrierComfy(mode="success")
    vllm = _FakeVLLM()
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(image_task, "VLLMClient", lambda _base_url: vllm)
    monkeypatch.setattr(image_task, "ComfyClient", lambda _base_url: comfy)
    commit_finished = threading.Event()
    allow_handler = threading.Event()
    original_commit = image_task.commit_generated_asset_image

    async def gated_commit(*args: object, **kwargs: object):
        result = await original_commit(*args, **kwargs)
        commit_finished.set()
        opened = await asyncio.to_thread(allow_handler.wait, 10)
        if not opened:
            raise RuntimeError("T9 post-commit barrier timed out")
        return result

    monkeypatch.setattr(image_task, "commit_generated_asset_image", gated_commit)
    application = _application(comfy=comfy, vllm=vllm)
    fixture = asyncio.run(_create_asset_task())
    try:
        with TestClient(application) as client:
            assert commit_finished.wait(10), "worker did not finish final transaction"
            response = client.post(f"/api/tasks/{fixture['task_id']}/cancel")
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "conflict"
            assert comfy.interrupt_calls == []
            allow_handler.set()
            row = _wait_for_status(fixture["task_id"], "done")
            assert row["progress"] == 1
            asset, images = asyncio.run(_read_asset_state(fixture))
            assert asset["image_prompt_cache"] == "cached prompt"
            assert len(images) == 1
            formal_path = tmp_path / images[0]["file_path"]
            assert formal_path.is_file()
            assert comfy.free_count == 1
    finally:
        allow_handler.set()
        asyncio.run(_cleanup_fixtures([fixture]))
        asyncio.run(engine.dispose())
