"""Conversation application service 消费的持久化契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..agent.runs import AgentRun
from ..ownership.models import Actor
from .models import (
    Conversation,
    ConversationMessage,
    RunCreation,
)


class ConversationStoreError(RuntimeError):
    """adapter 对外只暴露安全错误，不泄露连接或 SQL 细节。"""


class ConversationStore(Protocol):
    durable: bool

    def create_conversation(self, actor: Actor, now: datetime) -> Conversation: ...

    def get_conversation(
        self, owner_id: str, conversation_id: str
    ) -> Conversation | None: ...

    def list_conversations(
        self,
        owner_id: str,
        *,
        before: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[Conversation, ...]: ...

    def messages(
        self, owner_id: str, conversation_id: str
    ) -> tuple[ConversationMessage, ...]: ...

    def conversation_runs(
        self, owner_id: str, conversation_id: str
    ) -> tuple[AgentRun, ...]: ...

    def create_run(
        self,
        actor: Actor,
        conversation_id: str,
        message: str,
        client_request_id: str,
        now: datetime,
    ) -> RunCreation: ...

    def retry_run(
        self,
        actor: Actor,
        source_run_id: str,
        client_request_id: str,
        now: datetime,
    ) -> RunCreation: ...

    def get_run(self, owner_id: str, run_id: str) -> AgentRun | None: ...

    def rename_conversation(
        self, owner_id: str, conversation_id: str, title: str, now: datetime
    ) -> Conversation: ...

    def mark_conversation_deleting(
        self, owner_id: str, conversation_id: str, now: datetime
    ) -> tuple[str, ...]: ...

    def remove_conversation(self, owner_id: str, conversation_id: str) -> None: ...

    def deleting_conversations(self) -> tuple[tuple[str, str], ...]: ...

    def owner_conversation_ids(self, owner_id: str) -> tuple[str, ...]: ...

    def expired_guest_conversations(
        self, now: datetime
    ) -> tuple[tuple[str, str], ...]: ...
