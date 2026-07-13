"""Research preset for agentteam compat."""

from __future__ import annotations

from typing import Any, List

from internal.agentteam import PresetContract, PresetTask, build_preset_contract

_INPUT_FIELDS = ("id", "goal", "query", "upstream")
_OUTPUT_FIELDS = ("status", "result", "notes", "follow_up", "used_tools")
_TOOL_PERMISSIONS = ("search_web", "rag_search")
_NL = chr(10)


def build_research_contract() -> PresetContract:
    return build_preset_contract(
        name="research_agent",
        role="research",
        purpose="Agentic RAG researcher: 多轮改写、知识库/搜索检索、证据整理。",
        input_fields=_INPUT_FIELDS,
        output_fields=_OUTPUT_FIELDS,
        tool_permissions=_TOOL_PERMISSIONS,
        memory_policy="task_memory,rag",
        retrieval_policy="search_web,rag",
        prompt_template="Collect evidence and summarize findings.",
    )


def create_research_preset(agent: Any) -> "ResearchPreset":
    return ResearchPreset(agent)


class ResearchPreset:
    def __init__(self, agent: Any) -> None:
        self.agent = agent
        self._contract = build_research_contract()

    def name(self) -> str:
        return "research_agent"

    def description(self) -> str:
        return "Agentic RAG researcher: 多轮改写、知识库/搜索检索、证据整理。"

    def contract(self) -> PresetContract:
        return self._contract

    def run(self, task: PresetTask) -> str:
        query = (task.goal or task.query).strip()
        observations: List[str] = []
        rag = getattr(self.agent, "rag", None)
        if rag is not None and getattr(rag, "loaded", False):
            answer, results = rag.query(query)
            observations.append("Query: " + query + _NL + "RAG Answer: " + answer)
            for item in results or []:
                content = (item.get("content") or "").strip() if isinstance(item, dict) else ""
                if content:
                    observations.append("- " + _first_runes(content, 180))
        elif hasattr(self.agent, "tool_executor"):
            tool = self.agent.tool_executor.snapshot().get("search_web")
            if tool is not None:
                observations.append("Query: " + query + _NL + "Search Result: " + str(tool.func({"query": query})))
        if not observations:
            observations.append("未找到可用知识库或搜索结果。")
        return "## Research Findings" + _NL + _NL + _NL.join(observations)


def _first_runes(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "..."


ResearchAgent = ResearchPreset
