"""In-memory conversation 查询、标题与删除 adapter 行为。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4

from ...agent.runs import AgentRun
from ...conversation.errors import (
    AnonymousLimitExceeded,
    ConversationNotFound,
)
from ...conversation.models import Conversation, ConversationMessage
from ...ownership.errors import SessionInactive
from ...ownership.models import Actor
from .state import InMemoryPlatformState


class _InMemoryConversationMixin:
    state: InMemoryPlatformState

    def create_conversation(self, actor: Actor, now: datetime) -> Conversation:
        with self.state.lock:
            self._require_active_owner_if_known(actor.owner_id)
            if actor.kind != "user":
                live = sum(
                    item.owner_id == actor.owner_id
                    and item.lifecycle_state == "active"
                    for item in self.state.conversations.values()
                )
                attempts = self.state.guest_creates[actor.owner_id]
                cutoff = now - timedelta(minutes=10)
                while attempts and attempts[0] <= cutoff:
                    attempts.popleft()
                if live >= 10 or len(attempts) >= 5:
                    raise AnonymousLimitExceeded
                attempts.append(now)
            conversation = Conversation(
                str(uuid4()),
                actor.owner_id,
                actor.kind,
                "active",
                "新对话",
                "auto",
                now,
                now,
            )
            self.state.conversations[conversation.conversation_id] = conversation
            return conversation

    def get_conversation(
        self, owner_id: str, conversation_id: str
    ) -> Conversation | None:
        with self.state.lock:
            item = self.state.conversations.get(conversation_id)
            return item if item is not None and item.owner_id == owner_id else None

    def list_conversations(
        self,
        owner_id: str,
        *,
        before: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[Conversation, ...]:
        with self.state.lock:
            items = [
                item
                for item in self.state.conversations.values()
                if item.owner_id == owner_id and item.lifecycle_state == "active"
            ]
            items.sort(
                key=lambda item: (item.updated_at, item.conversation_id), reverse=True
            )
            if before is not None:
                items = [
                    item
                    for item in items
                    if (item.updated_at, item.conversation_id) < before
                ]
            return tuple(items[:limit])

    def messages(
        self, owner_id: str, conversation_id: str
    ) -> tuple[ConversationMessage, ...]:
        if self.get_conversation(owner_id, conversation_id) is None:
            return ()
        with self.state.lock:
            return tuple(self.state.messages.get(conversation_id, ()))

    def conversation_runs(
        self, owner_id: str, conversation_id: str
    ) -> tuple[AgentRun, ...]:
        if self.get_conversation(owner_id, conversation_id) is None:
            return ()
        with self.state.lock:
            return tuple(
                sorted(
                    (
                        run
                        for run in self.state.runs.values()
                        if run.conversation_id == conversation_id
                    ),
                    key=lambda run: (run.created_at, run.run_id),
                )
            )

    def rename_conversation(
        self, owner_id: str, conversation_id: str, title: str, now: datetime
    ) -> Conversation:
        with self.state.lock:
            conversation = self.get_conversation(owner_id, conversation_id)
            if conversation is None or conversation.lifecycle_state != "active":
                raise KeyError(conversation_id)
            updated = replace(
                conversation, title=title, title_source="manual", updated_at=now
            )
            self.state.conversations[conversation_id] = updated
            return updated

    def mark_conversation_deleting(
        self, owner_id: str, conversation_id: str, now: datetime
    ) -> tuple[str, ...]:
        with self.state.lock:
            conversation = self.get_conversation(owner_id, conversation_id)
            if conversation is None:
                return ()
            self.state.conversations[conversation_id] = replace(
                conversation, lifecycle_state="deleting", updated_at=now
            )
            run_ids: list[str] = []
            for run_id, run in tuple(self.state.runs.items()):
                if run.conversation_id == conversation_id and not run.terminal:
                    run_ids.append(run_id)
                    self.state.runs[run_id] = replace(
                        run,
                        cancel_requested_at=run.cancel_requested_at or now,
                        updated_at=now,
                    )
            return tuple(run_ids)

    def remove_conversation(self, owner_id: str, conversation_id: str) -> None:
        with self.state.lock:
            conversation = self.state.conversations.get(conversation_id)
            if conversation is None or conversation.owner_id != owner_id:
                return
            run_ids = {
                run.run_id
                for run in self.state.runs.values()
                if run.conversation_id == conversation_id
            }
            for run_id in run_ids:
                run = self.state.runs.pop(run_id)
                self.state.grants.pop(run.grant_id, None)
            for key in tuple(self.state.requests):
                if key[0] == conversation_id:
                    self.state.requests.pop(key, None)
            self.state.messages.pop(conversation_id, None)
            self.state.conversations.pop(conversation_id, None)

    def deleting_conversations(self) -> tuple[tuple[str, str], ...]:
        with self.state.lock:
            return tuple(
                (item.owner_id, item.conversation_id)
                for item in self.state.conversations.values()
                if item.lifecycle_state == "deleting"
            )

    def owner_conversation_ids(self, owner_id: str) -> tuple[str, ...]:
        with self.state.lock:
            return tuple(
                item.conversation_id
                for item in self.state.conversations.values()
                if item.owner_id == owner_id
            )

    def expired_guest_conversations(
        self, now: datetime
    ) -> tuple[tuple[str, str], ...]:
        with self.state.lock:
            return tuple(
                (item.owner_id, item.conversation_id)
                for item in self.state.conversations.values()
                if item.owner_kind != "user"
                and item.lifecycle_state == "active"
                and (item.last_successful_at or item.created_at) + timedelta(days=7)
                <= now
            )

    def _require_conversation(
        self, owner_id: str, conversation_id: str
    ) -> Conversation:
        item = self.state.conversations.get(conversation_id)
        if item is None or item.owner_id != owner_id:
            raise ConversationNotFound
        return item

    def _next_sequence(self, conversation_id: str) -> int:
        return (
            max(
                (item.sequence for item in self.state.messages[conversation_id]),
                default=0,
            )
            + 1
        )

    def _require_active_owner_if_known(self, owner_id: str) -> None:
        owner = self.state.owners.get(owner_id)
        if owner is not None and owner.lifecycle_state != "active":
            raise SessionInactive
