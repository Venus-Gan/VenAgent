"""Lightweight preset contracts for agentteam compat."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


def _as_tuple(values: Iterable[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    return tuple(str(value) for value in values)


@dataclass(frozen=True, slots=True)
class PresetTask:
    """Immutable task envelope compatible with preset runners."""

    id: str = ""
    goal: str = ""
    query: str = ""
    upstream: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        upstream = {} if self.upstream is None else dict(self.upstream)
        object.__setattr__(self, "upstream", MappingProxyType(upstream))


@dataclass(frozen=True, slots=True)
class PresetContract:
    """Stable metadata describing a preset without binding to implementation."""

    name: str
    role: str
    purpose: str
    input_fields: tuple[str, ...] = field(default_factory=tuple)
    output_fields: tuple[str, ...] = field(default_factory=tuple)
    tool_permissions: tuple[str, ...] = field(default_factory=tuple)
    memory_policy: str = ""
    retrieval_policy: str = ""
    prompt_template: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "role", str(self.role))
        object.__setattr__(self, "purpose", str(self.purpose))
        object.__setattr__(self, "input_fields", _as_tuple(self.input_fields))
        object.__setattr__(self, "output_fields", _as_tuple(self.output_fields))
        object.__setattr__(self, "tool_permissions", _as_tuple(self.tool_permissions))
        object.__setattr__(self, "memory_policy", str(self.memory_policy))
        object.__setattr__(self, "retrieval_policy", str(self.retrieval_policy))
        object.__setattr__(self, "prompt_template", str(self.prompt_template))


def _policy_text(value: str | Iterable[str] | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return ",".join(str(item).strip() for item in value if str(item).strip())


def build_preset_contract(
    *,
    name: str,
    role: str,
    purpose: str,
    input_fields: Iterable[str] | None = None,
    output_fields: Iterable[str] | None = None,
    tool_permissions: Iterable[str] | None = None,
    memory_policy: str | Iterable[str] | None = "",
    retrieval_policy: str | Iterable[str] | None = "",
    prompt_template: str = "",
) -> PresetContract:
    return PresetContract(
        name=name,
        role=role,
        purpose=purpose,
        input_fields=input_fields,
        output_fields=output_fields,
        tool_permissions=tool_permissions,
        memory_policy=_policy_text(memory_policy),
        retrieval_policy=_policy_text(retrieval_policy),
        prompt_template=prompt_template,
    )
