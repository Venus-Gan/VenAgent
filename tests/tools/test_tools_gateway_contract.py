"""M06 tools gateway 契约（单点）。

- lazy sandbox 描述符可达执行器：本文件单点。
- 幂等（同 key 二次调用不重执行）与 schema 校验失败：本文件单点。
- warn 审批「先等待、批准后恢复执行、重复调用仍不重执行」：本文件单点。
- 拒绝永不执行：本文件单点。
- run 授权被 authorizer 拒绝 → RunGrantInvalid 且不执行：本文件单点。
- 工具事件（started/completed）推送 SSE sink：本文件单点。

「拒绝后模型解释」「审批过期」由 tests/agent/test_m06_langgraph.py 覆盖；
agent 机制侧单点见 tests/agent/test_agent_tool_loop.py。
"""

from __future__ import annotations

import asyncio

import pytest

from venagent.tools.approval import ApprovalService
from venagent.tools.catalog import ToolCatalog
from venagent.tools.errors import RunGrantInvalid, ToolSchemaInvalid
from venagent.tools.gateway import ToolGateway
from venagent.tools.models import ToolResult
from venagent.tools.operation_store import OperationStore
from venagent.tools.policy import ToolExposurePolicy


def test_gateway_allows_lazy_sandbox_descriptor_to_reach_executor(
    tools_harness,
) -> None:
    calls: list[str] = []

    async def executor(
        _descriptor, _arguments
    ) -> ToolResult:
        calls.append("called")
        return ToolResult(
            tool_call_id="",
            operation_id="",
            status="success",
            summary="ok",
            content="ok",
        )

    async def scenario() -> None:
        policy = ToolExposurePolicy(
            policy_version="test-v1",
            allowed_tool_ids=("exec_command",),
            risk_overrides=(("exec_command", "safe"),),
        )
        catalog = ToolCatalog(policy)
        catalog.register(tools_harness.exec_command())
        snapshot = catalog.build_snapshot(
            sandbox_ready=False,
            sandbox_reason="sandbox_not_initialized",
        )
        gateway = ToolGateway(
            operations=OperationStore(),
            approvals=ApprovalService(),
            executor=executor,
        )
        result = await gateway.invoke(
            snapshot=snapshot,
            run_id="run-lazy-gateway",
            owner_id="owner-1",
            tool_call_id="call-lazy",
            operation_key="op-lazy",
            tool_id="exec_command",
            arguments={"command": "echo hi"},
            sandbox_ready=False,
        )
        assert result.status == "success"

    asyncio.run(scenario())
    assert calls == ["called"]


def test_gateway_is_idempotent_and_rejects_invalid_schema(tools_harness) -> None:
    calls: list[dict[str, object]] = []

    async def executor(_descriptor, arguments) -> ToolResult:
        calls.append(arguments)
        return ToolResult(
            tool_call_id="",
            operation_id="",
            status="success",
            summary="done",
            content="ok",
        )

    async def scenario() -> None:
        policy = ToolExposurePolicy(
            policy_version="test-v1",
            allowed_tool_ids=("exec_command",),
            risk_overrides=(("exec_command", "safe"),),
        )
        catalog = ToolCatalog(policy)
        catalog.register(tools_harness.exec_command())
        snapshot = catalog.build_snapshot(sandbox_ready=True)
        approvals = ApprovalService()
        operations = OperationStore()
        gateway = ToolGateway(
            operations=operations, approvals=approvals, executor=executor
        )
        first = await gateway.invoke(
            snapshot=snapshot,
            run_id="run-1",
            owner_id="owner-1",
            tool_call_id="call-1",
            operation_key="op-1",
            tool_id="exec_command",
            arguments={"command": "echo hi"},
            sandbox_ready=True,
        )
        second = await gateway.invoke(
            snapshot=snapshot,
            run_id="run-1",
            owner_id="owner-1",
            tool_call_id="call-1",
            operation_key="op-1",
            tool_id="exec_command",
            arguments={"command": "echo hi"},
            sandbox_ready=True,
        )
        assert first.status == "success"
        assert second.status == "success"
        assert second.content == first.content
        assert len(calls) == 1

        with pytest.raises(ToolSchemaInvalid):
            await gateway.invoke(
                snapshot=snapshot,
                run_id="run-2",
                owner_id="owner-1",
                tool_call_id="call-2",
                operation_key="op-2",
                tool_id="exec_command",
                arguments={},
                sandbox_ready=True,
            )

    asyncio.run(scenario())


def test_gateway_warn_approval_then_resume_is_authoritative(tools_harness) -> None:
    calls: list[str] = []

    async def executor(_descriptor, arguments) -> ToolResult:
        calls.append(str(arguments["command"]))
        return ToolResult(
            tool_call_id="",
            operation_id="",
            status="success",
            summary="ok",
            content="ok",
        )

    async def scenario() -> None:
        policy = ToolExposurePolicy(
            policy_version="test-v1",
            allowed_tool_ids=("exec_command",),
            risk_overrides=(("exec_command", "warn"),),
        )
        catalog = ToolCatalog(policy)
        catalog.register(tools_harness.exec_command())
        snapshot = catalog.build_snapshot(sandbox_ready=True)
        approvals = ApprovalService()
        operations = OperationStore()
        gateway = ToolGateway(
            operations=operations, approvals=approvals, executor=executor
        )
        waiting = await gateway.invoke(
            snapshot=snapshot,
            run_id="run-warn",
            owner_id="owner-1",
            tool_call_id="call-warn",
            operation_key="op-warn",
            tool_id="exec_command",
            arguments={"command": "danger"},
            sandbox_ready=True,
        )
        assert waiting.status == "awaiting_approval"
        assert waiting.approval_id is not None
        assert calls == []

        approval = approvals.decide(waiting.approval_id, "owner-1", True)
        resumed = await gateway.invoke(
            snapshot=snapshot,
            run_id="run-warn",
            owner_id="owner-1",
            tool_call_id="call-warn",
            operation_key="op-warn",
            tool_id="exec_command",
            arguments={"command": "danger"},
            sandbox_ready=True,
            approval_id=approval.approval_id,
        )
        assert resumed.status == "success"
        assert calls == ["danger"]
        duplicate = await gateway.invoke(
            snapshot=snapshot,
            run_id="run-warn",
            owner_id="owner-1",
            tool_call_id="call-warn",
            operation_key="op-warn",
            tool_id="exec_command",
            arguments={"command": "danger"},
            sandbox_ready=True,
        )
        assert duplicate.status == "success"
        assert calls == ["danger"]

    asyncio.run(scenario())


def test_gateway_rejection_never_executes(tools_harness) -> None:
    calls: list[str] = []

    async def executor(_descriptor, arguments) -> ToolResult:
        calls.append(str(arguments["command"]))
        raise AssertionError("must not execute")

    async def scenario() -> None:
        policy = ToolExposurePolicy(
            policy_version="test-v1",
            allowed_tool_ids=("exec_command",),
            risk_overrides=(("exec_command", "warn"),),
        )
        catalog = ToolCatalog(policy)
        catalog.register(tools_harness.exec_command())
        snapshot = catalog.build_snapshot(sandbox_ready=True)
        approvals = ApprovalService()
        operations = OperationStore()
        gateway = ToolGateway(
            operations=operations, approvals=approvals, executor=executor
        )
        waiting = await gateway.invoke(
            snapshot=snapshot,
            run_id="run-reject",
            owner_id="owner-1",
            tool_call_id="call-reject",
            operation_key="op-reject",
            tool_id="exec_command",
            arguments={"command": "danger"},
            sandbox_ready=True,
        )
        approvals.decide(
            waiting.approval_id, "owner-1", False, rejected_reason="用户拒绝"
        )
        rejected = await gateway.invoke(
            snapshot=snapshot,
            run_id="run-reject",
            owner_id="owner-1",
            tool_call_id="call-reject",
            operation_key="op-reject",
            tool_id="exec_command",
            arguments={"command": "danger"},
            sandbox_ready=True,
        )
        assert rejected.status == "blocked"

    asyncio.run(scenario())
    assert calls == []


def test_gateway_emits_tool_events_to_sse_sink(tools_harness) -> None:
    events: list[tuple[str, str]] = []

    async def sink(_run_id: str, kind: str, payload: dict[str, object]) -> None:
        events.append((kind, str(payload["tool_id"])))

    async def executor(_descriptor, arguments) -> ToolResult:
        return ToolResult(
            tool_call_id="",
            operation_id="",
            status="success",
            summary="ok",
            content="ok",
        )

    async def scenario() -> None:
        policy = ToolExposurePolicy(
            policy_version="test",
            allowed_tool_ids=("exec_command",),
            risk_overrides=(("exec_command", "safe"),),
        )
        catalog = ToolCatalog(policy)
        catalog.register(tools_harness.exec_command())
        snapshot = catalog.build_snapshot(sandbox_ready=True)
        gateway = ToolGateway(
            operations=OperationStore(),
            approvals=ApprovalService(),
            executor=executor,
        )
        gateway.set_event_sink(sink)
        await gateway.invoke(
            snapshot=snapshot,
            run_id="run-events",
            owner_id="owner-1",
            tool_call_id="call-events",
            operation_key="key-events",
            tool_id="exec_command",
            arguments={"command": "echo hi"},
            sandbox_ready=True,
        )

    asyncio.run(scenario())
    assert events == [
        ("started", "exec_command"),
        ("completed", "exec_command"),
    ]


def test_gateway_raises_run_grant_invalid_when_authorizer_rejects(
    tools_harness,
) -> None:
    calls: list[str] = []

    async def executor(_descriptor, _arguments) -> ToolResult:
        calls.append("called")
        return ToolResult(
            tool_call_id="",
            operation_id="",
            status="success",
            summary="ok",
            content="ok",
        )

    async def scenario() -> None:
        policy = ToolExposurePolicy(
            policy_version="test",
            allowed_tool_ids=("exec_command",),
            risk_overrides=(("exec_command", "safe"),),
        )
        catalog = ToolCatalog(policy)
        catalog.register(tools_harness.exec_command())
        snapshot = catalog.build_snapshot(sandbox_ready=True)
        gateway = ToolGateway(
            operations=OperationStore(),
            approvals=ApprovalService(),
            executor=executor,
            run_authorizer=lambda run_id, owner_id: False,
        )
        with pytest.raises(RunGrantInvalid):
            await gateway.invoke(
                snapshot=snapshot,
                run_id="run-authz",
                owner_id="owner-1",
                tool_call_id="call-authz",
                operation_key="key-authz",
                tool_id="exec_command",
                arguments={"command": "echo hi"},
                sandbox_ready=True,
            )

    asyncio.run(scenario())
    assert calls == []