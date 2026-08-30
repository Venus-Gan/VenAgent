"""Agent 消费方 port；run 状态不再归 conversation 聚合管理。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .runs import AgentRun


class MessageInvoker(Protocol):
    """模型 adapter 的最小异步流式边界。"""

    async def astream(self, messages: Any) -> AsyncIterator[Any]: ...


class ToolCallingModel(MessageInvoker, Protocol):
    """可选工具模型协议；普通测试模型无需实现。"""

    def bind_tools(self, tools: Sequence[dict[str, Any]]) -> Any: ...


class RunStoreError(RuntimeError):
    """run adapter 对外只暴露稳定错误，不泄露 SQL/连接细节。"""


class RunStore(Protocol):
    def get_run_internal(self, run_id: str) -> AgentRun | None: ...

    def authorize_run(self, run_id: str, now: datetime): ...

    def claim_next(self, worker_id: str, now: datetime, lease_duration: timedelta): ...

    def request_cancel(self, owner_id: str, run_id: str, now: datetime) -> AgentRun: ...

    def wait_approval_run(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        now: datetime,
    ) -> AgentRun: ...

    def cancel_waiting_approval(
        self,
        owner_id: str,
        run_id: str,
        now: datetime,
    ) -> AgentRun: ...

    def resume_run(self, run_id: str, now: datetime) -> AgentRun: ...

    def set_run_skill(
        self,
        owner_id: str,
        run_id: str,
        skill_id: str | None,
        skill_name: str | None,
        now: datetime,
    ) -> AgentRun: ...

    def succeed_run(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        answer: str,
        now: datetime,
        blocks: tuple[dict[str, str], ...] = (),
    ) -> AgentRun: ...

    def append_run_event(
        self, run_id: str, event_type: str, payload: dict[str, Any], now: datetime
    ): ...

    def run_events(
        self, owner_id: str, run_id: str, *, after_sequence: int = 0
    ): ...

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
