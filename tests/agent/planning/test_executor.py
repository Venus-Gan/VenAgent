"""Executor 层并发与竞速单测（伪造 tool_control）。"""

from __future__ import annotations

import asyncio

from src.agent.planning.executor import ExecutorDeps, executor_node
from src.agent.planning.subagents.base import SubAgentRegistry
from src.agent.state import Plan, PlanNode


class FakeToolControl:
    """按工具名返回预设结果；记录调用顺序供并发断言。"""

    def __init__(self, results: dict[str, str], delay: float = 0.05) -> None:
        self.results = results
        self.delay = delay
        self.calls: list[str] = []

    def stage_tool_call(self, run_id, owner_id, call):
        self.calls.append(call.name)
        return type("Staged", (), {"tool_call_id": call.id, "operation_key": "k", "tool_id": call.name})()

    async def resume_tool(self, run_id, owner_id, pending, *, cancel_event=None):
        await asyncio.sleep(self.delay)
        status = self.results.get(pending.tool_id, "success")
        return type(
            "Result",
            (),
            {
                "status": status,
                "summary": f"done:{pending.tool_id}",
                "content": f"content:{pending.tool_id}",
                "approval_id": None,
                "operation_id": "op",
                "error": None if status == "success" else "boom",
                "tool_call_id": pending.tool_call_id,
            },
        )()


def _node(node_id, tool, depends=(), race_group=None):
    return PlanNode(
        node_id=node_id,
        objective=f"do {node_id}",
        tool=tool,
        depends_on=depends,
        race_group=race_group,
    )


def _deps(tool_control, *, max_parallel=2, race_timeout_ms=5000, publish=None):
    async def _publish(run_id, event, **payload):
        pass

    return ExecutorDeps(
        run_id="r",
        owner_id="o",
        tool_control=tool_control,
        registry=SubAgentRegistry(),
        publish=publish or _publish,
        cancel_event=None,
        max_parallel=max_parallel,
        race_timeout_ms=race_timeout_ms,
    )


def test_layer_respects_max_parallel():
    """max_parallel=1 时同层节点串行（用完成顺序断言）。"""
    order: list[str] = []

    class OrderedControl(FakeToolControl):
        async def resume_tool(self, run_id, owner_id, pending, *, cancel_event=None):
            order.append(f"start:{pending.tool_id}")
            await asyncio.sleep(0.03)
            order.append(f"end:{pending.tool_id}")
            return await super().resume_tool(run_id, owner_id, pending, cancel_event=cancel_event)

    control = OrderedControl({"t1": "success", "t2": "success"})
    plan = Plan(revision=1, goal="g", nodes=(_node("a", tool="t1"), _node("b", tool="t2")))
    node = executor_node(_deps(control, max_parallel=1))
    state = {"plan": plan, "node_outcomes": ()}
    result = asyncio.run(node(state))
    outcomes = result["node_outcomes"]
    assert {o.outcome for o in outcomes} == {"succeeded"}
    assert order.index("end:t1") < order.index("start:t2")


def test_race_group_first_success_wins():
    """竞速组：慢的成功者胜出？不——先成功者胜，其余 skipped。"""

    class RaceControl(FakeToolControl):
        def __init__(self):
            super().__init__({})
            self.fast = "quick"

        async def resume_tool(self, run_id, owner_id, pending, *, cancel_event=None):
            if pending.tool_id == "slow_tool":
                await asyncio.sleep(0.2)
            else:
                await asyncio.sleep(0.01)
            status = "success"
            return type(
                "Result",
                (),
                {
                    "status": status,
                    "summary": f"done:{pending.tool_id}",
                    "content": f"content:{pending.tool_id}",
                    "approval_id": None,
                    "operation_id": "op",
                    "error": None,
                    "tool_call_id": pending.tool_call_id,
                },
            )()

    control = RaceControl()
    plan = Plan(
        revision=1,
        goal="g",
        nodes=(
            _node("slow", tool="slow_tool", race_group="search"),
            _node("fast", tool="fast_tool", race_group="search"),
        ),
    )
    node = executor_node(_deps(control))
    result = asyncio.run(node(state={"plan": plan, "node_outcomes": ()}))
    outcomes = {o.node_id: o for o in result["node_outcomes"]}
    assert outcomes["fast"].outcome == "succeeded"
    assert outcomes["slow"].outcome == "skipped"


def test_race_group_all_fail_marks_failed():
    control = FakeToolControl({"t1": "error", "t2": "error"})
    plan = Plan(
        revision=1,
        goal="g",
        nodes=(
            _node("a", tool="t1", race_group="g"),
            _node("b", tool="t2", race_group="g"),
        ),
    )
    node = executor_node(_deps(control))
    result = asyncio.run(node(state={"plan": plan, "node_outcomes": ()}))
    outcomes = {o.node_id: o for o in result["node_outcomes"]}
    assert all(o.outcome == "failed" for o in outcomes.values())


def test_tool_node_failure_records_outcome():
    control = FakeToolControl({"t1": "error"})
    plan = Plan(revision=1, goal="g", nodes=(_node("a", tool="t1"),))
    node = executor_node(_deps(control))
    result = asyncio.run(node(state={"plan": plan, "node_outcomes": ()}))
    (outcome,) = result["node_outcomes"]
    assert outcome.outcome == "failed"
    assert outcome.error_code == "boom"


def test_resolve_params_placeholder():
    """{{node.field}} 占位符从上游成功观察的 JSON 解析。"""
    from src.agent.planning.executor import _resolve_params
    from src.agent.state import NodeOutcome

    outcomes = (
        NodeOutcome(
            plan_revision=1,
            node_id="n1",
            logical_attempt=0,
            outcome="succeeded",
            observation='{"document_id": "doc_123", "status": "ready"}',
        ),
    )
    resolved = _resolve_params(
        {"document_id": "{{n1.document_id}}", "plain": "x"}, outcomes
    )
    assert resolved == {"document_id": "doc_123", "plain": "x"}


def test_resolve_params_rejects_unknown_field_and_pending_upstream():
    import pytest

    from src.agent.planning.executor import _resolve_params
    from src.agent.state import NodeOutcome

    outcomes = (
        NodeOutcome(
            plan_revision=1,
            node_id="n1",
            logical_attempt=0,
            outcome="succeeded",
            observation='{"document_id": "doc_123"}',
        ),
    )
    with pytest.raises(ValueError):
        _resolve_params({"document_id": "{{n1.missing}}"}, outcomes)
    with pytest.raises(ValueError):
        _resolve_params({"document_id": "{{n9.document_id}}"}, outcomes)


def test_resolve_params_text_fallback():
    """非 JSON 观察（exec_command 纯文本）降级为观察全文。"""
    from src.agent.planning.executor import _resolve_params
    from src.agent.state import NodeOutcome

    outcomes = (
        NodeOutcome(
            plan_revision=1,
            node_id="n1",
            logical_attempt=0,
            outcome="succeeded",
            observation="final-01-ok",
        ),
    )
    resolved = _resolve_params(
        {"content": "{{n1.output}}", "raw": "{{n1}}"}, outcomes
    )
    assert resolved == {"content": "final-01-ok", "raw": "final-01-ok"}
