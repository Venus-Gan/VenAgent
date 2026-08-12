"""长期事实的确定性合并决策；模型只能提供受约束的建议。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .facts import MemoryFact
from .policy import FactCandidate


class MergeAction(StrEnum):
    ADD = "ADD"
    UPDATE = "UPDATE"
    NOOP = "NOOP"
    QUARANTINE = "QUARANTINE"


@dataclass(frozen=True)
class MergeSuggestion:
    action: MergeAction
    confidence: float
    candidate_memory_id: str | None = None


@dataclass(frozen=True)
class MergeDecision:
    action: MergeAction
    previous: MemoryFact | None
    reason_code: str


class ConflictJudge(Protocol):
    def judge(
        self, candidate: FactCandidate, previous: MemoryFact
    ) -> MergeSuggestion: ...


def decide_merge(
    candidate: FactCandidate,
    previous: MemoryFact | None,
    judge: ConflictJudge | None = None,
) -> MergeDecision:
    """在模型建议之外重新执行 slot、纠正意图和置信度门控。"""
    if previous is None:
        return MergeDecision(MergeAction.ADD, None, "new_slot")
    if previous.fact.casefold() == candidate.fact.casefold():
        return MergeDecision(MergeAction.NOOP, previous, "same_fact")
    if previous.subject != candidate.subject or previous.slot != candidate.slot:
        return MergeDecision(MergeAction.ADD, None, "different_slot")
    if candidate.assertion_mode == "correction":
        return MergeDecision(MergeAction.UPDATE, previous, "explicit_correction")
    if judge is not None:
        try:
            suggestion = judge.judge(candidate, previous)
        except Exception:
            suggestion = None
        if (
            suggestion is not None
            and suggestion.action is MergeAction.QUARANTINE
            and 0.0 <= suggestion.confidence <= 1.0
        ):
            return MergeDecision(MergeAction.QUARANTINE, previous, "judge_ambiguous")
    return MergeDecision(MergeAction.QUARANTINE, previous, "ambiguous_slot_conflict")

