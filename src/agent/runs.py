"""持久 AgentRun 模型、状态机与进程内快速通知。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from .errors import (
    InvalidRunId,
    InvalidRunTransition,
    RunAuthorizationInvalid,
    RunCancelled,
    RunError,
    RunNotFound,
)
from .ports import RunStore

__all__ = [
    "ActiveRunContext",
    "AgentRun",
    "AgentRunLifecycle",
    "CancelToken",
    "InvalidRunId",
    "InvalidRunTransition",
    "RunAuthorizationInvalid",
    "RunCancelled",
    "RunError",
    "RunNotFound",
    "validate_run_id",
]

RunStatus = Literal[
    "queued",
    "running",
    "waiting_approval",
    "succeeded",
    "failed",
    "cancelled",
    "incompatible",
]
ACTIVE_RUN_STATUSES = frozenset({"queued", "running", "waiting_approval"})
TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled", "incompatible"})


@dataclass(frozen=True)
class AgentRun:
    run_id: str
    conversation_id: str
    owner_id: str
    input_message_id: str
    grant_id: str
    status: RunStatus
    runtime_contract_version: int
    created_at: datetime
    updated_at: datetime
    output_message_id: str | None = None
    retry_of_run_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    terminal_reason_code: str | None = None
    terminal_message: str | None = None
    phase: str | None = None
    completed_nodes: int = 0
    total_nodes: int = 1
    claimed_by: str | None = None
    claim_token: str | None = None
    lease_expires_at: datetime | None = None
    execution_attempt: int = 0
    selected_skill_id: str | None = None
    selected_skill_name: str | None = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES


class CancelToken:
    """只加速当前 worker 感知取消，权威请求仍在 AgentRun。"""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


@dataclass
class ActiveRunContext:
    run_id: str
    owner_id: str
    claim_token: str
    execution_attempt: int
    token: CancelToken
    execution_task: asyncio.Task[object] | None = None
    lease_uncertain: bool = False


class AgentRunLifecycle:
    def __init__(self, store: RunStore) -> None:
        self._store = store

    def claim_next(
        self, worker_id: str, now: datetime, lease_duration: timedelta
    ) -> AgentRun | None:
        return self._store.claim_next(worker_id, now, lease_duration)

    def request_cancel(self, owner_id: str, run_id: str, now: datetime) -> AgentRun:
        return self._store.request_cancel(owner_id, validate_run_id(run_id), now)

    def wait_approval(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        now: datetime,
    ) -> AgentRun:
        return self._store.wait_approval_run(
            validate_run_id(run_id),
            claim_token,
            execution_attempt,
            now,
        )

    def resume(self, run_id: str, now: datetime) -> AgentRun:
        return self._store.resume_run(validate_run_id(run_id), now)

    def cancel_waiting_approval(
        self,
        owner_id: str,
        run_id: str,
        now: datetime,
    ) -> AgentRun:
        return self._store.cancel_waiting_approval(
            owner_id,
            validate_run_id(run_id),
            now,
        )

    def succeed(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        answer: str,
        now: datetime,
        blocks: tuple[dict[str, str], ...] = (),
    ) -> AgentRun:
        return self._store.succeed_run(
            validate_run_id(run_id),
            claim_token,
            execution_attempt,
            answer,
            now,
            blocks,
        )

    def fail(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        reason_code: str,
        message: str,
        now: datetime,
    ) -> AgentRun:
        return self._store.fail_run(
            validate_run_id(run_id),
            claim_token,
            execution_attempt,
            reason_code,
            message,
            now,
        )

    def cancel(
        self,
        run_id: str,
        worker_id: str,
        claim_token: str,
        execution_attempt: int,
        reason_code: str,
        now: datetime,
    ) -> AgentRun:
        return self._store.cancel_run(
            validate_run_id(run_id),
            worker_id,
            claim_token,
            execution_attempt,
            reason_code,
            now,
        )

    def incompatible(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        message: str,
        now: datetime,
    ) -> AgentRun:
        return self._store.incompatible_run(
            validate_run_id(run_id),
            claim_token,
            execution_attempt,
            message,
            now,
        )


def validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str):
        raise InvalidRunId
    try:
        parsed = UUID(run_id)
    except (ValueError, AttributeError) as exc:
        raise InvalidRunId from exc
    canonical = str(parsed)
    if canonical != run_id:
        raise InvalidRunId
    return canonical
