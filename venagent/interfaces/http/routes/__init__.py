"""HTTP route group 的稳定注册入口。"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from ....agent.runtime import AgentRuntime
from ....config import AppConfig
from ....conversation.service import ConversationService
from ....memory.command_adapter import MemoryCommandAdapter
from ....ownership.service import OwnershipService
from .auth import register_auth_routes
from .conversations import register_conversation_routes
from .runs import register_run_routes


def register_routes(
    app: FastAPI,
    service: ConversationService,
    runtime: AgentRuntime,
    ownership: OwnershipService,
    memory_commands: MemoryCommandAdapter,
    config: AppConfig,
    finish_account_deletion: Callable[[str], None],
) -> None:
    register_auth_routes(app, ownership, config, finish_account_deletion)
    register_conversation_routes(app, service, runtime, ownership)
    register_run_routes(app, service, runtime, ownership, memory_commands)


__all__ = ["register_routes"]
