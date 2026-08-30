"""按 Tool 来源路由真实执行；Gateway 仍是唯一入口。

Source Executor 契约：`(descriptor, arguments, run_id, owner_id) -> ToolResult`；
router 以 inspect 兼容只接收 `(descriptor, arguments, run_id)` 的旧执行器。
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from .errors import ToolUnavailable
from .models import ToolDescriptor, ToolResult

SourceExecutor = Callable[..., Awaitable[ToolResult]]


class ToolExecutorRouter:
    def __init__(self) -> None:
        self._executors: dict[str, SourceExecutor] = {}

    def register(self, source: str, executor: SourceExecutor) -> None:
        self._executors[source] = executor

    async def __call__(
        self,
        descriptor: ToolDescriptor,
        arguments: dict[str, Any],
        run_id: str,
        owner_id: str | None = None,
    ) -> ToolResult:
        executor = self._executors.get(descriptor.source)
        if executor is None:
            raise ToolUnavailable
        if _accepts_owner(executor):
            return await executor(descriptor, arguments, run_id, owner_id)
        return await executor(descriptor, arguments, run_id)


def _accepts_owner(executor: SourceExecutor) -> bool:
    try:
        parameters = list(inspect.signature(executor).parameters.values())
    except (TypeError, ValueError):
        return False
    positional = [
        item
        for item in parameters
        if item.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if any(item.kind == inspect.Parameter.VAR_POSITIONAL for item in parameters):
        return True
    return len(positional) >= 4
