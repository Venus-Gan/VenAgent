"""Sandbox 硬约束的 System Prompt 投影。"""

from __future__ import annotations

from ..sandbox.models import SandboxCapability
from .context import ContextBlock, conservative_token_count


def sandbox_constraints_block(capability: SandboxCapability) -> ContextBlock:
    limits = "；".join(f"{key}={value}" for key, value in capability.resource_limits)
    if capability.ready:
        state = "就绪"
        lifecycle = ""
    elif capability.reason_code == "sandbox_not_initialized":
        state = "可按需创建"
        lifecycle = "调用 exec_command 并通过审批后，系统会为当前 Run 创建专属 Sandbox。"
    else:
        state = "不可用"
        lifecycle = ""
    content = (
        f"Sandbox 状态：{state}。"
        + lifecycle
        + (f"硬约束：{limits}。" if limits else "")
        + "命令执行绝不回退宿主机。"
    )
    return ContextBlock(
        block_id="sandbox-constraints",
        category="sandbox_constraints",
        source="m06-sandbox",
        content=content,
        priority=95,
        mandatory=True,
        token_count=conservative_token_count(content),
    )
