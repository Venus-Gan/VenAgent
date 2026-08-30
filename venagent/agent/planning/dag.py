"""计划 DAG 纯函数：就绪分层、跨 revision 依赖解析与校验。

Plan 是数据（LLM 运行时产出），本模块不持有任何 IO；Executor/Replanner
都通过这里解释"哪些节点现在可执行"。依赖可以指向：
- 当前 Plan 内的节点（须已 succeeded）；
- 历史 revision 的节点（在 node_outcomes 里有 succeeded 记录）——
  这就是"完整 Plan revision 只含剩余节点"语义的对接点。
"""

from __future__ import annotations

from ..state import NodeOutcome, Plan, PlanNode

SUCCEEDED = "succeeded"


def succeeded_ids(outcomes: tuple[NodeOutcome, ...]) -> frozenset[str]:
    """全部 revision 中成功过的节点 id 集合（Generator 观察来源）。"""
    return frozenset(
        item.node_id for item in outcomes if item.outcome == SUCCEEDED
    )


def resolved_ids(outcomes: tuple[NodeOutcome, ...]) -> frozenset[str]:
    """依赖满足集合：succeeded ∪ skipped（竞速败者不阻塞下游，但无观察产物）。"""
    return frozenset(
        item.node_id
        for item in outcomes
        if item.outcome in (SUCCEEDED, "skipped")
    )


def failed_node_ids(outcomes: tuple[NodeOutcome, ...]) -> frozenset[str]:
    """当前 Plan 各节点是否存在失败事实（供 Replanner 判定触发源）。"""
    return frozenset(
        item.node_id for item in outcomes if item.outcome == "failed"
    )


def is_pending(node: PlanNode, done: frozenset[str]) -> bool:
    return node.node_id not in done


def dependencies_satisfied(
    node: PlanNode, done: frozenset[str], known: frozenset[str]
) -> bool:
    """依赖全部解决（成功或竞速跳过）才算就绪；引用未知节点视为永不就绪。"""
    return all(dep in done for dep in node.depends_on) and all(
        dep in known for dep in node.depends_on
    )


def unresolvable_dependencies(
    nodes: tuple[PlanNode, ...], done: frozenset[str]
) -> tuple[str, ...]:
    """校验用：depends_on 指向计划内外都不存在的节点。"""
    known = frozenset(item.node_id for item in nodes) | done
    return tuple(
        f"{node.node_id}:{dep}"
        for node in nodes
        for dep in node.depends_on
        if dep not in known
    )


def ready_layer(
    plan: Plan, outcomes: tuple[NodeOutcome, ...]
) -> tuple[PlanNode, ...]:
    """当前可并行执行的一层：pending 且依赖全部满足。

    每次只返回一层（而不是预分层全集）——Executor 每次图节点执行跑一层，
    层间经 Replanner 决策，保证 checkpoint 粒度与审批暂停边界清晰。
    """
    done = resolved_ids(outcomes)
    known = frozenset(item.node_id for item in plan.nodes) | done
    return tuple(
        node
        for node in plan.nodes
        if is_pending(node, done)
        and dependencies_satisfied(node, done, known)
    )


def pending_nodes(
    plan: Plan, outcomes: tuple[NodeOutcome, ...]
) -> tuple[PlanNode, ...]:
    """剩余节点：succeeded/skipped 均为终态（与 ready_layer 的 resolved 口径一致）。

    口径必须与 ready_layer 一致——否则竞速败者会永远被当作"剩余待办"，
    replanner 确定性继续与空层 executor 互相空转直到图递归上限（实测 bug）。
    """
    done = resolved_ids(outcomes)
    return tuple(node for node in plan.nodes if is_pending(node, done))


def validate_plan(plan: Plan, *, known_tools: frozenset[str], known_agents: frozenset[str]) -> tuple[str, ...]:
    """结构校验：空计划 / 未知依赖 / 环 / 白名单。返回错误列表（空 = 合法）。"""
    errors: list[str] = []
    if not plan.nodes:
        errors.append("plan_empty")
    ids = [node.node_id for node in plan.nodes]
    if len(ids) != len(set(ids)):
        errors.append("duplicate_node_id")
    known_ids = set(ids)
    for node in plan.nodes:
        for dep in node.depends_on:
            if dep not in known_ids and dep not in {""}:
                errors.append(f"unknown_dependency:{node.node_id}:{dep}")
        if node.node_id in node.depends_on:
            errors.append(f"self_dependency:{node.node_id}")
        if node.node_type == "tool" and node.tool not in known_tools:
            errors.append(f"unknown_tool:{node.node_id}:{node.tool}")
        if node.node_type == "sub_agent" and node.agent_name not in known_agents:
            errors.append(f"unknown_agent:{node.node_id}:{node.agent_name}")
    if _has_cycle(plan.nodes):
        errors.append("plan_cycle")
    return tuple(errors)


def _has_cycle(nodes: tuple[PlanNode, ...]) -> bool:
    """Kahn 环检测：无法被拓扑消尽的图即有环。"""
    indegree = {node.node_id: 0 for node in nodes}
    edges: dict[str, list[str]] = {node.node_id: [] for node in nodes}
    for node in nodes:
        for dep in node.depends_on:
            if dep in indegree and dep != node.node_id:
                edges[dep].append(node.node_id)
                indegree[node.node_id] += 1
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    processed = 0
    while queue:
        current = queue.pop()
        processed += 1
        for downstream in edges[current]:
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                queue.append(downstream)
    return processed != len(nodes)


def observations_text(outcomes: tuple[NodeOutcome, ...], *, limit: int = 400) -> str:
    """把成功节点的观察压成 Replanner/Generator 可读的编号列表。"""
    lines = []
    for item in outcomes:
        if item.outcome != SUCCEEDED:
            continue
        executor = item.tool_call_id or item.node_id
        text = item.observation[:limit]
        lines.append(f"[{item.node_id} | {executor}] {text}")
    return "\n".join(lines)
