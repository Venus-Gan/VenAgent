from dataclasses import replace
from types import SimpleNamespace

import pytest

from internal.agent.agent import ChatOptions, UnifiedAgent
from internal.agent.cancel import CancelToken
from internal.agent.graph_runtime import GraphConfig
from internal.agent.langgraph.runtime import InMemorySaver, ReactCheckpoint, ReactRuntime
from internal.agent.policy.execution_projection import project_intent_decision
from internal.agent.policy.types import CapabilityScope, ExecutionProfile, IntentDecision
from internal.graph.task_graph import Node, NodeType, TaskGraph
from internal.llm.llm import Message
from venagent.orchestration.policy.execution_plan import (
    DispatchMode,
    ExecutionPlan,
)


def _decision(
    profile: ExecutionProfile = ExecutionProfile.WORKFLOW_TASK,
    *,
    graph_entry: str = "react",
    prompt_schema_key: str = "react",
    scope: CapabilityScope | None = None,
    clarify_needed: bool = False,
) -> IntentDecision:
    return IntentDecision(
        policy_version="v1",
        intent_class="workflow",
        execution_profile=profile,
        prompt_schema_key=prompt_schema_key,
        graph_entry=graph_entry,
        capability_scope=scope
        or CapabilityScope(
            tools=("search_web",),
            agents=("research",),
            memory=("stm", "preference", "ltm"),
            recovery=("checkpoint", "resume"),
        ),
        clarify_needed=clarify_needed,
        confidence=0.82,
        reason="test policy reason",
    )


def test_projects_every_decision_field_into_an_immutable_execution_plan():
    decision = _decision()

    plan = project_intent_decision(decision)

    assert plan == ExecutionPlan(
        execution_profile="workflow_task",
        dispatch_mode=DispatchMode.REACT,
        graph_entry="react",
        prompt_schema_key="react",
        tool_scope=("search_web",),
        agent_scope=("research_agent",),
        memory_scope=("stm", "preference", "ltm"),
        recovery_policy=("checkpoint", "resume"),
        clarify_needed=False,
        confidence=0.82,
        reason="test policy reason",
    )


def test_document_profile_uses_the_only_allowed_compatibility_bridge():
    decision = _decision(
        ExecutionProfile.DOCUMENT_FLOW,
        graph_entry="document",
        prompt_schema_key="tool",
    )

    plan = project_intent_decision(decision)

    assert plan.dispatch_mode is DispatchMode.REACT
    assert plan.graph_entry == "document"
    assert plan.prompt_schema_key == "tool"


def test_invalid_profile_mapping_fails_closed_to_clarify_without_scopes():
    decision = replace(_decision(), graph_entry="untrusted_node")

    plan = project_intent_decision(decision)

    assert plan.execution_profile == "clarify"
    assert plan.dispatch_mode is DispatchMode.CLARIFY
    assert plan.tool_scope == ()
    assert plan.agent_scope == ()
    assert plan.memory_scope == ()
    assert plan.recovery_policy == ()
    assert plan.clarify_needed is True
    assert plan.reason == "invalid execution mapping"


def test_explicit_clarify_decision_cannot_keep_tools_or_recovery_scope():
    decision = _decision(
        ExecutionProfile.CLARIFY,
        graph_entry="clarify",
        prompt_schema_key="chat",
        clarify_needed=True,
    )

    plan = project_intent_decision(decision)

    assert plan.dispatch_mode is DispatchMode.CLARIFY
    assert plan.tool_scope == ()
    assert plan.agent_scope == ()
    assert plan.memory_scope == ()
    assert plan.recovery_policy == ()


def test_canonical_agent_roles_map_to_compatibility_registry_ids_without_expansion():
    decision = _decision(
        scope=CapabilityScope(
            agents=("research", "writer"),
            memory=("stm",),
        )
    )

    plan = project_intent_decision(decision)

    assert plan.agent_scope == ("research_agent", "writer_agent")


def test_scopes_are_immutable_tuples_and_never_expand_during_projection():
    plan = project_intent_decision(_decision())

    assert isinstance(plan.tool_scope, tuple)
    assert isinstance(plan.agent_scope, tuple)
    assert isinstance(plan.memory_scope, tuple)
    assert isinstance(plan.recovery_policy, tuple)


def test_scoped_history_and_memory_prefix_exclude_unapproved_memory():
    agent = UnifiedAgent.__new__(UnifiedAgent)
    agent.stm = SimpleNamespace(
        get=lambda: [
            {"role": "user", "content": "old secret context"},
            {"role": "assistant", "content": "old response"},
        ]
    )
    agent.preference = SimpleNamespace(get_all=lambda: {"secret_preference": "hidden"})
    agent.ltm = SimpleNamespace(
        recall=lambda _query, _limit: [SimpleNamespace(content="hidden long-term memory")]
    )
    agent.cfg = SimpleNamespace(long_term_top_k=3)

    history = agent._build_history_messages("current request", memory_scope=())
    prefix = agent._build_memory_system_prefix("current request", memory_scope=())

    assert history == [Message(role="user", content="current request")]
    assert prefix == ""


def test_prepare_uses_execution_plan_schema_and_scope_for_shared_inputs(monkeypatch):
    from internal.agent import agent as agent_module

    decision = _decision(
        scope=CapabilityScope(
            tools=("search_web",),
            agents=("research",),
            memory=("stm",),
            recovery=(),
        )
    )
    calls: dict[str, object] = {}
    agent = UnifiedAgent.__new__(UnifiedAgent)
    agent.stm = SimpleNamespace(add=lambda *_args: None)
    agent.preference = SimpleNamespace(get_all=lambda: {}, save_batch=lambda *_args: None)
    agent.ltm = SimpleNamespace(recall=lambda *_args: [])
    agent.rag = SimpleNamespace(loaded=False)
    agent.tool_executor = SimpleNamespace(snapshot=lambda: {}, filter_tools=lambda _names: {})
    agent.subagents = SimpleNamespace(names=lambda: ())
    agent._save_chat_history = lambda *_args: None
    agent._intent_policy = lambda: SimpleNamespace(resolve=lambda _signal: decision)
    agent._build_intent_signal = lambda _query, _opts: object()
    agent._route_tools_from_scope = lambda scope: calls.setdefault("tools", scope) or {}
    agent._build_context_prefix = lambda query, schema_key, memory_scope: calls.setdefault(
        "context", (query, schema_key, memory_scope)
    ) or "context"
    agent._build_history_messages = lambda query, memory_scope: calls.setdefault(
        "history", (query, memory_scope)
    ) or [Message(role="user", content=query)]
    monkeypatch.setattr(agent_module, "async_update_memory", lambda *_args: None)

    prepared = agent._prepare("current request", ChatOptions())

    assert prepared["mode"] == "react"
    assert prepared["execution_plan"].agent_scope == ("research_agent",)
    assert calls["tools"] == ("search_web",)
    assert calls["context"] == ("current request", "react", ("stm",))
    assert calls["history"] == ("current request", ("stm",))


def test_subagent_nodes_are_filtered_before_compatibility_graph_execution():
    plan = project_intent_decision(_decision())
    nodes = [
        Node(id="research", type=NodeType.SUBAGENT, tool_name="research_agent"),
        Node(id="writer", type=NodeType.SUBAGENT, tool_name="writer_agent"),
        Node(id="tool", type=NodeType.TOOL, tool_name="search_web"),
    ]

    filtered = UnifiedAgent._filter_plan_nodes(nodes, plan.agent_scope)

    assert [node.id for node in filtered] == ["research", "tool"]


class _Tool:
    description = "fake"
    params = []

    @staticmethod
    def func(_params):
        return "ok"


class _RuntimeAgent:
    cfg = SimpleNamespace(max_retries=1, retry_delay_ms=1)

    def save_snapshot(self, _task):
        return None


def test_disabled_compat_checkpoint_does_not_write_or_restore_in_memory_state():
    saver = InMemorySaver()
    runtime = ReactRuntime(
        TaskGraph([Node(id="n1", type=NodeType.TOOL, tool_name="tool")]),
        _RuntimeAgent(),
        GraphConfig(max_parallel=1),
        {"tool": _Tool()},
        {"task_id": "task-1"},
        checkpointer=saver,
        checkpoint_enabled=False,
    )

    runtime.invoke(CancelToken(), {"configurable": {"thread_id": "thread-1"}})

    assert saver.get("thread-1") is None


def test_disabled_compat_checkpoint_resets_instead_of_restoring_saved_nodes():
    calls: list[str] = []
    saver = InMemorySaver()
    saver.save(
        "thread-1",
        ReactCheckpoint(
            thread_id="thread-1",
            nodes={"n1": {"status": "done", "result": "stale", "error": "", "retry_count": 0}},
        ),
    )
    tool = _Tool()
    tool.func = lambda _params: calls.append("called") or "fresh"
    runtime = ReactRuntime(
        TaskGraph([Node(id="n1", type=NodeType.TOOL, tool_name="tool")]),
        _RuntimeAgent(),
        GraphConfig(max_parallel=1),
        {"tool": tool},
        {"task_id": "task-1"},
        checkpointer=saver,
        checkpoint_enabled=False,
    )

    runtime.resume(CancelToken(), {"configurable": {"thread_id": "thread-1"}})

    assert calls == ["called"]


def test_clarify_mode_does_not_call_llm_or_execution_backends():
    agent = UnifiedAgent.__new__(UnifiedAgent)
    response = SimpleNamespace(answer="", tool_call=None, search_results=[], steps=[], task=None)
    calls = {"chat": 0, "rag": 0, "react": 0}
    agent._chat_response = lambda *_args: calls.__setitem__("chat", calls["chat"] + 1)
    agent._run_rag_query = lambda *_args, **_kwargs: calls.__setitem__("rag", calls["rag"] + 1)
    agent._run_react_with_tools = lambda *_args, **_kwargs: calls.__setitem__("react", calls["react"] + 1)

    agent._dispatch_mode(
        {
            "mode": "clarify",
            "query": "这个怎么弄",
            "mem_prefix": "",
            "hist_msgs": [],
            "route_tools": None,
            "extracted": "",
            "execution_plan": project_intent_decision(
                _decision(
                    ExecutionProfile.CLARIFY,
                    graph_entry="clarify",
                    prompt_schema_key="chat",
                    clarify_needed=True,
                )
            ),
        },
        response,
        CancelToken(),
    )

    assert response.answer == "请提供更多上下文或明确希望执行的操作。"
    assert calls == {"chat": 0, "rag": 0, "react": 0}
