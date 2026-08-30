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
    plan_mode: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "attachment_refs", tuple(self.attachment_refs))


@dataclass(frozen=True)
class PlanNode:
    node_id: str
    objective: str
    node_type: str = "tool"
    tool: str | None = None
    agent_name: str | None = None
    arguments_json: str = "{}"
    depends_on: tuple[str, ...] = ()
    race_group: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "depends_on", tuple(self.depends_on))


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
class PendingToolCallRef:
    """只保存定位引用，完整工具参数放在私有 InvocationStore。"""

    tool_call_id: str
    operation_key: str
    tool_id: str
    approval_id: str | None = None
    call_type: str = "tool_call"
    call_version: int = 1


@dataclass(frozen=True)
class ToolObservationRef:
    """只保存 Operation/ToolResult 引用，不保存原始输出或凭据。"""

    tool_call_id: str
    operation_id: str
    status: str
    summary: str
    approval_id: str | None = None


@dataclass(frozen=True)
class FinalAnswer:
    content: str
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    blocks: tuple[dict[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "blocks", tuple(dict(item) for item in self.blocks))
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))


@dataclass(frozen=True)
class RunFailure:
    code: str
    message: str
    retryable: bool
    failed_node_id: str | None = None
    source_ref: str | None = None


@dataclass(frozen=True)
class ClarificationRequest:
    """Planner 信息不足时向用户发起的结构化反问。"""

    question: str
    options: tuple[str, ...] = ()
    multi_select: bool = False
    allow_custom: bool = True
    allow_skip: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", tuple(self.options))


@dataclass(frozen=True)
class ClarificationAnswer:
    """用户对澄清请求的答复，经 Command(resume=...) 回填计划层。"""

    selected: tuple[str, ...] = ()
    custom: str | None = None
    skipped: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected", tuple(self.selected))

    def as_text(self) -> str:
        """把答复压成给 Planner 看的一段自然语言补充。"""
        if self.skipped:
            return "（用户选择忽略澄清，请按你的判断继续任务。）"
        parts = [f"「{item}」" for item in self.selected]
        if self.custom:
            parts.append(f"「{self.custom}」")
        if not parts:
            return "（用户未提供补充信息，请按你的判断继续任务。）"
        return "用户补充：选择了 " + "、".join(parts) + "。"


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
    plan_branch: str | None
    replan_action: str | None
    replans_used: int
    node_outcomes: Annotated[tuple[NodeOutcome, ...], merge_node_outcomes]
    clarification_request: ClarificationRequest | None
    clarification_answer: ClarificationAnswer | None
    approval_wait: ApprovalWait | None
    natural_memory_outcome: dict[str, object] | None
    pending_tool_call: PendingToolCallRef | None
    pending_tool_calls: tuple[PendingToolCallRef, ...] | None
    tool_observation: ToolObservationRef | None
    executed_tool_observations: tuple[tuple[PendingToolCallRef, ToolObservationRef], ...] | None
    final_answer: FinalAnswer | None
    failure: RunFailure | None
