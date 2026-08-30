"""可持久化 RunEvent 与 provider 显式内容分片归一化。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

AssistantBlockType = Literal["text", "reasoning"]
AssistantBlock = dict[str, str]


@dataclass(frozen=True)
class RunEvent:
    run_id: str
    sequence: int
    type: str
    payload: dict[str, Any]
    created_at: datetime

    @property
    def event(self) -> str:
        """兼容旧在线观察对象的属性名。"""
        return self.type


def normalize_assistant_chunk(chunk: Any) -> tuple[tuple[AssistantBlockType, str], ...]:
    """只提取 provider 明确返回的正文或 reasoning，不推断隐藏思维链。"""
    if isinstance(chunk, str):
        return (("text", chunk),) if chunk else ()

    parts: list[tuple[AssistantBlockType, str]] = []
    additional = getattr(chunk, "additional_kwargs", None)
    if isinstance(additional, dict):
        reasoning = additional.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            parts.append(("reasoning", reasoning))

    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        if content:
            parts.append(("text", content))
        return tuple(parts)
    if not isinstance(content, list):
        return tuple(parts)

    for item in content:
        if isinstance(item, str):
            if item:
                parts.append(("text", item))
            continue
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in {"reasoning", "reasoning_content", "thinking"}:
            value = _first_text(item, "reasoning", "reasoning_content", "text")
            if value:
                parts.append(("reasoning", value))
        elif item_type in {"text", "text_delta", "output_text"}:
            value = _first_text(item, "text", "content")
            if value:
                parts.append(("text", value))
    return tuple(parts)


class AssistantBlockAssembler:
    """把归一化增量装配成稳定 block，并产生可回放 chunk。"""

    def __init__(self) -> None:
        self._blocks: list[AssistantBlock] = []

    def push(
        self, block_type: AssistantBlockType, delta: str
    ) -> tuple[dict[str, Any], ...]:
        if not delta:
            return ()
        events: list[dict[str, Any]] = []
        if not self._blocks or self._blocks[-1]["type"] != block_type:
            index = len(self._blocks)
            self._blocks.append({"type": block_type, "text": ""})
            events.append(
                {"type": "block_start", "index": index, "block_type": block_type}
            )
        index = len(self._blocks) - 1
        self._blocks[index]["text"] += delta
        events.append(
            {
                "type": f"{block_type}_delta",
                "index": index,
                "delta": delta,
            }
        )
        return tuple(events)

    def finish(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {"type": "block_end", "index": index, "block": dict(block)}
            for index, block in enumerate(self._blocks)
        )

    @property
    def blocks(self) -> tuple[AssistantBlock, ...]:
        return tuple(dict(block) for block in self._blocks)


def _first_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str):
            return value
    return ""
