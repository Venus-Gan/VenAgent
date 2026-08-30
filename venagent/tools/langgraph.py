"""M06 的 LangGraph interrupt/resume Approval 暂停协议。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .approval import ApprovalService

ApprovalStatus = Literal["pending", "approved", "rejected", "expired"]


class ApprovalState(TypedDict, total=False):
    """审批节点只保存定位信号；决定权威始终在 ApprovalService。"""

    run_id: str
    owner_id: str
    tool_id: str
    tool_call_id: str
    operation_id: str
    operation_key: str
    approval_id: str | None
    status: ApprovalStatus
    reason: str
    resume: Any


def build_approval_node(approvals: ApprovalService):
    """返回幂等审批节点：首次 interrupt，恢复时按权威记录继续。"""

    async def approval_node(state: ApprovalState) -> dict[str, Any]:
        item = approvals.find_or_create(
            run_id=state["run_id"],
            owner_id=state["owner_id"],
            operation_id=state.get("operation_id", ""),
            tool_id=state["tool_id"],
            tool_call_id=state["tool_call_id"],
            reason=f"{state['tool_id']} 需要用户审批。",
            now=datetime.now(timezone.utc),
        )
        interrupt(
            {
                "kind": "approval",
                "approval_id": item.approval_id,
                "run_id": item.run_id,
                "tool_id": item.tool_id,
            }
        )
        # 恢复时节点从头重跑；决定只读自 ApprovalService，resume 值不授权。
        item = approvals.get(item.approval_id)
        if item.status == "approved":
            return {
                "approval_id": item.approval_id,
                "status": "approved",
                "reason": item.reason,
            }
        if item.status == "rejected":
            return {
                "approval_id": item.approval_id,
                "status": "rejected",
                "reason": item.rejected_reason or "用户拒绝",
            }
        if item.status == "expired":
            return {
                "approval_id": item.approval_id,
                "status": "expired",
                "reason": "审批已过期",
            }
        interrupt(
            {
                "kind": "approval",
                "approval_id": item.approval_id,
                "run_id": item.run_id,
                "tool_id": item.tool_id,
            }
        )
        return {"approval_id": item.approval_id, "status": "pending"}

    return approval_node


def compile_approval_graph(approval_node, checkpointer: Any = None):
    """构建 `run_id` 单线程审批图；checkpoint 由调用方提供。"""

    builder = StateGraph(ApprovalState)
    builder.add_node("approval", approval_node)
    builder.add_edge(START, "approval")
    builder.add_edge("approval", END)
    return builder.compile(checkpointer=checkpointer)


def approval_run_config(run_id: str) -> dict[str, dict[str, str]]:
    """业务 run 与审批 checkpoint thread 一一对应。"""

    return {"configurable": {"thread_id": run_id}}
