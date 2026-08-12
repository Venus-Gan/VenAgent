from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from venagent.agent.runs import AgentRunLifecycle
from venagent.conversation.errors import (
    ConversationNotFound,
    InvalidConversationId,
    RetryNotAllowed,
)
from venagent.conversation.service import ConversationService
from venagent.ownership.models import Actor
from venagent.repo.temporary import (
    TemporaryConversationRuntimeStore as MemoryRuntimeStore,
)

NOW = datetime(2026, 8, 3, tzinfo=timezone.utc)
ACTOR = Actor("owner-a", "user", "session-a", "alice", "durable")


def service() -> tuple[ConversationService, MemoryRuntimeStore]:
    store = MemoryRuntimeStore()
    return ConversationService(store, clock=lambda: NOW), store


def test_service_creates_owner_scoped_conversation_and_persists_user_message() -> None:
    app, _store = service()
    conversation = app.create_conversation(ACTOR)
    created = app.create_run(ACTOR, conversation.conversation_id, "问题", str(uuid4()))

    assert UUID(conversation.conversation_id)
    detail = app.get_conversation(ACTOR, conversation.conversation_id)
    assert detail.messages == (created.input_message,)
    assert detail.runs == (created.run,)


def test_invalid_and_cross_owner_conversation_are_safe_distinct_boundaries() -> None:
    app, _store = service()
    conversation = app.create_conversation(ACTOR)

    with pytest.raises(InvalidConversationId):
        app.get_conversation(ACTOR, "invalid")
    with pytest.raises(ConversationNotFound):
        app.get_conversation(
            Actor("owner-b", "user", "session-b", "bob", "durable"),
            conversation.conversation_id,
        )


def test_retry_creates_new_run_for_latest_unfinished_message_only() -> None:
    app, store = service()
    conversation = app.create_conversation(ACTOR)
    first = app.create_run(ACTOR, conversation.conversation_id, "问题", str(uuid4()))
    lifecycle = AgentRunLifecycle(store)
    claimed = lifecycle.claim_next("worker", NOW, timedelta(seconds=60))
    assert claimed is not None
    lifecycle.fail(
        claimed.run_id,
        claimed.claim_token or "",
        claimed.execution_attempt,
        "model_error",
        "模型调用失败",
        NOW,
    )

    retry = app.retry_run(ACTOR, first.run.run_id, str(uuid4()))

    assert retry.run.run_id != first.run.run_id
    assert retry.run.input_message_id == first.input_message.message_id
    assert retry.run.retry_of_run_id == first.run.run_id
    claimed_retry = lifecycle.claim_next("worker", NOW, timedelta(seconds=60))
    assert claimed_retry is not None
    lifecycle.fail(
        claimed_retry.run_id,
        claimed_retry.claim_token or "",
        claimed_retry.execution_attempt,
        "model_error",
        "模型调用失败",
        NOW,
    )
    app.create_run(ACTOR, conversation.conversation_id, "新问题", str(uuid4()))
    with pytest.raises(RetryNotAllowed):
        app.retry_run(ACTOR, first.run.run_id, str(uuid4()))
