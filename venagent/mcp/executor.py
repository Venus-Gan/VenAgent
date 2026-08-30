"""MCP Tool 到统一 ToolResult 的真实执行适配。"""

from __future__ import annotations

import json
from typing import Any

from ..tools.errors import ToolUnavailable
from ..tools.models import ToolDescriptor, ToolResult
from .client import McpClientManager, McpConnectionError
from .config import McpConfigStore


class McpToolExecutor:
    def __init__(self, store: McpConfigStore, manager: McpClientManager) -> None:
        self._store = store
        self._manager = manager

    async def __call__(
        self,
        descriptor: ToolDescriptor,
        arguments: dict[str, Any],
        _run_id: str,
    ) -> ToolResult:
        servers = {item.server_id: item for item in self._store.load()}
        server = servers.get(descriptor.server_id or "")
        if server is None or not server.enabled:
            raise ToolUnavailable
        try:
            result = await self._manager.call_tool(
                server, descriptor.public_name, arguments
            )
        except McpConnectionError as exc:
            error = ToolUnavailable(str(exc))
            error.code = str(exc) or "mcp_unavailable"
            raise error from exc
        content = _content_text(result.get("content"))
        is_error = bool(result.get("isError", False))
        return ToolResult(
            tool_call_id="",
            operation_id="",
            status="error" if is_error else "success",
            summary=(content[:1024] or ("MCP 调用失败。" if is_error else "MCP 调用完成。")),
            content=content,
            error="mcp_tool_error" if is_error else None,
        )


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif item is not None:
                parts.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(parts)
    if content is None:
        return ""
    return json.dumps(content, ensure_ascii=False)
