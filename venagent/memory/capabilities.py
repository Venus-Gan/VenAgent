"""M05 provider 的进程级状态源与去重状态转移日志。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import RLock
from typing import Literal

ProviderState = Literal[
    "healthy",
    "degraded",
    "recovering",
    "disabled",
    "unavailable",
    "purge_pending",
]


@dataclass(frozen=True)
class MemoryHealth:
    state: Literal["READY", "DEGRADED", "DISABLED", "FAILED"]
    reason_code: str
    pending: int = 0
    failed: int = 0
    index_pending: int = 0
    purge_pending: bool = False
    error_summary: str | None = None
    graph_pending: int = 0
    graph_failed: int = 0
    graph_reason: str | None = None


@dataclass(frozen=True)
class MemorySettings:
    enabled: bool
    deletion_generation: int
    purge_pending: bool
    pending_jobs: int = 0
    failed_jobs: int = 0
    index_pending: int = 0
    last_error_code: str | None = None
    graph_pending: int = 0
    graph_failed: int = 0


@dataclass(frozen=True)
class MemoryCapabilityStatus:
    component: str
    state: ProviderState
    reason_code: str


class MemoryCapabilityRegistry:
    """同一份状态同时供启动快照、运行时 health 和安全降级使用。"""

    def __init__(
        self,
        statuses: tuple[MemoryCapabilityStatus, ...],
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._statuses = {item.component: item for item in statuses}
        self._logger = logger or logging.getLogger("venagent.memory")
        self._lock = RLock()

    def snapshot(self) -> tuple[MemoryCapabilityStatus, ...]:
        with self._lock:
            return tuple(self._statuses[key] for key in sorted(self._statuses))

    def get(self, component: str) -> MemoryCapabilityStatus:
        with self._lock:
            return self._statuses[component]

    def transition(
        self, component: str, state: ProviderState, reason_code: str
    ) -> None:
        value = MemoryCapabilityStatus(component, state, reason_code)
        with self._lock:
            previous = self._statuses.get(component)
            if previous == value:
                return
            self._statuses[component] = value
        self._logger.warning(
            "记忆能力状态已变化：%s -> %s。",
            previous.state if previous else "unknown",
            state,
            extra={
                "component": component,
                "state": state,
                "reason_code": reason_code,
            },
        )

    def mark_ready(self, component: str, reason_code: str) -> None:
        current = self.get(component)
        if current.state != "healthy" or current.reason_code != reason_code:
            self.transition(component, "healthy", reason_code)
