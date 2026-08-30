"""聊天控制面命令 Registry，取代 run 路由中的硬编码分流。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from ..ownership.models import Actor

CommandKind = Literal["memory_command", "mcp_command", "command", "rag_command"]


@dataclass(frozen=True)
class CommandResult:
    kind: CommandKind
    code: str
    message: str


@dataclass(frozen=True)
class CommandOption:
    command: str
    description: str
    parent: str | None = None


class CommandAdapter(Protocol):
    def matches(self, content: str) -> bool: ...

    def execute(self, actor: Actor, content: str) -> CommandResult: ...

    def options(self) -> tuple[CommandOption, ...]: ...


class CommandRegistry:
    """按固定顺序检查 adapter；都不匹配则不属于控制面命令。"""

    def __init__(self, *adapters: CommandAdapter) -> None:
        self._adapters = tuple(adapters)

    def matches(self, content: str) -> bool:
        return any(adapter.matches(content) for adapter in self._adapters)

    def execute(self, actor: Actor, content: str) -> CommandResult:
        for adapter in self._adapters:
            if adapter.matches(content):
                return adapter.execute(actor, content)
        raise ValueError("unmatched command")

    def options(self) -> tuple[CommandOption, ...]:
        return tuple(option for adapter in self._adapters for option in adapter.options())
