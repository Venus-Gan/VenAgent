"""Agent 消费方 port；run 状态不再归 conversation 聚合管理。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .runs import AgentRun


class MessageInvoker(Protocol):
    """模型 adapter 的最小异步流式边界。"""

    async def astream(self, messages: Any) -> AsyncIterator[Any]: ...


class RunStoreError(RuntimeError):
    """run adapter 对外只暴露稳定错误，不泄露 SQL/连接细节。"""


class RunStore(Protocol):
    def get_run_internal(self, run_id: str) -> AgentRun | None: ...

    def authorize_run(self, run_id: str, now: datetime): ...

    def claim_next(self, worker_id: str, now: datetime, lease_duration: timedelta): ...

    def request_cancel(self, owner_id: str, run_id: str, now: datetime) -> AgentRun: ...

    def succeed_run(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        answer: str,
        now: datetime,
    ) -> AgentRun: ...

    def fail_run(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        reason_code: str,
        message: str,
        now: datetime,
    ) -> AgentRun: ...

    def heartbeat(
        self,
        run_id: str,
        worker_id: str,
        claim_token: str,
        execution_attempt: int,
        now: datetime,
        lease_duration: timedelta,
    ) -> AgentRun: ...

    def cancel_run(
        self,
        run_id: str,
        worker_id: str,
        claim_token: str,
        execution_attempt: int,
        reason_code: str,
        now: datetime,
    ) -> AgentRun: ...

    def incompatible_run(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        message: str,
        now: datetime,
    ) -> AgentRun: ...
