"""HTTP route group 的稳定注册入口。"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from ....agent.runtime import AgentRuntime
from ....command.registry import CommandRegistry
from ....config import AppConfig
from ....conversation.service import ConversationService
from ....document import DocumentService
from ....mcp.client import McpClientManager
from ....mcp.config import McpConfigStore
from ....ownership.service import OwnershipService
from ....skills.hub import SkillHubService
from ....tools.control import ToolControlContext
from .auth import register_auth_routes
from .control import register_control_routes
from .conversations import register_conversation_routes
from .documents import register_document_routes
from .runs import register_run_routes
from .settings import register_settings_routes


def register_routes(
    app: FastAPI,
    service: ConversationService,
    runtime: AgentRuntime,
    ownership: OwnershipService,
    command_registry: CommandRegistry,
    config: AppConfig,
    finish_account_deletion: Callable[[str], None],
    tool_control: ToolControlContext,
    mcp_store: McpConfigStore,
    mcp_manager: McpClientManager,
    skill_hub: SkillHubService,
    document_service: DocumentService | None = None,
) -> None:
    register_auth_routes(app, ownership, config, finish_account_deletion)
    register_control_routes(
        app,
        ownership,
        tool_control,
        mcp_store,
        mcp_manager,
        skill_hub,
        runtime,
    )
    register_conversation_routes(app, service, runtime, ownership)
    register_run_routes(
        app, service, runtime, ownership, command_registry, tool_control
    )
    register_settings_routes(app, ownership, config)
    register_document_routes(app, document_service, ownership, config)


__all__ = ["register_routes"]
