"""MCP 原生工具到统一 ToolDescriptor 的投影。"""

from __future__ import annotations

from collections import Counter

from ..tools.catalog import ToolCatalog
from ..tools.models import ToolDescriptor
from ..tools.schema import schema_supported
from .config import McpServerConfig, McpToolManifest


class McpToolCatalog:
    """按 Server 的 allow/deny 暴露原生工具，冲突名才加稳定前缀。"""

    def __init__(self, servers: tuple[McpServerConfig, ...] = ()) -> None:
        self._servers = {item.server_id: item for item in servers}
        self._conflicts = {
            name
            for name, count in Counter(
                tool.name
                for server in servers
                if server.enabled
                for tool in server.declared_tools
            ).items()
            if count > 1
        }

    def refresh(self, servers: tuple[McpServerConfig, ...]) -> None:
        self._servers = {item.server_id: item for item in servers}
        self._conflicts = {
            name
            for name, count in Counter(
                tool.name
                for server in servers
                if server.enabled
                for tool in server.declared_tools
            ).items()
            if count > 1
        }

    def available_servers(self) -> frozenset[str]:
        return frozenset(
            server_id
            for server_id, server in self._servers.items()
            if server.enabled
        )

    def tools_for(
        self, server: McpServerConfig, manifests: tuple[McpToolManifest, ...]
    ) -> tuple[ToolDescriptor, ...]:
        """把 MCP 工具投影为统一描述符；deny 优先，未 allow 默认不暴露。"""
        descriptors: list[ToolDescriptor] = []
        for manifest in manifests:
            valid_schema = schema_supported(manifest.input_schema)
            tool_id = manifest.name
            if manifest.name in self._conflicts:
                tool_id = f"{server.server_id}:{manifest.name}"
            # destructive 只是输入信号：可执行时本地策略要求 warn 审批，不直接 block。
            risk = (
                "warn"
                if manifest.destructive_hint and server.tools.exposed(manifest.name)
                else "safe"
            )
            descriptors.append(
                ToolDescriptor(
                    tool_id=tool_id,
                    public_name=manifest.name,
                    source="mcp",
                    description=manifest.description,
                    input_schema=manifest.input_schema,
                    server_id=server.server_id,
                    risk=risk,
                    exposed=server.tools.exposed(manifest.name) and valid_schema,
                    unavailable_reason=(
                        None
                        if server.tools.exposed(manifest.name) and valid_schema
                    else (
                        "mcp_schema_unsupported"
                        if not valid_schema
                        else (
                            "mcp_tool_denied"
                            if manifest.name in server.tools.deny
                            else "mcp_tool_not_in_allow"
                        )
                    )
                    ),
                )
            )
        return tuple(descriptors)

    def register_all(self, tool_catalog: ToolCatalog) -> None:
        """把启用 Server 的原生工具注册进统一 Catalog。"""
        for server in self._servers.values():
            if server.enabled:
                tool_catalog.register_many(
                    self.tools_for(server, server.declared_tools)
                )
