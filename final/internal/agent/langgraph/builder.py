from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from inspect import Parameter, signature
from typing import Any, Callable, Mapping

from internal.graph.task_graph import TaskGraph

from .nodes import make_react_node
from .state import ReactState, initial_react_state, merge_react_state

START = "__start__"
END = "__end__"

NodeFn = Callable[..., Mapping[str, Any] | None]
RouterFn = Callable[[Mapping[str, Any]], Any]


@dataclass(frozen=True)
class _ConditionalEdge:
    router: RouterFn
    path_map: Any


@dataclass
class CompiledStateGraph:
    nodes: dict[str, NodeFn]
    static_edges: dict[str, list[str]]
    conditional_edges: dict[str, _ConditionalEdge]
    start_targets: list[str]
    predecessor_counts: dict[str, int]

    def invoke(self, state: Mapping[str, Any] | None, config: Any | None = None) -> ReactState:
        working_state: ReactState = (
            initial_react_state(str((state or {}).get("query", "")))
            if state is None
            else dict(state)  # type: ignore[assignment]
        )
        if state is not None:
            working_state = dict(state)  # type: ignore[assignment]

        remaining = dict(self.predecessor_counts)
        ready: deque[str] = deque()
        queued: set[str] = set()
        executed: set[str] = set()

        initial_targets = self.start_targets or sorted(
            node_id for node_id, count in remaining.items() if count == 0
        )
        for node_id in initial_targets:
            if node_id in self.nodes and node_id not in queued and node_id not in executed:
                ready.append(node_id)
                queued.add(node_id)

        while ready:
            node_id = ready.popleft()
            queued.discard(node_id)
            if node_id in executed or node_id == END:
                continue

            runner = self.nodes[node_id]
            update = _call_node(runner, working_state, config)
            if update is None:
                update = {}
            if not isinstance(update, Mapping):
                raise TypeError(f"node {node_id!r} must return a mapping or None")
            working_state = merge_react_state(working_state, update)
            executed.add(node_id)

            next_targets = list(self.static_edges.get(node_id, []))
            conditional = self.conditional_edges.get(node_id)
            if conditional is not None:
                route_value = conditional.router(working_state)
                next_targets.extend(_resolve_targets(conditional.path_map, route_value))

            for target in next_targets:
                if target in (START, END) or target not in self.nodes:
                    continue
                remaining[target] = remaining.get(target, 0) - 1
                if remaining[target] <= 0 and target not in executed and target not in queued:
                    ready.append(target)
                    queued.add(target)

        return working_state


@dataclass
class StateGraph:
    schema: Any | None = None
    nodes: dict[str, NodeFn] = field(default_factory=dict)
    static_edges: dict[str, list[str]] = field(default_factory=dict)
    conditional_edges: dict[str, _ConditionalEdge] = field(default_factory=dict)

    def add_node(self, name: str, func: NodeFn, ends: Any = None, **_kwargs: Any) -> "StateGraph":
        self.nodes[name] = func
        if ends is not None:
            _ = _normalize_ends(ends)
        return self

    def add_edge(self, source: str, target: str) -> "StateGraph":
        self.static_edges.setdefault(source, []).append(target)
        return self

    def add_conditional_edges(
        self,
        source: str,
        router: RouterFn,
        path_map: Any = None,
    ) -> "StateGraph":
        self.conditional_edges[source] = _ConditionalEdge(router=router, path_map=path_map)
        return self

    def compile(self, *_args: Any, **_kwargs: Any) -> CompiledStateGraph:
        self._validate()
        return CompiledStateGraph(
            nodes=dict(self.nodes),
            static_edges={source: list(targets) for source, targets in self.static_edges.items()},
            conditional_edges=dict(self.conditional_edges),
            start_targets=list(self.static_edges.get(START, [])),
            predecessor_counts=self._predecessor_counts(),
        )

    def _predecessor_counts(self) -> dict[str, int]:
        counts = {node_id: 0 for node_id in self.nodes}
        for source, targets in self.static_edges.items():
            if source == END:
                continue
            for target in targets:
                if target in (START, END) or target not in counts:
                    continue
                counts[target] += 1
        return counts

    def _validate(self) -> None:
        missing = [node_id for node_id in self.static_edges.get(START, []) if node_id not in self.nodes]
        if missing:
            raise ValueError(f"missing start nodes: {', '.join(sorted(missing))}")

        for source, targets in self.static_edges.items():
            if source not in self.nodes and source not in {START, END}:
                raise ValueError(f"missing source node {source!r}")
            for target in targets:
                if target not in self.nodes and target not in {START, END}:
                    raise ValueError(f"missing target node {target!r}")

        for source, conditional in self.conditional_edges.items():
            if source not in self.nodes and source not in {START, END}:
                raise ValueError(f"missing conditional source node {source!r}")
            _validate_path_map(conditional.path_map, self.nodes)


def build_react_graph(
    task_graph: TaskGraph,
    node_factory: Callable[[Any], Callable[[Mapping[str, Any]], Mapping[str, Any] | None]] | None = None,
) -> CompiledStateGraph:
    """Compile a task graph into a runnable react StateGraph."""

    task_graph.validate()
    graph = StateGraph()
    factory = node_factory or make_react_node

    for node_id in sorted(task_graph.nodes):
        node = task_graph.nodes[node_id]
        graph.add_node(node.id, factory(node))

    roots = sorted(node_id for node_id, node in task_graph.nodes.items() if not node.depends_on)
    for root in roots:
        graph.add_edge(START, root)

    for node in task_graph.nodes.values():
        for dep in sorted(node.depends_on or []):
            graph.add_edge(dep, node.id)
        if not task_graph.adj.get(node.id):
            graph.add_edge(node.id, END)

    return graph.compile()


def _call_node(func: NodeFn, state: Mapping[str, Any], config: Any | None) -> Any:
    try:
        sig = signature(func)
    except (TypeError, ValueError):
        return func(state, config)

    positional = [
        param
        for param in sig.parameters.values()
        if param.kind in {Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD}
    ]
    if any(param.kind == Parameter.VAR_POSITIONAL for param in sig.parameters.values()) or len(positional) >= 2:
        return func(state, config)
    return func(state)


def _normalize_ends(ends: Any) -> list[str]:
    if ends is None:
        return []
    if isinstance(ends, dict):
        value = ends.get("ends", [])
        return list(value) if isinstance(value, (list, tuple, set)) else [str(value)]
    if isinstance(ends, (list, tuple, set)):
        return [str(item) for item in ends]
    return [str(ends)]


def _resolve_targets(path_map: Any, route_value: Any) -> list[str]:
    if route_value is None:
        return []
    if isinstance(route_value, (list, tuple, set)):
        routes = list(route_value)
    else:
        routes = [route_value]

    resolved: list[str] = []
    if isinstance(path_map, dict):
        for route in routes:
            target = path_map.get(route, route)
            resolved.extend(_normalize_route_target(target))
        return resolved

    allowed = set(_normalize_ends(path_map)) if path_map is not None else set()
    for route in routes:
        if not allowed or str(route) in allowed:
            resolved.extend(_normalize_route_target(route))
    return resolved


def _normalize_route_target(target: Any) -> list[str]:
    if target is None:
        return []
    if isinstance(target, (list, tuple, set)):
        return [str(item) for item in target]
    return [str(target)]


def _validate_path_map(path_map: Any, nodes: Mapping[str, NodeFn]) -> None:
    if path_map is None:
        return
    if isinstance(path_map, dict):
        values = path_map.values()
    elif isinstance(path_map, (list, tuple, set)):
        values = path_map
    else:
        values = [path_map]

    for value in values:
        for target in _normalize_route_target(value):
            if target in {START, END}:
                continue
            if target not in nodes:
                raise ValueError(f"missing conditional target node {target!r}")
