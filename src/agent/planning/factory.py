"""计划层图节点工厂：每 run 构建一组节点闭包（Generator / rag_answer 等）。

Generator：把成功节点的观察合成为最终回答（流式）；
rag_answer：Selector RAG 支——复用 M08 HybridSearchService 生成引用回答。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ..events import AssistantBlockAssembler, normalize_assistant_chunk
from ..runs import RunCancelled
from ..state import FinalAnswer, RunState, TaskInput
from .dag import observations_text
from .executor import ExecutorDeps, executor_node
from .planner import planner_node
from .replanner import replanner_node
from .selector import selector_node

_RAG_ANSWER_SYSTEM_PROMPT = (
    "你是一个基于知识库回答问题的助手。请仅根据提供的上下文内容回答问题，"
    "不要编造信息。引用编号 [n] 只能引用给定的编号。如果上下文不足以回答，"
    "请明确说明。回答使用中文。"
)

_MAX_STREAM_OUTPUT_BYTES = 128 * 1024


@dataclass(frozen=True)
class PlanningNodes:
    """一次 run 的计划层节点集合（传给 compile_agent_graph 的可选节点）。"""

    selector: Any
    planner: Any
    executor: Any
    replanner: Any
    generator: Any
    rag_answer: Any


class PlanningRuntime:
    """AgentRuntime 持有的计划层装配规格；每 run 调 build_nodes 产出节点闭包。"""

    def __init__(
        self,
        *,
        model: Any,
        tool_control: Any,
        registry: Any,
        rag_search: Any | None,
        planning_config: Any,
        enabled: bool = True,
    ) -> None:
        self._model = model
        self._tool_control = tool_control
        self._registry = registry
        self._rag_search = rag_search
        self._planning_config = planning_config
        self.enabled = enabled

    def build_nodes(
        self,
        *,
        run_id: str,
        owner_id: str,
        active: Any,
        execution_attempt: int,
        publish,
        mem_prefix: str = "",
    ) -> PlanningNodes:
        return build_planning_nodes(
            run_id=run_id,
            owner_id=owner_id,
            model=self._model,
            tool_control=self._tool_control,
            registry=self._registry,
            rag_search=self._rag_search,
            publish=publish,
            cancel_event=active.token._event,
            execution_attempt=execution_attempt,
            planning_config=self._planning_config,
            mem_prefix=mem_prefix,
        )


async def _stream_text(
    *,
    run_id: str,
    model: Any,
    messages: tuple[Any, ...],
    execution_attempt: int,
    publish,
    cancel_event: asyncio.Event | None,
) -> tuple[str, tuple[dict[str, str], ...]]:
    """流式生成最终文本（Generator / rag_answer 共用）。"""
    assembler = AssistantBlockAssembler()
    output_bytes = 0

    async def _iterate():
        astream = getattr(model, "astream", None)
        if callable(astream):
            async for chunk in astream(messages):
                yield chunk
            return
        invoke = getattr(model, "ainvoke", None)
        if callable(invoke):
            yield await invoke(messages)
            return
        yield await asyncio.to_thread(model.invoke, messages)

    async for chunk in _iterate():
        if cancel_event is not None and cancel_event.is_set():
            raise RunCancelled
        for block_type, delta in normalize_assistant_chunk(chunk):
            delta_bytes = len(delta.encode("utf-8"))
            if output_bytes + delta_bytes > _MAX_STREAM_OUTPUT_BYTES:
                raise RuntimeError("model output limit exceeded")
            output_bytes += delta_bytes
            for normalized in assembler.push(block_type, delta):
                await publish(
                    run_id,
                    "assistant.chunk",
                    execution_attempt=execution_attempt,
                    chunk=normalized,
                )
    for normalized in assembler.finish():
        await publish(
            run_id,
            "assistant.chunk",
            execution_attempt=execution_attempt,
            chunk=normalized,
        )
    text = "".join(
        item.get("text", "")
        for item in assembler.blocks
        if item.get("type") == "text"
    )
    return text, assembler.blocks


def build_planning_nodes(
    *,
    run_id: str,
    owner_id: str,
    model: Any,
    tool_control: Any,
    registry: Any,
    rag_search: Any | None,
    publish,
    cancel_event: asyncio.Event | None,
    execution_attempt: int,
    planning_config: Any,
    mem_prefix: str = "",
) -> PlanningNodes:
    """每 run 构建计划层节点（闭包捕获 run 上下文）。

    mem_prefix：AgentRuntime 每 run 一次装配的记忆/工具状态前缀（projected
    system_messages 段，AGI-saber memPrefix 同构），拼进四个 LLM 节点的
    SystemMessage；HumanMessage（节点专属 prompt）不动。"" 时与 M07 现状一致。
    """
    snapshot = tool_control.snapshot(run_id=run_id)
    exposed = tuple(item for item in snapshot.tools if item.exposed)
    from .planner import ToolInfo

    tools = tuple(
        ToolInfo(
            name=item.tool_id,
            description=item.description,
            parameters_json=_params_summary(item.input_schema),
        )
        for item in exposed
    )
    agents = registry.infos() if registry is not None else ()
    rag_loaded = rag_search is not None and rag_search.mode != "unavailable"

    def _with_mem_prefix(content: str) -> SystemMessage:
        return SystemMessage(content=(mem_prefix + "\n\n" if mem_prefix else "") + content)

    selector = selector_node(
        run_id=run_id, model=model, rag_loaded=rag_loaded, publish=publish
    )
    planner = planner_node(
        run_id=run_id,
        model=model,
        tools=tools,
        agents=agents,  # type: ignore[arg-type]
        publish=publish,
        max_nodes=planning_config.max_plan_nodes,
        mem_prefix=mem_prefix,
    )
    executor = executor_node(
        ExecutorDeps(
            run_id=run_id,
            owner_id=owner_id,
            tool_control=tool_control,
            registry=registry,
            publish=publish,
            cancel_event=cancel_event,
            max_parallel=planning_config.max_parallel,
            race_timeout_ms=planning_config.race_timeout_ms,
        )
    )
    replanner = replanner_node(
        run_id=run_id,
        model=model,
        tools=tools,
        agents=agents,  # type: ignore[arg-type]
        publish=publish,
        max_replan=planning_config.max_replan,
        append_limit=planning_config.replan_append_limit,
        max_nodes=planning_config.max_plan_nodes,
        mem_prefix=mem_prefix,
    )

    async def generator(state: RunState) -> dict[str, Any]:
        task_input = state.get("task_input")
        if not isinstance(task_input, TaskInput):
            raise RuntimeError("run is missing task input")
        observations = observations_text(state.get("node_outcomes") or ())
        prompt = (
            f"{task_input.content}\n\n以下是各执行步骤的观察结果，请综合它们"
            f"生成面向用户的最终回答；不要编造观察之外的事实：\n\n{observations}"
        )
        text, blocks = await _stream_text(
            run_id=run_id,
            model=model,
            messages=(
                _with_mem_prefix("你是任务执行协调者，基于各步骤观察产出最终回答。"),
                HumanMessage(content=prompt),
            ),
            execution_attempt=execution_attempt,
            publish=publish,
            cancel_event=cancel_event,
        )
        if not text:
            raise RuntimeError("generator produced no text")
        return {
            "phase": "synthesizing",
            "final_answer": FinalAnswer(text, blocks=blocks),
            "failure": None,
        }

    async def rag_answer(state: RunState) -> dict[str, Any]:
        task_input = state.get("task_input")
        if not isinstance(task_input, TaskInput):
            raise RuntimeError("run is missing task input")
        if rag_search is None or rag_search.mode == "unavailable":
            return {
                "phase": "synthesizing",
                "final_answer": FinalAnswer(
                    "知识库检索未配置或不可用，请检查 Milvus / Elasticsearch 配置。",
                ),
                "failure": None,
            }
        try:
            result = await asyncio.to_thread(
                rag_search.search, owner_id, task_input.content
            )
        except Exception:
            result = None
        if result is None or result.mode == "unavailable":
            return {
                "phase": "synthesizing",
                "final_answer": FinalAnswer("知识库检索当前不可用，请稍后重试。"),
                "failure": None,
            }
        if not result.sources:
            return {
                "phase": "synthesizing",
                "final_answer": FinalAnswer("知识库中未找到相关内容。"),
                "failure": None,
            }
        context = "\n\n".join(
            f"[{index + 1}] {source.parent_content or source.chunk_content}"
            for index, source in enumerate(result.sources)
        )
        await publish(
            run_id,
            "rag.retrieved",
            mode=result.mode,
            sources=len(result.sources),
            degraded=list(result.degraded),
        )
        text, blocks = await _stream_text(
            run_id=run_id,
            model=model,
            messages=(
                _with_mem_prefix(_RAG_ANSWER_SYSTEM_PROMPT),
                HumanMessage(content=f"上下文：\n{context}\n\n问题：{task_input.content}"),
            ),
            execution_attempt=execution_attempt,
            publish=publish,
            cancel_event=cancel_event,
        )
        if not text:
            text = "检索到以下相关内容。"
        citation_lines = [
            f"[{index + 1}] {source.title or source.document_id}"
            + (f" / {source.section}" if source.section else "")
            for index, source in enumerate(result.sources)
        ]
        flags = []
        if result.degraded:
            flags.append("检索降级：" + ",".join(result.degraded))
        if result.reranked:
            flags.append("已重排")
        suffix = f"（来源：{result.mode}" + ("，" + "；".join(flags) if flags else "") + "）"
        full_text = "\n".join(
            [text.strip(), suffix, "\n".join(citation_lines)]
        )
        return {
            "phase": "synthesizing",
            "final_answer": FinalAnswer(full_text, blocks=blocks),
            "failure": None,
        }

    return PlanningNodes(
        selector=selector,
        planner=planner,
        executor=executor,
        replanner=replanner,
        generator=generator,
        rag_answer=rag_answer,
    )


def _params_summary(input_schema: dict[str, Any]) -> str:

    properties = input_schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return "{}"
    required = input_schema.get("required")
    parts = []
    for name, spec in properties.items():
        spec_dict = spec if isinstance(spec, dict) else {}
        marker = "*" if isinstance(required, list) and name in required else ""
        description = str(spec_dict.get("type", "any"))
        parts.append(f'{name}{marker}({description})')
    return "{" + ", ".join(parts) + "}"
