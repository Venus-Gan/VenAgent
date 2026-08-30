"""模型调用上下文、区块与预算结果值对象。"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class ContextBlock:
    block_id: str
    category: str
    source: str
    content: str
    priority: int
    mandatory: bool
    token_count: int
    source_ref: str | None = None
    sensitivity: str = "internal"
    captured_at: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class BudgetReport:
    input_budget: int
    selected_tokens: int
    selected_block_ids: tuple[str, ...]
    omitted_block_ids: tuple[str, ...]
    token_count_method: str = "provided"


@dataclass(frozen=True)
class ModelCallContext:
    system_messages: tuple[str, ...]
    messages: tuple[str, ...]
    tools: tuple[str, ...]
    budget_report: BudgetReport
    policy_version: str


def conservative_token_count(content: str) -> int:
    """无模型 tokenizer 时使用偏保守的 UTF-8 字节估算。"""

    return max(1, ceil(len(content.encode("utf-8")) / 3))
