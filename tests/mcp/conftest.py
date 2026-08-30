"""tests/mcp 装配工厂：tool_control、MCP HTTP app 与假 MCP server 就近暴露。

收编本模块重复装配（原 test_m06_mcp.py 内联 _tool_control / create_app 样板），
fake_mcp_server 以 fixture 对外暴露。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from venagent.interfaces.http.app import create_app
from venagent.mcp.client import McpClientManager
from venagent.mcp.config import McpConfigStore
from venagent.platform.runtime import build_persistence_runtime
from venagent.sandbox.docker import DockerSandboxRuntime
from venagent.skills.catalog import SkillCatalog
from venagent.tools.approval import ApprovalService
from venagent.tools.catalog import ToolCatalog
from venagent.tools.control import ToolControlContext
from venagent.tools.gateway import ToolGateway
from venagent.tools.models import ToolDescriptor
from venagent.tools.operation_store import OperationStore
from venagent.tools.policy import ToolExposurePolicy

FAKE_MCP_SERVER = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


@pytest.fixture
def fake_mcp_server() -> Path:
    """随被测模块就近的假 MCP stdio server 脚本（92 行 JSON-RPC 循环）。"""
    return FAKE_MCP_SERVER


def _build_tool_control() -> ToolControlContext:
    """最小工具控制上下文（只登记 exec_command，gateway/approval 全内存）。"""
    policy = ToolExposurePolicy(
        policy_version="test-v1",
        allowed_tool_ids=("exec_command",),
    )
    catalog = ToolCatalog(policy)
    catalog.register(
        ToolDescriptor(
            tool_id="exec_command",
            public_name="exec_command",
            source="native",
            description="exec",
            input_schema={"type": "object", "properties": {}},
            risk="warn",
        )
    )
    approvals = ApprovalService()
    operations = OperationStore()
    return ToolControlContext(
        catalog=catalog,
        sandbox=DockerSandboxRuntime(probe=lambda: False),
        skills=SkillCatalog(),
        gateway=ToolGateway(operations=operations, approvals=approvals),
        approvals=approvals,
        operations=operations,
    )


@pytest.fixture
def tool_control() -> ToolControlContext:
    return _build_tool_control()


@pytest.fixture
def mcp_app_factory():
    """构建 MCP 管理 HTTP app；config_path 由调用方持临时目录。"""

    def build_app(config_path: Path, *, client_factory=None):
        store = McpConfigStore(config_path)
        store.ensure_defaults()
        return create_app(
            persistence_runtime=build_persistence_runtime({}),
            tool_control=_build_tool_control(),
            mcp_config_store=store,
            mcp_manager=McpClientManager(client_factory=client_factory),
        )

    return build_app