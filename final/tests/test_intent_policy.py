import json
from dataclasses import asdict

from internal.agent.policy.intent_policy import IntentPolicy
from internal.agent.policy.types import (
    CapabilityScope,
    ExecutionProfile,
    IntentDecision,
    IntentSignal,
)


def test_intent_decision_serializes_cleanly():
    decision = IntentDecision(
        policy_version="1",
        intent_class="conversation",
        execution_profile=ExecutionProfile.DEFAULT_CHAT,
        prompt_schema_key="chat",
        graph_entry="chat",
        capability_scope=CapabilityScope(
            tools=(),
            agents=(),
            memory=("stm", "preference"),
            recovery=(),
        ),
        clarify_needed=False,
        confidence=0.95,
        reason="default conversation",
    )

    encoded = json.dumps(asdict(decision), ensure_ascii=False)

    assert '"execution_profile": "default_chat"' in encoded
    assert '"memory": ["stm", "preference"]' in encoded


def test_explicit_selected_tools_narrows_scope():
    policy = IntentPolicy()
    signal = IntentSignal(
        query="请用搜索工具查一下天气",
        explicit=True,
        selected_tools=("search_web", "missing_tool"),
        available_tools=("search_web", "get_time"),
    )

    decision = policy.resolve(signal)

    assert decision.execution_profile is ExecutionProfile.SINGLE_TOOL
    assert decision.intent_class == "tool_call"
    assert decision.capability_scope.tools == ("search_web",)
    assert decision.clarify_needed is False


def test_explicit_rag_request_uses_knowledge_profile():
    policy = IntentPolicy()
    signal = IntentSignal(
        query="请基于知识库回答",
        explicit=True,
        use_rag=True,
        rag_loaded=True,
    )

    decision = policy.resolve(signal)

    assert decision.execution_profile is ExecutionProfile.KNOWLEDGE_ANSWER
    assert decision.intent_class == "retrieval"
    assert decision.prompt_schema_key == "rag"
    assert "rag_search" in decision.capability_scope.tools


def test_document_request_selects_document_flow():
    policy = IntentPolicy()
    signal = IntentSignal(query="帮我整理这份文档并写成摘要")

    decision = policy.resolve(signal)

    assert decision.execution_profile is ExecutionProfile.DOCUMENT_FLOW
    assert decision.intent_class == "workflow"
    assert decision.graph_entry == "document"
    assert "write_document" in decision.capability_scope.tools


def test_low_confidence_query_falls_back_to_clarify():
    policy = IntentPolicy()
    signal = IntentSignal(query="这个怎么弄")

    decision = policy.resolve(signal)

    assert decision.execution_profile is ExecutionProfile.CLARIFY
    assert decision.clarify_needed is True
    assert decision.confidence < 0.5
    assert decision.capability_scope.tools == ()
