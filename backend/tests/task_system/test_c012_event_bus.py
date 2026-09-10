from __future__ import annotations

import asyncio

from app.tasks.events import EventBus, TaskEvent


def test_c012_event_bus_bounds_slow_subscriber_and_preserves_healthy_order() -> None:
    async def run() -> None:
        bus = EventBus()
        overflowed = asyncio.Event()
        slow = bus.subscribe_queue(overflow_event=overflowed)
        healthy = bus.subscribe()
        assert bus.subscriber_count == 2

        events = [
            TaskEvent(
                task_id=index,
                type="gen_assets",
                status="running" if index < 256 else "done",
                progress=index / 256,
                message=f"event-{index}",
            )
            for index in range(257)
        ]
        healthy_payloads: list[dict[str, object]] = []

        async def consume_healthy() -> None:
            for _ in events:
                healthy_payloads.append(await healthy.get())

        healthy_consumer = asyncio.create_task(consume_healthy())
        for event in events[:256]:
            await bus.publish(event)
            assert slow.qsize() <= 256
            assert healthy.qsize() <= 256
            await asyncio.sleep(0)

        await bus.publish(events[256])
        await asyncio.sleep(0)
        await healthy_consumer
        assert slow.qsize() == 256
        assert overflowed.is_set()
        assert bus.subscriber_count == 1

        assert [payload["task_id"] for payload in healthy_payloads] == list(range(257))
        assert healthy_payloads[-1] == {
            "task_id": 256,
            "type": "gen_assets",
            "status": "done",
            "progress": 1.0,
            "message": "event-256",
        }
        assert all(
            set(payload) == {"task_id", "type", "status", "progress", "message"}
            for payload in healthy_payloads
        )
        assert [slow.get_nowait()["task_id"] for _ in range(256)] == list(range(256))
        assert slow.empty()

        bus.unsubscribe(slow)
        bus.unsubscribe(slow)
        bus.unsubscribe(healthy)
        bus.unsubscribe(healthy)
        assert bus.subscriber_count == 0

        replacement = bus.subscribe()
        await bus.publish(
            TaskEvent(
                task_id=999,
                type="gen_assets",
                status="done",
                progress=1.0,
                message="fresh-only",
            )
        )
        assert replacement.get_nowait()["task_id"] == 999
        assert replacement.empty()
        print(
            "C012 EventBus observations "
            f"slow_qsize={slow.qsize()} healthy_events={len(healthy_payloads)} "
            f"overflow_notified={overflowed.is_set()} subscribers={bus.subscriber_count}"
        )

    asyncio.run(run())
