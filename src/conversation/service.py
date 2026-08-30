"""Owner-scoped conversation、正式消息和 run 创建用例。"""

from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import datetime, timezone

from ..agent.ports import RunStore
from ..agent.runs import AgentRun, validate_run_id
from ..ownership.models import Actor
from .errors import ConversationNotFound, InvalidConversationId
from .models import Conversation, ConversationDetail, ConversationPage, RunCreation
from .ports import ConversationStore
from .rules import (
    validate_client_request_id,
    validate_conversation_id,
    validate_message,
    validate_title,
)


class ConversationService:
    def __init__(
        self,
        store: ConversationStore,
        *,
        run_store: RunStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        # 当前 adapter 同时实现两个 port；显式字段阻止业务契约再次聚合。
        self._run_store = run_store or store  # type: ignore[assignment]
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def store(self) -> ConversationStore:
        return self._store

    def create_conversation(self, actor: Actor) -> Conversation:
        return self._store.create_conversation(actor, self._now())

    def list_conversations(
        self, actor: Actor, *, cursor: str | None = None, limit: int = 20
    ) -> ConversationPage:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        before = _decode_cursor(cursor) if cursor else None
        rows = self._store.list_conversations(
            actor.owner_id, before=before, limit=limit + 1
        )
        visible = rows[:limit]
        next_cursor = None
        if len(rows) > limit and visible:
            last = visible[-1]
            next_cursor = _encode_cursor(last.updated_at, last.conversation_id)
        return ConversationPage(visible, next_cursor)

    def get_conversation(
        self, actor: Actor, conversation_id: str
    ) -> ConversationDetail:
        canonical = validate_conversation_id(conversation_id)
        conversation = self._store.get_conversation(actor.owner_id, canonical)
        if conversation is None or conversation.lifecycle_state != "active":
            raise ConversationNotFound
        return ConversationDetail(
            conversation,
            self._store.messages(actor.owner_id, canonical),
            self._store.conversation_runs(actor.owner_id, canonical),
        )

    def create_run(
        self,
        actor: Actor,
        conversation_id: str,
        message: str,
        client_request_id: str,
    ) -> RunCreation:
        canonical = validate_conversation_id(conversation_id)
        content = validate_message(message)
        request_id = validate_client_request_id(client_request_id)
        return self._store.create_run(
            actor, canonical, content, request_id, self._now()
        )

    def retry_run(
        self, actor: Actor, run_id: str, client_request_id: str
    ) -> RunCreation:
        return self._store.retry_run(
            actor,
            validate_run_id(run_id),
            validate_client_request_id(client_request_id),
            self._now(),
        )

    def get_run(self, actor: Actor, run_id: str) -> AgentRun:
        run = self._store.get_run(actor.owner_id, validate_run_id(run_id))
        if run is None:
            from ..agent.runs import RunNotFound

            raise RunNotFound
        return run

    def set_run_skill(
        self,
        actor: Actor,
        run_id: str,
        skill_id: str | None,
        skill_name: str | None,
    ) -> AgentRun:
        return self._run_store.set_run_skill(
            actor.owner_id,
            validate_run_id(run_id),
            skill_id,
            skill_name,
            self._now(),
        )

    def request_cancel(self, actor: Actor, run_id: str) -> AgentRun:
        canonical = validate_run_id(run_id)
        return self._run_store.request_cancel(actor.owner_id, canonical, self._now())

    def rename_conversation(
        self, actor: Actor, conversation_id: str, title: str
    ) -> Conversation:
        canonical = validate_conversation_id(conversation_id)
        normalized = validate_title(title)
        try:
            return self._store.rename_conversation(
                actor.owner_id, canonical, normalized, self._now()
            )
        except KeyError as exc:
            raise ConversationNotFound from exc

    def delete_conversation(
        self, actor: Actor, conversation_id: str
    ) -> tuple[str, ...]:
        canonical = validate_conversation_id(conversation_id)
        return self._store.mark_conversation_deleting(
            actor.owner_id, canonical, self._now()
        )

    def finish_conversation_deletion(self, owner_id: str, conversation_id: str) -> None:
        self._store.remove_conversation(owner_id, conversation_id)

    def mark_owner_conversation_deleting(
        self, owner_id: str, conversation_id: str
    ) -> tuple[str, ...]:
        return self._store.mark_conversation_deleting(
            owner_id, conversation_id, self._now()
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _encode_cursor(updated_at: datetime, conversation_id: str) -> str:
    raw = f"{updated_at.isoformat()}|{conversation_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
        timestamp, conversation_id = raw.split("|", 1)
        return datetime.fromisoformat(timestamp), validate_conversation_id(
            conversation_id
        )
    except Exception as exc:
        raise InvalidConversationId from exc
