"""统一 Native/MCP Tool Catalog 与不可变快照。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from uuid import uuid4

from .models import ToolCatalogSnapshot, ToolDescriptor
from .policy import ToolExposurePolicy


class ToolCatalog:
    def __init__(self, policy: ToolExposurePolicy) -> None:
        self._policy = policy
        self._tools: dict[str, ToolDescriptor] = {}

    def register(self, descriptor: ToolDescriptor) -> None:
        self._tools[descriptor.tool_id] = descriptor

    def register_many(self, descriptors: Iterable[ToolDescriptor]) -> None:
        for descriptor in descriptors:
            self.register(descriptor)

    def tool(self, tool_id: str) -> ToolDescriptor | None:
        return self._tools.get(tool_id)

    def remove_by_source(self, source: str) -> None:
        """删除某来源全部描述符，供 MCP 配置变更后重建目录。"""
        self._tools = {
            tool_id: descriptor
            for tool_id, descriptor in self._tools.items()
            if descriptor.source != source
        }

    def build_snapshot(
        self,
        *,
        sandbox_ready: bool,
        catalog_revision: int = 1,
        sandbox_reason: str | None = None,
        available_servers: frozenset[str] = frozenset(),
        run_id: str | None = None,
        now: datetime | None = None,
    ) -> ToolCatalogSnapshot:
        now = now or datetime.now(timezone.utc)
        tools: list[ToolDescriptor] = []
        for descriptor in self._tools.values():
            exposed = descriptor.exposed and self._policy.exposure_for(
                descriptor.tool_id, descriptor.source
            )
            reason: str | None = descriptor.unavailable_reason
            if descriptor.source == "mcp" and descriptor.server_id not in available_servers:
                exposed = False
                reason = "mcp_server_unavailable"
            elif (
                descriptor.source == "native"
                and descriptor.tool_id == "exec_command"
                and not sandbox_ready
                and sandbox_reason != "sandbox_not_initialized"
            ):
                exposed = False
                reason = sandbox_reason or "sandbox_unavailable"
            tools.append(
                ToolDescriptor(
                    tool_id=descriptor.tool_id,
                    public_name=descriptor.public_name,
                    source=descriptor.source,
                    description=descriptor.description,
                    input_schema=descriptor.input_schema,
                    server_id=descriptor.server_id,
                    risk=self._policy.risk_for(descriptor.tool_id, descriptor.risk),
                    version=descriptor.version,
                    exposed=exposed,
                    unavailable_reason=reason,
                    metadata=descriptor.metadata,
                )
            )
        return ToolCatalogSnapshot(
            snapshot_id=str(uuid4()),
            created_at=now.isoformat(),
            policy_version=self._policy.policy_version,
            catalog_revision=catalog_revision,
            sandbox_state=(
                "ready"
                if sandbox_ready
                else "lazy"
                if sandbox_reason == "sandbox_not_initialized"
                else "unavailable"
            ),
            tools=tuple(tools),
            run_id=run_id,
        )
