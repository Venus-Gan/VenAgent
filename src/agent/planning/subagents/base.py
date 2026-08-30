"""子 Agent 基座：A1 轻量形态（async 类内部小循环，非子图非 prebuilt）。

子 Agent 工具调用必须经 ToolControlContext（M06 权威），v1 限 safe 风险级
工具——由 bootstrap 注册工具时定级保证；此处不再二次放行 warn/block。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from ....tools.models import ModelToolCall, ToolResult

Publish = Callable[[str, str, dict[str, Any]], Any]


@dataclass(frozen=True)
class UpstreamItem:
    node_id: str
    executor: str
    observation: str


@dataclass(frozen=True)
class SubAgentContext:
    run_id: str
    owner_id: str
    plan_revision: int
    node_id: str
    attempt: int
    goal: str
    upstream: tuple[UpstreamItem, ...]
    tool_control: Any
    publish: Publish
    cancel_event: asyncio.Event | None

    async def invoke_tool(
        self, tool_name: str, arguments: dict[str, Any], *, sequence: int = 0
    ) -> ToolResult:
        """经 Gateway 执行工具（幂等 call id：恢复重跑不重复副作用）。"""
        call = ModelToolCall(
            id=f"sub-{self.node_id}-a{self.attempt}-s{sequence}-{tool_name}",
            name=tool_name,
            arguments=arguments,
        )
        return await self.tool_control.invoke_tool(
            self.run_id,
            self.owner_id,
            call,
            cancel_event=self.cancel_event,
        )

    def upstream_text(self) -> str:
        return "\n".join(
            f"[{item.node_id} | {item.executor}] {item.observation}"
            for item in self.upstream
        )


@dataclass(frozen=True)
class SubAgentResult:
    success: bool
    content: str
    error_code: str | None = None


class SubAgent(Protocol):
    name: str
    description: str

    async def run(self, context: SubAgentContext) -> SubAgentResult: ...


class SubAgentRegistry:
    """子 Agent 注册表：name/description 暴露给 Planner，执行体按名取用。"""

    def __init__(self) -> None:
        self._agents: dict[str, SubAgent] = {}

    def register(self, agent: SubAgent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> SubAgent | None:
        return self._agents.get(name)

    def infos(self) -> tuple[Any, ...]:
        """给 Planner 的 (name, description) 列表。"""
        from ..planner import AgentInfo

        return tuple(
            AgentInfo(name=agent.name, description=agent.description)
            for agent in self._agents.values()
        )

    def __len__(self) -> int:
        return len(self._agents)


async def llm_text(model: Any, prompt: str, *, system: str = "你是任务执行专家。") -> str:
    """子 Agent 内部的单次 LLM 调用（非流式，结果进 NodeOutcome）。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    messages = (SystemMessage(content=system), HumanMessage(content=prompt))
    ainvoke = getattr(model, "ainvoke", None)
    if callable(ainvoke):
        response = await ainvoke(messages)
    else:
        response = await asyncio.to_thread(model.invoke, messages)
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    content = getattr(response, "content", None)
    return content if isinstance(content, str) else str(response)
