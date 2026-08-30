"""把既有 MemoryCommandAdapter 包装为统一命令契约。"""

from __future__ import annotations

from ..memory.management import MemoryCommandAdapter as LegacyMemoryCommands
from ..ownership.models import Actor
from .registry import CommandOption, CommandResult


class MemoryCommandAdapter:
    def __init__(self, adapter: LegacyMemoryCommands) -> None:
        self._adapter = adapter

    @staticmethod
    def matches(content: str) -> bool:
        return LegacyMemoryCommands.matches(content)

    def execute(self, actor: Actor, content: str) -> CommandResult:
        result = self._adapter.execute(actor, content)
        return CommandResult(
            kind="memory_command", code=result.code, message=result.message
        )

    @staticmethod
    def options() -> tuple[CommandOption, ...]:
        return (
            CommandOption("/memory", "查看长期记忆"),
            CommandOption("/memory status", "查看记忆状态", "/memory"),
            CommandOption("/memory list", "列出长期记忆", "/memory"),
            CommandOption("/memory show <id>", "查看一条记忆", "/memory"),
            CommandOption("/memory update <id> <fact>", "更新一条记忆", "/memory"),
            CommandOption("/memory forget <id>", "忘记一条记忆", "/memory"),
            CommandOption("/memory revoke-source <source>", "撤销来源", "/memory"),
            CommandOption("/memory disable", "停用长期记忆", "/memory"),
            CommandOption("/memory enable", "启用长期记忆", "/memory"),
            CommandOption("/memory delete-all", "删除全部长期记忆", "/memory"),
        )
