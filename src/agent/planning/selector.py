"""Selector：编排层第一步意图分发（ADR-0007）。

规则只承担两件已存在的事——`/plan` 显式命令与命令旁路（后者在 HTTP 层，
不进 run）——其余交给一次轻量结构化模型分类（react / rag / direct 三选一）。
不新造关键词规则表（AGI-saber infra_router 死代码教训）。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage

from ..state import RunState, TaskInput

Branch = Literal["react", "rag", "baseline"]

_CLASSIFY_PROMPT = (
    "你是意图分类器。根据用户任务选择执行分支，只输出 JSON：\n"
    '{"branch": "react" | "rag" | "direct"}\n'
    "- react：需要多步推理、多个工具协作、或先调研再产出的复合任务。\n"
    "- rag：明确的知识库/文档检索问题（答案大概率在私有知识库里）。\n"
    "- direct：闲聊、单步问答、或单个简单工具就能完成的任务。\n"
    "只输出 JSON，不要输出其他内容。"
)


def task_without_plan_prefix(content: str) -> tuple[str, bool]:
    """解析 /plan 显式命令前缀；返回（正文, 是否计划模式）。"""
    stripped = content.strip()
    if stripped == "/plan":
        return "", True
    if stripped.startswith("/plan "):
        return stripped[len("/plan "):].strip(), True
    return content, False


def select_branch_sync(task_input: TaskInput, rag_loaded: bool) -> Branch | None:
    """确定性 fast-path：/plan 显式命令直接进 react。None = 需要模型判断。"""
    if task_input.plan_mode:
        return "react"
    return None


async def select_branch(
    run_id: str,
    task_input: TaskInput,
    *,
    model: Any,
    rag_loaded: bool,
    publish,
) -> Branch:
    """Selector 节点主体：fast-path → 一次结构化模型分类 → 兜底 baseline。"""
    fast = select_branch_sync(task_input, rag_loaded)
    if fast is not None:
        await publish(run_id, "route.selected", branch=fast, reason="plan_mode")
        return fast
    branch = await _classify(model, task_input.content, rag_loaded)
    await publish(run_id, "route.selected", branch=branch, reason="model")
    return branch


async def _classify(model: Any, content: str, rag_loaded: bool) -> Branch:
    allowed: list[str] = ["react", "direct"] if not rag_loaded else [
        "react",
        "rag",
        "direct",
    ]
    try:
        raw = await _invoke_model(model, _CLASSIFY_PROMPT, content)
        branch = _parse_branch(raw, allowed)
    except Exception:
        return "baseline"
    if branch == "rag" and not rag_loaded:
        return "baseline"
    if branch == "direct":
        return "baseline"
    return branch  # type: ignore[return-value]


async def _invoke_model(model: Any, system: str, content: str) -> str:
    messages = (SystemMessage(content=system), HumanMessage(content=content))
    ainvoke = getattr(model, "ainvoke", None)
    if callable(ainvoke):
        response = await ainvoke(messages)
    else:
        response = await asyncio.to_thread(model.invoke, messages)
    if isinstance(response, str):
        return response
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    result = getattr(response, "content", None)
    return result if isinstance(result, str) else str(response)


def _parse_branch(raw: str, allowed: list[str]) -> str:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match is None:
        raise ValueError("no json in classifier output")
    data = json.loads(match.group(0))
    branch = str(data.get("branch", "")).strip().lower()
    if branch == "direct":
        return "direct"
    if branch in allowed:
        return branch
    raise ValueError(f"branch out of allowed set: {branch}")


def selector_node(
    *,
    run_id: str,
    model: Any,
    rag_loaded: bool,
    publish,
) -> Any:
    """构造 LangGraph selector 节点闭包（每个 run 构建一次）。"""

    async def selector(state: RunState) -> dict[str, Any]:
        task_input = state.get("task_input")
        if not isinstance(task_input, TaskInput):
            raise RuntimeError("run is missing task input")
        branch = await select_branch(
            run_id,
            task_input,
            model=model,
            rag_loaded=rag_loaded,
            publish=publish,
        )
        return {
            "phase": "selecting_tools",
            "plan_branch": branch,
        }

    return selector
