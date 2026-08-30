"""memory 隔离契约：歧义候选隔离、新证据重评、TTL 过期、解析失败不解除隔离（原 test_memory_context.py 拆分四）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.memory.ports import MemoryStoreError as StoreError
from src.memory.service import MemoryService
from src.repo.inmemory import (
    InMemoryOwnershipStore as MemoryOwnershipStore,
)
from tests.memory._store import InMemoryMemoryStore

NOW = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)

def test_ambiguous_candidate_is_quarantined_hidden_and_expires(memory_service) -> None:
    current = [NOW]
    service, store, actor, state = memory_service()
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: current[0],
    )
    auth = service.command_authorization(actor)

    candidate = service.remember(
        auth,
        "我住在杭州，我住在苏州",
        source_ref="message:ambiguous",
        source_order=1,
        explicit=False,
    )

    assert candidate is not None and candidate.status == "quarantine"
    assert service.list(auth).items == ()
    assert service.context_blocks(auth, "我住在哪里") == ()

    current[0] = NOW + timedelta(days=31)
    assert store.expire_due(current[0]) == 1
    expired = store.get_fact(actor.owner_id, candidate.memory_id)
    assert expired is not None
    assert expired.status == "expired" and expired.fact == ""

def test_new_qualified_source_re_evaluates_quarantine_and_temporal_ttl_is_enforced(memory_service) -> None:
    current = [NOW]
    service, store, actor, state = memory_service()
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: current[0],
        quarantine_ttl=timedelta(days=7),
    )
    auth = service.command_authorization(actor)
    quarantined = service.remember(
        auth,
        "我目前住在杭州，我目前住在苏州",
        source_ref="message:ambiguous-ttl",
        source_order=1,
        explicit=False,
    )
    resolved = service.remember(
        auth,
        "我目前住在苏州",
        source_ref="message:resolved",
        source_order=2,
        explicit=False,
    )

    assert quarantined is not None and resolved is not None
    assert store.get_fact(actor.owner_id, quarantined.memory_id).status == "superseded"
    assert service.list(auth).items == (resolved,)

    current[0] = NOW + timedelta(days=181)
    assert service.list(auth).items == ()
    assert store.get_fact(actor.owner_id, resolved.memory_id).status == "expired"

def test_quarantine_is_not_resolved_when_replacement_persistence_fails(memory_service) -> None:
    class FailingResolvedFactStore(InMemoryMemoryStore):
        fail_active_write = False

        def save_fact(self, fact, source, now):
            if self.fail_active_write and fact.status == "active":
                raise StoreError("injected active fact failure")
            return super().save_fact(fact, source, now)

    _unused, _store, actor, state = memory_service()
    store = FailingResolvedFactStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)
    quarantined = service.remember(
        auth,
        "我住在杭州，我住在苏州",
        source_ref="message:quarantine-before-failure",
        source_order=1,
        explicit=False,
    )
    assert quarantined is not None

    store.fail_active_write = True
    with pytest.raises(StoreError):
        service.remember(
            auth,
            "我住在苏州",
            source_ref="message:failed-resolution",
            source_order=2,
            explicit=False,
        )

    unchanged = store.get_fact(actor.owner_id, quarantined.memory_id)
    assert unchanged is not None and unchanged.status == "quarantine"