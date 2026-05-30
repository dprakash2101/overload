from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._queues: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, event: str, handler: Callable) -> None:
        self._handlers[event].append(handler)

    def unsubscribe(self, event: str, handler: Callable) -> None:
        handlers = self._handlers.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    def create_queue(self, event: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._queues[event].append(queue)
        return queue

    def remove_queue(self, event: str, queue: asyncio.Queue) -> None:
        queues = self._queues.get(event, [])
        if queue in queues:
            queues.remove(queue)

    async def emit(self, event: str, data: Any = None) -> None:
        logger.debug("Event emitted: %s", event)

        for handler in self._handlers.get(event, []):
            try:
                result = handler(data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Error in event handler for %s", event)

        for queue in self._queues.get(event, []):
            try:
                queue.put_nowait({"event": event, "data": data})
            except asyncio.QueueFull:
                logger.warning("Event queue full for %s, dropping event", event)
