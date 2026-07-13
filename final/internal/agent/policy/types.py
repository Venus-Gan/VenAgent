from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExecutionProfile(str, Enum):
    DEFAULT_CHAT = "default_chat"
    KNOWLEDGE_ANSWER = "knowledge_answer"
    SINGLE_TOOL = "single_tool"
    WORKFLOW_TASK = "workflow_task"
    DOCUMENT_FLOW = "document_flow"
    CLARIFY = "clarify"

    @classmethod
    def coerce(
        cls,
        value: str | ExecutionProfile | None,
    ) -> ExecutionProfile | None:
        if value is None:
            return None
        if isinstance(value, cls):
            return value

        normalized = str(value).strip().lower().replace("-", "_")
        aliases = {
            "chat": cls.DEFAULT_CHAT,
            "default": cls.DEFAULT_CHAT,
            "default_chat": cls.DEFAULT_CHAT,
            "rag": cls.KNOWLEDGE_ANSWER,
            "knowledge": cls.KNOWLEDGE_ANSWER,
            "knowledge_answer": cls.KNOWLEDGE_ANSWER,
            "tool": cls.SINGLE_TOOL,
            "single_tool": cls.SINGLE_TOOL,
            "react": cls.WORKFLOW_TASK,
            "workflow": cls.WORKFLOW_TASK,
            "workflow_task": cls.WORKFLOW_TASK,
            "doc": cls.DOCUMENT_FLOW,
            "document": cls.DOCUMENT_FLOW,
            "document_flow": cls.DOCUMENT_FLOW,
            "clarify": cls.CLARIFY,
        }
        resolved = aliases.get(normalized)
        if resolved is not None:
            return resolved
        try:
            return cls(normalized)
        except ValueError:
            return None


@dataclass(frozen=True)
class CapabilityScope:
    tools: tuple[str, ...] = ()
    agents: tuple[str, ...] = ()
    memory: tuple[str, ...] = ()
    recovery: tuple[str, ...] = ()

    def narrowed(
        self,
        *,
        tools: tuple[str, ...] | None = None,
        agents: tuple[str, ...] | None = None,
        memory: tuple[str, ...] | None = None,
        recovery: tuple[str, ...] | None = None,
    ) -> CapabilityScope:
        return CapabilityScope(
            tools=self.tools if tools is None else tools,
            agents=self.agents if agents is None else agents,
            memory=self.memory if memory is None else memory,
            recovery=self.recovery if recovery is None else recovery,
        )


@dataclass(frozen=True)
class IntentSignal:
    query: str
    explicit: bool = False
    selected_tools: tuple[str, ...] = ()
    use_rag: bool = False
    rag_loaded: bool = False
    requested_profile: str | ExecutionProfile | None = None
    available_tools: tuple[str, ...] = ()
    available_agents: tuple[str, ...] = ()
    allow_documents: bool = True


@dataclass(frozen=True)
class IntentDecision:
    policy_version: str
    intent_class: str
    execution_profile: ExecutionProfile
    prompt_schema_key: str
    graph_entry: str
    capability_scope: CapabilityScope
    clarify_needed: bool
    confidence: float
    reason: str

    @property
    def tool_scope(self) -> tuple[str, ...]:
        return self.capability_scope.tools

    @property
    def agent_scope(self) -> tuple[str, ...]:
        return self.capability_scope.agents

    @property
    def memory_scope(self) -> tuple[str, ...]:
        return self.capability_scope.memory

    @property
    def recovery_policy(self) -> tuple[str, ...]:
        return self.capability_scope.recovery
