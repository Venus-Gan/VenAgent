from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.config import EmbeddingConfig
from src.llm.embeddings import EmbeddingError, HttpEmbeddingClient
from src.memory.embedding import MemoryIndex, cosine_similarity
from src.memory.long_term.facts import MemoryFact
from src.memory.model_adapters import StructuredMemoryExtractor
from src.memory.service import MemoryService
from src.ownership.models import Actor, OwnerRecord, SessionRecord
from src.repo.inmemory import InMemoryOwnershipStore, InMemoryPlatformState
from tests.memory._store import InMemoryMemoryStore

NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


class _Embedding:
    def __init__(self, values: dict[str, tuple[float, ...]]) -> None:
        self._values = values

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple(self._values[text] for text in texts)


def _fact(memory_id: str, owner_id: str, fact: str) -> MemoryFact:
    return MemoryFact(
        memory_id,
        owner_id,
        "tenant",
        "我",
        "project",
        fact,
        "active",
        (f"message:{memory_id}",),
        NOW,
        NOW,
    )


def test_cosine_similarity_rejects_invalid_vectors() -> None:
    assert cosine_similarity((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        cosine_similarity((1.0,), (1.0, 0.0))
    with pytest.raises(ValueError):
        cosine_similarity((0.0, 0.0), (1.0, 0.0))


def test_index_search_is_owner_scoped_and_ranked() -> None:
    store = InMemoryMemoryStore()
    embedding = _Embedding(
        {
            "我负责支付系统": (1.0, 0.0),
            "我负责搜索系统": (0.0, 1.0),
            "支付项目": (0.9, 0.1),
        }
    )
    index = MemoryIndex(store, embedding, model="embedding-v1")
    first = _fact("one", "owner-a", "我负责支付系统")
    second = _fact("two", "owner-a", "我负责搜索系统")
    foreign = _fact("three", "owner-b", "我负责支付系统")
    for fact in (first, second, foreign):
        index.project(fact, now=NOW)

    matches = index.search("owner-a", "tenant", "支付项目", limit=5)

    assert tuple(item.memory_id for item in matches) == ("one", "two")
    assert all(item.memory_id != "three" for item in matches)


def test_http_embedding_client_reorders_and_validates_vectors() -> None:
    config = EmbeddingConfig(
        api_url="https://provider.invalid/v1/embeddings",
        api_key="secret",  # type: ignore[arg-type]
        model="embedding-v1",
    )
    calls: list[tuple[str, dict[str, str], dict[str, object], float]] = []

    def request(url, headers, payload, timeout):
        calls.append((url, dict(headers), dict(payload), timeout))
        return {
            "data": [
                {"index": 1, "embedding": [0.0, 1.0]},
                {"index": 0, "embedding": [1.0, 0.0]},
            ]
        }

    client = HttpEmbeddingClient(config, request=request)

    assert client.embed(("a", "b")) == ((1.0, 0.0), (0.0, 1.0))
    assert calls[0][1]["Authorization"] == "Bearer secret"


def test_http_embedding_client_hides_provider_failures() -> None:
    config = EmbeddingConfig(
        api_url="https://provider.invalid/v1/embeddings",
        api_key="secret",  # type: ignore[arg-type]
        model="embedding-v1",
        max_retries=0,
    )

    def request(*_args):
        raise RuntimeError("secret payload and provider response")

    with pytest.raises(EmbeddingError, match="embedding request failed") as captured:
        HttpEmbeddingClient(config, request=request).embed(("private text",))
    assert "private text" not in str(captured.value)
    assert "secret payload" not in str(captured.value)


def test_durable_index_job_uses_owner_epoch_and_duplicate_keeps_ready() -> None:
    owner_id = "11111111-1111-1111-1111-111111111111"
    session_id = "22222222-2222-2222-2222-222222222222"
    state = InMemoryPlatformState(
        owners={owner_id: OwnerRecord(owner_id, "user", "active", 3)},
        sessions={
            session_id: SessionRecord(
                session_id, owner_id, "user", "hash", NOW + timedelta(days=1)
            )
        },
    )
    ownership = InMemoryOwnershipStore(
        state, account_available=True, mode="durable"
    )
    store = InMemoryMemoryStore(durable=True)
    index = MemoryIndex(
        store,
        _Embedding({"我住在杭州": (1.0, 0.0)}),
        model="embedding-v1",
    )
    service = MemoryService(
        store,
        ownership,
        cursor_secret="x" * 32,
        clock=lambda: NOW,
        memory_index=index,
    )
    actor = Actor(owner_id, "user", session_id, "alice", "durable")
    auth = service.command_authorization(actor)

    fact = service.remember(
        auth,
        "我住在杭州",
        source_ref="message:index-job",
        source_order=1,
        explicit=True,
    )
    assert fact is not None and fact.index_status == "pending"

    service.process_pending_jobs(limit=8)
    ready = service.show(auth, fact.memory_id)
    assert ready.index_status == "ready"

    duplicate = service.remember(
        auth,
        "我住在杭州",
        source_ref="message:index-job",
        source_order=1,
        explicit=True,
    )
    assert duplicate is not None and duplicate.index_status == "ready"

    service.forget(auth, fact.memory_id)
    service.process_pending_jobs(limit=8)
    assert store.index_records(
        owner_id, "default", "embedding-v1", "m05-dense-v1"
    ) == ()


def test_extraction_job_delegates_non_regex_facts_to_structured_extractor() -> None:
    owner_id = "33333333-3333-3333-3333-333333333333"
    session_id = "44444444-4444-4444-4444-444444444444"
    content = "我的办公时区是 UTC+8，我的办公地点在上海"
    state = InMemoryPlatformState(
        owners={owner_id: OwnerRecord(owner_id, "user", "active", 1)},
        sessions={
            session_id: SessionRecord(
                session_id, owner_id, "user", "hash", NOW + timedelta(days=1)
            )
        },
    )
    store = InMemoryMemoryStore(durable=True)
    service = MemoryService(
        store,
        InMemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
        extractor=StructuredMemoryExtractor(
            lambda source: json.dumps(
                {
                    "schema_version": "m05-extractor-v1",
                    "candidates": [
                        {
                            "subject": "我",
                            "slot": "timezone",
                            "value": "UTC+8",
                            "fact": "我的办公时区是 UTC+8",
                            "assertion_mode": "statement",
                            "temporal_scope": "current",
                            "confidence": 0.9,
                                "source_span": {
                                    "start": 0,
                                    "end": len("我的办公时区是 UTC+8"),
                                },
                        },
                        {
                            "subject": "我",
                            "slot": "office_location",
                            "value": "上海",
                            "fact": "我的办公地点在上海",
                            "assertion_mode": "statement",
                            "temporal_scope": "current",
                            "confidence": 0.9,
                                "source_span": {
                                    "start": len("我的办公时区是 UTC+8，"),
                                    "end": len(source),
                                },
                        }
                    ],
                },
                ensure_ascii=False,
            )
        ),
    )
    actor = Actor(owner_id, "user", session_id, "alice", "durable")
    auth = service.command_authorization(actor)

    assert service.enqueue_extraction(
        auth,
        content,
        source_ref="message:structured",
        source_order=1,
    )
    assert service.process_pending_jobs() == 1
    facts = store.active_facts(owner_id, "default")
    assert {fact.slot for fact in facts} == {"timezone", "office_location"}
