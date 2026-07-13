"""Doc preset for agentteam compat."""

from __future__ import annotations

import json
import re
from typing import Any

from internal.agentteam import PresetContract, PresetTask, build_preset_contract
from internal.document.library import DOCUMENT_SOURCE_AGENT, WriteRequest

_INPUT_FIELDS = ("id", "goal", "query", "upstream")
_OUTPUT_FIELDS = ("status", "result", "notes", "follow_up", "used_tools")
_TOOL_PERMISSIONS = ("write_document",)
_NL = chr(10)


def build_doc_contract() -> PresetContract:
    return build_preset_contract(
        name="doc_agent",
        role="doc",
        purpose="将上游结果保存到本地文档库，并同步写入 RAG。",
        input_fields=_INPUT_FIELDS,
        output_fields=_OUTPUT_FIELDS,
        tool_permissions=_TOOL_PERMISSIONS,
        memory_policy="task_memory,document_store",
        retrieval_policy="writer_output,review_output",
        prompt_template="Persist the final report as a document.",
    )


def create_doc_preset(agent: Any) -> "DocPreset":
    return DocPreset(agent)


class DocPreset:
    def __init__(self, agent: Any) -> None:
        self.agent = agent
        self._contract = build_doc_contract()

    def name(self) -> str:
        return "doc_agent"

    def description(self) -> str:
        return "将上游结果保存到本地文档库，并同步写入 RAG。"

    def contract(self) -> PresetContract:
        return self._contract

    def run(self, task: PresetTask) -> str:
        content = _document_content(task) or task.query
        title = _document_title(content, task.goal, task.query)
        result = self.agent.write_document(
            WriteRequest(
                title=title,
                doc_type="report",
                source=DOCUMENT_SOURCE_AGENT,
                created_by=self.name(),
                content_md=content,
                summary=_first_runes(content, 180),
                metadata={
                    "sub_agent": self.name(),
                    "task_id": task.id,
                    "review": _first_runes(_upstream_by_agent(task, "review_agent"), 1200),
                },
            ),
            True,
        )
        return json.dumps(_jsonable(result), ensure_ascii=False, indent=2)


def _document_content(task: PresetTask) -> str:
    writer = _upstream_by_agent(task, "writer_agent")
    if writer.strip():
        return _strip_markdown_fence(writer)
    for key in sorted(task.upstream):
        value = (task.upstream[key] or "").strip()
        if value:
            return _strip_markdown_fence(value)
    return task.query.strip()


def _upstream_by_agent(task: PresetTask, agent_name: str) -> str:
    for key in sorted(task.upstream):
        if agent_name in key:
            return task.upstream[key] or ""
    return ""


def _document_title(content: str, goal: str, query: str) -> str:
    for text in (query, goal):
        explicit = _explicit_requested_title(text)
        if explicit:
            return _first_runes(explicit, 80)
    heading = _markdown_title(content)
    if heading:
        return _first_runes(heading, 80)
    return _safe_title("", query or goal)


def _markdown_title(content: str) -> str:
    content = _strip_markdown_fence(content)
    fallback = ""
    in_fence = False
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if not match:
            continue
        title = match.group(2).strip("# \t*_`")
        if _is_generic_heading(title):
            continue
        if len(match.group(1)) == 1:
            return title
        if not fallback:
            fallback = title
    return fallback


def _explicit_requested_title(text: str) -> str:
    text = (text or "").strip()
    for marker, end in [
        ("标题为《", "》"),
        ("标题是《", "》"),
        ("题为《", "》"),
        ('标题为"', '"'),
        ('标题是"', '"'),
        ('题为"', '"'),
    ]:
        start = text.find(marker)
        if start < 0:
            continue
        rest = text[start + len(marker) :]
        stop = rest.find(end)
        if stop > 0:
            return rest[:stop].strip()
    return ""


def _strip_markdown_fence(text: str) -> str:
    trimmed = (text or "").strip()
    lines = trimmed.splitlines()
    if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip().startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return trimmed


def _is_generic_heading(title: str) -> bool:
    value = (title or "").strip().lower()
    return value in {
        "摘要",
        "分析",
        "建议",
        "下一步",
        "结论",
        "review",
        "findings",
        "evidence",
        "open questions",
        "research findings",
    }


def _safe_title(goal: str, query: str) -> str:
    title = (goal or query or "").strip()
    for prefix in ("生成", "撰写"):
        if title.startswith(prefix):
            title = title[len(prefix) :].strip()
    return _first_runes(title or "Agent Report", 60)


def _first_runes(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "..."


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return _jsonable(asdict(value))
    return value


DocAgent = DocPreset
