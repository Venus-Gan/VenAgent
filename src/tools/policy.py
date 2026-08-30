"""本地 safe/warn/block 与 allow/deny 暴露策略。"""

from __future__ import annotations

from dataclasses import dataclass

from .models import RiskLevel


@dataclass(frozen=True)
class ToolExposurePolicy:
    policy_version: str
    allowed_tool_ids: tuple[str, ...] = ()
    denied_tool_ids: tuple[str, ...] = ()
    default_expose: bool = False
    risk_overrides: tuple[tuple[str, RiskLevel], ...] = ()

    def exposure_for(self, tool_id: str, source: str = "native") -> bool:
        if tool_id in self.denied_tool_ids:
            return False
        if tool_id in self.allowed_tool_ids:
            return True
        # MCP 已由 Server allow/deny 收窄，默认策略不能把明确 allow 再次清空。
        return source == "mcp" or self.default_expose

    def risk_for(self, tool_id: str, default: RiskLevel) -> RiskLevel:
        for candidate, risk in self.risk_overrides:
            if candidate == tool_id:
                return risk
        return default


@dataclass(frozen=True)
class DefaultToolPolicy:
    """无配置时的保守默认：只暴露显式 allow 项。

    M07：rag_search / 文档三件套按定稿以 safe 级入目录（per-owner 边界
    由 Gateway run_authorizer 与服务层 owner 过滤保证），故加入 allow 列表。
    """

    policy_version: str = "m07-default-v1"
    allowed_tool_ids: tuple[str, ...] = (
        "exec_command",
        "rag_search",
        "write_document",
        "list_documents",
        "read_document",
    )
    denied_tool_ids: tuple[str, ...] = ()
    default_expose: bool = False
    risk_overrides: tuple[tuple[str, RiskLevel], ...] = ()

    def as_exposure_policy(self) -> ToolExposurePolicy:
        return ToolExposurePolicy(
            policy_version=self.policy_version,
            allowed_tool_ids=self.allowed_tool_ids,
            denied_tool_ids=self.denied_tool_ids,
            default_expose=self.default_expose,
            risk_overrides=self.risk_overrides,
        )
