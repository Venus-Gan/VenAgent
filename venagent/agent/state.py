"""单个 AgentRun 的显式 LangGraph State。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict


class StateConsistencyError(RuntimeError):
    """同一逻辑节点重放产生了不一致结果。"""


@dataclass(frozen=True)
class TaskInput:
    input_message_id: str
    content: str
    attachment_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "attachment_refs", tuple(self.attachment_refs))


@dataclass(frozen=True)
class PlanNode:
    node_id: str
    objective: str


@dataclass(frozen=True)
class Plan:
    revision: int
    goal: str
    nodes: tuple[PlanNode, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))


@dataclass(frozen=True)
class NodeOutcome:
    plan_revision: int
    node_id: str
    logical_attempt: int
    outcome: str
    observation: str
    retryable: bool = False
    tool_call_id: str | None = None
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))

    @property
    def key(self) -> tuple[int, str, int]:
        return (self.plan_revision, self.node_id, self.logical_attempt)


def merge_node_outcomes(
    current: tuple[NodeOutcome, ...],
    update: tuple[NodeOutcome, ...],
) -> tuple[NodeOutcome, ...]:
    """稳定合并 checkpoint replay，拒绝同一逻辑尝试的分叉事实。"""
    merged = {item.key: item for item in current}
    for item in update:
        existing = merged.get(item.key)
        if existing is not None and existing != item:
            raise StateConsistencyError(
                f"conflicting node outcome for {item.plan_revision}:{item.node_id}:"
                f"{item.logical_attempt}"
            )
        merged[item.key] = item
    return tuple(merged[key] for key in sorted(merged))


@dataclass(frozen=True)
class ApprovalItemRef:
    node_id: str
    tool_call_id: str


@dataclass(frozen=True)
class ApprovalWait:
    approval_id: str
    plan_revision: int
    item_refs: tuple[ApprovalItemRef, ...]
    requested_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_refs", tuple(self.item_refs))


@dataclass(frozen=True)
class FinalAnswer:
    content: str
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))


@dataclass(frozen=True)
class RunFailure:
    code: str
    message: str
    retryable: bool
    failed_node_id: str | None = None
    source_ref: str | None = None


RunPhase = Literal[
    "planning",
    "selecting_tools",
    "authorizing",
    "awaiting_approval",
    "executing",
    "replanning",
    "synthesizing",
]


class RunState(TypedDict, total=False):
    task_input: TaskInput
    phase: RunPhase
    plan: Plan
    node_outcomes: Annotated[tuple[NodeOutcome, ...], merge_node_outcomes]
    approval_wait: ApprovalWait | None
    final_answer: FinalAnswer | None
    failure: RunFailure | None
