from __future__ import annotations

from typing import Any, Callable, Mapping

from internal.graph.task_graph import Node

NodeFactory = Callable[[Node], Callable[[Mapping[str, Any]], Mapping[str, Any] | None]]


def default_react_node_factory(node: Node) -> Callable[[Mapping[str, Any]], Mapping[str, Any]]:
    """Fallback node factory for task graph nodes.

    The planner-facing card still allows callers to inject a custom factory,
    but the default keeps the graph runnable for the simplest cases.
    """

    def runner(_state: Mapping[str, Any]) -> Mapping[str, Any]:
        label = node.tool_name or node.name or node.id
        return {
            "steps": [{"id": node.id, "type": node.type.value}],
            "results": [label],
            "events": [{"type": node.id, "node": node.id}],
        }

    return runner


def make_react_node(
    node: Node,
    node_factory: NodeFactory | None = None,
) -> Callable[[Mapping[str, Any]], Mapping[str, Any]]:
    """Wrap a task graph node into a partial-update node function."""

    factory = node_factory or default_react_node_factory
    runner = factory(node)
    if not callable(runner):
        raise TypeError("node_factory must return a callable")

    def wrapped(state: Mapping[str, Any]) -> Mapping[str, Any]:
        update = runner(state)
        if update is None:
            return {}
        if not isinstance(update, Mapping):
            raise TypeError("react nodes must return a mapping of partial updates")
        return dict(update)

    return wrapped
