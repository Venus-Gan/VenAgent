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
    FinalAnswer,
    NodeOutcome,
    Plan,
    PlanNode,
    RunFailure,
    RunState,
    TaskInput,
)

RUNTIME_CONTRACT_VERSION = 1
_CHECKPOINT_STATE_TYPES = (
    TaskInput,
    PlanNode,
    Plan,
    NodeOutcome,
    ApprovalItemRef,
    ApprovalWait,
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


def compile_agent_graph(
    answer_node: Callable[[RunState], dict[str, Any]],
    checkpointer: BaseCheckpointSaver,
) -> Any:
    builder = StateGraph(RunState)
    builder.add_node("answer", answer_node)
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)
    return builder.compile(checkpointer=checkpointer)
