"""计划 DAG 纯函数单测。"""

from __future__ import annotations

from src.agent.planning.dag import (
    _has_cycle,
    ready_layer,
    resolved_ids,
    succeeded_ids,
    unresolvable_dependencies,
    validate_plan,
)
from src.agent.state import NodeOutcome, Plan, PlanNode


def _node(node_id: str, depends: tuple[str, ...] = (), tool: str = "t1") -> PlanNode:
    return PlanNode(
        node_id=node_id,
        objective=f"do {node_id}",
        tool=tool,
        depends_on=depends,
    )


def _outcome(node_id: str, outcome: str, revision: int = 1) -> NodeOutcome:
    return NodeOutcome(
        plan_revision=revision,
        node_id=node_id,
        logical_attempt=0,
        outcome=outcome,
        observation="ok",
    )


def test_ready_layer_respects_dependencies():
    plan = Plan(revision=1, goal="g", nodes=(_node("a"), _node("b", ("a",))))
    assert [n.node_id for n in ready_layer(plan, ())] == ["a"]
    outcomes = (_outcome("a", "succeeded"),)
    assert [n.node_id for n in ready_layer(plan, outcomes)] == ["b"]


def test_skipped_dependency_does_not_block():
    """竞速败者记 skipped，下游按已解决处理。"""
    plan = Plan(revision=1, goal="g", nodes=(_node("a"), _node("b", ("a",))))
    outcomes = (_outcome("a", "skipped"),)
    assert [n.node_id for n in ready_layer(plan, outcomes)] == ["b"]
    assert resolved_ids(outcomes) == {"a"}
    assert succeeded_ids(outcomes) == set()


def test_cross_revision_dependency():
    """Replanner 剩余计划可依赖历史 revision 的成功节点。"""
    plan_v2 = Plan(revision=2, goal="g", nodes=(_node("c", ("a",)),))
    outcomes = (_outcome("a", "succeeded", revision=1),)
    assert [n.node_id for n in ready_layer(plan_v2, outcomes)] == ["c"]


def test_validate_plan_detects_unknown_tool_and_cycle():
    nodes = (_node("a", tool="nope"),)
    errors = validate_plan(
        Plan(revision=1, goal="g", nodes=nodes),
        known_tools=frozenset({"t1"}),
        known_agents=frozenset(),
    )
    assert "unknown_tool:a:nope" in errors

    cycle = (_node("a", ("b",)), _node("b", ("a",)))
    assert _has_cycle(cycle)
    errors = validate_plan(
        Plan(revision=1, goal="g", nodes=cycle),
        known_tools=frozenset({"t1"}),
        known_agents=frozenset(),
    )
    assert "plan_cycle" in errors


def test_unresolvable_dependencies():
    nodes = (_node("a", ("ghost",)),)
    assert unresolvable_dependencies(nodes, frozenset()) == ("a:ghost",)
    assert unresolvable_dependencies(nodes, frozenset({"ghost"})) == ()


def test_skipped_node_is_terminal_for_pending():
    """竞速败者 skipped 后不得再被视为剩余待办（防止 executor⇄replanner 空转）。"""
    from src.agent.planning.dag import pending_nodes

    plan = Plan(revision=1, goal="g", nodes=(_node("a"), _node("b")))
    outcomes = (_outcome("a", "skipped"), _outcome("b", "succeeded"))
    assert pending_nodes(plan, outcomes) == ()
