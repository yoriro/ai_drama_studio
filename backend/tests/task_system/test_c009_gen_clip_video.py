from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.api import tasks as task_api
from app.core.config import settings
from app.integrations.workflow_binding import load_minimax_binding_snapshot
from app.services.clip_video_inputs import build_minimaxh3_response_format
from app.tasks import gen_clip_video as video_task
from app.tasks.queue import ClaimedTask


class _FakeContext:
    def __init__(self, *, cancel_at: int | None = None) -> None:
        self.cancel_at = cancel_at
        self.safe_calls = 0
        self.heartbeats: list[float] = []

    async def cancel_safe_point(self) -> SimpleNamespace:
        self.safe_calls += 1
        status = "canceled" if self.cancel_at == self.safe_calls else "running"
        return SimpleNamespace(task=SimpleNamespace(status=status))

    async def heartbeat(self, progress: float) -> None:
        self.heartbeats.append(progress)

    async def cancel_requested(self) -> bool:
        return self.cancel_at is not None and self.safe_calls >= self.cancel_at


class _FakeVLLM:
    def __init__(
        self,
        events: list[tuple[str, object]],
        *,
        response: object | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.response = (
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"prompt": "built prompt"})
                        }
                    }
                ]
            }
            if response is None
            else response
        )
        self.error = error
        self.calls: list[str] = []
        self.chat_requests: list[dict[str, object]] = []

    async def wake(self) -> None:
        self.calls.append("wake")
        self.events.append(("wake", None))

    async def sleep(self) -> None:
        self.calls.append("sleep")
        self.events.append(("sleep", None))

    async def structured_chat(self, **request: object) -> object:
        self.calls.append("chat")
        self.chat_requests.append(copy.deepcopy(request))
        self.events.append(("chat", copy.deepcopy(request)))
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.response)


class _FakeWebSocket:
    def __init__(self, events: list[tuple[str, object]], messages: list[dict[str, object]]) -> None:
        self.events = events
        self.messages = messages

    async def recv(self) -> str:
        if not self.messages:
            raise AssertionError("Comfy websocket received more messages than expected")
        message = self.messages.pop(0)
        self.events.append(("recv", message["type"]))
        return json.dumps(message)


class _FakeComfy:
    def __init__(
        self,
        events: list[tuple[str, object]],
        *,
        mode: str = "success",
        free_error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.mode = mode
        self.free_error = free_error
        self.upload_calls: list[dict[str, object]] = []
        self.submit_calls: list[dict[str, object]] = []
        self.history_calls: list[str] = []
        self.view_calls: list[tuple[str, str, str]] = []
        self.free_calls = 0

    async def upload_image(
        self, *, filename: str, content: bytes, subfolder: str
    ) -> dict[str, object]:
        call = {
            "filename": filename,
            "content": content,
            "subfolder": subfolder,
        }
        self.upload_calls.append(call)
        self.events.append(("upload", call))
        if self.mode == "upload":
            return {"name": "not-an-image.txt", "subfolder": subfolder, "type": "input"}
        return {
            "name": filename,
            "subfolder": subfolder,
            "type": "input",
            "fullpath": "must-not-be-read",
        }

    @asynccontextmanager
    async def connect_ws(self, client_id: str):
        self.events.append(("connect", client_id))
        messages = [
            {
                "type": "progress",
                "data": {"prompt_id": client_id, "value": 1, "max": 2},
            },
            {
                "type": "executing",
                "data": {"prompt_id": client_id, "node": "168"},
            },
            {
                "type": "progress",
                "data": {"prompt_id": client_id, "value": 2, "max": 2},
            },
            {
                "type": "execution_success",
                "data": {"prompt_id": client_id},
            },
        ]
        yield _FakeWebSocket(self.events, messages)

    async def submit(
        self,
        *,
        prompt: dict[str, object],
        client_id: str,
        prompt_id: str,
    ) -> dict[str, object]:
        call = {
            "prompt": copy.deepcopy(prompt),
            "client_id": client_id,
            "prompt_id": prompt_id,
        }
        self.submit_calls.append(call)
        self.events.append(("submit", call))
        if self.mode in {"submit", "primary_free"}:
            raise RuntimeError("submit-primary")
        return {"prompt_id": prompt_id}

    async def history(self, prompt_id: str) -> dict[str, object]:
        self.history_calls.append(prompt_id)
        self.events.append(("history", prompt_id))
        if self.mode == "history":
            return {
                prompt_id: {
                    "status": {"status_str": "success"},
                    "outputs": {"168": {"gifs": []}},
                }
            }
        return {
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
        }

    async def view_stream(
        self, *, filename: str, subfolder: str, media_type: str
    ):
        self.view_calls.append((filename, subfolder, media_type))
        self.events.append(("view", self.view_calls[-1]))
        if self.mode == "view":
            raise RuntimeError("view-primary")
        yield b"not-a-real-mp4-yet"

    async def free(self) -> None:
        self.free_calls += 1
        self.events.append(("free", None))
        if self.free_error is not None:
            raise self.free_error


def _task_fixture(data_dir: Path, *, reference_count: int, cached_prompt: str | None) -> ClaimedTask:
    binding = load_minimax_binding_snapshot()
    references: list[dict[str, object]] = []
    reference_media: list[dict[str, object]] = []
    for index in range(1, reference_count + 1):
        relative_path = Path("projects", "1", "assets", str(index), f"{index}.png")
        content = f"reference-{index}".encode()
        path = data_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        references.append(
            {
                "slot_no": index,
                "reference_name": f"subject{index}",
                "asset_type": "character",
                "asset_name": f"subject {index}",
                "asset_description": f"description {index}",
                "image_source": "asset_current",
                "image_id": index,
                "override_sha256": None,
            }
        )
        reference_media.append(
            {
                "file_path": relative_path.as_posix(),
                "extension": "png",
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    snapshot = {
        "clip": {"id": 7, "episode_id": 3, "revision": 2, "generation_mode": "ref2v"},
        "rendered_prompt": "rendered prompt from the frozen snapshot",
        "model": "model-from-snapshot",
        "temperature": 0.35,
        "guided_json_schema": build_minimaxh3_response_format(),
        "seed": 12345,
        "requested_duration": 3,
        "comfy_prompt_id": "prompt-42",
        "workflow": binding.workflow_payload(),
        "shots": [],
        "references": references,
        "reference_media": reference_media,
        "cached_prompt": cached_prompt,
    }
    return ClaimedTask(
        id=42,
        type="gen_clip_video",
        target_id=7,
        request_id=None,
        payload={
            "input_snapshot": snapshot,
            "input_hash": "input-hash-from-snapshot",
            "source_revisions": {},
        },
    )


def _patch_clients(
    monkeypatch: pytest.MonkeyPatch,
    data_dir: Path,
    vllm: _FakeVLLM,
    comfy: _FakeComfy,
) -> None:
    monkeypatch.setattr(settings, "DATA_DIR", data_dir)
    monkeypatch.setattr(video_task, "VLLMClient", lambda _base_url: vllm)
    monkeypatch.setattr(video_task, "ComfyClient", lambda _base_url: comfy)


def test_c009_gen_clip_video_cache_miss_runs_snapshot_pipeline_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "miss"
    events: list[tuple[str, object]] = []
    vllm = _FakeVLLM(events)
    comfy = _FakeComfy(events)
    _patch_clients(monkeypatch, data_dir, vllm, comfy)
    task = _task_fixture(data_dir, reference_count=2, cached_prompt=None)
    context = _FakeContext()

    result = asyncio.run(video_task.gen_clip_video_handler(task, context))

    assert result is not None
    assert result.built_prompt == "built prompt"
    assert result.temp_path == data_dir / "tmp" / "clip-videos" / "42.mp4"
    assert result.temp_path.read_bytes() == b"not-a-real-mp4-yet"
    assert vllm.calls == ["wake", "chat", "sleep"]
    assert vllm.chat_requests == [
        {
            "messages": [
                {
                    "role": "user",
                    "content": "rendered prompt from the frozen snapshot",
                }
            ],
            "model": "model-from-snapshot",
            "temperature": 0.35,
            "schema_name": "minimaxh3",
            "schema": {
                "type": "object",
                "properties": {"prompt": {"type": "string"}},
                "required": ["prompt"],
                "additionalProperties": False,
            },
        }
    ]
    assert [call["filename"] for call in comfy.upload_calls] == [
        "subject1.png",
        "subject2.png",
    ]
    assert [call["subfolder"] for call in comfy.upload_calls] == [
        "c009/task-42",
        "c009/task-42",
    ]
    assert [call["content"] for call in comfy.upload_calls] == [
        b"reference-1",
        b"reference-2",
    ]
    assert len(comfy.submit_calls) == 1
    submitted = comfy.submit_calls[0]["prompt"]
    assert submitted["138"]["inputs"]["value"] == "built prompt"
    assert submitted["129"]["inputs"]["noise_seed"] == 12345
    assert submitted["132"]["inputs"]["value"] == 3
    assert submitted["137"]["inputs"]["image"] == "c009/task-42/subject1.png"
    assert submitted["139"]["inputs"]["image"] == "c009/task-42/subject2.png"
    assert "146" not in submitted
    assert "400" not in submitted
    assert submitted["186"]["inputs"]["ref_images.ref_image_0"] == ["137", 0]
    assert submitted["186"]["inputs"]["ref_images.ref_image_1"] == ["139", 0]
    assert "ref_images.ref_image_2" not in submitted["186"]["inputs"]
    assert comfy.history_calls == ["prompt-42"]
    assert comfy.view_calls == [("clip.mp4", "output", "output")]
    assert comfy.free_calls == 1
    assert context.heartbeats == [0.575, 0.9]


def test_c009_gen_clip_video_cache_hit_skips_chat_but_sleeps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "hit"
    events: list[tuple[str, object]] = []
    vllm = _FakeVLLM(events)
    comfy = _FakeComfy(events)
    _patch_clients(monkeypatch, data_dir, vllm, comfy)
    task = _task_fixture(data_dir, reference_count=1, cached_prompt="cached prompt")

    result = asyncio.run(video_task.gen_clip_video_handler(task, _FakeContext()))

    assert result is not None
    assert result.built_prompt == "cached prompt"
    assert vllm.calls == ["sleep"]
    assert vllm.chat_requests == []
    assert len(comfy.upload_calls) == 1
    assert len(comfy.submit_calls) == 1
    assert comfy.free_calls == 1


@pytest.mark.parametrize(
    "bad_response",
    [
        {"choices": [{"message": {"content": '{"prompt":"ok","extra":1}'}}]},
        {"choices": [{"message": {"content": '{"prompt":null}'}}]},
        {"choices": [{"message": {"content": '{"prompt":"   "}'}}]},
        {"choices": [{"message": {"content": "not-json"}}]},
        {"choices": [{"message": {"content": "[1]"}}]},
    ],
    ids=["extra-key", "null", "blank", "invalid-json", "wrong-json-type"],
)
def test_c009_gen_clip_video_rejects_hostile_vllm_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_response: object,
) -> None:
    data_dir = tmp_path / "vllm-hostile"
    events: list[tuple[str, object]] = []
    vllm = _FakeVLLM(events, response=bad_response)
    comfy = _FakeComfy(events)
    _patch_clients(monkeypatch, data_dir, vllm, comfy)
    task = _task_fixture(data_dir, reference_count=1, cached_prompt=None)

    with pytest.raises(ValueError):
        asyncio.run(video_task.gen_clip_video_handler(task, _FakeContext()))

    assert vllm.calls == ["wake", "chat", "sleep"]
    assert comfy.upload_calls == []
    assert comfy.submit_calls == []
    assert comfy.free_calls == 1
    assert not (data_dir / "tmp" / "clip-videos" / "42.mp4").exists()


def test_c009_gen_clip_video_vllm_transport_error_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "vllm-transport"
    events: list[tuple[str, object]] = []
    error = httpx.ConnectError(
        "vLLM unavailable", request=httpx.Request("POST", "http://vllm/chat")
    )
    vllm = _FakeVLLM(events, error=error)
    comfy = _FakeComfy(events)
    _patch_clients(monkeypatch, data_dir, vllm, comfy)
    task = _task_fixture(data_dir, reference_count=1, cached_prompt=None)

    with pytest.raises(httpx.ConnectError):
        asyncio.run(video_task.gen_clip_video_handler(task, _FakeContext()))

    assert vllm.calls == ["wake", "chat", "sleep"]
    assert comfy.submit_calls == []
    assert comfy.free_calls == 1


@pytest.mark.parametrize("mode", ["upload", "submit", "history", "view"])
def test_c009_gen_clip_video_comfy_failure_frees_once_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    data_dir = tmp_path / f"comfy-{mode}"
    events: list[tuple[str, object]] = []
    vllm = _FakeVLLM(events)
    comfy = _FakeComfy(events, mode=mode)
    _patch_clients(monkeypatch, data_dir, vllm, comfy)
    task = _task_fixture(data_dir, reference_count=1, cached_prompt="cached prompt")

    with pytest.raises((RuntimeError, ValueError, video_task.ComfyResourceError)):
        asyncio.run(video_task.gen_clip_video_handler(task, _FakeContext()))

    assert comfy.free_calls == 1
    assert len(comfy.upload_calls) <= 1
    assert len(comfy.submit_calls) <= 1
    assert not (data_dir / "tmp" / "clip-videos" / "42.mp4").exists()


def test_c009_gen_clip_video_preserves_primary_and_free_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "double-error"
    events: list[tuple[str, object]] = []
    vllm = _FakeVLLM(events)
    comfy = _FakeComfy(
        events,
        mode="submit",
        free_error=RuntimeError("free-secondary"),
    )
    _patch_clients(monkeypatch, data_dir, vllm, comfy)
    task = _task_fixture(data_dir, reference_count=1, cached_prompt="cached prompt")

    with pytest.raises(video_task.ComfyResourceError) as raised:
        asyncio.run(video_task.gen_clip_video_handler(task, _FakeContext()))

    assert "submit-primary" in str(raised.value)
    assert "free-secondary" in str(raised.value)
    assert comfy.free_calls == 1


def test_c009_gen_clip_video_free_error_cleans_successful_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "free-after-success"
    events: list[tuple[str, object]] = []
    vllm = _FakeVLLM(events)
    comfy = _FakeComfy(events, free_error=RuntimeError("free-secondary"))
    _patch_clients(monkeypatch, data_dir, vllm, comfy)
    task = _task_fixture(data_dir, reference_count=1, cached_prompt="cached prompt")

    with pytest.raises(video_task.ComfyResourceError) as raised:
        asyncio.run(video_task.gen_clip_video_handler(task, _FakeContext()))

    assert "free-secondary" in str(raised.value)
    assert comfy.free_calls == 1
    assert comfy.view_calls == [("clip.mp4", "output", "output")]
    assert not (data_dir / "tmp" / "clip-videos" / "42.mp4").exists()


def test_c009_gen_clip_video_preserves_primary_and_cleanup_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline_dir = tmp_path / "cleanup-baseline"
    baseline_events: list[tuple[str, object]] = []
    baseline_vllm = _FakeVLLM(baseline_events)
    baseline_comfy = _FakeComfy(baseline_events)
    _patch_clients(monkeypatch, baseline_dir, baseline_vllm, baseline_comfy)
    baseline_task = _task_fixture(
        baseline_dir, reference_count=1, cached_prompt="cached prompt"
    )
    baseline_context = _FakeContext()
    baseline_result = asyncio.run(
        video_task.gen_clip_video_handler(baseline_task, baseline_context)
    )
    assert baseline_result is not None
    baseline_result.temp_path.unlink()

    data_dir = tmp_path / "cleanup-error"
    events: list[tuple[str, object]] = []
    vllm = _FakeVLLM(events)
    comfy = _FakeComfy(events)
    _patch_clients(monkeypatch, data_dir, vllm, comfy)
    task = _task_fixture(data_dir, reference_count=1, cached_prompt="cached prompt")

    def fail_cleanup(_path: Path) -> None:
        raise OSError("cleanup-secondary")

    monkeypatch.setattr(video_task, "cleanup_clip_video_temp", fail_cleanup)
    with pytest.raises(video_task.ComfyResourceError) as raised:
        asyncio.run(
            video_task.gen_clip_video_handler(
                task, _FakeContext(cancel_at=baseline_context.safe_calls - 1)
            )
        )

    assert "Comfy primary error" in str(raised.value)
    assert "cleanup-secondary" in str(raised.value)
    assert comfy.free_calls == 1
    (data_dir / "tmp" / "clip-videos" / "42.mp4").unlink(missing_ok=True)


def test_c009_gen_clip_video_cancels_at_every_worker_safe_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline_dir = tmp_path / "safe-point-baseline"
    events: list[tuple[str, object]] = []
    vllm = _FakeVLLM(events)
    comfy = _FakeComfy(events)
    _patch_clients(monkeypatch, baseline_dir, vllm, comfy)
    task = _task_fixture(baseline_dir, reference_count=1, cached_prompt="cached prompt")
    baseline_context = _FakeContext()
    baseline_result = asyncio.run(
        video_task.gen_clip_video_handler(task, baseline_context)
    )
    assert baseline_result is not None
    baseline_result.temp_path.unlink()
    safe_point_count = baseline_context.safe_calls
    assert safe_point_count > 0

    for cancel_at in range(1, safe_point_count + 1):
        data_dir = tmp_path / f"cancel-{cancel_at}"
        events = []
        vllm = _FakeVLLM(events)
        comfy = _FakeComfy(events)
        _patch_clients(monkeypatch, data_dir, vllm, comfy)
        task = _task_fixture(
            data_dir, reference_count=1, cached_prompt="cached prompt"
        )
        context = _FakeContext(cancel_at=cancel_at)

        result = asyncio.run(video_task.gen_clip_video_handler(task, context))

        assert result is None, cancel_at
        assert context.safe_calls == cancel_at
        assert not (data_dir / "tmp" / "clip-videos" / "42.mp4").exists()
        assert comfy.free_calls == 1


class _FakeCancelSession:
    @asynccontextmanager
    async def begin(self):
        yield


class _FakeCancelComfy:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[str] = []

    async def interrupt(self, prompt_id: str) -> None:
        self.calls.append(prompt_id)
        if self.error is not None:
            raise self.error


class _FakeCancelQueue:
    def __init__(self, task: object) -> None:
        self.task = task
        self.published: list[object] = []

    async def request_cancel(self, _session: object, task_id: int) -> object:
        assert task_id == self.task.id
        return SimpleNamespace(changed=True, task=self.task)

    async def publish_committed(self, change: object) -> None:
        self.published.append(change)


class _FakeCancelRequest:
    def __init__(self, queue: _FakeCancelQueue, comfy: _FakeCancelComfy) -> None:
        self.app = SimpleNamespace(
            state=SimpleNamespace(task_queue=queue, comfy_client=comfy)
        )

    async def body(self) -> bytes:
        return b""


def test_c009_cancel_route_interrupts_running_gen_clip_video_from_snapshot() -> None:
    task = SimpleNamespace(
        id=42,
        status="running",
        type="gen_clip_video",
        payload={"input_snapshot": {"comfy_prompt_id": "prompt-42"}},
    )
    comfy = _FakeCancelComfy()
    queue = _FakeCancelQueue(task)
    request = _FakeCancelRequest(queue, comfy)

    result = asyncio.run(task_api.cancel_task(42, request, _FakeCancelSession()))

    assert result is task
    assert comfy.calls == ["prompt-42"]
    assert queue.published


def test_c009_cancel_route_keeps_running_intent_when_interrupt_fails() -> None:
    error = httpx.ConnectError(
        "Comfy unavailable", request=httpx.Request("POST", "http://comfy/interrupt")
    )
    task = SimpleNamespace(
        id=42,
        status="running",
        type="gen_clip_video",
        payload={"input_snapshot": {"comfy_prompt_id": "prompt-42"}},
    )
    comfy = _FakeCancelComfy(error)
    queue = _FakeCancelQueue(task)
    request = _FakeCancelRequest(queue, comfy)

    result = asyncio.run(task_api.cancel_task(42, request, _FakeCancelSession()))

    assert result is task
    assert task.status == "running"
    assert comfy.calls == ["prompt-42"]
