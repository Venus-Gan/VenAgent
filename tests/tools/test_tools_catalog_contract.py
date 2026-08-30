"""M06 tools catalog 契约（单点）。

- catalog 允许/拒绝/可用性快照（含 lazy sandbox 状态）：本文件单点。
- 新 run 绑定新快照、已绑定 run 不受 catalog refresh 影响：本文件单点。
- langchain schema 适配只暴露快照内工具：本文件单点。
"""

from __future__ import annotations

import asyncio

from src.tools.catalog import ToolCatalog
from src.tools.langchain import snapshot_to_langchain_tools
from src.tools.models import ToolDescriptor
from src.tools.policy import ToolExposurePolicy


def test_catalog_honors_allow_deny_and_availability(tools_harness) -> None:
    policy = ToolExposurePolicy(
        policy_version="test-v1",
        allowed_tool_ids=("exec_command", "tavily_search"),
        denied_tool_ids=("blocked_tool",),
    )
    catalog = ToolCatalog(policy)
    catalog.register(tools_harness.exec_command())
    catalog.register(tools_harness.mcp_search())
    catalog.register(
        ToolDescriptor(
            tool_id="blocked_tool",
            public_name="blocked_tool",
            source="native",
            description="blocked",
            input_schema={},
        )
    )

    without_sandbox = catalog.build_snapshot(
        sandbox_ready=False, available_servers=frozenset({"tavily"})
    )
    assert without_sandbox.by_id("exec_command").exposed is False
    assert (
        without_sandbox.by_id("exec_command").unavailable_reason
        == "sandbox_unavailable"
    )
    assert without_sandbox.by_id("tavily_search").exposed is True
    assert without_sandbox.by_id("blocked_tool").exposed is False

    without_mcp = catalog.build_snapshot(
        sandbox_ready=True, available_servers=frozenset()
    )
    assert without_mcp.by_id("tavily_search").exposed is False
    assert (
        without_mcp.by_id("tavily_search").unavailable_reason
        == "mcp_server_unavailable"
    )
    assert without_mcp.by_id("exec_command").exposed is True

    lazy = catalog.build_snapshot(
        sandbox_ready=False,
        sandbox_reason="sandbox_not_initialized",
    )
    assert lazy.sandbox_state == "lazy"
    assert lazy.by_id("exec_command").exposed is True


def test_catalog_refresh_affects_new_runs_but_not_bound_run_snapshot(
    tools_harness,
) -> None:
    control = tools_harness.tool_control(sandbox_ready=True)

    async def scenario() -> None:
        bound = await control.start_run("run-bound")
        control.catalog.register(
            ToolDescriptor(
                tool_id="new_tool",
                public_name="new_tool",
                source="mcp",
                description="new",
                input_schema={"type": "object", "properties": {}},
                server_id="tavily",
            )
        )
        control.mark_catalog_refreshed()

        current = control.snapshot()
        still_bound = control.snapshot(run_id="run-bound")

        assert current.catalog_revision > bound.catalog_revision
        assert current.by_id("new_tool") is not None
        assert still_bound.catalog_revision == bound.catalog_revision
        assert still_bound.by_id("new_tool") is None
        await control.stop_run("run-bound")

    asyncio.run(scenario())


def test_langchain_tool_schema_adapter_exposes_only_snapshot_tools(
    tools_harness,
) -> None:
    policy = ToolExposurePolicy(
        policy_version="test",
        allowed_tool_ids=("exec_command", "tavily_search"),
        denied_tool_ids=("blocked_tool",),
    )
    catalog = ToolCatalog(policy)
    catalog.register(tools_harness.exec_command())
    catalog.register(tools_harness.mcp_search())
    catalog.register(
        ToolDescriptor(
            tool_id="blocked_tool",
            public_name="blocked_tool",
            source="native",
            description="blocked",
            input_schema={},
        )
    )
    snapshot = catalog.build_snapshot(
        sandbox_ready=True, available_servers=frozenset({"tavily"})
    )
    tools = snapshot_to_langchain_tools(snapshot)
    names = [item["name"] for item in tools]
    assert names == ["exec_command", "tavily_search"]
    assert tools[0]["parameters"] == tools_harness.exec_command().input_schema