"""计划图端到端单测：selector → planner → executor → replanner → generator。

用伪造节点依赖注入验证图布线与状态流转（不经真实 LLM）。
"""

from __future__ import annotations

import asyncio

from langgraph.checkpoint.memory import InMemorySaver

from src.agent.graph import compile_agent_graph
from src.agent.state import (
    FinalAnswer,
    NodeOutcome,
    Plan,
    PlanNode,
    RunState,
)


def _baseline_nodes():
    async def prepare(state):
        return {"phase": "synthesizing"}

    async def model_decision(state):
        return {
            "phase": "synthesizing",
            "final_answer": FinalAnswer("baseline answer"),
        }

    async def execute_tool(state):
        raise RuntimeError("not expected in this test")

    async def model_finalize(state):
        return {"phase": "synthesizing", "final_answer": FinalAnswer("final")}

    async def final(state):
        return {}

    return {
        "prepare": prepare,
        "model_decision": model_decision,
        "execute_tool": execute_tool,
        "model_finalize": model_finalize,
        "final": final,
    }


def test_react_flow_end_to_end():
    async def selector(state):
        return {"phase": "selecting_tools", "plan_branch": "react"}

    async def planner(state):
        return {
            "phase": "planning",
            "plan": Plan(
                revision=1,
                goal="g",
                nodes=(
                    PlanNode(node_id="n1", objective="a", tool="t1"),
                    PlanNode(node_id="n2", objective="b", tool="t1", depends_on=("n1",)),
                ),
            ),
        }

    async def executor(state):
        plan = state["plan"]
        outcomes = state.get("node_outcomes") or ()
        done = {o.node_id for o in outcomes if o.outcome == "succeeded"}
        pending = [n for n in plan.nodes if n.node_id not in done]
        new = tuple(
            NodeOutcome(
                plan_revision=plan.revision,
                node_id=node.node_id,
                logical_attempt=0,
                outcome="succeeded",
                observation=f"obs:{node.node_id}",
            )
            for node in pending
        )
        return {"phase": "executing", "node_outcomes": new}

    replan_calls = {"count": 0}

    async def replanner(state):
        outcomes = state.get("node_outcomes") or ()
        if len(outcomes) < 2 and replan_calls["count"] == 0:
            replan_calls["count"] += 1
            return {"phase": "replanning", "replan_action": "execute", "replans_used": 1}
        return {"phase": "synthesizing", "replan_action": "generate"}

    async def generator(state):
        return {
            "phase": "synthesizing",
            "final_answer": FinalAnswer("generated"),
        }

    async def rag_answer(state):
        raise RuntimeError("not expected")

    baseline = _baseline_nodes()
    graph = compile_agent_graph(
        lambda state: {},
        InMemorySaver(),
        prepare_node=baseline["prepare"],
        model_decision_node=baseline["model_decision"],
        execute_tool_node=baseline["execute_tool"],
        model_finalize_node=baseline["model_finalize"],
        final_node=baseline["final"],
        selector_node=selector,
        planner_node=planner,
        executor_node=executor,
        replanner_node=replanner,
        generator_node=generator,
        rag_answer_node=rag_answer,
    )
    initial: RunState = {"task_input": None}  # type: ignore[dict-item]
    initial["task_input"] = __import__(
        "src.agent.state", fromlist=["TaskInput"]
    ).TaskInput("m1", "任务", plan_mode=True)
    result = asyncio.run(
        graph.ainvoke(initial, {"configurable": {"thread_id": "t1"}})
    )
    assert isinstance(result["final_answer"], FinalAnswer)
    assert result["final_answer"].content == "generated"
    assert len(result["node_outcomes"]) == 2


def test_baseline_flow_still_reaches_model_decision():
    """selector 判 baseline 时走既有五节点路径。"""

    async def selector(state):
        return {"phase": "selecting_tools", "plan_branch": "baseline"}

    async def planner(state):
        raise RuntimeError("planner must not run on baseline branch")

    async def executor(state):
        raise RuntimeError("executor must not run on baseline branch")

    async def replanner(state):
        raise RuntimeError("replanner must not run on baseline branch")

    async def generator(state):
        raise RuntimeError("generator must not run on baseline branch")

    async def rag_answer(state):
        raise RuntimeError("rag must not run on baseline branch")

    baseline = _baseline_nodes()
    graph = compile_agent_graph(
        lambda state: {},
        InMemorySaver(),
        prepare_node=baseline["prepare"],
        model_decision_node=baseline["model_decision"],
        execute_tool_node=baseline["execute_tool"],
        model_finalize_node=baseline["model_finalize"],
        final_node=baseline["final"],
        selector_node=selector,
        planner_node=planner,
        executor_node=executor,
        replanner_node=replanner,
        generator_node=generator,
        rag_answer_node=rag_answer,
    )
    from src.agent.state import TaskInput

    result = asyncio.run(
        graph.ainvoke(
            {"task_input": TaskInput("m1", "任务")},
            {"configurable": {"thread_id": "t2"}},
        )
    )
    assert result["final_answer"].content == "baseline answer"
