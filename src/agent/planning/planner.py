"""Planner：LLM 运行时产出计划（运行时 DAG，非编译期图）。

三档输出：plan（节点 DAG）/ clarify（结构化反问）/ direct（回落基线图）。
输出清洗与白名单校验对标 AGI-saber plan_graph 的降级链：
工具必须在 run 快照内、子 Agent 必须已注册、依赖必须可解析、有环即整体降级。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ..state import (
    ClarificationAnswer,
    ClarificationRequest,
    Plan,
    PlanNode,
    RunState,
    TaskInput,
)
from .dag import validate_plan

_MAX_CLARIFICATION_OPTIONS = 6
_MAX_OPTION_LENGTH = 120
_MAX_GOAL_LENGTH = 300

_PLANNER_SYSTEM_PROMPT = (
    "你是任务规划器。判断任务并把复合任务拆成节点 DAG，只输出 JSON：\n"
    '{"action": "plan" | "clarify" | "direct",\n'
    ' "nodes": [{"id": "n1", "type": "tool" | "sub_agent", "tool": "工具名",\n'
    '            "agent": "子Agent名", "goal": "这一步做什么",\n'
    '            "params": {}, "depends_on": [], "race_group": null}],\n'
    ' "clarification": {"question": "...", "options": ["..."],\n'
    '                   "multi_select": false}}\n'
    "规则：\n"
    "1. 单步能完成 → action=direct，不要规划。\n"
    "2. 缺关键信息且无法合理假设 → action=clarify，给出问题与候选项。\n"
    "3. 只能使用列出的工具/子 Agent，params 必须匹配其参数 schema。\n"
    "4. B 节点依赖 A 的输出 → depends_on: [\"nA\"]；无依赖 → []。\n"
    "5. 同类可替换的工具（如本地检索与外部检索）设相同 race_group 竞速。"
    "竞速组之后只规划一个汇总/加工节点，其 depends_on 指向竞速组的全部成员；"
    "不要为每个竞速成员各配一个汇总节点。\n"
    "6. id 用 n1、n2… 唯一命名；节点总数尽量少。\n"
    "7. 后续节点的参数若依赖前序节点的运行时输出，用占位符 {{节点id.字段名}}"
    "（例如 read_document 的 document_id 填 \"{{n1.document_id}}\"）；"
    "不要凭空猜测运行时才会产生的值。\n"
    "8. 研究/调研/总结/报告/方案/分析类复合任务：使用子 Agent 流水线"
    "research_agent（检索调研）→ writer_agent（成文）→ review_agent（审查）"
    "→ doc_agent（落库保存）；用户要求保存/落库/写报告到文档库时必须包含 "
    "doc_agent 节点，且其 depends_on 指向 writer 节点；不要用普通工具节点"
    "替代这条流水线。"
)


@dataclass(frozen=True)
class ToolInfo:
    """暴露给 Planner 的工具清单条目（来自 run 快照，不含执行体）。"""

    name: str
    description: str
    parameters_json: str


@dataclass(frozen=True)
class AgentInfo:
    name: str
    description: str


def _tool_catalog_text(tools: tuple[ToolInfo, ...]) -> str:
    if not tools:
        return "（当前无可用工具）"
    return "\n".join(
        f"- {item.name}：{item.description} 参数：{item.parameters_json}"
        for item in tools
    )


def _agent_catalog_text(agents: tuple[AgentInfo, ...]) -> str:
    if not agents:
        return "（无子 Agent 可用；type 只能是 tool）"
    return "\n".join(
        f"- {item.name}：{item.description}" for item in agents
    )


def _clarification_supplement(answer: ClarificationAnswer | None) -> str:
    if answer is None:
        return ""
    return f"\n\n{answer.as_text()}"


def parse_planner_output(raw: str) -> dict[str, Any]:
    """从模型输出提取 JSON 对象（剥 ```json 围栏 / 前后噪声）。"""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match is None:
        raise ValueError("planner output contains no json object")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("planner output is not an object")
    return data


def sanitize_plan(
    data: dict[str, Any],
    *,
    goal: str,
    known_tools: frozenset[str],
    known_agents: frozenset[str],
    max_nodes: int,
    revision: int = 1,
    allow_external_deps: bool = False,
) -> tuple[Plan, tuple[str, ...]]:
    """白名单过滤 + 结构校验；返回（计划, 丢弃原因列表）。空计划抛 ValueError。

    allow_external_deps=True 时跳过计划内依赖校验（Replanner 追加节点可依赖
    原计划节点）；完整计划（剩余+追加）的合并校验由调用方负责。
    """
    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list):
        raise ValueError("planner output missing nodes")
    dropped: list[str] = []
    seen: set[str] = set()
    nodes: list[PlanNode] = []
    for index, raw in enumerate(raw_nodes[: max_nodes * 2]):
        if not isinstance(raw, dict) or len(nodes) >= max_nodes:
            dropped.append(f"n{index + 1}:over_limit_or_invalid")
            continue
        node_id = str(raw.get("id") or f"n{len(nodes) + 1}").strip() or f"n{len(nodes) + 1}"
        if node_id in seen:
            dropped.append(f"{node_id}:duplicate_id")
            continue
        node_type = str(raw.get("type") or "tool").strip()
        tool = raw.get("tool")
        agent = raw.get("agent")
        if node_type == "sub_agent":
            if not isinstance(agent, str) or agent not in known_agents:
                dropped.append(f"{node_id}:unknown_agent")
                continue
            tool = None
        else:
            node_type = "tool"
            if not isinstance(tool, str) or tool not in known_tools:
                dropped.append(f"{node_id}:unknown_tool:{tool}")
                continue
            agent = None
        depends = raw.get("depends_on") or []
        if not isinstance(depends, list):
            depends = []
        depends_on = tuple(
            str(item) for item in depends if isinstance(item, str) and item
        )
        goal = str(raw.get("goal") or raw.get("objective") or node_type)[:_MAX_GOAL_LENGTH]
        params = raw.get("params") or raw.get("arguments") or {}
        if not isinstance(params, dict):
            params = {}
        seen.add(node_id)
        nodes.append(
            PlanNode(
                node_id=node_id,
                objective=goal,
                node_type=node_type,
                tool=tool,
                agent_name=agent,
                arguments_json=json.dumps(params, ensure_ascii=False),
                depends_on=depends_on,
                race_group=(
                    str(raw["race_group"]) if isinstance(raw.get("race_group"), str) else None
                ),
            )
        )
    plan = Plan(revision=revision, goal=goal[:_MAX_GOAL_LENGTH], nodes=tuple(nodes))
    if allow_external_deps:
        # 仅查环与重复；跨计划依赖的合法性由合并后的完整计划校验。
        from .dag import _has_cycle

        if _has_cycle(plan.nodes):
            raise ValueError("plan invalid: plan_cycle")
        if not nodes:
            raise ValueError("plan invalid: plan_empty")
    else:
        errors = validate_plan(
            plan,
            known_tools=known_tools,
            known_agents=known_agents,
        )
        if errors or not nodes:
            raise ValueError("plan invalid: " + ",".join(errors))
    return plan, tuple(dropped)


def sanitize_clarification(data: dict[str, Any]) -> ClarificationRequest | None:
    raw = data.get("clarification")
    if not isinstance(raw, dict):
        return None
    question = str(raw.get("question") or "").strip()
    if not question:
        return None
    options_raw = raw.get("options") or []
    if not isinstance(options_raw, list):
        options_raw = []
    options = tuple(
        str(item)[:_MAX_OPTION_LENGTH]
        for item in options_raw
        if isinstance(item, (str, int, float)) and str(item).strip()
    )[:_MAX_CLARIFICATION_OPTIONS]
    return ClarificationRequest(
        question=question[:500],
        options=options,
        multi_select=bool(raw.get("multi_select")),
        allow_custom=True,
        allow_skip=True,
    )


def planner_node(
    *,
    run_id: str,
    model: Any,
    tools: tuple[ToolInfo, ...],
    agents: tuple[AgentInfo, ...],
    publish,
    max_nodes: int = 8,
    mem_prefix: str = "",
) -> Any:
    """构造 LangGraph planner 节点闭包。

    澄清 interrupt 就地发生在节点内：interrupt() 返回用户答案后带上补充
    重新规划（一次澄清预算；再次不足则按现有信息尽力规划）。

    mem_prefix：每 run 一次装配的记忆/工具状态前缀（AGI-saber memPrefix
    同构），拼进 LLM 调用的 SystemMessage；HumanMessage（任务规则 + 工具
    清单 + 子 Agent 注册表）不动。"" 时与 M07 现状一致。
    """
    known_tools = frozenset(item.name for item in tools)
    known_agents = frozenset(item.name for item in agents)

    async def planner(state: RunState) -> dict[str, Any]:
        task_input = state.get("task_input")
        if not isinstance(task_input, TaskInput):
            raise RuntimeError("run is missing task input")
        answer = state.get("clarification_answer")
        task_text = task_input.content + _clarification_supplement(answer)
        await publish(run_id, "plan.planning_started", task_chars=len(task_text))
        data = await _plan_once(model, task_text, tools, agents, mem_prefix)
        action = str(data.get("action") or "direct")

        if action == "clarify" and answer is None:
            request = sanitize_clarification(data)
            if request is not None:
                await publish(
                    run_id,
                    "clarification.requested",
                    question=request.question,
                    options=list(request.options),
                    multi_select=request.multi_select,
                )
                user_answer: Any = interrupt_clarification(request)
                # 恢复后带答案重新规划一次；此时不再澄清（防止循环）。
                revised_text = task_text + _clarification_supplement(user_answer)
                data = await _plan_once(model, revised_text, tools, agents, mem_prefix)
                action = str(data.get("action") or "direct")

        if action == "plan":
            try:
                plan, dropped = sanitize_plan(
                    data,
                    goal=task_text,
                    known_tools=known_tools,
                    known_agents=known_agents,
                    max_nodes=max_nodes,
                )
            except ValueError as exc:
                await publish(
                    run_id,
                    "plan.degraded",
                    reason="planner_output_invalid",
                    detail=str(exc)[:200],
                )
                return {"phase": "selecting_tools", "plan": None}
            if dropped:
                await publish(run_id, "plan.nodes_dropped", items=list(dropped))
            await publish(
                run_id,
                "plan.created",
                revision=plan.revision,
                nodes=[
                    {
                        "id": node.node_id,
                        "type": node.node_type,
                        "tool": node.tool,
                        "agent": node.agent_name,
                        "goal": node.objective,
                        "depends_on": list(node.depends_on),
                        "race_group": node.race_group,
                    }
                    for node in plan.nodes
                ],
            )
            return {"phase": "planning", "plan": plan}
        return {"phase": "selecting_tools", "plan": None}

    return planner


async def _plan_once(
    model: Any,
    task_text: str,
    tools: tuple[ToolInfo, ...],
    agents: tuple[AgentInfo, ...],
    mem_prefix: str = "",
) -> dict[str, Any]:
    prompt = (
        f"{_PLANNER_SYSTEM_PROMPT}\n\n可用工具：\n{_tool_catalog_text(tools)}\n\n"
        f"可用子 Agent：\n{_agent_catalog_text(agents)}\n\n任务：{task_text}"
    )
    raw = await _invoke(model, prompt, system_prefix=mem_prefix)
    try:
        return parse_planner_output(raw)
    except (ValueError, json.JSONDecodeError):
        # 单次重试：把坏输出连同修正要求再给一次。
        retry_prompt = (
            f"{prompt}\n\n你上一次的输出不是合法 JSON（片段：{raw[:200]}）。"
            "请重新只输出一个合法 JSON 对象。"
        )
        raw = await _invoke(model, retry_prompt, system_prefix=mem_prefix)
        return parse_planner_output(raw)


async def _invoke(model: Any, prompt: str, system_prefix: str = "") -> str:
    system = (system_prefix + "\n\n" if system_prefix else "") + "你只输出 JSON。"
    messages = (SystemMessage(content=system), HumanMessage(content=prompt))
    ainvoke = getattr(model, "ainvoke", None)
    if callable(ainvoke):
        response = await ainvoke(messages)
    else:
        import asyncio

        response = await asyncio.to_thread(model.invoke, messages)
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    content = getattr(response, "content", None)
    return content if isinstance(content, str) else str(response)


def interrupt_clarification(request: ClarificationRequest) -> ClarificationAnswer:
    """在 planner 节点内暂停等待用户答复（与审批 interrupt 同机制）。"""
    from langgraph.types import interrupt

    answer = interrupt(
        {
            "kind": "clarification",
            "question": request.question,
            "options": list(request.options),
            "multi_select": request.multi_select,
            "allow_custom": request.allow_custom,
            "allow_skip": request.allow_skip,
        }
    )
    if isinstance(answer, ClarificationAnswer):
        return answer
    if isinstance(answer, dict):
        return ClarificationAnswer(
            selected=tuple(str(item) for item in answer.get("selected", ()) or ()),
            custom=answer.get("custom") if isinstance(answer.get("custom"), str) else None,
            skipped=bool(answer.get("skipped")),
        )
    return ClarificationAnswer(skipped=True)
