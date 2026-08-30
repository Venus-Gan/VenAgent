"""四个内置子 Agent：research → writer → review → doc（对照 AGI-saber 形态）。

research：LLM 改写目标为多条互补查询 → rag_search 检索 → 汇总 findings；
writer：上游结果整理为 Markdown 报告；
review：报告结构/事实/缺口审查，给出可信度；
doc：报告落库（write_document，M08 文档库即 RAG 事实源）。
"""

from __future__ import annotations

import json
from typing import Any

from .base import SubAgentContext, SubAgentResult, llm_text

_REWRITE_PROMPT = (
    "把研究目标改写为 2-3 条互补的知识库检索查询，只输出 JSON：\n"
    '{"queries": ["...", "..."]}\n'
    "查询应覆盖目标的不同侧面，避免同义重复。"
)

_RESEARCH_PROMPT = (
    "你是研究员。基于以下检索证据完成研究目标，输出结构化 Markdown：\n"
    "## Findings（关键发现）\n## Evidence（证据要点，标注来源编号）\n"
    "## Open Questions（未尽事项）\n"
    "只依据证据，不编造；证据不足要明确说明。\n\n研究目标：{goal}\n\n检索证据：\n{evidence}"
)

_WRITER_PROMPT = (
    "你是撰写员。把研究材料整理成一份 Markdown 报告，包含：标题、摘要、"
    "分析主体、结论与建议。只依据提供的材料，不要引入外部事实。\n\n"
    "研究材料：\n{material}\n\n审查意见（如有）：\n{review}"
)

_REVIEW_PROMPT = (
    "你是审稿员。审查报告的结构完整性、事实一致性与证据缺口，只输出 JSON：\n"
    '{"issues": ["..."], "confidence": 0.0, "verdict": "pass" | "needs_fix"}\n\n报告：\n{report}'
)


class ResearchAgent:
    name = "research_agent"
    description = "研究子 Agent：改写检索查询并调用知识库检索，输出结构化研究发现。"

    def __init__(self, model: Any, rag_tool: str = "rag_search") -> None:
        self._model = model
        self._rag_tool = rag_tool

    async def run(self, context: SubAgentContext) -> SubAgentResult:
        try:
            raw = await llm_text(self._model, _REWRITE_PROMPT + f"\n\n目标：{context.goal}")
            queries = _parse_queries(raw)
        except Exception:
            queries = [context.goal]
        if not queries:
            queries = [context.goal]
        evidence_parts: list[str] = []
        used = 0
        for index, query in enumerate(queries[:3]):
            result = await context.invoke_tool(
                self._rag_tool, {"query": query}, sequence=index
            )
            used += 1
            if result.status == "success" and result.content:
                evidence_parts.append(f"[Q{index + 1}：{query}]\n{result.content[:2500]}")
            else:
                evidence_parts.append(f"[Q{index + 1}：{query}] 检索失败：{result.summary}")
        try:
            findings = await llm_text(
                self._model,
                _RESEARCH_PROMPT.format(
                    goal=context.goal, evidence="\n\n".join(evidence_parts)
                ),
                system="你是研究员，只依据证据输出。",
            )
        except Exception as exc:
            return SubAgentResult(False, "", error_code=f"research_llm_failed:{exc}")
        return SubAgentResult(True, f"共执行 {used} 条检索。\n\n{findings}")


class WriterAgent:
    name = "writer_agent"
    description = "撰写子 Agent：把研究结果整理为 Markdown 报告（标题/摘要/分析/结论）。"

    def __init__(self, model: Any) -> None:
        self._model = model

    async def run(self, context: SubAgentContext) -> SubAgentResult:
        material = context.upstream_text() or context.goal
        review = ""
        for item in context.upstream:
            if "review" in item.executor:
                review = item.observation
        try:
            report = await llm_text(
                self._model,
                _WRITER_PROMPT.format(material=material, review=review or "（无）"),
                system="你是撰写员，只依据材料输出 Markdown。",
            )
        except Exception as exc:
            return SubAgentResult(False, "", error_code=f"writer_llm_failed:{exc}")
        return SubAgentResult(True, report)


class ReviewAgent:
    name = "review_agent"
    description = "审查子 Agent：检查报告结构与事实一致性，输出问题清单与可信度。"

    def __init__(self, model: Any) -> None:
        self._model = model

    async def run(self, context: SubAgentContext) -> SubAgentResult:
        report = context.upstream_text() or context.goal
        # prompt 内含 JSON 大括号示例，不能用 str.format（会被当格式字段解析）。
        prompt = (
            "你是审稿员。审查报告的结构完整性、事实一致性与证据缺口，只输出 JSON：\n"
            '{"issues": ["..."], "confidence": 0.0, "verdict": "pass" | "needs_fix"}\n\n报告：\n'
            + report[:8000]
        )
        try:
            raw = await llm_text(self._model, prompt, system="你只输出 JSON。")
        except Exception as exc:
            return SubAgentResult(False, "", error_code=f"review_llm_failed:{exc}")
        return SubAgentResult(True, raw)


class DocAgent:
    name = "doc_agent"
    description = (
        "落库子 Agent：把报告写入本地文档库并自动进入知识库索引"
        "（需要上游 writer 产物）。"
    )

    async def run(self, context: SubAgentContext) -> SubAgentResult:
        report = ""
        for item in context.upstream:
            if "writer" in item.executor:
                report = item.observation
        if not report:
            report = context.upstream_text() or context.goal
        # 标题优先级：用户任务中显式指定的 .md 文件名 > 报告首行标题 > goal 截断。
        import re

        filename_match = re.search(r"([\w\u4e00-\u9fff-]+\.md)", context.goal)
        title = None
        if filename_match:
            title = filename_match.group(1)[:80]
        if not title:
            title = _report_title(report) or context.goal[:60]
        result = await context.invoke_tool(
            "write_document",
            {
                "filename": title if title.endswith(".md") else f"{title}.md",
                "title": title.removesuffix(".md"),
                "content": report,
            },
            sequence=0,
        )
        if result.status != "success":
            return SubAgentResult(
                False, result.summary, error_code=result.error or "document_write_failed"
            )
        return SubAgentResult(True, f"报告已落库：{title}\n{result.summary}")


def _parse_queries(raw: str) -> list[str]:
    match = None
    import re

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match is None:
        return []
    data = json.loads(match.group(0))
    queries = data.get("queries") if isinstance(data, dict) else None
    if not isinstance(queries, list):
        return []
    return [str(item) for item in queries if isinstance(item, str) and item.strip()]


def _report_title(report: str) -> str | None:
    for line in report.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:80]
    return None
