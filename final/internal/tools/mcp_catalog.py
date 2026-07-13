"""Canonical tool catalog helpers.

The catalog normalizes tool metadata into a stable shape that can be shared by
the tool executor, HTTP handlers, and any UI-facing code.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Sequence


def _stringify(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def normalize_tool_param(param: Mapping[str, Any]) -> Dict[str, str]:
    """Normalize a single tool parameter into the canonical schema."""

    return {
        "name": _stringify(param.get("name")),
        "type": _stringify(param.get("type"), "string"),
        "description": _stringify(param.get("description")),
    }


def normalize_tool_params(params: Sequence[Mapping[str, Any]] | None) -> list[Dict[str, str]]:
    """Normalize a list of tool parameters into canonical catalog entries."""

    if not params:
        return []
    return [normalize_tool_param(param) for param in params]


def tool_to_catalog_entry(tool: Any) -> Dict[str, Any]:
    """Convert a tool object into the stable catalog schema.

    The canonical field is ``params``. ``parameters`` is kept as a compatibility
    alias for older consumers that still expect the previous schema.
    """

    params = normalize_tool_params(getattr(tool, "params", None))
    entry = {
        "name": _stringify(getattr(tool, "name", "")),
        "description": _stringify(getattr(tool, "description", "")),
        "params": params,
        "is_mcp": bool(getattr(tool, "is_mcp", False)),
    }
    entry["parameters"] = [dict(param) for param in params]
    return entry


def tools_to_catalog_entries(tools: Iterable[Any]) -> list[Dict[str, Any]]:
    """Convert an iterable of tools into catalog entries."""

    return [tool_to_catalog_entry(tool) for tool in tools]
