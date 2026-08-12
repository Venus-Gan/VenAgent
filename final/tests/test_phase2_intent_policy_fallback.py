import ast
from pathlib import Path

import pytest

from internal.agent import router
from internal.agent.policy import ExecutionProfile, IntentPolicy, IntentSignal
from internal.agent.policy.fallback import (
    detect_compatible_tool,
    has_compatible_tool_intent,
    has_compatible_workflow_intent,
)


_DEFAULT_TOOL_NAMES = (
    "search_web",
    "get_time",
    "get_weather",
    "rag_search",
    "write_document",
    "read_document",
    "list_documents",
    "ingest_document",
    "exec_command",
)


@pytest.mark.parametrize(
    ("query", "available_tools"),
    (
        ("现在几点", ("get_time", "get_weather")),
        ("天气和现在时间", ("get_time", "get_weather")),
        ("搜索 VenAgent", ("search_web", "rag_search")),
        ("知识库里有什么", ("rag_search",)),
        ("文档在哪里", ("rag_search",)),
        ("Python 是什么", ("search_web",)),
        ("天气怎么样", ("search_web",)),
        ("普通聊天", ("search_web",)),
    ),
)
def test_fallback_tool_detection_matches_legacy_router(query, available_tools):
    expected = router.detect_tool(query, dict.fromkeys(available_tools, True))

    actual = detect_compatible_tool(query, available_tools)

    assert actual == expected


def test_fallback_uses_legacy_default_tool_names_when_policy_has_no_live_tool_snapshot():
    expected = router.detect_tool("现在几点", dict.fromkeys(_DEFAULT_TOOL_NAMES, True))

    actual = detect_compatible_tool("现在几点", ())

    assert actual == expected == "get_time"


@pytest.mark.parametrize(
    "query",
    ("现在几点，天气怎么样", "搜索资料并总结", "查找资料和天气"),
)
def test_fallback_workflow_detection_matches_legacy_router(query):
    assert has_compatible_workflow_intent(query) is router.need_react(query)


@pytest.mark.parametrize(
    "query",
    ("天气和温度", "搜索 VenAgent", "普通聊天", "知识库问题"),
)
def test_fallback_single_category_and_non_matches_match_legacy_workflow_router(query):
    assert has_compatible_workflow_intent(query) is router.need_react(query)


@pytest.mark.parametrize(
    "query",
    ("查询天气", "搜索资料", "这是什么", "查找文档", "普通聊天"),
)
def test_fallback_generic_tool_detection_matches_legacy_router(query):
    assert has_compatible_tool_intent(query) is router.need_tool(query)


def test_policy_uses_fallback_for_automatic_tool_classification_without_expanding_scope():
    decision = IntentPolicy().resolve(
        IntentSignal(query="天气怎么样", available_tools=("get_weather",))
    )

    assert decision.execution_profile is ExecutionProfile.SINGLE_TOOL
    assert decision.capability_scope.tools == ()
    assert decision.reason == "tool keyword detected: get_weather"


def test_policy_uses_fallback_for_requested_single_tool_without_expanding_scope():
    decision = IntentPolicy().resolve(
        IntentSignal(
            query="现在几点",
            requested_profile="single_tool",
            available_tools=("get_time",),
        )
    )

    assert decision.execution_profile is ExecutionProfile.SINGLE_TOOL
    assert decision.capability_scope.tools == ()
    assert decision.reason == "requested profile normalized to single tool: get_time"


def test_policy_fallback_preserves_fail_closed_rag_and_ambiguous_paths():
    rag_decision = IntentPolicy().resolve(
        IntentSignal(query="知识库里有什么", available_tools=("rag_search",), rag_loaded=False)
    )
    ambiguous_decision = IntentPolicy().resolve(IntentSignal(query="这个怎么安排"))

    assert rag_decision.execution_profile is ExecutionProfile.CLARIFY
    assert rag_decision.capability_scope.tools == ()
    assert ambiguous_decision.execution_profile is ExecutionProfile.CLARIFY
    assert ambiguous_decision.capability_scope.tools == ()


def test_policy_rejects_explicit_unavailable_tools_before_keyword_fallback():
    decision = IntentPolicy().resolve(
        IntentSignal(
            query="现在几点",
            selected_tools=("missing_tool",),
            available_tools=("get_time",),
        )
    )

    assert decision.execution_profile is ExecutionProfile.CLARIFY
    assert decision.reason == "explicit tool selection is unavailable"


def test_policy_keeps_explicit_rag_unavailable_as_clarify():
    decision = IntentPolicy().resolve(
        IntentSignal(query="请基于知识库回答", explicit=True, use_rag=True, rag_loaded=False)
    )

    assert decision.execution_profile is ExecutionProfile.CLARIFY
    assert decision.reason == "explicit RAG request but rag is unavailable"


@pytest.mark.parametrize(
    ("signal", "profile", "reason"),
    (
        (
            IntentSignal(query="天气和总结"),
            ExecutionProfile.WORKFLOW_TASK,
            "multi-step workflow detected",
        ),
        (
            IntentSignal(query="请解释背景", rag_loaded=True),
            ExecutionProfile.KNOWLEDGE_ANSWER,
            "knowledge retrieval detected",
        ),
        (
            IntentSignal(query="知识", rag_loaded=True),
            ExecutionProfile.KNOWLEDGE_ANSWER,
            "rag_search detected",
        ),
        (
            IntentSignal(query="知识", rag_loaded=False),
            ExecutionProfile.CLARIFY,
            "rag_search detected but rag is unavailable",
        ),
        (
            IntentSignal(query="天气", available_tools=("search_web",)),
            ExecutionProfile.SINGLE_TOOL,
            "generic tool keyword detected",
        ),
        (IntentSignal(query="您好"), ExecutionProfile.DEFAULT_CHAT, "greeting detected"),
        (
            IntentSignal(query="请讲一个故事"),
            ExecutionProfile.DEFAULT_CHAT,
            "safe conversational default",
        ),
    ),
)
def test_policy_fallback_classifies_automatic_compatibility_paths(signal, profile, reason):
    decision = IntentPolicy().resolve(signal)

    assert decision.execution_profile is profile
    assert decision.reason == reason


@pytest.mark.parametrize(
    ("signal", "profile", "reason"),
    (
        (
            IntentSignal(query="任意", requested_profile="clarify"),
            ExecutionProfile.CLARIFY,
            "requested clarify profile",
        ),
        (
            IntentSignal(query="任意", requested_profile="knowledge", rag_loaded=True),
            ExecutionProfile.KNOWLEDGE_ANSWER,
            "requested knowledge profile",
        ),
        (
            IntentSignal(query="任意", requested_profile="knowledge", rag_loaded=False),
            ExecutionProfile.CLARIFY,
            "requested knowledge profile without rag",
        ),
        (
            IntentSignal(query="任意", requested_profile="document", allow_documents=True),
            ExecutionProfile.DOCUMENT_FLOW,
            "requested document profile",
        ),
        (
            IntentSignal(query="任意", requested_profile="document", allow_documents=False),
            ExecutionProfile.CLARIFY,
            "requested document profile disabled",
        ),
        (
            IntentSignal(query="任意", requested_profile="workflow"),
            ExecutionProfile.WORKFLOW_TASK,
            "requested workflow profile",
        ),
    ),
)
def test_policy_preserves_requested_profile_precedence(signal, profile, reason):
    decision = IntentPolicy().resolve(signal)

    assert decision.execution_profile is profile
    assert decision.reason == reason


def test_production_policy_package_cannot_import_legacy_router():
    policy_dir = Path(__file__).parents[1] / "internal" / "agent" / "policy"
    violations = []

    for path in policy_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported_names = {alias.name for alias in node.names}
                if node.module in {"router", "internal.agent.router"} or (
                    node.module is None and "router" in imported_names
                ):
                    violations.append(f"{path.name}: relative router import")
                if node.module == "internal.agent" and "router" in imported_names:
                    violations.append(f"{path.name}: package router import")
            if isinstance(node, ast.Import) and any(
                alias.name == "internal.agent.router" for alias in node.names
            ):
                violations.append(f"{path.name}: absolute router import")
            if isinstance(node, ast.Call) and node.args:
                imported_module = node.args[0]
                is_router = (
                    isinstance(imported_module, ast.Constant)
                    and imported_module.value == "internal.agent.router"
                )
                function_name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else ""
                )
                if is_router and function_name in {"__import__", "import_module"}:
                    violations.append(f"{path.name}: dynamic router import")

    assert violations == []
