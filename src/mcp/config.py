"""MCP Server 全局配置：原子读写、凭据引用与工具 allow/deny。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

McpTransport = Literal["stdio", "streamable_http"]


@dataclass(frozen=True)
class McpToolManifest:
    """客户端发现到的原生工具；仅作为输入信号，本地策略是权威。"""

    name: str
    description: str
    input_schema: dict[str, Any]
    read_only_hint: bool = False
    destructive_hint: bool = False


@dataclass(frozen=True)
class McpToolPolicy:
    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()

    def exposed(self, tool_name: str) -> bool:
        if tool_name in self.deny:
            return False
        if self.allow:
            return tool_name in self.allow
        return False


@dataclass(frozen=True)
class McpServerConfig:
    server_id: str
    name: str
    transport: McpTransport
    enabled: bool
    tools: McpToolPolicy = McpToolPolicy()
    command: str | None = None
    args: tuple[str, ...] = ()
    url: str | None = None
    credential_ref: str | None = None
    env_refs: tuple[str, ...] = ()
    declared_tools: tuple[McpToolManifest, ...] = ()


class McpConfigStore:
    """以 JSON 原子更新 `mcp-servers.json`，失败保留最后一份有效配置。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def ensure_defaults(self) -> None:
        if not self._path.is_file():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self.save(())

    def load(self) -> tuple[McpServerConfig, ...]:
        if not self._path.is_file():
            return ()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("mcp config is invalid") from exc
        if not isinstance(raw, list):
            raise ValueError("mcp config must be a list")
        return tuple(_parse_server(item) for item in raw)

    def save(self, servers: tuple[McpServerConfig, ...]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [asdict(item) for item in servers],
            ensure_ascii=False,
            indent=2,
        )
        # 先写同目录临时文件再替换，保证并发读或失败不会看到半写配置。
        fd, temp_name = tempfile.mkstemp(
            prefix="mcp-servers-", suffix=".json", dir=self._path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self._path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def upsert(self, server: McpServerConfig) -> tuple[McpServerConfig, ...]:
        current = {item.server_id: item for item in self.load()}
        current[server.server_id] = server
        ordered = tuple(
            current[item.server_id] for item in self.load() if item.server_id in current
        )
        if server.server_id not in {item.server_id for item in ordered}:
            ordered = (*ordered, server)
        self.save(ordered)
        return ordered

    def remove(self, server_id: str) -> tuple[McpServerConfig, ...]:
        remaining = tuple(item for item in self.load() if item.server_id != server_id)
        self.save(remaining)
        return remaining


def _parse_server(raw: Any) -> McpServerConfig:
    if not isinstance(raw, dict):
        raise ValueError("mcp server entry must be an object")
    tools_raw = raw.get("tools", {})
    tools = McpToolPolicy(
        allow=tuple(tools_raw.get("allow", ())),
        deny=tuple(tools_raw.get("deny", ())),
    )
    declared = tuple(
        McpToolManifest(
            name=item["name"],
            description=item.get("description", ""),
            input_schema=item.get("input_schema", {}),
            read_only_hint=bool(item.get("read_only_hint", False)),
            destructive_hint=bool(item.get("destructive_hint", False)),
        )
        for item in raw.get("declared_tools", ())
    )
    return McpServerConfig(
        server_id=raw["server_id"],
        name=raw.get("name", raw["server_id"]),
        transport=raw.get("transport", "stdio"),
        enabled=bool(raw.get("enabled", False)),
        tools=tools,
        command=raw.get("command"),
        args=tuple(raw.get("args", ())),
        url=raw.get("url"),
        credential_ref=raw.get("credential_ref"),
        env_refs=tuple(raw.get("env_refs", ())),
        declared_tools=declared,
    )
