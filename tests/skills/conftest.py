"""tests/skills 装配工厂：SkillHub HTTP app 与共享 tool_control 就近暴露。

收编本模块重复装配（原 test_m06_skill_hub.py 内联 _tool_control / create_app 样板）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from venagent.interfaces.http.app import create_app
from venagent.mcp.config import McpConfigStore
from venagent.platform.runtime import build_persistence_runtime
from venagent.sandbox.docker import DockerSandboxRuntime
from venagent.skills.catalog import SkillCatalog
from venagent.skills.hub import SkillHubService
from venagent.tools.approval import ApprovalService
from venagent.tools.catalog import ToolCatalog
from venagent.tools.control import ToolControlContext
from venagent.tools.gateway import ToolGateway
from venagent.tools.models import ToolDescriptor
from venagent.tools.operation_store import OperationStore
from venagent.tools.policy import ToolExposurePolicy


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
def skill_hub_app_factory():
    """构建 SkillHub HTTP app；config_path 由调用方持临时目录。"""

    def build_app(config_path: Path, github_client):
        store = McpConfigStore(config_path)
        store.ensure_defaults()
        return create_app(
            persistence_runtime=build_persistence_runtime({}),
            tool_control=_build_tool_control(),
            mcp_config_store=store,
            skill_hub=SkillHubService(github_client),
        )

    return build_app