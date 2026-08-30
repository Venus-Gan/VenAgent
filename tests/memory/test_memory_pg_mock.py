"""memory 仓储层（mock）契约：临时仓储快照锁、PG repeatable-read 快照、任务租约/idempotent 队列、快照一致性校验（原 test_memory_context.py 拆分六）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event, Thread

import pytest

from tests.memory._store import InMemoryMemoryStore
from venagent.memory.errors import MemoryPurgePending
from venagent.memory.service import MemoryService
from venagent.repo.inmemory import (
    InMemoryOwnershipStore as MemoryOwnershipStore,
)
from venagent.repo.postgresql.memory import PostgresMemoryStore

NOW = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)

def test_async_extraction_is_idempotent_and_stale_generation_cannot_revive_data(memory_service, run_memory_auth) -> None:
    service, store, actor, _state = memory_service()
    auth = run_memory_auth(service, actor)

    first = service.enqueue_extraction(
        auth,
        "我住在杭州",
        source_ref="message:async",
        source_order=1,
    )
    duplicate = service.enqueue_extraction(
        auth,
        "我住在杭州",
        source_ref="message:async",
        source_order=1,
    )
    command_auth = service.command_authorization(actor)
    token, _count = service.request_delete_all(command_auth)
    service.confirm_delete_all(command_auth, token)

    assert first is True and duplicate is False
    with pytest.raises(MemoryPurgePending):
        service.set_enabled(command_auth, True)
    service.process_pending_jobs(limit=8)
    assert store.active_facts(actor.owner_id, "default") == ()
    assert store.settings(actor.owner_id).purge_pending is False

def test_claimed_job_lease_is_recovered_after_worker_loss(memory_service, run_memory_auth) -> None:
    service, store, actor, _state = memory_service()
    auth = run_memory_auth(service, actor)
    service.enqueue_extraction(
        auth,
        "我住在杭州",
        source_ref="message:lease",
        source_order=1,
    )

    first_claim = store.claim_jobs(NOW, limit=1)
    before_expiry = store.claim_jobs(NOW + timedelta(seconds=29), limit=1)
    recovered = store.claim_jobs(NOW + timedelta(seconds=31), limit=1)

    assert first_claim[0].attempts == 1
    assert before_expiry == ()
    assert recovered[0].job_id == first_claim[0].job_id
    assert recovered[0].attempts == 2
    assert first_claim[0].claim_token != recovered[0].claim_token
    assert (
        store.complete_job(
            first_claim[0].job_id,
            first_claim[0].claim_token or "",
            NOW + timedelta(seconds=31),
        )
        is False
    )
    assert (
        store.complete_job(
            recovered[0].job_id,
            recovered[0].claim_token or "",
            NOW + timedelta(seconds=31),
        )
        is True
    )

def test_recall_discards_snapshot_when_deletion_generation_changes(memory_service, save_recall_fact) -> None:
    class GenerationChangingStore(InMemoryMemoryStore):
        change_generation = False

        def recall_snapshot(self, owner_id, tenant_id):
            snapshot = super().recall_snapshot(owner_id, tenant_id)
            if self.change_generation:
                with self._lock:
                    self._settings[owner_id] = replace(
                        snapshot.settings,
                        deletion_generation=snapshot.settings.deletion_generation + 1,
                    )
                self.change_generation = False
            return snapshot

    _unused, _store, actor, state = memory_service()
    store = GenerationChangingStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)
    save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0005-000000000001",
        "我住在杭州",
        1,
    )
    store.change_generation = True

    assert service.context_blocks(auth, "杭州") == ()

def test_recall_discards_snapshot_when_authorization_epoch_changes(memory_service, save_recall_fact) -> None:
    class EpochChangingStore(InMemoryMemoryStore):
        revoke = None

        def recall_snapshot(self, owner_id, tenant_id):
            snapshot = super().recall_snapshot(owner_id, tenant_id)
            if self.revoke is not None:
                revoke, self.revoke = self.revoke, None
                revoke()
            return snapshot

    _unused, _store, actor, state = memory_service()
    store = EpochChangingStore(durable=True)
    ownership = MemoryOwnershipStore(state, account_available=True, mode="durable")
    service = MemoryService(
        store,
        ownership,
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)
    save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0006-000000000001",
        "我住在杭州",
        1,
    )
    store.revoke = lambda: ownership.mark_owner_deleting(actor.owner_id, NOW)

    assert service.context_blocks(auth, "杭州") == ()

def test_temporary_recall_snapshot_holds_one_lock_for_all_components() -> None:
    class PausingStore(InMemoryMemoryStore):
        pause = False
        entered = Event()
        release = Event()

        def active_facts(self, owner_id, tenant_id):
            values = super().active_facts(owner_id, tenant_id)
            if self.pause:
                self.entered.set()
                assert self.release.wait(timeout=2)
            return values

    store = PausingStore(durable=True)
    owner_id = "11111111-1111-1111-1111-111111111111"
    store.pause = True
    snapshots = []
    writer_done = Event()
    reader = Thread(
        target=lambda: snapshots.append(store.recall_snapshot(owner_id, "default"))
    )
    reader.start()
    assert store.entered.wait(timeout=2)

    writer = Thread(
        target=lambda: (
            store.set_enabled(owner_id, False, NOW),
            writer_done.set(),
        )
    )
    writer.start()
    assert not writer_done.wait(timeout=0.05)
    store.release.set()
    reader.join(timeout=2)
    writer.join(timeout=2)

    assert snapshots[0].settings.enabled is True
    assert writer_done.is_set()

def test_postgres_recall_snapshot_starts_one_repeatable_read_transaction() -> None:
    class EmptyResult:
        @staticmethod
        def fetchone():
            return None

        @staticmethod
        def fetchall():
            return ()

    class Context:
        def __init__(self, value):
            self.value = value

        def __enter__(self):
            return self.value

        def __exit__(self, exc_type, exc, traceback):
            return False

    class Connection:
        def __init__(self):
            self.statements = []
            self.transaction_count = 0

        def transaction(self):
            self.transaction_count += 1
            return Context(self)

        def execute(self, query, params=None):
            del params
            self.statements.append(" ".join(query.split()))
            return EmptyResult()

    connection = Connection()

    class Pool:
        @staticmethod
        def connection():
            return Context(connection)

    store = PostgresMemoryStore(Pool())  # type: ignore[arg-type]

    snapshot = store.recall_snapshot("owner", "tenant")

    assert connection.transaction_count == 1
    assert connection.statements[0] == (
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    )
    assert any("FROM memory_facts" in item for item in connection.statements)
    assert any("FROM memory_sources" in item for item in connection.statements)
    assert any("FROM memory_graph_authority" in item for item in connection.statements)
    assert all("memory_edges" not in item for item in connection.statements)
    assert snapshot.owner_id == "owner" and snapshot.tenant_id == "tenant"