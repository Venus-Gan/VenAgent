"""Lifespan-managed durable memory job consumer."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from .service import MemoryService

LOGGER = logging.getLogger("venagent.memory.job_worker")


class MemoryMaintenanceWorker:
    def __init__(
        self, service: MemoryService, *, poll_interval: float = 1.0, batch_size: int = 8
    ) -> None:
        self._service = service
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(
                    self._service.process_pending_jobs, limit=self._batch_size
                )
            except Exception:
                LOGGER.warning(
                    "记忆后台维护单轮失败。",
                    extra={"reason_code": "memory_maintenance_iteration_failed"},
                )
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._poll_interval
                )
            except asyncio.TimeoutError:
                continue
