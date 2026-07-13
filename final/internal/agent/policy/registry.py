from __future__ import annotations

from dataclasses import dataclass

from .types import CapabilityScope, ExecutionProfile


@dataclass(frozen=True)
class ProfileSpec:
    intent_class: str
    prompt_schema_key: str
    graph_entry: str
    capability_scope: CapabilityScope
    clarify_needed: bool = False
    confidence: float = 0.9


PROFILE_REGISTRY: dict[ExecutionProfile, ProfileSpec] = {
    ExecutionProfile.DEFAULT_CHAT: ProfileSpec(
        intent_class="conversation",
        prompt_schema_key="chat",
        graph_entry="chat",
        capability_scope=CapabilityScope(
            tools=(),
            agents=(),
            memory=("stm", "preference", "task_memory"),
            recovery=(),
        ),
        confidence=0.8,
    ),
    ExecutionProfile.KNOWLEDGE_ANSWER: ProfileSpec(
        intent_class="retrieval",
        prompt_schema_key="rag",
        graph_entry="rag",
        capability_scope=CapabilityScope(
            tools=("rag_search",),
            agents=(),
            memory=("stm", "ltm", "preference"),
            recovery=(),
        ),
        confidence=0.88,
    ),
    ExecutionProfile.SINGLE_TOOL: ProfileSpec(
        intent_class="tool_call",
        prompt_schema_key="tool",
        graph_entry="tool",
        capability_scope=CapabilityScope(
            tools=(),
            agents=(),
            memory=("stm", "preference"),
            recovery=(),
        ),
        confidence=0.92,
    ),
    ExecutionProfile.WORKFLOW_TASK: ProfileSpec(
        intent_class="workflow",
        prompt_schema_key="react",
        graph_entry="react",
        capability_scope=CapabilityScope(
            tools=(
                "search_web",
                "get_time",
                "get_weather",
                "rag_search",
                "write_document",
                "read_document",
                "list_documents",
                "ingest_document",
                "exec_command",
            ),
            agents=("research", "writer", "review", "doc"),
            memory=("stm", "ltm", "preference", "task_memory"),
            recovery=("checkpoint", "resume", "interrupt"),
        ),
        confidence=0.82,
    ),
    ExecutionProfile.DOCUMENT_FLOW: ProfileSpec(
        intent_class="workflow",
        prompt_schema_key="tool",
        graph_entry="document",
        capability_scope=CapabilityScope(
            tools=("write_document", "read_document", "list_documents", "ingest_document", "rag_search"),
            agents=("writer", "doc"),
            memory=("stm", "ltm", "task_memory"),
            recovery=("checkpoint", "resume"),
        ),
        confidence=0.84,
    ),
    ExecutionProfile.CLARIFY: ProfileSpec(
        intent_class="clarify",
        prompt_schema_key="chat",
        graph_entry="clarify",
        capability_scope=CapabilityScope(
            tools=(),
            agents=(),
            memory=("stm", "preference"),
            recovery=(),
        ),
        clarify_needed=True,
        confidence=0.3,
    ),
}


def get_profile_spec(profile: ExecutionProfile) -> ProfileSpec:
    return PROFILE_REGISTRY[profile]
