"""把已授权、已排序的 memory 候选转换为上下文区块。"""

from __future__ import annotations

from typing import Protocol

from ..conversation.models import ConversationMessage
from ..memory.authorization import MemoryAuthorization, MemoryRequestSnapshot
from ..memory.long_term.facts import MemoryFact
from ..memory.short_term import MemorySummary
from .context import ContextBlock, conservative_token_count


class MemoryRecallPort(Protocol):
    def long_term_candidates(
        self,
        auth: MemoryAuthorization,
        query: str,
        *,
        limit: int = 5,
        snapshot: MemoryRequestSnapshot | None = None,
    ) -> tuple[MemoryFact, ...]: ...

    def summary_candidates(
        self,
        auth: MemoryAuthorization,
        messages: tuple[ConversationMessage, ...],
        input_message_id: str,
        *,
        token_budget: int = 20_000,
        snapshot: MemoryRequestSnapshot | None = None,
    ) -> tuple[MemorySummary, ...]: ...


class MemoryRecallProvider:
    """只负责 Prompt 形状，不参与授权、生命周期或候选排序。"""

    def __init__(self, recall: MemoryRecallPort) -> None:
        self._recall = recall

    def context_blocks(
        self,
        auth: MemoryAuthorization,
        query: str,
        *,
        limit: int = 5,
        snapshot: MemoryRequestSnapshot | None = None,
    ) -> tuple[ContextBlock, ...]:
        return tuple(
            ContextBlock(
                block_id=f"memory:{fact.memory_id}",
                category="long_term_memory",
                source="memory-service",
                content=f"已确认的用户记忆：{fact.fact}",
                priority=70,
                mandatory=False,
                token_count=conservative_token_count(fact.fact),
                source_ref=fact.source_refs[0] if fact.source_refs else None,
                captured_at=fact.updated_at.isoformat(),
                metadata=(
                    ("memory_id", fact.memory_id),
                    ("slot", fact.slot),
                    ("index_status", fact.index_status),
                    ("rank", str(rank)),
                ),
            )
            for rank, fact in enumerate(
                self._recall.long_term_candidates(
                    auth, query, limit=limit, snapshot=snapshot
                ),
                start=1,
            )
        )

    def summary_blocks(
        self,
        auth: MemoryAuthorization,
        messages: tuple[ConversationMessage, ...],
        input_message_id: str,
        *,
        token_budget: int = 20_000,
        snapshot: MemoryRequestSnapshot | None = None,
    ) -> tuple[ContextBlock, ...]:
        return tuple(
            ContextBlock(
                block_id=f"summary:{summary.summary_id}",
                category="short_term_summary",
                source="memory-summary",
                content=f"较早对话摘要：\n{summary.content}",
                priority=80,
                mandatory=False,
                token_count=conservative_token_count(summary.content),
                source_ref=(
                    f"messages:{summary.first_message_id}:{summary.last_message_id}"
                ),
                captured_at=summary.created_at.isoformat(),
            )
            for summary in self._recall.summary_candidates(
                auth,
                messages,
                input_message_id,
                token_budget=token_budget,
                snapshot=snapshot,
            )
        )
