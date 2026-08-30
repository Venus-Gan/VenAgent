"""上下文 section、placement 与角色投影策略。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Placement = Literal["system_messages", "messages", "tools"]


@dataclass(frozen=True)
class SectionSpec:
    section_kind: str
    placement: Placement
    required: bool
    priority: int
    token_budget: int
    failure_policy: str = "omit"


@dataclass(frozen=True)
class ProjectionPolicy:
    version: str
    model_role: str
    sections: tuple[SectionSpec, ...]


FOUNDATION_POLICY = ProjectionPolicy(
    version="foundation-m06-v1",
    model_role="answer",
    sections=(
        SectionSpec("stable_rules", "system_messages", True, 100, 512, "fail"),
        SectionSpec("security", "system_messages", True, 100, 512, "fail"),
        SectionSpec("sandbox_constraints", "system_messages", False, 95, 2_000, "omit"),
        SectionSpec("tool_status", "system_messages", False, 90, 4_000, "omit"),
        SectionSpec("skill_context", "system_messages", False, 70, 4_000, "omit"),
        SectionSpec("conversation", "messages", True, 90, 24_000, "fail"),
        SectionSpec("short_term_summary", "messages", False, 80, 4_000, "omit"),
        SectionSpec("long_term_memory", "system_messages", False, 70, 2_000, "omit"),
        SectionSpec("output_contract", "system_messages", True, 100, 256, "fail"),
    ),
)
