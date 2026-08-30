"""Planner 输出清洗与校验单测。"""

from __future__ import annotations

import pytest

from src.agent.planning.planner import (
    parse_planner_output,
    sanitize_clarification,
    sanitize_plan,
)

KNOWN_TOOLS = frozenset({"rag_search", "exec_command"})
KNOWN_AGENTS = frozenset({"research_agent"})


def _plan_data(**overrides):
    data = {
        "action": "plan",
        "nodes": [
            {"id": "n1", "type": "tool", "tool": "rag_search", "goal": "检索"},
            {
                "id": "n2",
                "type": "tool",
                "tool": "exec_command",
                "goal": "执行",
                "depends_on": ["n1"],
            },
        ],
    }
    data.update(overrides)
    return data


def test_parse_strips_code_fence():
    raw = '```json\n{"action": "plan", "nodes": []}\n```'
    assert parse_planner_output(raw)["action"] == "plan"


def test_sanitize_whitelist_and_deps():
    plan, dropped = sanitize_plan(
        _plan_data(),
        goal="g",
        known_tools=KNOWN_TOOLS,
        known_agents=KNOWN_AGENTS,
        max_nodes=8,
    )
    assert [node.node_id for node in plan.nodes] == ["n1", "n2"]
    assert plan.nodes[1].depends_on == ("n1",)
    assert dropped == ()


def test_sanitize_drops_unknown_tool():
    """未知工具节点被丢弃；全部无效则整体降级（抛 ValueError）。"""
    plan, dropped = sanitize_plan(
        _plan_data(
            nodes=[
                {"id": "n1", "type": "tool", "tool": "ghost"},
                {"id": "n2", "type": "tool", "tool": "rag_search"},
            ]
        ),
        goal="g",
        known_tools=KNOWN_TOOLS,
        known_agents=KNOWN_AGENTS,
        max_nodes=8,
    )
    assert dropped == ("n1:unknown_tool:ghost",)
    assert [node.node_id for node in plan.nodes] == ["n2"]

    with pytest.raises(ValueError):
        sanitize_plan(
            _plan_data(nodes=[{"id": "n1", "type": "tool", "tool": "ghost"}]),
            goal="g",
            known_tools=KNOWN_TOOLS,
            known_agents=KNOWN_AGENTS,
            max_nodes=8,
        )


def test_sanitize_rejects_cycle():
    with pytest.raises(ValueError):
        sanitize_plan(
            _plan_data(
                nodes=[
                    {"id": "n1", "type": "tool", "tool": "rag_search", "depends_on": ["n2"]},
                    {"id": "n2", "type": "tool", "tool": "rag_search", "depends_on": ["n1"]},
                ]
            ),
            goal="g",
            known_tools=KNOWN_TOOLS,
            known_agents=KNOWN_AGENTS,
            max_nodes=8,
        )


def test_sanitize_external_deps_allowed_for_replan():
    """Replanner 追加节点可依赖原计划节点（结构校验由合并后的完整计划负责）。"""
    plan, _ = sanitize_plan(
        _plan_data(
            nodes=[
                {
                    "id": "r1",
                    "type": "tool",
                    "tool": "rag_search",
                    "depends_on": ["n9"],
                }
            ]
        ),
        goal="g",
        known_tools=KNOWN_TOOLS,
        known_agents=KNOWN_AGENTS,
        max_nodes=3,
        revision=2,
        allow_external_deps=True,
    )
    assert plan.nodes[0].depends_on == ("n9",)


def test_sanitize_clarification_bounds():
    request = sanitize_clarification(
        {
            "clarification": {
                "question": "选哪个？",
                "options": [f"opt{i}" for i in range(10)],
                "multi_select": True,
            }
        }
    )
    assert request is not None
    assert len(request.options) == 6
    assert request.multi_select
    assert sanitize_clarification({"clarification": {"question": ""}}) is None
    assert sanitize_clarification({}) is None
