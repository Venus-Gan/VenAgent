"""Conversation 与正式消息的不可变业务模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ..agent.runs import AgentRun
from ..ownership.models import ActorKind


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
    owner_id: str
    owner_kind: ActorKind
    lifecycle_state: Literal["active", "deleting"]
    title: str
    title_source: Literal["auto", "manual"]
    created_at: datetime
    updated_at: datetime
    last_successful_at: datetime | None = None


@dataclass(frozen=True)
class ConversationMessage:
    message_id: str
    conversation_id: str
    owner_id: str
    role: Literal["user", "assistant"]
    content: str
    sequence: int
    created_at: datetime
    client_request_id: str | None = None
    source_run_id: str | None = None
    reply_to_message_id: str | None = None
    content_blocks: tuple[dict[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "content_blocks", tuple(dict(item) for item in self.content_blocks)
        )


@dataclass(frozen=True)
class ConversationPage:
    items: tuple[Conversation, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class ConversationDetail:
    conversation: Conversation
    messages: tuple[ConversationMessage, ...]
    runs: tuple[AgentRun, ...]


@dataclass(frozen=True)
class RunCreation:
    run: AgentRun
    input_message: ConversationMessage
