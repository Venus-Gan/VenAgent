"""Writer preset for agentteam compat."""

from __future__ import annotations

from typing import Any

from internal.agentteam import PresetContract, PresetTask, build_preset_contract

_INPUT_FIELDS = ("id", "goal", "query", "upstream")
_OUTPUT_FIELDS = ("status", "result", "notes", "follow_up", "used_tools")
_TOOL_PERMISSIONS = ()
_NL = chr(10)


def build_writer_contract() -> PresetContract:
    return build_preset_contract(
        name="writer_agent",
        role="writer",
        purpose="将上游研究结果整理为 Markdown 报告。",
        input_fields=_INPUT_FIELDS,
        output_fields=_OUTPUT_FIELDS,
        tool_permissions=_TOOL_PERMISSIONS,
        memory_policy="task_memory",
        retrieval_policy="upstream",
        prompt_template="Synthesize upstream findings into Markdown.",
    )


def create_writer_preset(agent: Any) -> "WriterPreset":
    return WriterPreset(agent)


class WriterPreset:
    def __init__(self, agent: Any) -> None:
        self.agent = agent
        self._contract = build_writer_contract()

    def name(self) -> str:
        return "writer_agent"

    def description(self) -> str:
        return "将上游研究结果整理为 Markdown 报告。"

    def contract(self) -> PresetContract:
        return self._contract

    def run(self, task: PresetTask) -> str:
        material = _upstream_text(task)
        if not _is_real_llm(self.agent):
            return "# " + _safe_title(task.goal, task.query) + _NL + _NL + material
        return self.agent._llm_generate(
            "你是 writer_agent。请把输入整理为清晰 Markdown 报告，包含摘要、分析、建议和下一步。",
            "写作目标：" + task.goal + _NL + _NL + "材料：" + _NL + material,
        )


def _upstream_text(task: PresetTask) -> str:
    if not task.upstream:
        return task.query
    parts = []
    for key in sorted(task.upstream):
        parts.append("## " + key + _NL + _NL + (task.upstream[key] or ""))
    return (_NL + _NL).join(parts).strip()


def _is_real_llm(agent: Any) -> bool:
    fn = getattr(getattr(agent, "cfg", None), "is_real_llm", None)
    return bool(callable(fn) and fn())


def _safe_title(goal: str, query: str) -> str:
    title = (goal or query or "").strip()
    for prefix in ("生成", "撰写"):
        if title.startswith(prefix):
            title = title[len(prefix):].strip()
    return _first_runes(title or "Agent Report", 60)


def _first_runes(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "..."


WriterAgent = WriterPreset
