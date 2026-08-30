from __future__ import annotations

from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessageChunk

from venagent.agent.events import normalize_assistant_chunk
from venagent.ownership.models import Actor
from venagent.repo.inmemory import InMemoryConversationRuntimeStore


def actor(owner_id: str = "00000000-0000-0000-0000-000000000001") -> Actor:
    return Actor("guest", owner_id, "session-1", 1)


def test_temporary_run_events_are_ordered_and_owner_scoped() -> None:
    now = datetime.now(timezone.utc)
    store = InMemoryConversationRuntimeStore()
    conversation = store.create_conversation(actor(), now)
    creation = store.create_run(
        actor(), conversation.conversation_id, "问题", "request-1", now
    )

    started = store.append_run_event(
        creation.run.run_id, "run.started", {"phase": "synthesizing"}, now
    )
    chunk = store.append_run_event(
        creation.run.run_id,
        "assistant.chunk",
        {
            "execution_attempt": 1,
            "chunk": {
                "type": "text_delta",
                "index": 0,
                "delta": "回答",
            },
        },
        now,
    )

    assert (started.sequence, chunk.sequence) == (1, 2)
    assert store.run_events(actor().owner_id, creation.run.run_id) == (
        started,
        chunk,
    )
    assert store.run_events(actor().owner_id, creation.run.run_id, after_sequence=1) == (
        chunk,
    )
    with pytest.raises(Exception):
        store.run_events(
            "00000000-0000-0000-0000-000000000002", creation.run.run_id
        )


def test_normalize_assistant_chunk_keeps_explicit_reasoning_separate() -> None:
    chunk = AIMessageChunk(
        content="正文",
        additional_kwargs={"reasoning_content": "分析"},
    )

    assert normalize_assistant_chunk(chunk) == (
        ("reasoning", "分析"),
        ("text", "正文"),
    )


def test_normalize_assistant_chunk_supports_standard_content_blocks() -> None:
    chunk = AIMessageChunk(
        content=[
            {"type": "reasoning", "reasoning": "先判断"},
            {"type": "text", "text": "再回答"},
        ]
    )

    assert normalize_assistant_chunk(chunk) == (
        ("reasoning", "先判断"),
        ("text", "再回答"),
    )
