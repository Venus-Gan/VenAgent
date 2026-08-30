"""Executor：按 Plan 拓扑分层执行，层内 asyncio 并发 + RaceGroup 竞速。

- 每次图节点执行只跑一层；层间经 Replanner 决策（checkpoint 粒度清晰）；
- 并发由信号量 max_parallel 约束；同 race_group 节点竞速，First-success-wins；
- 工具节点复用 M06 权威链（stage → gateway → 审批 interrupt）；
- 中断恢复时节点从头重跑，幂等性由确定性 tool_call_id + Gateway 去重保证。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from langgraph.errors import GraphBubbleUp

from ..state import NodeOutcome, Plan, PlanNode, RunState
from .dag import ready_layer
from .subagents.base import SubAgentContext, SubAgentRegistry, UpstreamItem

_OBSERVATION_LIMIT = 4000


@dataclass(frozen=True)
class LayerResult:
    outcomes: tuple[NodeOutcome, ...]
    raced: bool = False


class ExecutorDeps:
    """Executor 节点的全部外部依赖（每 run 构建一次闭包）。"""

    def __init__(
        self,
        *,
        run_id: str,
        owner_id: str,
        tool_control: Any,
        registry: SubAgentRegistry,
        publish,
        cancel_event: asyncio.Event | None,
        max_parallel: int = 2,
        race_timeout_ms: int = 30000,
    ) -> None:
        self.run_id = run_id
        self.owner_id = owner_id
        self.tool_control = tool_control
        self.registry = registry
        self.publish = publish
        self.cancel_event = cancel_event
        self.max_parallel = max(1, max_parallel)
        self.race_timeout = race_timeout_ms / 1000.0 if race_timeout_ms > 0 else None


def executor_node(deps: ExecutorDeps) -> Any:
    semaphore = asyncio.Semaphore(deps.max_parallel)

    async def executor(state: RunState) -> dict[str, Any]:
        plan = state.get("plan")
        if not isinstance(plan, Plan):
            raise RuntimeError("executor requires plan in state")
        outcomes = state.get("node_outcomes") or ()
        layer = ready_layer(plan, outcomes)
        if not layer:
            return {"phase": "executing", "replan_action": "generate"}
        await deps.publish(
            deps.run_id,
            "plan.layer_started",
            revision=plan.revision,
            nodes=[node.node_id for node in layer],
        )
        result = await _run_layer(plan, layer, outcomes, deps, semaphore)
        return {
            "phase": "executing",
            "node_outcomes": result.outcomes,
        }

    return executor


async def _run_layer(
    plan: Plan,
    layer: tuple[PlanNode, ...],
    outcomes: tuple[NodeOutcome, ...],
    deps: ExecutorDeps,
    semaphore: asyncio.Semaphore,
) -> LayerResult:
    """一层并发执行：无组节点各自跑，同 race_group 组内竞速。"""
    groups: dict[str, list[PlanNode]] = {}
    singles: list[PlanNode] = []
    for node in layer:
        if node.race_group:
            groups.setdefault(node.race_group, []).append(node)
        else:
            singles.append(node)

    async def guarded(coro):
        async with semaphore:
            return await coro

    tasks: dict[str, asyncio.Task[NodeOutcome]] = {}
    for node in singles:
        tasks[node.node_id] = asyncio.create_task(
            guarded(_run_single(plan, node, outcomes, deps))
        )
    for group_name, members in groups.items():
        tasks[f"race:{group_name}"] = asyncio.create_task(
            guarded(_run_race(plan, group_name, members, outcomes, deps))
        )

    collected: list[NodeOutcome] = []
    wait_results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for value in wait_results:
        if isinstance(value, Exception):
            raise value
        if isinstance(value, NodeOutcome):
            collected.append(value)
        elif isinstance(value, list):
            collected.extend(value)
        elif isinstance(value, tuple) and value and isinstance(value[0], NodeOutcome):
            collected.extend(value)  # type: ignore[arg-type]
    return LayerResult(outcomes=tuple(collected))


def _attempt_of(node_id: str, outcomes: tuple[NodeOutcome, ...]) -> int:
    return sum(1 for item in outcomes if item.node_id == node_id)


async def _run_single(
    plan: Plan,
    node: PlanNode,
    outcomes: tuple[NodeOutcome, ...],
    deps: ExecutorDeps,
) -> NodeOutcome:
    attempt = _attempt_of(node.node_id, outcomes)
    await deps.publish(
        deps.run_id,
        "node.started",
        revision=plan.revision,
        node_id=node.node_id,
        node_type=node.node_type,
        executor=node.tool or node.agent_name,
        goal=node.objective,
    )
    try:
        if node.node_type == "sub_agent":
            outcome = await _run_sub_agent(plan, node, attempt, outcomes, deps)
        else:
            outcome = await _run_tool_node(plan, node, attempt, outcomes, deps)
    except asyncio.CancelledError:
        raise
    except GraphBubbleUp:
        # 审批/澄清等 interrupt 暂停信号必须上抛给 LangGraph，
        # 绝不能被节点失败兜底吞掉（否则拒绝后的重核路径永远走不到）。
        raise
    except Exception as exc:  # noqa: BLE001 - 节点失败即事实，交 Replanner 决策
        outcome = NodeOutcome(
            plan_revision=plan.revision,
            node_id=node.node_id,
            logical_attempt=attempt,
            outcome="failed",
            observation=str(exc)[:_OBSERVATION_LIMIT],
            retryable=False,
            error_code="node_execution_failed",
        )
    await deps.publish(
        deps.run_id,
        "node.completed" if outcome.outcome == "succeeded" else "node.failed",
        revision=plan.revision,
        node_id=node.node_id,
        outcome=outcome.outcome,
        summary=outcome.observation[:300],
        error_code=outcome.error_code,
    )
    return outcome


async def _run_tool_node(
    plan: Plan, node: PlanNode, attempt: int, outcomes: tuple[NodeOutcome, ...], deps: ExecutorDeps
) -> NodeOutcome:
    assert node.tool is not None
    arguments = json.loads(node.arguments_json or "{}")
    if not isinstance(arguments, dict):
        arguments = {}
    arguments = _resolve_params(arguments, outcomes)
    from ...tools.models import ModelToolCall

    call = ModelToolCall(
        id=f"plan-r{plan.revision}-{node.node_id}-a{attempt}",
        name=node.tool,
        arguments=arguments,
    )
    staged = deps.tool_control.stage_tool_call(
        deps.run_id, deps.owner_id, call
    )
    from ...agent.state import PendingToolCallRef

    pending = PendingToolCallRef(
        tool_call_id=staged.tool_call_id,
        operation_key=staged.operation_key,
        tool_id=staged.tool_id,
    )
    result = await deps.tool_control.resume_tool(
        deps.run_id,
        deps.owner_id,
        pending,
        cancel_event=deps.cancel_event,
    )
    while result.status == "awaiting_approval":
        from langgraph.types import interrupt

        interrupt(
            {
                "kind": "approval",
                "approval_id": result.approval_id,
                "run_id": deps.run_id,
                "tool_id": node.tool,
                "tool_call_id": call.id,
            }
        )
        result = await deps.tool_control.resume_tool(
            deps.run_id,
            deps.owner_id,
            pending,
            cancel_event=deps.cancel_event,
        )
    if result.status == "success":
        observation = result.content or result.summary
        return NodeOutcome(
            plan_revision=plan.revision,
            node_id=node.node_id,
            logical_attempt=attempt,
            outcome="succeeded",
            observation=observation[:_OBSERVATION_LIMIT],
            tool_call_id=call.id,
            error_code=None,
        )
    return NodeOutcome(
        plan_revision=plan.revision,
        node_id=node.node_id,
        logical_attempt=attempt,
        outcome="failed",
        observation=result.summary or "工具执行失败",
        retryable=False,
        tool_call_id=call.id,
        error_code=result.error or "tool_execution_failed",
    )


async def _run_sub_agent(
    plan: Plan,
    node: PlanNode,
    attempt: int,
    outcomes: tuple[NodeOutcome, ...],
    deps: ExecutorDeps,
) -> NodeOutcome:
    agent = deps.registry.get(node.agent_name or "")
    if agent is None:
        raise RuntimeError(f"sub agent not registered: {node.agent_name}")
    upstream = _upstream_results(node, outcomes)
    context = SubAgentContext(
        run_id=deps.run_id,
        owner_id=deps.owner_id,
        plan_revision=plan.revision,
        node_id=node.node_id,
        attempt=attempt,
        goal=node.objective,
        upstream=upstream,
        tool_control=deps.tool_control,
        publish=deps.publish,
        cancel_event=deps.cancel_event,
    )
    result = await agent.run(context)
    return NodeOutcome(
        plan_revision=plan.revision,
        node_id=node.node_id,
        logical_attempt=attempt,
        outcome="succeeded" if result.success else "failed",
        observation=result.content[:_OBSERVATION_LIMIT],
        tool_call_id=node.agent_name,
        error_code=result.error_code,
    )


def _upstream_results(
    node: PlanNode, outcomes: tuple[NodeOutcome, ...]
) -> tuple[UpstreamItem, ...]:
    """上游产物列表，供子 Agent 识别哪个结果是正文、哪个是审查意见。"""
    latest: dict[str, NodeOutcome] = {}
    for item in outcomes:
        if item.outcome == "succeeded":
            latest[item.node_id] = item
    return tuple(
        UpstreamItem(
            node_id=dep,
            executor=latest[dep].tool_call_id or dep,
            observation=latest[dep].observation[:2000],
        )
        for dep in node.depends_on
        if dep in latest
    )


_PARAM_REF_PATTERN = r"^\{\{\s*([A-Za-z0-9_\-]+)(?:\.([A-Za-z0-9_\-]+))?\s*\}\}$"
# 无字段名的 {{node}} 形式取上游观察全文（文本型工具输出）。


def _resolve_params(
    arguments: dict[str, Any], outcomes: tuple[NodeOutcome, ...]
) -> dict[str, Any]:
    """解析 {{node_id.field}} 运行时占位符（XCom 风格）。

    上游成功节点的 observation 是工具返回的 JSON（rag_search/write_document
    等结构化工具）；解析后取字段值填入参数。解析失败抛 ValueError，由
    节点失败路径记录为明确错误（planner 不该猜运行时值）。
    """
    import re

    succeeded: dict[str, str] = {
        item.node_id: item.observation
        for item in outcomes
        if item.outcome == "succeeded"
    }
    resolved: dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(value, str):
            match = re.match(_PARAM_REF_PATTERN, value.strip())
            if match:
                node_id, field = match.group(1), match.group(2)
                if node_id not in succeeded:
                    raise ValueError(
                        "参数占位符的上游节点 %s 尚未成功执行" % node_id
                    )
                observation = succeeded[node_id]
                try:
                    payload = json.loads(observation)
                except json.JSONDecodeError:
                    payload = None
                if payload is None or not isinstance(payload, dict):
                    # 文本型工具（如 exec_command）的观察不是 JSON：
                    # {{node}} 与 {{node.field}} 都降级为观察全文。
                    resolved[key] = observation
                    continue
                if not field:
                    resolved[key] = observation
                    continue
                if field not in payload:
                    raise ValueError(
                        f"上游节点 {node_id} 的观察缺少字段 {field}"
                    )
                resolved[key] = payload[field]
                continue
        resolved[key] = value
    return resolved


async def _run_race(
    plan: Plan,
    group_name: str,
    members: list[PlanNode],
    outcomes: tuple[NodeOutcome, ...],
    deps: ExecutorDeps,
) -> list[NodeOutcome]:
    """竞速组：谁先返回非错误结果谁胜出，其余取消记 skipped。"""
    attempts = {
        node.node_id: _attempt_of(node.node_id, outcomes) for node in members
    }
    tasks = {
        node.node_id: asyncio.create_task(_run_single(plan, node, outcomes, deps))
        for node in members
    }
    timeout = deps.race_timeout
    deadline = (
        asyncio.get_running_loop().time() + timeout if timeout is not None else None
    )
    pending: set[asyncio.Task[NodeOutcome]] = set(tasks.values())
    done: set[asyncio.Task[NodeOutcome]] = set()

    winner: NodeOutcome | None = None
    while pending:
        remaining_budget = (
            None if deadline is None else max(deadline - asyncio.get_running_loop().time(), 0.01)
        )
        try:
            finished, pending = await asyncio.wait(
                pending,
                timeout=remaining_budget,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError:
            for task in pending:
                task.cancel()
            raise
        done |= finished
        for task in finished:
            outcome = task.result()
            if outcome.outcome == "succeeded":
                winner = outcome
                break
        if winner is not None:
            break
        if deadline is not None and asyncio.get_running_loop().time() >= deadline:
            break

    if winner is not None:
        await deps.publish(
            deps.run_id,
            "race.won",
            group=group_name,
            winner=winner.node_id,
        )
        loser_ids = [node_id for node_id in tasks if node_id != winner.node_id]
    else:
        loser_ids = []

    remaining = [task for node_id, task in tasks.items() if node_id in loser_ids]
    for task in remaining:
        task.cancel()
    if remaining:
        await asyncio.gather(*remaining, return_exceptions=True)

    if winner is not None:
        results: list[NodeOutcome] = [winner]
        for node_id in loser_ids:
            await deps.publish(
                deps.run_id,
                "node.skipped",
                revision=plan.revision,
                node_id=node_id,
                group=group_name,
                winner=winner.node_id,
            )
            results.append(
                NodeOutcome(
                    plan_revision=plan.revision,
                    node_id=node_id,
                    logical_attempt=attempts[node_id],
                    outcome="skipped",
                    observation="竞速落败，结果弃用。",
                )
            )
        return results

    # 全部失败 / 超时：收集已完成任务的失败事实，未完成的标 failed。
    results = []
    for node_id, task in tasks.items():
        if task in done:
            results.append(task.result())
        else:
            results.append(
                NodeOutcome(
                    plan_revision=plan.revision,
                    node_id=node_id,
                    logical_attempt=attempts[node_id],
                    outcome="failed",
                    observation="竞速组超时或全部失败。",
                    error_code="race_timeout",
                )
            )
    return results
