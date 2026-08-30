"""M06 tools MCP 契约（单点）。

- MCP config 原子存取、绝不落盘 secret 值：本文件单点。
- MCP tool catalog 解决 server 冲突与 deny：本文件单点。
- /mcp 命令注册表分派与空 catalog 解释：本文件单点。
"""

from __future__ import annotations

from pathlib import Path

from venagent.command.mcp_adapter import McpCommandAdapter
from venagent.command.registry import CommandRegistry
from venagent.mcp.catalog import McpToolCatalog
from venagent.mcp.config import (
    McpConfigStore,
    McpServerConfig,
    McpToolManifest,
    McpToolPolicy,
)


def test_mcp_config_store_is_atomic_and_never_stores_secret_values(
    tmp_path: Path, tools_harness
) -> None:
    store = McpConfigStore(tmp_path / "servers.json")
    store.ensure_defaults()
    server = McpServerConfig(
        server_id="tavily",
        name="Tavily",
        transport="stdio",
        enabled=True,
        command="npx -y tavily-mcp",
        credential_ref="TAVILY_API_KEY",
        tools=McpToolPolicy(allow=("tavily_search",)),
        declared_tools=(
            McpToolManifest(
                name="tavily_search",
                description="Search the web",
                input_schema={"type": "object", "properties": {}},
            ),
        ),
    )
    store.upsert(server)
    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].credential_ref == "TAVILY_API_KEY"
    assert "secret-value" not in (tmp_path / "servers.json").read_text(
        encoding="utf-8"
    )
    store.remove("tavily")
    assert store.load() == ()


def test_mcp_tool_catalog_resolves_conflicts_and_deny() -> None:
    server_a = McpServerConfig(
        server_id="a",
        name="A",
        transport="stdio",
        enabled=True,
        command="cmd-a",
        tools=McpToolPolicy(allow=("search",)),
        declared_tools=(
            McpToolManifest(
                name="search",
                description="A search",
                input_schema={"type": "object", "properties": {}},
            ),
        ),
    )
    server_b = McpServerConfig(
        server_id="b",
        name="B",
        transport="stdio",
        enabled=True,
        command="cmd-b",
        tools=McpToolPolicy(allow=("search",), deny=("search",)),
        declared_tools=(
            McpToolManifest(
                name="search",
                description="B search",
                input_schema={"type": "object", "properties": {}},
            ),
        ),
    )
    catalog = McpToolCatalog((server_a, server_b))
    descriptors = (
        *catalog.tools_for(server_a, server_a.declared_tools),
        *catalog.tools_for(server_b, server_b.declared_tools),
    )
    ids = [item.tool_id for item in descriptors]
    assert "a:search" in ids
    assert "b:search" in ids
    assert next(item for item in descriptors if item.server_id == "b").exposed is False
    assert next(item for item in descriptors if item.server_id == "a").exposed is True


def test_command_registry_dispatches_mcp_control(
    tmp_path: Path, tools_harness
) -> None:
    store = McpConfigStore(tmp_path / "servers.json")
    store.ensure_defaults()
    server = McpServerConfig(
        server_id="tavily",
        name="Tavily",
        transport="stdio",
        enabled=True,
        command="npx -y tavily-mcp",
        tools=McpToolPolicy(allow=("tavily_search",)),
        declared_tools=(
            McpToolManifest(
                name="tavily_search",
                description="Search",
                input_schema={"type": "object", "properties": {}},
            ),
        ),
    )
    store.upsert(server)
    adapter = McpCommandAdapter(store, McpToolCatalog((server,)))
    registry = CommandRegistry(adapter)
    assert registry.matches("/mcp tools tavily")
    result = registry.execute(tools_harness.test_actor(), "/mcp tools tavily")
    assert result.code == "mcp_tools"
    assert "tavily_search" in result.message


def test_mcp_command_explains_empty_server_catalog(
    tmp_path: Path, tools_harness
) -> None:
    store = McpConfigStore(tmp_path / "servers.json")
    adapter = McpCommandAdapter(store, McpToolCatalog(()))

    result = adapter.execute(tools_harness.test_actor(), "/mcp")

    assert result.code == "mcp_empty"
    assert "当前没有配置 MCP Server" in result.message