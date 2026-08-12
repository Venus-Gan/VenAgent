from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event, Thread

import pytest

from venagent.memory.authorization import MemoryAuthorization
from venagent.memory.capabilities import (
    MemoryCapabilityRegistry,
    MemoryCapabilityStatus,
)
from venagent.memory.command_adapter import MemoryCommandAdapter
from venagent.memory.errors import (
    MemoryConfirmationInvalid,
    MemoryDisableNotPersisted,
    MemoryInvalidCursor,
    MemoryPurgePending,
    MemoryUnauthorized,
    MemoryUnsafeContent,
    MemoryUnsupported,
)
from venagent.memory.graph import MemoryEdge, build_g1_edges, replay_g1_edges
from venagent.memory.long_term.extractor import StructuredMemoryExtractor
from venagent.memory.long_term.facts import MemoryFact, MemorySource
from venagent.memory.ports import G1GraphSnapshot
from venagent.memory.ports import MemoryStoreError as StoreError
from venagent.memory.service import MemoryService
from venagent.ownership.models import (
    Actor,
    ExecutionAuthorization,
    OwnerRecord,
    SessionRecord,
)
from venagent.repo.postgresql.memory import PostgresMemoryStore
from venagent.repo.temporary import (
    TemporaryOwnershipStore as MemoryOwnershipStore,
)
from venagent.repo.temporary import (
    TemporaryPlatformState as MemoryState,
)
from venagent.repo.temporary.memory import TemporaryMemoryStore as InMemoryMemoryStore

NOW = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)


def _service(owner_id: str = "11111111-1111-1111-1111-111111111111"):
    session_id = "22222222-2222-2222-2222-222222222222"
    state = MemoryState(
        owners={owner_id: OwnerRecord(owner_id, "user", "active", 3)},
        sessions={
            session_id: SessionRecord(
                session_id,
                owner_id,
                "user",
                "hash",
                NOW + timedelta(days=1),
            )
        },
    )
    ownership = MemoryOwnershipStore(state, account_available=True, mode="durable")
    store = InMemoryMemoryStore(durable=True)
    service = MemoryService(store, ownership, cursor_secret="x" * 32, clock=lambda: NOW)
    actor = Actor(owner_id, "user", session_id, "alice", "durable")
    return service, store, actor, state


def test_command_authorization_is_bound_to_active_session_and_epoch() -> None:
    service, _store, actor, state = _service()
    auth = service.command_authorization(actor)

    assert auth.owner_id == actor.owner_id
    assert auth.authorization_epoch == 3
    assert auth.run_id is None
    assert auth.source_kind == "command"

    state.owners[actor.owner_id] = OwnerRecord(actor.owner_id, "user", "active", 4)
    with pytest.raises(MemoryUnauthorized):
        service.status(auth)


def test_memory_update_command_can_read_its_authorized_target() -> None:
    service, store, actor, _state = _service()
    adapter = MemoryCommandAdapter(service)
    remembered = service.remember(
        service.command_authorization(actor, action="write"),
        "我叫小维",
        source_ref="message:update-command",
        source_order=1,
        explicit=True,
    )

    assert remembered is not None
    original = store.active_facts(actor.owner_id, "default")[0]

    updated = adapter.execute(actor, f"/memory update {original.memory_id} 我叫阿维")

    assert updated.code == "memory_updated"
    assert store.get_fact(actor.owner_id, original.memory_id).status == "superseded"


def test_durable_guest_cannot_enable_or_write_long_term_memory() -> None:
    owner_id = "88888888-8888-8888-8888-888888888888"
    session_id = "99999999-9999-9999-9999-999999999999"
    state = MemoryState(
        owners={owner_id: OwnerRecord(owner_id, "guest", "active", 1)},
        sessions={
            session_id: SessionRecord(
                session_id,
                owner_id,
                "guest",
                "hash",
                NOW + timedelta(days=1),
            )
        },
    )
    ownership = MemoryOwnershipStore(state, account_available=True, mode="durable")
    service = MemoryService(
        InMemoryMemoryStore(durable=True),
        ownership,
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    actor = Actor(owner_id, "guest", session_id, mode="durable")
    auth = service.command_authorization(actor, action="write")

    assert service.status(service.command_authorization(actor)).state == "DISABLED"
    with pytest.raises(MemoryUnsupported):
        service.set_enabled(service.command_authorization(actor), True)
    with pytest.raises(MemoryUnsupported):
        service.remember(
            auth,
            "记住，我叫小维",
            source_ref="message:guest",
            source_order=1,
            explicit=True,
        )


def test_fact_update_delete_source_and_g1_edges_are_lifecycle_safe() -> None:
    service, store, actor, _state = _service()
    auth = service.command_authorization(actor)
    first = service.remember(
        auth,
        "记住，我叫小维",
        source_ref="message:1",
        source_order=1,
        explicit=True,
    )
    second = service.remember(
        auth,
        "我负责小维项目",
        source_ref="message:2",
        source_order=2,
        explicit=False,
    )

    assert first is not None and second is not None
    assert first.index_status == "ready" and second.index_status == "ready"
    assert service.status(auth).graph_pending == 1
    service.process_pending_jobs()
    edges = store.edges(actor.owner_id, "default")
    assert any(
        edge.relation == "FOLLOWS"
        and edge.from_memory_id == first.memory_id
        and edge.to_memory_id == second.memory_id
        and edge.registry_version == "m05-g1-v1"
        for edge in edges
    )

    replacement = service.update(auth, first.memory_id, "我叫维安")
    service.process_pending_jobs()
    assert store.get_fact(actor.owner_id, first.memory_id).status == "superseded"
    assert replacement.supersedes_id == first.memory_id
    assert any(
        edge.from_memory_id == first.memory_id and edge.active is False
        for edge in store.edges(actor.owner_id, "default")
    )

    service.forget(auth, replacement.memory_id)
    service.process_pending_jobs()
    assert service.list(auth).items == (second,)
    tombstone = store.get_fact(actor.owner_id, replacement.memory_id)
    assert tombstone is not None
    assert (tombstone.subject, tombstone.slot, tombstone.fact) == ("", "", "")
    assert all(
        replacement.memory_id not in {edge.from_memory_id, edge.to_memory_id}
        for edge in store.edges(actor.owner_id, "default")
        if edge.active
    )
    service.delete_all(auth)
    superseded = store.get_fact(actor.owner_id, first.memory_id)
    assert superseded is not None and superseded.fact == ""


def test_secret_and_preference_are_never_persisted() -> None:
    service, _store, actor, _state = _service()
    auth = service.command_authorization(actor)

    with pytest.raises(MemoryUnsafeContent):
        service.remember(
            auth,
            "记住，我的密码：secret-123",
            source_ref="message:secret",
            source_order=1,
            explicit=True,
        )
    run_auth = _run_memory_auth(service, actor)
    assert not service.enqueue_extraction(
        run_auth,
        "我住在杭州，密码：secret-123",
        source_ref="message:secret-queue",
        source_order=2,
    )
    assert service.status(service.command_authorization(actor)).pending == 0


def test_natural_remember_splits_once_and_partially_saves_mixed_message() -> None:
    _unused, store, actor, state = _service()
    content = "请记住，我叫林舟，我喜欢乌龙茶"
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
        extractor=_mixed_extractor(prefix_length=4),
    )

    outcome = service.process_natural_intent(
        _execution_authorization(service, actor),
        content,
        source_ref="message:mixed-explicit",
        source_order=1,
    )

    assert outcome is not None
    assert (outcome.status, outcome.saved_count, outcome.rejected_count) == (
        "partial",
        1,
        1,
    )
    assert outcome.reason_codes == ("preference_not_persisted",)
    facts = store.active_facts(actor.owner_id, "default")
    assert [(fact.slot, fact.fact) for fact in facts] == [("name", "我叫林舟")]


def test_ordinary_mixed_message_is_filtered_after_async_extraction() -> None:
    _unused, store, actor, state = _service()
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
        extractor=_mixed_extractor(prefix_length=0),
    )
    auth = _run_memory_auth(service, actor)

    assert service.enqueue_extraction(
        auth,
        "我叫林舟，我喜欢乌龙茶",
        source_ref="message:mixed-async",
        source_order=1,
    )
    assert service.process_pending_jobs() == 1

    facts = store.active_facts(actor.owner_id, "default")
    assert [(fact.slot, fact.fact) for fact in facts] == [("name", "我叫林舟")]


def test_natural_forget_returns_authoritative_delete_outcome() -> None:
    service, store, actor, _state = _service()
    remembered = service.remember(
        service.command_authorization(actor, action="write"),
        "我叫林舟",
        source_ref="message:remembered-name",
        source_order=1,
        explicit=True,
    )
    assert remembered is not None

    outcome = service.process_natural_intent(
        _execution_authorization(service, actor),
        "忘记我叫林舟",
        source_ref="message:forget-name",
        source_order=2,
    )

    assert outcome is not None and outcome.status == "deleted"
    assert store.active_facts(actor.owner_id, "default") == ()


def test_special_category_and_third_party_policy_are_applied_before_storage() -> None:
    service, _store, actor, _state = _service()
    auth = service.command_authorization(actor)

    first_party = service.remember(
        auth,
        "记住，我被诊断为高血压",
        source_ref="message:health-self",
        source_order=1,
        explicit=True,
    )
    third_party = service.remember(
        auth,
        "小张住在苏州",
        source_ref="message:third-party",
        source_order=2,
        explicit=False,
    )

    assert first_party is not None and first_party.sensitivity == "health"
    assert third_party is not None and third_party.subject == "小张"
    with pytest.raises(MemoryUnsafeContent):
        service.remember(
            auth,
            "记住，小张被诊断为糖尿病",
            source_ref="message:health-third-party",
            source_order=3,
            explicit=True,
        )
    with pytest.raises(MemoryUnsafeContent):
        service.remember(
            auth,
            "记住，我喜欢简短回答",
            source_ref="message:preference",
            source_order=2,
            explicit=True,
        )


def test_list_cursor_is_owner_bound_and_tamper_evident() -> None:
    service, store, actor, _state = _service()
    auth = service.command_authorization(actor)
    for index in range(21):
        at = NOW + timedelta(seconds=index)
        memory_id = f"00000000-0000-0000-0000-{index:012d}"
        source = MemorySource(
            f"message:{index}",
            actor.owner_id,
            "default",
            "user_message",
            None,
            index,
            at,
        )
        store.save_fact(
            MemoryFact(
                memory_id,
                actor.owner_id,
                "default",
                "我",
                f"slot-{index}",
                f"事实 {index}",
                "active",
                (source.source_ref,),
                at,
                at,
            ),
            source,
            at,
        )
    page = service.list(auth)

    assert len(page.items) == 20
    assert page.next_cursor is not None
    assert len(service.list(auth, page.next_cursor).items) == 1
    with pytest.raises(MemoryInvalidCursor):
        service.list(auth, page.next_cursor[:-1] + "x")


def test_memory_command_is_deterministic_and_does_not_create_a_run() -> None:
    service, store, actor, _state = _service()
    adapter = MemoryCommandAdapter(service)
    auth = service.command_authorization(actor)
    fact = service.remember(
        auth,
        "我住在杭州",
        source_ref="message:location",
        source_order=1,
        explicit=False,
    )
    assert fact is not None

    result = adapter.execute(actor, "/memory list")
    forgotten = adapter.execute(actor, f"/memory forget {fact.memory_id}")

    assert result.code == "memory_list" and fact.memory_id in result.message
    assert forgotten.code == "memory_forgotten"
    assert store.get_fact(actor.owner_id, fact.memory_id).status == "deleted"


def test_source_reference_cannot_cross_owner_authorization_scope() -> None:
    _service_instance, store, actor, _state = _service()
    source = MemorySource(
        "shared-source-ref",
        actor.owner_id,
        "default",
        "user_message",
        None,
        1,
        NOW,
    )
    first = MemoryFact(
        "55555555-5555-5555-5555-555555555555",
        actor.owner_id,
        "default",
        "我",
        "name",
        "我叫小维",
        "active",
        (source.source_ref,),
        NOW,
        NOW,
    )
    store.save_fact(first, source, NOW)
    other_owner = "66666666-6666-6666-6666-666666666666"
    conflicting_source = MemorySource(
        source.source_ref,
        other_owner,
        "default",
        "user_message",
        None,
        1,
        NOW,
    )
    conflicting_fact = MemoryFact(
        "77777777-7777-7777-7777-777777777777",
        other_owner,
        "default",
        "我",
        "name",
        "我叫另一个人",
        "active",
        (source.source_ref,),
        NOW,
        NOW,
    )

    with pytest.raises(StoreError):
        store.save_fact(conflicting_fact, conflicting_source, NOW)


def test_delete_all_confirmation_is_single_use_and_rechecks_state() -> None:
    service, store, actor, _state = _service()
    auth = service.command_authorization(actor)
    fact = service.remember(
        auth,
        "我住在杭州",
        source_ref="message:location",
        source_order=1,
        explicit=False,
    )
    assert fact is not None
    token, count = service.request_delete_all(auth)
    assert count == 1

    extra_at = NOW + timedelta(seconds=1)
    extra_source = MemorySource(
        "message:extra",
        actor.owner_id,
        "default",
        "user_message",
        None,
        2,
        extra_at,
    )
    store.save_fact(
        MemoryFact(
            "33333333-3333-3333-3333-333333333333",
            actor.owner_id,
            "default",
            "我",
            "occupation",
            "我的职业是工程师",
            "active",
            (extra_source.source_ref,),
            extra_at,
            extra_at,
        ),
        extra_source,
        extra_at,
    )
    with pytest.raises(MemoryConfirmationInvalid):
        service.confirm_delete_all(auth, token)

    fresh_token, fresh_count = service.request_delete_all(auth)
    assert fresh_count == 2
    assert service.confirm_delete_all(auth, fresh_token) == 2
    with pytest.raises(MemoryConfirmationInvalid):
        service.confirm_delete_all(auth, fresh_token)


def test_multi_fact_source_revocation_requires_confirmation() -> None:
    service, store, actor, _state = _service()
    auth = service.command_authorization(actor)
    source = MemorySource(
        "tool:execution:1",
        actor.owner_id,
        "default",
        "tool_result",
        None,
        1,
        NOW,
    )
    for index in range(2):
        memory_id = f"44444444-4444-4444-4444-{index:012d}"
        store.save_fact(
            MemoryFact(
                memory_id,
                actor.owner_id,
                "default",
                "我",
                f"tool-slot-{index}",
                f"工具事实 {index}",
                "active",
                (source.source_ref,),
                NOW,
                NOW,
            ),
            source,
            NOW,
        )

    count, token = service.request_revoke_source(auth, source.source_ref)
    assert count == 2 and token is not None
    assert service.confirm_revoke_source(auth, source.source_ref, token) == 2
    assert store.active_facts(actor.owner_id, "default") == ()
    with pytest.raises(MemoryConfirmationInvalid):
        service.confirm_revoke_source(auth, source.source_ref, token)


def test_explicit_remember_reports_success_after_authoritative_commit() -> None:
    service, store, actor, _state = _service()

    result = service.process_natural_intent(
        _execution_authorization(service, actor),
        "记住，我叫小维",
        source_ref="message:authoritative-commit",
        source_order=1,
    )

    assert result is not None and result.status == "saved"
    assert len(store.active_facts(actor.owner_id, "default")) == 1


def test_short_term_summary_is_rebuildable_and_suppresses_corrected_turn() -> None:
    service, _store, actor, _state = _service()
    auth = _run_memory_auth(
        service, actor, conversation_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )
    messages = (
        _message(auth, 1, "user", "我住在杭州"),
        _message(auth, 2, "assistant", "已了解你住在杭州"),
        _message(auth, 3, "user", "我负责火星项目"),
        _message(auth, 4, "assistant", "项目上下文已记录"),
        _message(auth, 5, "user", "我住在苏州"),
        _message(auth, 6, "assistant", "已按新地点回答"),
    )
    snapshot = service.capture_snapshot(auth)

    blocks = service.summary_blocks(
        auth,
        messages,
        messages[-1].message_id,
        token_budget=20,
        snapshot=snapshot,
    )
    rebuilt = service.summary_blocks(
        auth,
        messages,
        messages[-1].message_id,
        token_budget=20,
        snapshot=snapshot,
    )

    assert len(blocks) == 1 and rebuilt == blocks
    assert "火星项目" in blocks[0].content
    assert "杭州" not in blocks[0].content
    assert (
        blocks[0].source_ref
        == f"messages:{messages[0].message_id}:{messages[3].message_id}"
    )


def test_short_term_summary_is_rebuilt_after_a_later_correction() -> None:
    service, _store, actor, _state = _service()
    auth = _run_memory_auth(
        service, actor, conversation_id="abababab-abab-abab-abab-abababababab"
    )
    initial_messages = (
        _message(auth, 1, "user", "我住在杭州"),
        _message(auth, 2, "assistant", "已了解你住在杭州"),
        _message(auth, 3, "user", "我负责火星项目"),
        _message(auth, 4, "assistant", "项目上下文已记录"),
    )
    initial = service.summary_blocks(
        auth,
        initial_messages,
        initial_messages[-1].message_id,
        token_budget=8,
    )

    corrected_messages = initial_messages + (
        _message(auth, 5, "user", "我住在苏州"),
        _message(auth, 6, "assistant", "已按新地点回答"),
    )
    rebuilt = service.summary_blocks(
        auth,
        corrected_messages,
        corrected_messages[-1].message_id,
        token_budget=8,
    )

    assert len(initial) == len(rebuilt) == 1
    assert initial[0].block_id != rebuilt[0].block_id
    assert "杭州" in initial[0].content
    assert "杭州" not in rebuilt[0].content
    assert "火星项目" in rebuilt[0].content


def test_short_term_summary_failure_falls_back_to_recent_complete_turns() -> None:
    service, store, actor, state = _service()
    failing = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
        summary_builder=lambda _older, _recent: (_ for _ in ()).throw(RuntimeError()),
    )
    auth = _run_memory_auth(
        failing, actor, conversation_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )
    messages = (
        _message(auth, 1, "user", "较早问题"),
        _message(auth, 2, "assistant", "较早回答"),
        _message(auth, 3, "user", "当前问题"),
        _message(auth, 4, "assistant", "当前回答"),
    )

    recent = failing.conversation_context(
        auth, messages, messages[-1].message_id, token_budget=8
    )
    blocks = failing.summary_blocks(
        auth, messages, messages[-1].message_id, token_budget=8
    )

    assert tuple(item.sequence for item in recent) == (3, 4)
    assert blocks == ()


def test_ambiguous_candidate_is_quarantined_hidden_and_expires() -> None:
    current = [NOW]
    service, store, actor, state = _service()
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


def test_new_qualified_source_re_evaluates_quarantine_and_temporal_ttl_is_enforced() -> (
    None
):
    current = [NOW]
    service, store, actor, state = _service()
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


def test_quarantine_is_not_resolved_when_replacement_persistence_fails() -> None:
    class FailingResolvedFactStore(InMemoryMemoryStore):
        fail_active_write = False

        def save_fact(self, fact, source, now):
            if self.fail_active_write and fact.status == "active":
                raise StoreError("injected active fact failure")
            return super().save_fact(fact, source, now)

    _unused, _store, actor, state = _service()
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


def test_async_extraction_is_idempotent_and_stale_generation_cannot_revive_data() -> (
    None
):
    service, store, actor, _state = _service()
    auth = _run_memory_auth(service, actor)

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


def test_claimed_job_lease_is_recovered_after_worker_loss() -> None:
    service, store, actor, _state = _service()
    auth = _run_memory_auth(service, actor)
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


def test_graph_pending_is_visible_while_facts_remain_recallable() -> None:
    class RecoverableGraphStore(InMemoryMemoryStore):
        fail_graph = True

        def replace_graph(
            self,
            owner_id,
            tenant_id,
            edges,
            target_revision,
            deletion_generation,
            registry_version,
        ):
            if self.fail_graph:
                raise StoreError("injected graph failure")
            return super().replace_graph(
                owner_id,
                tenant_id,
                edges,
                target_revision,
                deletion_generation,
                registry_version,
            )

    current = [NOW]
    _unused, _store, actor, state = _service()
    store = RecoverableGraphStore(durable=True)
    registry = MemoryCapabilityRegistry(
        (
            MemoryCapabilityStatus("memory-extraction", "healthy", "memory_ready"),
            MemoryCapabilityStatus("memory-graph-g1", "healthy", "memory_ready"),
        )
    )
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: current[0],
        capability_registry=registry,
    )
    auth = service.command_authorization(actor)
    fact = service.remember(
        auth,
        "我住在杭州",
        source_ref="message:index",
        source_order=1,
        explicit=False,
    )

    assert fact is not None and fact.index_status == "ready"
    assert service.status(auth).index_pending == 0
    assert service.status(auth).graph_pending == 1
    assert service.context_blocks(auth, "杭州")

    service.process_pending_jobs()
    assert service.status(auth).graph_pending == 1
    assert registry.get("memory-graph-g1").state == "degraded"
    assert registry.get("memory-extraction").state == "healthy"
    store.fail_graph = False
    current[0] += timedelta(seconds=2)
    service.process_pending_jobs()
    recovered = service.show(auth, fact.memory_id)
    assert recovered.index_status == "ready"
    assert service.status(auth).graph_pending == 0
    assert registry.get("memory-graph-g1").state == "healthy"
    assert service.context_blocks(auth, "杭州")


def test_owner_tombstone_is_retained_until_graph_purge_converges() -> None:
    service, store, actor, state = _service()
    auth = service.command_authorization(actor)
    assert service.remember(
        auth,
        "我住在杭州",
        source_ref="message:owner-delete",
        source_order=1,
        explicit=False,
    ) is not None
    state.owners[actor.owner_id] = replace(
        state.owners[actor.owner_id], lifecycle_state="deleting"
    )

    assert service.prepare_owner_deletion(actor.owner_id) is False
    assert state.owners[actor.owner_id].lifecycle_state == "deleting"
    service.process_pending_jobs(limit=8)

    assert store.settings(actor.owner_id).purge_pending is False
    assert service.prepare_owner_deletion(actor.owner_id) is True


def test_disable_store_failure_still_stops_current_process_injection() -> None:
    class FailingDisableStore(InMemoryMemoryStore):
        def set_enabled(self, owner_id, enabled, now):
            if not enabled:
                raise StoreError("injected setting failure")
            return super().set_enabled(owner_id, enabled, now)

    _unused, _store, actor, state = _service()
    store = FailingDisableStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)

    with pytest.raises(MemoryDisableNotPersisted):
        service.set_enabled(auth, False)

    assert service.capture_snapshot(auth, allow_disabled=True).enabled is False


def test_explicit_remember_store_failure_returns_immediate_safe_result() -> None:
    class FailingWriteStore(InMemoryMemoryStore):
        def save_fact(self, fact, source, now):
            raise StoreError("secret database detail")

    _unused, _store, actor, state = _service()
    service = MemoryService(
        FailingWriteStore(durable=True),
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )

    result = service.process_natural_intent(
        _execution_authorization(service, actor),
        "记住，我住在杭州",
        source_ref="message:failing-natural-write",
        source_order=1,
    )

    assert result is not None
    assert result.status == "unavailable"
    assert "secret" not in " ".join(result.reason_codes)


def test_background_retry_is_bounded_and_exposes_only_safe_error_summary() -> None:
    class FailingWriteStore(InMemoryMemoryStore):
        recovered = False

        def save_fact(self, fact, source, now):
            if not self.recovered:
                raise StoreError(f"raw fact must not leak: {fact.fact}")
            return super().save_fact(fact, source, now)

    current = [NOW]
    _unused, _store, actor, state = _service()
    store = FailingWriteStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: current[0],
    )
    auth = _run_memory_auth(service, actor)
    service.enqueue_extraction(
        auth,
        "我住在杭州",
        source_ref="message:retry",
        source_order=1,
    )

    for seconds in (0, 2, 5):
        current[0] = NOW + timedelta(seconds=seconds)
        service.process_pending_jobs()

    health = service.status(service.command_authorization(actor))
    assert health.pending == 0 and health.failed == 1
    assert health.error_summary == "store_unavailable"
    assert "杭州" not in (health.error_summary or "")

    store.recovered = True
    assert service.replay_failed_jobs(auth) == 1
    service.process_pending_jobs()
    facts = store.active_facts(actor.owner_id, "default")
    assert len(facts) == 1 and facts[0].fact == "我住在杭州"


def test_request_snapshot_does_not_mix_provider_recovery() -> None:
    service, store, actor, state = _service()
    registry = MemoryCapabilityRegistry(
        (
            MemoryCapabilityStatus("memory-short-term", "healthy", "ready"),
            MemoryCapabilityStatus("memory-long-term", "unavailable", "timeout"),
            MemoryCapabilityStatus("memory-extraction", "healthy", "ready"),
            MemoryCapabilityStatus("memory-graph-g1", "healthy", "ready"),
        )
    )
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
        capability_registry=registry,
    )
    auth = service.command_authorization(actor)
    fact = service.remember(
        auth,
        "我住在杭州",
        source_ref="message:snapshot",
        source_order=1,
        explicit=False,
    )
    assert fact is not None
    snapshot = service.capture_snapshot(auth)
    registry.transition("memory-long-term", "healthy", "recovered")

    assert service.context_blocks(auth, "杭州", snapshot=snapshot) == ()
    assert service.context_blocks(auth, "杭州")


def test_graph_registry_replay_reports_compatibility_changes() -> None:
    service, store, actor, _state = _service()
    auth = service.command_authorization(actor)
    service.remember(
        auth, "我住在杭州", source_ref="message:1", source_order=1, explicit=False
    )
    service.remember(
        auth, "我负责火星项目", source_ref="message:2", source_order=2, explicit=False
    )
    facts = store.active_facts(actor.owner_id, "default")
    sources = {
        ref: store.source(actor.owner_id, ref)
        for fact in facts
        for ref in fact.source_refs
    }
    valid_sources = {key: value for key, value in sources.items() if value is not None}
    previous = build_g1_edges(facts, valid_sources)

    replayed, report = replay_g1_edges(facts, valid_sources, previous)

    assert replayed == previous
    assert report.retained_edges == report.previous_active_edges
    assert report.added_edges == 0 and report.removed_edges == 0


def test_g1_similarity_path_adds_at_most_one_deterministic_neighbor() -> None:
    class InjectedGraphStore(InMemoryMemoryStore):
        injected: tuple[MemoryEdge, ...] = ()

        def read_edges(
            self,
            owner_id,
            tenant_id,
            seed_ids,
            expected_revision,
            deletion_generation,
            registry_version,
        ):
            del seed_ids
            return _injected_graph_snapshot(
                owner_id,
                tenant_id,
                expected_revision,
                deletion_generation,
                registry_version,
                self.injected,
            )

    _unused, _store, actor, state = _service()
    store = InjectedGraphStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)
    seed = _save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0002-000000000001",
        "alpha beta coordinator",
        1,
    )
    first_neighbor = _save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0002-000000000002",
        "technical architecture",
        2,
    )
    newest_neighbor = _save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0002-000000000003",
        "release governance",
        3,
    )
    store.injected = (
        _recall_edge(seed, first_neighbor, "SIMILAR_TO", "edge:similar:first"),
        _recall_edge(seed, newest_neighbor, "SIMILAR_TO", "edge:similar:newest"),
    )

    first = service.context_blocks(auth, "coordinator", limit=5)
    replay = service.context_blocks(auth, "coordinator", limit=5)

    assert replay == first
    assert tuple(block.block_id for block in first) == (
        f"memory:{seed.memory_id}",
        f"memory:{newest_neighbor.memory_id}",
    )


def test_g1_follows_and_weak_similarity_path_do_not_inject_neighbors() -> None:
    class InjectedGraphStore(InMemoryMemoryStore):
        injected: tuple[MemoryEdge, ...] = ()

        def read_edges(
            self,
            owner_id,
            tenant_id,
            seed_ids,
            expected_revision,
            deletion_generation,
            registry_version,
        ):
            del seed_ids
            return _injected_graph_snapshot(
                owner_id,
                tenant_id,
                expected_revision,
                deletion_generation,
                registry_version,
                self.injected,
            )

    _unused, _store, actor, state = _service()
    store = InjectedGraphStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)
    follows_seed = _save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0003-000000000001",
        "alpha beta coordinator",
        1,
    )
    follows_neighbor = _save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0003-000000000002",
        "technical architecture",
        2,
    )
    weak_seed = _save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0003-000000000003",
        "coordinator abcdefghijklmnopqrstuvwxyz 0123456789",
        3,
    )
    weak_neighbor = _save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0003-000000000004",
        "release governance",
        4,
    )
    store.injected = (
        _recall_edge(follows_seed, follows_neighbor, "FOLLOWS", "edge:follows:ignored"),
        _recall_edge(weak_seed, weak_neighbor, "SIMILAR_TO", "edge:similar:weak"),
    )

    blocks = service.context_blocks(auth, "coordinator", limit=5)

    block_ids = {block.block_id for block in blocks}
    assert f"memory:{follows_seed.memory_id}" in block_ids
    assert f"memory:{weak_seed.memory_id}" in block_ids
    assert f"memory:{follows_neighbor.memory_id}" not in block_ids
    assert f"memory:{weak_neighbor.memory_id}" not in block_ids


def test_g1_does_not_expand_a_second_hop() -> None:
    class InjectedGraphStore(InMemoryMemoryStore):
        injected: tuple[MemoryEdge, ...] = ()

        def read_edges(
            self,
            owner_id,
            tenant_id,
            seed_ids,
            expected_revision,
            deletion_generation,
            registry_version,
        ):
            del seed_ids
            return _injected_graph_snapshot(
                owner_id,
                tenant_id,
                expected_revision,
                deletion_generation,
                registry_version,
                self.injected,
            )

    _unused, _store, actor, state = _service()
    store = InjectedGraphStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)
    seed = _save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0004-000000000001",
        "alpha beta coordinator",
        1,
    )
    first_hop = _save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0004-000000000002",
        "technical architecture",
        2,
    )
    second_hop = _save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0004-000000000003",
        "release governance",
        3,
    )
    store.injected = (
        _recall_edge(seed, first_hop, "SIMILAR_TO", "edge:first-hop"),
        _recall_edge(first_hop, second_hop, "SIMILAR_TO", "edge:second-hop"),
    )

    block_ids = {
        block.block_id for block in service.context_blocks(auth, "coordinator")
    }

    assert f"memory:{first_hop.memory_id}" in block_ids
    assert f"memory:{second_hop.memory_id}" not in block_ids


def test_graph_snapshot_failure_falls_back_to_direct_facts() -> None:
    class FailingGraphStore(InMemoryMemoryStore):
        fail_graph = False

        def read_edges(
            self,
            owner_id,
            tenant_id,
            seed_ids,
            expected_revision,
            deletion_generation,
            registry_version,
        ):
            if self.fail_graph:
                raise StoreError("injected graph read failure")
            return super().read_edges(
                owner_id,
                tenant_id,
                seed_ids,
                expected_revision,
                deletion_generation,
                registry_version,
            )

    _unused, _store, actor, state = _service()
    store = FailingGraphStore(durable=True)
    registry = MemoryCapabilityRegistry(
        (
            MemoryCapabilityStatus("memory-long-term", "healthy", "ready"),
            MemoryCapabilityStatus("memory-graph-g1", "healthy", "ready"),
        )
    )
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
        capability_registry=registry,
    )
    auth = service.command_authorization(actor)
    fact = service.remember(
        auth,
        "我住在杭州",
        source_ref="message:graph-fallback",
        source_order=1,
        explicit=False,
    )
    assert fact is not None
    store.fail_graph = True

    blocks = service.context_blocks(auth, "杭州")

    assert tuple(block.block_id for block in blocks) == (f"memory:{fact.memory_id}",)
    assert registry.get("memory-graph-g1").state == "degraded"


def test_recall_discards_snapshot_when_deletion_generation_changes() -> None:
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

    _unused, _store, actor, state = _service()
    store = GenerationChangingStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)
    _save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0005-000000000001",
        "我住在杭州",
        1,
    )
    store.change_generation = True

    assert service.context_blocks(auth, "杭州") == ()


def test_recall_discards_snapshot_when_authorization_epoch_changes() -> None:
    class EpochChangingStore(InMemoryMemoryStore):
        revoke = None

        def recall_snapshot(self, owner_id, tenant_id):
            snapshot = super().recall_snapshot(owner_id, tenant_id)
            if self.revoke is not None:
                revoke, self.revoke = self.revoke, None
                revoke()
            return snapshot

    _unused, _store, actor, state = _service()
    store = EpochChangingStore(durable=True)
    ownership = MemoryOwnershipStore(state, account_available=True, mode="durable")
    service = MemoryService(
        store,
        ownership,
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)
    _save_recall_fact(
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


def test_authoritative_read_failure_omits_long_term_memory() -> None:
    class FailingReadStore(InMemoryMemoryStore):
        def active_facts(self, owner_id, tenant_id):
            raise StoreError("injected authoritative read failure")

    _unused, _store, actor, state = _service()
    service = MemoryService(
        FailingReadStore(durable=True),
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )

    assert service.context_blocks(service.command_authorization(actor), "杭州") == ()


def test_secondary_filter_rejects_cross_owner_adapter_results() -> None:
    class CrossOwnerStore(InMemoryMemoryStore):
        foreign: MemoryFact | None = None

        def active_facts(self, owner_id, tenant_id):
            values = super().active_facts(owner_id, tenant_id)
            return values + ((self.foreign,) if self.foreign is not None else ())

    _unused, _store, actor, state = _service()
    store = CrossOwnerStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)
    own = service.remember(
        auth,
        "我住在杭州",
        source_ref="message:own",
        source_order=1,
        explicit=False,
    )
    assert own is not None
    store.foreign = replace(
        own,
        memory_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        owner_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        fact="其他 owner 负责秘密项目",
    )

    blocks = service.context_blocks(auth, "项目 杭州")

    assert all("秘密项目" not in block.content for block in blocks)
    assert any("杭州" in block.content for block in blocks)


def test_secondary_filter_rejects_unknown_graph_relation_and_registry() -> None:
    class UnknownEdgeStore(InMemoryMemoryStore):
        injected: MemoryEdge | None = None

        def read_edges(
            self,
            owner_id,
            tenant_id,
            seed_ids,
            expected_revision,
            deletion_generation,
            registry_version,
        ):
            del seed_ids
            edges = (self.injected,) if self.injected is not None else ()
            return G1GraphSnapshot(
                owner_id,
                tenant_id,
                expected_revision,
                deletion_generation,
                registry_version,
                tuple(
                    replace(
                        edge,
                        projection_revision=expected_revision,
                        deletion_generation=deletion_generation,
                    )
                    for edge in edges
                ),
            )

    _unused, _store, actor, state = _service()
    store = UnknownEdgeStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)
    first = service.remember(
        auth, "我住在杭州", source_ref="message:g1", source_order=1, explicit=False
    )
    second = service.remember(
        auth,
        "我负责火星项目",
        source_ref="message:g2",
        source_order=2,
        explicit=False,
    )
    assert first is not None and second is not None
    store.injected = MemoryEdge(
        "unknown-edge",
        actor.owner_id,
        "default",
        "SIMILAR_TO",
        first.memory_id,
        second.memory_id,
        "unknown-registry",
        True,
        "injected",
        NOW,
    )

    blocks = service.context_blocks(auth, "杭州")

    assert any(first.memory_id in block.block_id for block in blocks)
    assert all(second.memory_id not in block.block_id for block in blocks)


def _run_memory_auth(
    service: MemoryService,
    actor: Actor,
    *,
    conversation_id: str = "cccccccc-cccc-cccc-cccc-cccccccccccc",
) -> MemoryAuthorization:
    command = service.command_authorization(actor)
    return MemoryAuthorization(
        owner_id=command.owner_id,
        tenant_id=command.tenant_id,
        allowed_data_scopes=command.allowed_data_scopes,
        allowed_action_classes=command.allowed_action_classes,
        authorization_epoch=command.authorization_epoch,
        source_kind="run",
        action="manage",
        run_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        conversation_id=conversation_id,
    )


def _execution_authorization(
    service: MemoryService,
    actor: Actor,
    *,
    conversation_id: str = "cccccccc-cccc-cccc-cccc-cccccccccccc",
) -> ExecutionAuthorization:
    command = service.command_authorization(actor)
    return ExecutionAuthorization(
        run_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        owner_id=command.owner_id,
        tenant_id=command.tenant_id,
        conversation_id=conversation_id,
        allowed_data_scopes=command.allowed_data_scopes,
        allowed_action_classes=command.allowed_action_classes,
        authorization_epoch=command.authorization_epoch,
    )


def _mixed_extractor(*, prefix_length: int) -> StructuredMemoryExtractor:
    return StructuredMemoryExtractor(
        lambda _content: {
            "schema_version": "m05-extractor-v1",
            "candidates": [
                {
                    "subject": "我",
                    "slot": "name",
                    "value": "林舟",
                    "fact": "我叫林舟",
                    "assertion_mode": "statement",
                    "temporal_scope": "current",
                    "confidence": 0.99,
                    "source_span": {
                        "start": prefix_length,
                        "end": prefix_length + 4,
                    },
                },
                {
                    "subject": "我",
                    "slot": "beverage_preference",
                    "value": "乌龙茶",
                    "fact": "我喜欢乌龙茶",
                    "assertion_mode": "statement",
                    "temporal_scope": "current",
                    "confidence": 0.99,
                    "source_span": {
                        "start": prefix_length + 5,
                        "end": prefix_length + 11,
                    },
                },
            ],
        }
    )


def _save_recall_fact(
    store: InMemoryMemoryStore,
    owner_id: str,
    memory_id: str,
    content: str,
    source_order: int,
) -> MemoryFact:
    created_at = NOW + timedelta(seconds=source_order)
    source = MemorySource(
        source_ref=f"recall-source:{memory_id}",
        owner_id=owner_id,
        tenant_id="default",
        source_kind="user_message",
        conversation_id=None,
        source_order=source_order,
        created_at=created_at,
    )
    fact = MemoryFact(
        memory_id=memory_id,
        owner_id=owner_id,
        tenant_id="default",
        subject="test",
        slot=f"slot-{source_order}",
        fact=content,
        status="active",
        source_refs=(source.source_ref,),
        created_at=created_at,
        updated_at=created_at,
    )
    return store.save_fact(fact, source, created_at)


def _recall_edge(
    left: MemoryFact,
    right: MemoryFact,
    relation: str,
    edge_id: str,
) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        owner_id=left.owner_id,
        tenant_id=left.tenant_id,
        relation=relation,  # type: ignore[arg-type]
        from_memory_id=left.memory_id,
        to_memory_id=right.memory_id,
        registry_version="m05-g1-v1",
        active=True,
        source="test",
        created_at=max(left.updated_at, right.updated_at),
    )


def _injected_graph_snapshot(
    owner_id: str,
    tenant_id: str,
    revision: int,
    generation: int,
    registry_version: str,
    edges: tuple[MemoryEdge, ...],
) -> G1GraphSnapshot:
    return G1GraphSnapshot(
        owner_id,
        tenant_id,
        revision,
        generation,
        registry_version,
        tuple(
            replace(
                edge,
                projection_revision=revision,
                deletion_generation=generation,
                registry_version=registry_version,
            )
            for edge in edges
        ),
    )


def _message(auth: MemoryAuthorization, sequence: int, role: str, content: str):
    from venagent.conversation.models import ConversationMessage

    return ConversationMessage(
        message_id=f"00000000-0000-0000-0001-{sequence:012d}",
        conversation_id=auth.conversation_id or "",
        owner_id=auth.owner_id,
        role=role,  # type: ignore[arg-type]
        content=content,
        sequence=sequence,
        created_at=NOW + timedelta(seconds=sequence),
        client_request_id=(
            f"10000000-0000-0000-0001-{sequence:012d}" if role == "user" else None
        ),
        source_run_id=(
            f"20000000-0000-0000-0001-{sequence:012d}" if role == "assistant" else None
        ),
        reply_to_message_id=(
            f"00000000-0000-0000-0001-{sequence - 1:012d}"
            if role == "assistant"
            else None
        ),
    )
