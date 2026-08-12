"""运行期在线观察分发，不保存 token 或运行事实。"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, AsyncIterator


@dataclass(frozen=True)
class RunObservation:
    run_id: str
    event: str
    sequence: int
    payload: dict[str, Any]


class RunObservationHub:
    """只分发在线观察，不拥有 run 生命周期。"""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[RunObservation]]] = {}
        self._sequences: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def publish(self, run_id: str, event: str, **payload: Any) -> None:
        async with self._lock:
            sequence = self._sequences.get(run_id, 0) + 1
            self._sequences[run_id] = sequence
            observation = RunObservation(run_id, event, sequence, payload)
            subscribers = tuple(self._subscribers.get(run_id, ()))
        for queue in subscribers:
            with suppress(asyncio.QueueFull):
                queue.put_nowait(observation)

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
