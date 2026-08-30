"""Tool 目录、快照、Operation 与 ToolResult 值对象。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

RiskLevel = Literal["safe", "warn", "block"]
ToolSource = Literal["native", "mcp"]
OperationStatus = Literal[
    "queued",
    "running",
    "awaiting_approval",
    "succeeded",
    "failed",
    "cancelled",
]
ToolResultStatus = Literal[
    "success", "error", "blocked", "cancelled", "awaiting_approval"
]


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    source: str
    size_bytes: int
    content_type: str = "application/octet-stream"
    checksum_sha256: str | None = None


@dataclass(frozen=True)
class ModelToolCall:
    """模型返回的单个 tool call，参数已经过类型归一化。"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class StagedToolCall:
    """已保存到私有调用载荷存储的定位信息。"""

    tool_call_id: str
    operation_key: str
    tool_id: str


@dataclass(frozen=True)
class ToolDescriptor:
    tool_id: str
    public_name: str
    source: ToolSource
    description: str
    input_schema: dict[str, Any]
    server_id: str | None = None
    risk: RiskLevel = "safe"
    version: str = "1"
    exposed: bool = True
    unavailable_reason: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ToolCatalogSnapshot:
    snapshot_id: str
    created_at: str
    policy_version: str
    catalog_revision: int
    sandbox_state: str
    tools: tuple[ToolDescriptor, ...]
    run_id: str | None = None

    def exposed_tools(self) -> tuple[ToolDescriptor, ...]:
        return tuple(tool for tool in self.tools if tool.exposed)

    def by_id(self, tool_id: str) -> ToolDescriptor | None:
        return next((item for item in self.tools if item.tool_id == tool_id), None)


@dataclass
class Operation:
    operation_id: str
    run_id: str
    owner_id: str
    tool_call_id: str
    operation_key: str
    tool_id: str
    status: OperationStatus
    risk: RiskLevel
    created_at: datetime
    updated_at: datetime
    approval_id: str | None = None
    error_code: str | None = None
    result_summary: str | None = None
    source: ToolSource = "native"
    server_id: str | None = None
    arguments_summary: str = "{}"
    risk_reason: str | None = None
    timing_ms: int = 0
    artifacts: tuple[ArtifactRef, ...] = ()
    sandbox_generation_id: str | None = None
    sandbox_state: str = "not_requested"


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    operation_id: str
    status: ToolResultStatus
    summary: str
    content: str
    artifacts: tuple[ArtifactRef, ...] = ()
    error: str | None = None
    timing_ms: int = 0
    approval_id: str | None = None


@dataclass(frozen=True)
class ApprovalItem:
    approval_id: str
    run_id: str
    owner_id: str
    operation_id: str
    tool_id: str
    tool_call_id: str
    risk: RiskLevel
    reason: str
    created_at: datetime
    expires_at: datetime
    status: Literal["pending", "approved", "rejected", "expired", "cancelled"] = "pending"
    decided_at: datetime | None = None
    rejected_reason: str | None = None
