"""Replanner 触发判定与修订合并单测。"""

from __future__ import annotations

from venagent.agent.planning.replanner import detect_trigger
from venagent.agent.state import NodeOutcome, Plan, PlanNode


def _node(node_id, depends=(), tool="t1"):
    return PlanNode(node_id=node_id, objective=node_id, tool=tool, depends_on=depends)


def _outcome(node_id, outcome, error_code=None):
    return NodeOutcome(
        plan_revision=1,
        node_id=node_id,
        logical_attempt=0,
        outcome=outcome,
        observation="x",
        error_code=error_code,
    )


def test_no_failure_is_observation_insufficient():
    plan = Plan(revision=1, goal="g", nodes=(_node("a"),))
    assert detect_trigger(plan, (_outcome("a", "succeeded"),)) == "observation_insufficient"


def test_approval_rejected_is_premise_changed():
    plan = Plan(revision=1, goal="g", nodes=(_node("a", tool="exec_command"),))
    outcomes = (_outcome("a", "failed", error_code="approval_rejected"),)
    assert detect_trigger(plan, outcomes) == "premise_changed"


def test_failed_dependency_is_dependency_invalidated():
    plan = Plan(
        revision=1, goal="g", nodes=(_node("a"), _node("b", ("a",)))
    )
    outcomes = (_outcome("a", "failed", error_code="boom"),)
    assert detect_trigger(plan, outcomes) == "dependency_invalidated"


def test_plain_failure_is_node_failed():
    plan = Plan(revision=1, goal="g", nodes=(_node("a"), _node("b")))
    outcomes = (_outcome("a", "failed", error_code="boom"),)
    assert detect_trigger(plan, outcomes) == "node_failed"
