"""Review preset for agentteam compat."""

from __future__ import annotations

from typing import Any

from internal.agentteam import PresetContract, PresetTask, build_preset_contract

_INPUT_FIELDS = ("id", "goal", "query", "upstream")
_OUTPUT_FIELDS = ("status", "result", "notes", "follow_up", "used_tools")
_TOOL_PERMISSIONS = ()
_NL = chr(10)


def build_review_contract() -> PresetContract:
    return build_preset_contract(
        name="review_agent",
        role="review",
        purpose="检查报告结构、事实一致性、证据覆盖和风险。",
        input_fields=_INPUT_FIELDS,
        output_fields=_OUTPUT_FIELDS,
        tool_permissions=_TOOL_PERMISSIONS,
        memory_policy="task_memory",
        retrieval_policy="upstream",
        prompt_template="Review the material for gaps and risks.",
    )


def create_review_preset(agent: Any) -> "ReviewPreset":
    return ReviewPreset(agent)


class ReviewPreset:
    def __init__(self, agent: Any) -> None:
        self.agent = agent
        self._contract = build_review_contract()

    def name(self) -> str:
        return "review_agent"

    def description(self) -> str:
        return "检查报告结构、事实一致性、证据覆盖和风险。"

    def contract(self) -> PresetContract:
        return self._contract

    def run(self, task: PresetTask) -> str:
        material = _upstream_text(task)
        if not _is_real_llm(self.agent):
            return "Review: 内容已整理；建议人工确认关键事实。"
        return self.agent._llm_generate(
            "你是 review_agent。请审查输入，输出问题清单、可信度和需要补证据的点。",
            material,
        )


def _upstream_text(task: PresetTask) -> str:
    if not task.upstream:
        return task.query
    parts = []
    for key in sorted(task.upstream):
        parts.append(f"## {key}{_NL}{_NL}{task.upstream[key]}")
    return (_NL + _NL).join(parts).strip()


def _is_real_llm(agent: Any) -> bool:
    fn = getattr(getattr(agent, "cfg", None), "is_real_llm", None)
    return bool(callable(fn) and fn())


ReviewAgent = ReviewPreset
