"""Legacy adapter from IntentDecision to the target execution-plan contract."""

from __future__ import annotations

from venagent.orchestration.policy.execution_plan import ExecutionPlan, build_execution_plan

from .types import IntentDecision


_COMPAT_AGENT_IDS: dict[str, str] = {
    "research": "research_agent",
    "writer": "writer_agent",
    "review": "review_agent",
    "doc": "doc_agent",
    "research_agent": "research_agent",
    "writer_agent": "writer_agent",
    "review_agent": "review_agent",
    "doc_agent": "doc_agent",
}


def project_intent_decision(decision: IntentDecision) -> ExecutionPlan:
    """Narrow legacy role names to registered compatibility participant IDs."""

    scope = decision.capability_scope
    return build_execution_plan(
        execution_profile=decision.execution_profile.value,
        graph_entry=decision.graph_entry,
        prompt_schema_key=decision.prompt_schema_key,
        tool_scope=scope.tools,
        agent_scope=_compat_agent_scope(scope.agents),
        memory_scope=scope.memory,
        recovery_policy=scope.recovery,
        clarify_needed=decision.clarify_needed,
        confidence=decision.confidence,
        reason=decision.reason,
    )


def _compat_agent_scope(roles: tuple[str, ...]) -> tuple[str, ...]:
    identifiers = tuple(
        _COMPAT_AGENT_IDS[role]
        for role in roles
        if role in _COMPAT_AGENT_IDS
    )
    return tuple(dict.fromkeys(identifiers))
