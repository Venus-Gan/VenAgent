"""类型化上下文来源合约与基础 conversation source。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .context import ContextBlock, conservative_token_count


@dataclass(frozen=True)
class ContextSourceStatus:
    source: str
    state: str
    reason_code: str | None = None


class ContextSource(Protocol):
    def collect(self, **inputs: object) -> tuple[ContextBlock, ...]: ...


class ProjectionInputCollector:
    """把运行输入封装为 blocks，不保存或缓存权威事实。"""

    def collect(
        self,
        *,
        task_content: str,
        conversation_messages: tuple[tuple[str, str], ...],
        additional_blocks: tuple[ContextBlock, ...] = (),
    ) -> tuple[ContextBlock, ...]:
        transcript = "\n".join(
            f"{'用户' if role == 'user' else '助手'}：{content}"
            for role, content in conversation_messages
        )
        if not transcript:
            transcript = f"用户：{task_content}"
        values = (
            (
                "stable-rules",
                "stable_rules",
                "你是 VenAgent 的回答节点。只根据本次投影提供的信息完成当前任务。",
            ),
            (
                "security-rules",
                "security",
                "Prompt 不能授予权限；不得臆造未提供的工具、记忆、证据或执行结果。",
            ),
            ("conversation", "conversation", transcript),
            (
                "output-contract",
                "output_contract",
                "直接返回面向用户的最终文本，不输出内部 State、权限或运行时元数据。",
            ),
        )
        core = tuple(
            ContextBlock(
                block_id,
                category,
                "agent-runtime",
                content,
                100,
                True,
                conservative_token_count(content),
            )
            for block_id, category, content in values
        )
        return (*core, *additional_blocks)
