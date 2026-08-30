"""运行期在线观察分发，不保存 token 或运行事实。"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from .events import RunEvent

RunObservation = RunEvent


class RunObservationHub:
    """只分发在线观察，不拥有 run 生命周期。"""

    def __init__(self, store: Any | None = None) -> None:
        self._store = store
        self._subscribers: dict[str, set[asyncio.Queue[RunObservation]]] = {}
        self._sequences: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def publish(self, run_id: str, event: str, **payload: Any) -> RunEvent:
        async with self._lock:
            append_event = getattr(self._store, "append_run_event", None)
            if not callable(append_event):
                sequence = self._sequences.get(run_id, 0) + 1
                self._sequences[run_id] = sequence
                observation = RunEvent(
                    run_id, sequence, event, payload, datetime.now(timezone.utc)
                )
            else:
                observation = await asyncio.to_thread(
                    append_event,
                    run_id,
                    event,
                    payload,
                    datetime.now(timezone.utc),
                )
            subscribers = tuple(self._subscribers.get(run_id, ()))
        for queue in subscribers:
            with suppress(asyncio.QueueFull):
                queue.put_nowait(observation)
        return observation

    async def subscribe(self, run_id: str) -> AsyncIterator[RunObservation]:
        queue: asyncio.Queue[RunObservation] = asyncio.Queue(maxsize=128)
        async with self._lock:
            self._subscribers.setdefault(run_id, set()).add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                subscribers = self._subscribers.get(run_id)
                if subscribers is not None:
                    subscribers.discard(queue)
                    if not subscribers:
                        self._subscribers.pop(run_id, None)
