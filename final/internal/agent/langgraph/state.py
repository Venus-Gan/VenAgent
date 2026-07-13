from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, TypedDict


class MessageRecord(TypedDict, total=False):
    role: str
    content: str


class StepRecord(TypedDict, total=False):
    id: str
    type: str
    content: str
    tool: str
    params: dict[str, Any]


class EventRecord(TypedDict, total=False):
    type: str
    route: str
    node: str
    status: str


class ReactState(TypedDict, total=False):
    query: str
    route: str
    messages: list[MessageRecord]
    steps: list[StepRecord]
    results: list[Any]
    events: list[EventRecord]


_LIST_FIELDS = {"messages", "steps", "results", "events"}


def initial_react_state(query: str) -> ReactState:
    """Create a fresh react state with reducer-friendly list defaults."""

    return {
        "query": query,
        "route": "",
        "messages": [],
        "steps": [],
        "results": [],
        "events": [],
    }


def merge_react_state(state: Mapping[str, Any], update: Mapping[str, Any]) -> ReactState:
    """Merge a partial update into react state without overwriting list fields."""

    merged: dict[str, Any] = dict(state)
    for key, value in update.items():
        if key in _LIST_FIELDS:
            merged[key] = list(merged.get(key, [])) + _coerce_list(value)
            continue
        merged[key] = deepcopy(value)

    for key in _LIST_FIELDS:
        merged.setdefault(key, [])
    merged.setdefault("route", "")
    merged.setdefault("query", "")
    return merged  # type: ignore[return-value]


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]
