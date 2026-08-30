"""LangGraph 构建和 checkpoint identity 的唯一入口。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from .state import (
    ApprovalItemRef,
    ApprovalWait,
    ClarificationAnswer,
    ClarificationRequest,
    FinalAnswer,
    NodeOutcome,
    PendingToolCallRef,
    Plan,
    PlanNode,
    RunFailure,
    RunState,
    TaskInput,
    ToolObservationRef,
)

RUNTIME_CONTRACT_VERSION = 3
_CHECKPOINT_STATE_TYPES = (
    TaskInput,
    PlanNode,
    Plan,
    NodeOutcome,
    ClarificationRequest,
    ClarificationAnswer,
    ApprovalItemRef,
    ApprovalWait,
    PendingToolCallRef,
    ToolObservationRef,
    FinalAnswer,
    RunFailure,
)


def checkpoint_serializer() -> JsonPlusSerializer:
    """为全部 checkpointer 路径创建同一份最小显式类型许可。"""
    allowlist = [(item.__module__, item.__qualname__) for item in _CHECKPOINT_STATE_TYPES]
    return JsonPlusSerializer(allowed_msgpack_modules=allowlist)


def run_config(run_id: str) -> dict[str, dict[str, str]]:
    """业务 run 与 checkpoint thread 一一对应，禁止 conversation 复用链。"""
    return {"configurable": {"thread_id": run_id}}


def _route_after_decision(state: RunState) -> str:
    if state.get("pending_tool_call") is not None:
        return "execute_tool"
    if state.get("tool_observation") is not None:
        return "model_finalize"
    return "final"


def _route_after_finalize(state: RunState) -> str:
    """多工具顺序执行：有待执行工具则回 model_decision，否则到 final。"""
    pending_calls = state.get("pending_tool_calls")
    if pending_calls and len(pending_calls) > 0:
        return "model_decision"
    return "final"


def _route_after_selector(state: RunState) -> str:
    """Selector 隐性分发三支：react（计划层）/ rag（知识库引用回答）/ baseline。"""
    branch = state.get("plan_branch") or "baseline"
    if branch == "react":
        return "planner"
    if branch == "rag":
        return "rag_answer"
    return "model_decision"


def _route_after_planner(state: RunState) -> str:
    """Planner 产出计划则进 Executor，否则回落基线图（解析失败/直答）。"""
    if state.get("plan") is not None:
        return "executor"
    return "model_decision"


def _route_after_replanner(state: RunState) -> str:
    """Replanner 显式决策：execute（继续/修订后执行）| generate（合成答案）| give_up（失败）。"""
    action = state.get("replan_action") or "generate"
    if action == "execute":
        return "executor"
    if action == "give_up":
        return "final"
    return "generator"


_PLANNING_NODE_NAMES = (
    "selector",
    "planner",
    "executor",
    "replanner",
    "generator",
    "rag_answer",
)


def compile_agent_graph(
    answer_node: Callable[[RunState], dict[str, Any]],
    checkpointer: BaseCheckpointSaver,
    *,
    prepare_node: Callable[[RunState], dict[str, Any]] | None = None,
    model_decision_node: Callable[[RunState], dict[str, Any]] | None = None,
    execute_tool_node: Callable[[RunState], dict[str, Any]] | None = None,
    model_finalize_node: Callable[[RunState], dict[str, Any]] | None = None,
    final_node: Callable[[RunState], dict[str, Any]] | None = None,
    selector_node: Callable[[RunState], dict[str, Any]] | None = None,
    planner_node: Callable[[RunState], dict[str, Any]] | None = None,
    executor_node: Callable[[RunState], dict[str, Any]] | None = None,
    replanner_node: Callable[[RunState], dict[str, Any]] | None = None,
    generator_node: Callable[[RunState], dict[str, Any]] | None = None,
    rag_answer_node: Callable[[RunState], dict[str, Any]] | None = None,
) -> Any:
    """构建 M07 计划图（superset）；未提供计划节点时保持基线/旧 answer 图兼容。

    图形态（M07 定稿）：
        START → prepare → selector ─┬─ baseline → model_decision（既有五节点基线循环）
                                    ├─ react    → planner ─┬─ executor ⇄ replanner
                                    └─ rag      → rag_answer                    │
        executor → replanner → {executor | generator | final}；generator/rag_answer → final
    """
    if prepare_node is None or model_decision_node is None:
        builder = StateGraph(RunState)
        builder.add_node("answer", answer_node)
        builder.add_edge(START, "answer")
        builder.add_edge("answer", END)
        return builder.compile(checkpointer=checkpointer)

    builder = StateGraph(RunState)
    builder.add_node("prepare", prepare_node)
    builder.add_node("model_decision", model_decision_node)
    builder.add_node("execute_tool", execute_tool_node)
    builder.add_node("model_finalize", model_finalize_node)
    builder.add_node("final", final_node or (lambda state: state))

    if selector_node is None or planner_node is None or executor_node is None:
        # 未装配计划层：保持 M06 基线图边不变（checkpoint 兼容）。
        builder.add_edge(START, "prepare")
        builder.add_edge("prepare", "model_decision")
        builder.add_conditional_edges(
            "model_decision",
            _route_after_decision,
            {
                "execute_tool": "execute_tool",
                "model_finalize": "model_finalize",
                "final": "final",
            },
        )
        builder.add_edge("execute_tool", "model_finalize")
        builder.add_conditional_edges(
            "model_finalize",
            _route_after_finalize,
            {
                "model_decision": "model_decision",
                "final": "final",
            },
        )
        builder.add_edge("final", END)
        return builder.compile(checkpointer=checkpointer)

    builder.add_node("selector", selector_node)
    builder.add_node("planner", planner_node)
    builder.add_node("executor", executor_node)
    builder.add_node("replanner", replanner_node)
    builder.add_node("generator", generator_node)
    builder.add_node(
        "rag_answer", rag_answer_node or (lambda state: {"phase": "synthesizing"})
    )
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "selector")
    builder.add_conditional_edges(
        "selector",
        _route_after_selector,
        {
            "planner": "planner",
            "rag_answer": "rag_answer",
            "model_decision": "model_decision",
        },
    )
    builder.add_conditional_edges(
        "planner",
        _route_after_planner,
        {
            "executor": "executor",
            "model_decision": "model_decision",
        },
    )
    builder.add_edge("executor", "replanner")
    builder.add_conditional_edges(
        "replanner",
        _route_after_replanner,
        {
            "executor": "executor",
            "generator": "generator",
            "final": "final",
        },
    )
    builder.add_edge("generator", "final")
    builder.add_edge("rag_answer", "final")
    builder.add_conditional_edges(
        "model_decision",
        _route_after_decision,
        {
            "execute_tool": "execute_tool",
            "model_finalize": "model_finalize",
            "final": "final",
        },
    )
    builder.add_edge("execute_tool", "model_finalize")
    builder.add_conditional_edges(
        "model_finalize",
        _route_after_finalize,
        {
            "model_decision": "model_decision",
            "final": "final",
        },
    )
    builder.add_edge("final", END)
    return builder.compile(checkpointer=checkpointer)
