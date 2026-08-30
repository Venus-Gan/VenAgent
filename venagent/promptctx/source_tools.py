"""当前模型调用可发现的工具状态投影，不携带完整 Schema。"""

from __future__ import annotations

from ..tools.models import ToolCatalogSnapshot
from .context import ContextBlock, conservative_token_count


def tool_capability_block(snapshot: ToolCatalogSnapshot) -> ContextBlock:
    exposed = snapshot.exposed_tools()
    if not exposed:
        content = "当前没有可调用的工具。"
    else:
        lines = [
            f"- {item.public_name}（来源：{item.source}，风险：{item.risk}）{item.description}"
            for item in exposed
        ]
        content = "当前模型调用可发现以下工具，执行仍由 Tool Gateway 权威复核：\n" + "\n".join(
            lines
        )
    return ContextBlock(
        block_id="tool-status",
        category="tool_status",
        source="m06-tools",
        content=content,
        priority=90,
        mandatory=False,
        token_count=conservative_token_count(content),
        source_ref=f"snapshot:{snapshot.snapshot_id}",
    )


def tool_operation_summary_block(
    *,
    pending_approvals: int,
    recent_operations: tuple[str, ...],
) -> ContextBlock:
    lines = [f"待审批：{pending_approvals}"]
    if recent_operations:
        lines.append("近期操作：" + "、".join(recent_operations[:5]))
    content = "工具控制状态：" + "；".join(lines)
    return ContextBlock(
        block_id="tool-operations",
        category="tool_status",
        source="m06-tools",
        content=content,
        priority=80,
        mandatory=False,
        token_count=conservative_token_count(content),
    )
