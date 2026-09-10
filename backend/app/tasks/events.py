"""A small in-process event bus for committed task changes.

The queue never publishes from a database mutation.  Callers commit the
transaction first and then call ``TaskQueue.publish_committed`` (or call an
``EventBus.publish`` callback themselves).  ``EventBus`` exposes queues so an
HTTP/WebSocket adapter can own connection lifetime and transport details.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias


@dataclass(frozen=True, slots=True)
class TaskEvent:
    """The only event shape emitted by the queue publisher boundary."""

    task_id: int
    type: str
    status: str
    progress: float
    message: str

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-ready event without exposing the task payload."""

        return {
            "task_id": self.task_id,
            "type": self.type,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
        }


TaskEventPublisher: TypeAlias = "Callable[[TaskEvent], Awaitable[None]]"


class EventBus:
    """Fan out committed task events to current subscribers only.

    ``subscribe_queue`` returns an ``asyncio.Queue`` of plain dictionaries.
    The bus does not replay history.  A transport adapter must call
    ``unsubscribe`` when its connection closes.
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, object]]] = set()
        self._overflow_events: dict[
            asyncio.Queue[dict[str, object]], asyncio.Event
        ] = {}

    def subscribe_queue(
        self, *, overflow_event: asyncio.Event | None = None
    ) -> asyncio.Queue[dict[str, object]]:
        """Create and register a queue for future events."""

        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        if overflow_event is not None:
            self._overflow_events[queue] = overflow_event
        return queue

    def subscribe(
        self, *, overflow_event: asyncio.Event | None = None
    ) -> asyncio.Queue[dict[str, object]]:
        """Readable alias for ``subscribe_queue`` for transport adapters."""

        return self.subscribe_queue(overflow_event=overflow_event)

    def unsubscribe(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        """Stop delivery to a previously subscribed queue."""

        self._subscribers.discard(queue)
        self._overflow_events.pop(queue, None)

    @property
    def subscriber_count(self) -> int:
        """Return the number of currently connected event consumers."""

        return len(self._subscribers)

    async def publish(self, event: TaskEvent | Mapping[str, Any]) -> None:
        """Publish one already-committed event to current subscribers."""

        payload = event.as_dict() if isinstance(event, TaskEvent) else dict(event)
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(dict(payload))
            except asyncio.QueueFull:
                self._subscribers.discard(queue)
                overflow_event = self._overflow_events.pop(queue, None)
                if overflow_event is not None:
                    overflow_event.set()
