from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

import app.api.tasks as tasks_api
from app.tasks.events import EventBus, TaskEvent


def _event(task_id: int = 1) -> TaskEvent:
    return TaskEvent(
        task_id=task_id,
        type="gen_assets",
        status="running",
        progress=0.5,
        message="C012 websocket event",
    )


class _BlockingReceiveWebSocket:
    def __init__(self, bus: EventBus) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(task_event_bus=bus))
        self.accepted = asyncio.Event()
        self.receive_started = asyncio.Event()
        self.receive_cancelled = asyncio.Event()
        self.send_started = asyncio.Event()
        self.send_cancelled = asyncio.Event()
        self.close_codes: list[int | None] = []

    async def accept(self) -> None:
        self.accepted.set()

    async def receive(self) -> dict[str, object]:
        self.receive_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.receive_cancelled.set()
            raise
        raise AssertionError("blocking receive unexpectedly returned")

    async def send_json(self, _payload: object) -> None:
        self.send_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.send_cancelled.set()
            raise
        raise AssertionError("blocking send unexpectedly returned")

    async def close(self, *, code: int | None = None) -> None:
        self.close_codes.append(code)


class _SendErrorWebSocket(_BlockingReceiveWebSocket):
    async def send_json(self, _payload: object) -> None:
        self.send_started.set()
        raise RuntimeError("controlled send failure")


class _SimultaneousWebSocket:
    def __init__(self, bus: EventBus) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(task_event_bus=bus))
        self.receive_started = asyncio.Event()
        self.first_receive_release = asyncio.Event()
        self.normal_receive_observed = False
        self.receive_calls = 0
        self.sent: list[dict[str, object]] = []
        self.close_codes: list[int | None] = []

    async def accept(self) -> None:
        return None

    async def receive(self) -> dict[str, object]:
        self.receive_calls += 1
        if self.receive_calls == 1:
            self.receive_started.set()
            await self.first_receive_release.wait()
            self.normal_receive_observed = True
            return {"type": "websocket.receive", "text": "ping"}
        return {"type": "websocket.disconnect"}

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(dict(payload))

    async def close(self, *, code: int | None = None) -> None:
        self.close_codes.append(code)


def _assert_no_pending_transport_tasks() -> None:
    current = asyncio.current_task()
    assert [
        task
        for task in asyncio.all_tasks()
        if task is not current and not task.done()
    ] == []


def test_c012_ws_overflow_notifies_owner_closes_1013_and_cleans_receive(
    caplog,
) -> None:
    async def run() -> None:
        bus = EventBus()
        websocket = _BlockingReceiveWebSocket(bus)
        route_task = asyncio.create_task(tasks_api.task_events(websocket))
        await asyncio.wait_for(websocket.receive_started.wait(), timeout=1)

        for task_id in range(257):
            await bus.publish(_event(task_id))
        await asyncio.wait_for(route_task, timeout=1)

        assert websocket.close_codes == [1013]
        assert websocket.receive_cancelled.is_set()
        assert not websocket.send_started.is_set()
        assert bus.subscriber_count == 0
        assert "reason=subscription_overflow" in caplog.text
        _assert_no_pending_transport_tasks()

    with caplog.at_level("WARNING", logger="app.api.tasks"):
        asyncio.run(run())


def test_c012_ws_send_timeout_cancels_all_transport_tasks(monkeypatch, caplog) -> None:
    async def run() -> None:
        bus = EventBus()
        websocket = _BlockingReceiveWebSocket(bus)
        route_task = asyncio.create_task(tasks_api.task_events(websocket))
        await asyncio.wait_for(websocket.receive_started.wait(), timeout=1)
        await bus.publish(_event())
        await asyncio.wait_for(websocket.send_started.wait(), timeout=1)
        await asyncio.wait_for(route_task, timeout=1)

        assert websocket.close_codes == [1013]
        assert websocket.send_cancelled.is_set()
        assert websocket.receive_cancelled.is_set()
        assert bus.subscriber_count == 0
        assert "reason=send_timeout" in caplog.text
        _assert_no_pending_transport_tasks()

    assert tasks_api.WS_SEND_TIMEOUT_SECONDS == 10.0
    monkeypatch.setattr(tasks_api, "WS_SEND_TIMEOUT_SECONDS", 0.01)
    with caplog.at_level("WARNING", logger="app.api.tasks"):
        asyncio.run(run())


def test_c012_ws_send_error_closes_1013_without_task_state_mutation(caplog) -> None:
    async def run() -> None:
        bus = EventBus()
        websocket = _SendErrorWebSocket(bus)
        route_task = asyncio.create_task(tasks_api.task_events(websocket))
        await asyncio.wait_for(websocket.receive_started.wait(), timeout=1)
        await bus.publish(_event())
        await asyncio.wait_for(websocket.send_started.wait(), timeout=1)
        await asyncio.wait_for(route_task, timeout=1)

        assert websocket.close_codes == [1013]
        assert websocket.receive_cancelled.is_set()
        assert bus.subscriber_count == 0
        assert "reason=send_error" in caplog.text
        assert "controlled send failure" in caplog.text
        _assert_no_pending_transport_tasks()

    with caplog.at_level("WARNING", logger="app.api.tasks"):
        asyncio.run(run())


def test_c012_ws_observes_normal_receive_and_ready_event_together() -> None:
    async def run() -> None:
        bus = EventBus()
        websocket = _SimultaneousWebSocket(bus)
        route_task = asyncio.create_task(tasks_api.task_events(websocket))
        await asyncio.wait_for(websocket.receive_started.wait(), timeout=1)
        await bus.publish(_event(42))
        websocket.first_receive_release.set()
        await asyncio.wait_for(route_task, timeout=1)

        assert websocket.normal_receive_observed
        assert websocket.receive_calls == 2
        assert websocket.sent == [_event(42).as_dict()]
        assert websocket.close_codes == []
        assert bus.subscriber_count == 0
        _assert_no_pending_transport_tasks()

    asyncio.run(run())


def test_c012_ws_application_cancellation_awaits_receive_and_unsubscribes() -> None:
    async def run() -> None:
        bus = EventBus()
        websocket = _BlockingReceiveWebSocket(bus)
        route_task = asyncio.create_task(tasks_api.task_events(websocket))
        await asyncio.wait_for(websocket.receive_started.wait(), timeout=1)
        route_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await route_task

        assert websocket.receive_cancelled.is_set()
        assert websocket.close_codes == []
        assert bus.subscriber_count == 0
        _assert_no_pending_transport_tasks()

    asyncio.run(run())
