"""In-memory event bus for optimize runs.

Lets a background `run_optimize` task (sync thread) emit structured events and
lets SSE subscribers (async HTTP handlers) consume them by `task_id`. This
replaces the hard-coded simulated stream in ``api/routes/optimize_stream.py``
with real events from the running optimizer.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any


CLOSE_SENTINEL = {"event": "__close__"}


class OptimizeEventBus:
    """Per-task_id fan-out of optimizer events.

    Emission from the optimizer runs in a thread pool (sync), while subscribers
    are FastAPI async generators. A threading lock guards subscriber metadata;
    the event loop is pulled from each subscriber at subscribe time so events
    can be scheduled onto the right loop from sync code.
    """

    def __init__(self, history_limit: int = 500) -> None:
        self._history_limit = history_limit
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._subscribers: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
        self._closed: set[str] = set()
        self._lock = threading.Lock()

    def emit(self, task_id: str, event_type: str, data: dict[str, Any]) -> None:
        """Emit one event. Safe to call from sync or async contexts."""
        payload = {"event": event_type, "data": dict(data)}
        with self._lock:
            history = self._history.setdefault(task_id, [])
            history.append(payload)
            if len(history) > self._history_limit:
                del history[0 : len(history) - self._history_limit]
            subs = list(self._subscribers.get(task_id, ()))
        for loop, queue in subs:
            self._schedule_put(loop, queue, payload)

    def close(self, task_id: str) -> None:
        """Signal the run is done; streams drain and exit."""
        with self._lock:
            self._closed.add(task_id)
            subs = list(self._subscribers.get(task_id, ()))
        for loop, queue in subs:
            self._schedule_put(loop, queue, CLOSE_SENTINEL)

    async def subscribe(self, task_id: str) -> asyncio.Queue:
        """Return an async queue that receives events for ``task_id``."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=1024)
        with self._lock:
            for past in self._history.get(task_id, ()):
                queue.put_nowait(past)
            closed = task_id in self._closed
            self._subscribers.setdefault(task_id, []).append((loop, queue))
        if closed:
            queue.put_nowait(CLOSE_SENTINEL)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(task_id)
            if not subs:
                return
            self._subscribers[task_id] = [
                (loop, q) for (loop, q) in subs if q is not queue
            ]

    def is_known(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._history or task_id in self._closed

    @staticmethod
    def _schedule_put(
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue,
        payload: dict[str, Any],
    ) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, payload)
        except RuntimeError:
            pass
