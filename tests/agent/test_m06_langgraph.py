"""LangGraph interrupt/resume 审批暂停协议测试。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from src.tools.approval import ApprovalService
from src.tools.errors import ApprovalExpired
from src.tools.langgraph import (
    approval_run_config,
    build_approval_node,
    compile_approval_graph,
)


def _initial() -> dict[str, str]:
    return {
        "run_id": "run-1",
        "owner_id": "owner-1",
        "tool_id": "exec_command",
        "tool_call_id": "call-1",
        "operation_id": "op-1",
        "operation_key": "key-1",
    }


def test_approval_graph_interrupts_then_resumes_approved() -> None:
    approvals = ApprovalService()
    graph = compile_approval_graph(build_approval_node(approvals), MemorySaver())
    config = approval_run_config("run-1")

    result = asyncio.run(graph.ainvoke(_initial(), config))
    interrupt_payload = result["__interrupt__"][0].value
    approval_id = interrupt_payload["approval_id"]
    assert approval_id is not None

    approvals.decide(approval_id, "owner-1", True)
    result = asyncio.run(graph.ainvoke(Command(resume="approved"), config))
    assert result["status"] == "approved"

    # 同一 checkpoint 再次 resume 不创建第二条审批，也不改变权威状态。
    replayed = asyncio.run(graph.ainvoke(Command(resume="approved"), config))
    assert replayed["approval_id"] == approval_id
    assert approvals.get(approval_id).status == "approved"


def test_approval_graph_rejection_returns_structured_failure() -> None:
    approvals = ApprovalService()
    graph = compile_approval_graph(build_approval_node(approvals), MemorySaver())
    config = approval_run_config("run-reject")

    result = asyncio.run(graph.ainvoke(_initial(), config))
    approval_id = result["__interrupt__"][0].value["approval_id"]
    approvals.decide(approval_id, "owner-1", False, rejected_reason="用户拒绝")
    result = asyncio.run(graph.ainvoke(Command(resume="rejected"), config))
    assert result["status"] == "rejected"
    assert result["reason"] == "用户拒绝"


def test_approval_graph_expiry_is_authoritative() -> None:
    approvals = ApprovalService(ttl=timedelta(seconds=60))
    graph = compile_approval_graph(build_approval_node(approvals), MemorySaver())
    config = approval_run_config("run-expire")

    result = asyncio.run(graph.ainvoke(_initial(), config))
    approval_id = result["__interrupt__"][0].value["approval_id"]
    future = datetime.now(timezone.utc) + timedelta(minutes=2)
    with pytest.raises(ApprovalExpired):
        approvals.decide(approval_id, "owner-1", True, now=future)
    result = asyncio.run(graph.ainvoke(Command(resume="approved"), config))
    assert result["status"] == "expired"
