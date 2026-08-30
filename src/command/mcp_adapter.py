"""`/mcp` 控制面：逐级浏览 Server 与工具暴露状态。"""

from __future__ import annotations

from collections.abc import Callable

from ..mcp.catalog import McpToolCatalog
from ..mcp.config import McpConfigStore
from ..ownership.models import Actor
from .registry import CommandOption, CommandResult


class McpCommandAdapter:
    def __init__(
        self,
        config_store: McpConfigStore,
        catalog: McpToolCatalog,
        ready_servers: Callable[[], frozenset[str]] | None = None,
    ) -> None:
        self._store = config_store
        self._catalog = catalog
        self._ready_servers = ready_servers

    @staticmethod
    def matches(content: str) -> bool:
        return content.strip() == "/mcp" or content.lstrip().startswith("/mcp ")

    def execute(self, actor: Actor, content: str) -> CommandResult:
        parts = content.strip().split()
        servers = {item.server_id: item for item in self._store.load()}
        if len(parts) == 1:
            if not servers:
                return CommandResult(
                    "mcp_command",
                    "mcp_empty",
                    "当前没有配置 MCP Server。请先在控制面新增 Server，再使用 /mcp show <server> 或 /mcp tools <server>。",
                )
            return CommandResult(
                "mcp_command",
                "mcp_help",
                "可用命令：/mcp show <server>|tools <server>",
            )
        catalog = McpToolCatalog(tuple(servers.values()))
        operation = parts[1]
        if operation == "show" and len(parts) == 3:
            server = servers.get(parts[2])
            if server is None:
                return CommandResult(
                    "mcp_command", "mcp_server_not_found", "未找到该 MCP Server。"
                )
            descriptors = catalog.tools_for(server, server.declared_tools)
            exposed = sum(item.exposed for item in descriptors)
            ready = (
                server.server_id in self._ready_servers()
                if self._ready_servers is not None
                else bool(server.declared_tools)
            )
            endpoint = server.command or server.url or "未配置"
            return CommandResult(
                "mcp_command",
                "mcp_show",
                f"名称：{server.name}\n类型：{server.transport}\n启动方式：{endpoint}\n"
                f"状态：{'ready' if ready else ('disabled' if not server.enabled else 'not_ready')}\n"
                f"启用：{'是' if server.enabled else '否'}\n"
                f"认证状态：{'已配置' if server.credential_ref else '未配置'}\n"
                f"能力：tools\n工具数量：{len(descriptors)}\n暴露工具数量：{exposed}\n最近错误：无",
            )
        if operation == "tools" and len(parts) == 3:
            server = servers.get(parts[2])
            if server is None:
                return CommandResult(
                    "mcp_command", "mcp_server_not_found", "未找到该 MCP Server。"
                )
            descriptors = catalog.tools_for(server, server.declared_tools)
            lines = [
                f"{item.public_name}\n  描述：{item.description}\n"
                f"  状态：{'exposed' if item.exposed else 'blocked'}\n"
                f"  原因：{'命中 allow' if item.exposed else _reason_text(item.unavailable_reason)}"
                for item in descriptors
            ]
            return CommandResult(
                "mcp_command",
                "mcp_tools",
                "\n".join(lines) if lines else "该 Server 没有可用工具。",
            )
        return CommandResult(
            "mcp_command", "mcp_invalid_command", "命令格式无效，请使用 /mcp help。"
        )

    def options(self) -> tuple[CommandOption, ...]:
        options = [CommandOption("/mcp", "查看 Server 提供的 MCP 及暴露状态")]
        for server in self._store.load():
            options.extend(
                (
                    CommandOption(
                        f"/mcp show {server.server_id}",
                        f"查看 {server.name} 的 Server 状态与配置",
                        "/mcp",
                    ),
                    CommandOption(
                        f"/mcp tools {server.server_id}",
                        f"查看 {server.name} 提供的工具与暴露状态",
                        "/mcp",
                    ),
                )
            )
        return tuple(options)


def _reason_text(reason: str | None) -> str:
    return {
        "mcp_tool_denied": "命中 deny",
        "mcp_tool_not_in_allow": "未加入 allow",
        "mcp_schema_unsupported": "输入 Schema 不受支持",
        "mcp_server_unavailable": "Server 未 ready",
    }.get(reason or "", reason or "未暴露")
