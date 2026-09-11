from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.api import tasks as tasks_api
from app.tasks.events import EventBus, TaskEvent


def _event(task_id: int = 1) -> TaskEvent:
    return TaskEvent(
        task_id=task_id,
        type="gen_assets",
        status="running",
        progress=0.25,
        message="C012 T39 event",
    )


class _ControlledWebSocket:
    def __init__(self, bus: EventBus, *, disconnect_on_receive: bool = False) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(task_event_bus=bus))
        self.disconnect_on_receive = disconnect_on_receive
        self.receive_started = asyncio.Event()
        self.receive_cancelled = asyncio.Event()
        self.release_disconnect = asyncio.Event()
        self.send_started = asyncio.Event()
        self.send_cancelled = asyncio.Event()
        self.sent: list[dict[str, object]] = []
        self.close_codes: list[int | None] = []

    async def accept(self) -> None:
        return None

    async def receive(self) -> dict[str, object]:
        self.receive_started.set()
        if self.disconnect_on_receive:
            await self.release_disconnect.wait()
            return {"type": "websocket.disconnect"}
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.receive_cancelled.set()
            raise
        raise AssertionError("blocking receive unexpectedly returned")

    async def send_json(self, payload: dict[str, object]) -> None:
        self.send_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.send_cancelled.set()
            raise
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


def test_c012_ws_overflow_during_blocked_send_closes_owner_immediately(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    assert tasks_api.WS_SEND_TIMEOUT_SECONDS == 10.0
    monkeypatch.setattr(tasks_api, "WS_SEND_TIMEOUT_SECONDS", 0.2)

    async def run() -> None:
        bus = EventBus()
        websocket = _ControlledWebSocket(bus)
        route_task = asyncio.create_task(tasks_api.task_events(websocket))
        await asyncio.wait_for(websocket.receive_started.wait(), timeout=1)
        await bus.publish(_event())
        await asyncio.wait_for(websocket.send_started.wait(), timeout=1)

        for task_id in range(2, 259):
            await bus.publish(_event(task_id))

        await asyncio.wait_for(route_task, timeout=1)
        assert websocket.close_codes == [1013]
        assert websocket.send_cancelled.is_set()
        assert websocket.receive_cancelled.is_set()
        assert bus.subscriber_count == 0
        assert "reason=subscription_overflow" in caplog.text
        assert "reason=send_timeout" not in caplog.text
        _assert_no_pending_transport_tasks()

    with caplog.at_level("WARNING", logger="app.api.tasks"):
        asyncio.run(run())


def test_c012_ws_send_timeout_without_overflow_keeps_timeout_contract(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(tasks_api, "WS_SEND_TIMEOUT_SECONDS", 0.02)

    async def run() -> None:
        bus = EventBus()
        websocket = _ControlledWebSocket(bus)
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

    with caplog.at_level("WARNING", logger="app.api.tasks"):
        asyncio.run(run())


def test_c012_ws_disconnect_and_application_exit_release_transport_tasks() -> None:
    async def run_disconnect() -> None:
        bus = EventBus()
        websocket = _ControlledWebSocket(bus, disconnect_on_receive=True)
        route_task = asyncio.create_task(tasks_api.task_events(websocket))
        await asyncio.wait_for(websocket.receive_started.wait(), timeout=1)
        websocket.release_disconnect.set()
        await asyncio.wait_for(route_task, timeout=1)

        assert websocket.close_codes == []
        assert bus.subscriber_count == 0
        _assert_no_pending_transport_tasks()

    async def run_application_exit() -> None:
        bus = EventBus()
        websocket = _ControlledWebSocket(bus)
        route_task = asyncio.create_task(tasks_api.task_events(websocket))
        await asyncio.wait_for(websocket.receive_started.wait(), timeout=1)
        route_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await route_task

        assert websocket.receive_cancelled.is_set()
        assert websocket.close_codes == []
        assert bus.subscriber_count == 0
        _assert_no_pending_transport_tasks()

    asyncio.run(run_disconnect())
    asyncio.run(run_application_exit())
