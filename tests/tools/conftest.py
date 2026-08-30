"""tests/tools/ 共用装配（D5：模块 conftest 收编描述符与 control factory）。

仅暴露公开符号；目录测试各自按契约域独占断言（网关/审批/catalog 单点）。
"""

from __future__ import annotations

import types

import pytest

from venagent.ownership.models import Actor
from venagent.sandbox.models import SandboxCapability
from venagent.skills.catalog import SkillCatalog
from venagent.tools.approval import ApprovalService
from venagent.tools.catalog import ToolCatalog
from venagent.tools.control import ToolControlContext
from venagent.tools.gateway import ToolGateway
from venagent.tools.models import ToolDescriptor
from venagent.tools.operation_store import OperationStore
from venagent.tools.policy import ToolExposurePolicy


def _exec_command() -> ToolDescriptor:
    return ToolDescriptor(
        tool_id="exec_command",
        public_name="exec_command",
        source="native",
        description="在 Docker Sandbox 中执行受控命令",
        input_schema={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
        risk="warn",
    )


def _mcp_search() -> ToolDescriptor:
    return ToolDescriptor(
        tool_id="tavily_search",
        public_name="tavily_search",
        source="mcp",
        description="Tavily 搜索",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        server_id="tavily",
        risk="safe",
    )


def _test_actor() -> Actor:
    return Actor(owner_id="owner-1", kind="guest", session_id="session-1")


class _FakeReadySandbox:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready

    async def start_run(
        self, run_id: str, *, allow_create: bool = True, generation_id: str | None = None
    ) -> SandboxCapability:
        return self.capability(run_id)

    async def stop_run(self, run_id: str) -> None:
        return None

    def capability(self, run_id: str | None = None) -> SandboxCapability:
        return SandboxCapability(
            provider="docker",
            ready=self.ready,
            reason_code=None if self.ready else "docker_unavailable",
        )


def _make_tool_control(sandbox_ready: bool = False) -> ToolControlContext:
    policy = ToolExposurePolicy(
        policy_version="test-v1",
        allowed_tool_ids=("exec_command", "tavily_search"),
    )
    catalog = ToolCatalog(policy)
    catalog.register(_exec_command())
    catalog.register(_mcp_search())
    sandbox = _FakeReadySandbox(sandbox_ready)
    approvals = ApprovalService()
    operations = OperationStore()
    gateway = ToolGateway(operations=operations, approvals=approvals)
    return ToolControlContext(
        catalog=catalog,
        sandbox=sandbox,  # type: ignore[arg-type]
        skills=SkillCatalog(),
        gateway=gateway,
        approvals=approvals,
        operations=operations,
    )


@pytest.fixture
def tools_harness() -> types.SimpleNamespace:
    """tools 契约测试共用装配入口。"""
    return types.SimpleNamespace(
        exec_command=_exec_command,
        mcp_search=_mcp_search,
        test_actor=_test_actor,
        FakeReadySandbox=_FakeReadySandbox,
        tool_control=_make_tool_control,
    )