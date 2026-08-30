"""Replanner：事件驱动的完整 Plan revision（ADR-0005）。

四类触发（M07 定稿 Q4/Q8）：
- node_failed：节点重试耗尽仍失败；
- observation_insufficient：每层完成后观察不足以达成 goal；
- dependency_invalidated：失败节点存在下游依赖（与 node_failed 同检测点、语义分流）；
- premise_changed：审批被拒、RAG/工具目录运行时不可用。

额度 max_replan 共享防死循环；追加节点 ≤ append_limit；产环即回滚修订。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage

from ..state import NodeOutcome, Plan, RunFailure, RunState
from .dag import observations_text, pending_nodes, validate_plan
from .planner import AgentInfo, ToolInfo, parse_planner_output, sanitize_plan

ReplanTrigger = Literal[
    "node_failed",
    "observation_insufficient",
    "dependency_invalidated",
    "premise_changed",
]

PREMISE_ERROR_CODES = frozenset(
    {"approval_rejected", "rag_unavailable", "tool_catalog_unavailable"}
)

_REPLANNER_PROMPT = (
    "你是重规划器。任务进行中出现新情况，判断是否需要补充执行步骤。只输出 JSON：\n"
    '{"action": "append" | "done" | "give_up",\n'
    ' "nodes": [{"id": "r1", "type": "tool", "tool": "工具名", "agent": null,\n'
    '            "goal": "这一步做什么", "params": {}, "depends_on": ["n1"],\n'
    '            "race_group": null}]}\n'
    "判断规则：\n"
    "1. 已有观察足以完成任务 → action=done，nodes 留空。\n"
    "2. 观察不足或有失败节点需要替代 → action=append（最多 %d 个节点）。\n"
    "3. 无法通过补充步骤完成 → action=give_up。\n"
    "4. 只能使用列出的工具/子 Agent；新节点 depends_on 可指向任何已有节点 id；"
    "不要重复已完成节点做过的事；失败节点优先换工具/换参数替代。\n"
    "5. 参数依赖前序节点运行时输出时，用占位符 {{节点id.字段名}}，"
    "不要凭空猜测运行时才会产生的值。"
)


def detect_trigger(
    plan: Plan, outcomes: tuple[NodeOutcome, ...]
) -> ReplanTrigger | None:
    """判定本次层间决策的触发源。返回 None = 无失败，走观察不足判断。"""
    latest_failures: dict[str, NodeOutcome] = {}
    for item in outcomes:
        if item.outcome == "failed":
            latest_failures[item.node_id] = item
    if not latest_failures:
        return "observation_insufficient"
    for item in latest_failures.values():
        if item.error_code in PREMISE_ERROR_CODES:
            return "premise_changed"
    pending_ids = {node.node_id for node in pending_nodes(plan, outcomes)}
    for node in plan.nodes:
        if node.node_id in pending_ids and any(
            dep in latest_failures for dep in node.depends_on
        ):
            return "dependency_invalidated"
    return "node_failed"


@dataclass(frozen=True)
class _ReplanOutput:
    action: Literal["append", "done", "give_up"]
    plan: Plan | None


def replanner_node(
    *,
    run_id: str,
    model: Any,
    tools: tuple[ToolInfo, ...],
    agents: tuple[AgentInfo, ...],
    publish,
    max_replan: int = 2,
    append_limit: int = 3,
    max_nodes: int = 8,
    mem_prefix: str = "",
) -> Any:
    """构造 LangGraph replanner 节点闭包（每 run 构建一次）。

    mem_prefix：每 run 一次装配的记忆/工具状态前缀（AGI-saber memPrefix
    同构），拼进 LLM 调用的 SystemMessage；HumanMessage（触发原因 + 计划
    快照 + 工具/子 Agent 清单）不动。"" 时与 M07 现状一致。
    """
    known_tools = frozenset(item.name for item in tools)
    known_agents = frozenset(item.name for item in agents)

    async def replanner(state: RunState) -> dict[str, Any]:
        plan = state.get("plan")
        if not isinstance(plan, Plan):
            raise RuntimeError("replanner requires plan in state")
        outcomes = state.get("node_outcomes") or ()
        used = int(state.get("replans_used") or 0)
        remaining = pending_nodes(plan, outcomes)
        has_failures = any(item.outcome == "failed" for item in outcomes)

        # 确定性优先：有剩余节点且无失败 → 直接继续下一层，不消耗 LLM 判断。
        # （层间 LLM 误判 done 会把流水线剩余节点整段跳过——B2 验收实测教训。）
        if remaining and not has_failures:
            return {
                "phase": "replanning",
                "replan_action": "execute",
                "replans_used": used,
            }

        if not remaining:
            # 全部节点已执行：判断观察是否足以达成目标（⑥ 观察不足 → 追加）。
            trigger = "observation_insufficient"
            if used >= max_replan:
                return {
                    "phase": "synthesizing",
                    "replan_action": "generate",
                    "replans_used": used,
                }
        else:
            trigger = detect_trigger(plan, outcomes)
            if used >= max_replan:
                await publish(
                    run_id,
                    "plan.replan_exhausted",
                    trigger=trigger,
                    used=used,
                    max=max_replan,
                )
                return {
                    "phase": "replanning",
                    "replan_action": "give_up",
                    "failure": RunFailure(code="replan_exhausted", message=f"重规划额度已用尽（触发：{trigger}），任务无法继续。", retryable=False),
                    "replans_used": used,
                }

        output = await _ask_replanner(
            model,
            plan,
            outcomes,
            trigger,
            tools,
            agents,
            append_limit,
            known_tools,
            known_agents,
            max_nodes,
            mem_prefix,
        )
        used += 1
        await publish(
            run_id,
            "plan.replan_decision",
            trigger=trigger,
            action=output.action,
            used=used,
            max=max_replan,
        )
        if output.action == "generate":
            return {
                "phase": "synthesizing",
                "replan_action": "generate",
                "replans_used": used,
            }
        if output.action == "give_up":
            return {
                "phase": "replanning",
                "replan_action": "give_up",
                "failure": RunFailure(code="plan_gave_up", message=f"Replanner 判断任务无法完成（触发：{trigger}）。", retryable=False),
                "replans_used": used,
            }
        if output.plan is None:
            # 追加无效且未回滚成原计划：无剩余则合成，否则继续执行。
            action = "generate" if not remaining else "execute"
            return {
                "phase": "replanning" if remaining else "synthesizing",
                "replan_action": action,
                "replans_used": used,
            }
        appended_ids = [
            node.node_id
            for node in output.plan.nodes
            if node.node_id not in {item.node_id for item in plan.nodes}
        ]
        appended_detail = [
            {
                "id": node.node_id,
                "goal": node.objective,
                "tool": node.tool,
                "agent": node.agent_name,
                "depends_on": list(node.depends_on),
                "race_group": node.race_group,
            }
            for node in output.plan.nodes
            if node.node_id not in {item.node_id for item in plan.nodes}
        ]
        await publish(
            run_id,
            "plan.revised",
            revision=output.plan.revision,
            appended=appended_ids,
            appended_nodes=appended_detail,
        )
        return {
            "phase": "replanning",
            "plan": output.plan,
            "replan_action": "execute",
            "replans_used": used,
        }

    return replanner


async def _ask_replanner(
    model: Any,
    plan: Plan,
    outcomes: tuple[NodeOutcome, ...],
    trigger: ReplanTrigger,
    tools: tuple[ToolInfo, ...],
    agents: tuple[AgentInfo, ...],
    append_limit: int,
    known_tools: frozenset[str],
    known_agents: frozenset[str],
    max_nodes: int,
    mem_prefix: str = "",
) -> _ReplanOutput:
    """调 LLM 产出决策；输出无效视为 done（观察足够，去合成）。"""
    done_ids = {item.node_id for item in outcomes if item.outcome == "succeeded"}
    failed_items = [item for item in outcomes if item.outcome == "failed"]
    snapshot_lines = [
        f"- {node.node_id} ({node.tool or node.agent_name}) "
        f"[{'done' if node.node_id in done_ids else 'pending'}]：{node.objective}"
        for node in plan.nodes
    ]
    failure_lines = [
        f"- {item.node_id}: {item.observation[:200]} (code={item.error_code})"
        for item in failed_items
    ]
    prompt_parts = [
        _REPLANNER_PROMPT % append_limit,
        f"触发原因：{trigger}",
        f"当前计划（revision {plan.revision}）：\n" + "\n".join(snapshot_lines),
    ]
    if failure_lines:
        prompt_parts.append("失败节点：\n" + "\n".join(failure_lines))
    prompt_parts.append(f"已有观察：\n{observations_text(outcomes) or '（暂无）'}")
    prompt_parts.append(
        "可用工具：\n"
        + ("\n".join(f"- {item.name}：{item.description}" for item in tools) or "（无）")
    )
    prompt_parts.append(
        "可用子 Agent：\n"
        + ("\n".join(f"- {item.name}：{item.description}" for item in agents) or "（无）")
    )
    prompt_parts.append(f"任务目标：{plan.goal}")
    system = (mem_prefix + "\n\n" if mem_prefix else "") + "你只输出 JSON。"
    messages = (
        SystemMessage(content=system),
        HumanMessage(content="\n\n".join(prompt_parts)),
    )
    try:
        ainvoke = getattr(model, "ainvoke", None)
        if callable(ainvoke):
            response = await ainvoke(messages)
        else:
            import asyncio

            response = await asyncio.to_thread(model.invoke, messages)
        text = getattr(response, "text", None)
        raw = text if isinstance(text, str) and text.strip() else str(getattr(response, "content", ""))
        data = parse_planner_output(raw)
    except Exception:
        return _ReplanOutput(action="generate", plan=None)
    action = str(data.get("action") or "done")
    if action == "give_up":
        return _ReplanOutput(action="give_up", plan=None)
    if action != "append":
        return _ReplanOutput(action="generate", plan=None)
    try:
        appended, _dropped = sanitize_plan(
            data,
            goal=plan.goal,
            known_tools=known_tools,
            known_agents=known_agents,
            max_nodes=min(append_limit, max_nodes),
            revision=plan.revision + 1,
            allow_external_deps=True,
        )
    except (ValueError, KeyError):
        return _ReplanOutput(action="generate", plan=None)
    # 已失败的节点视为"被替代"：排除出剩余集，避免替代节点与失败节点
    # 同时执行（实测：拒绝后的 exec_command 会再次挂起等审批）。
    failed_ids = {
        item.node_id for item in outcomes if item.outcome == "failed"
    }
    surviving = tuple(
        node for node in pending_nodes(plan, outcomes)
        if node.node_id not in failed_ids
    )
    merged = Plan(
        revision=plan.revision + 1,
        goal=plan.goal,
        nodes=surviving + appended.nodes,
    )
    errors = validate_plan(merged, known_tools=known_tools, known_agents=known_agents)
    if errors:
        # 产环或悬空依赖：回滚本次修订，继续执行原计划。
        return _ReplanOutput(action="append", plan=None)
    return _ReplanOutput(action="append", plan=merged)
