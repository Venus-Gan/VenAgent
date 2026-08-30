"""memory 服务层行为契约：授权边界、内容保护、安全失败与后台任务收敛（原 test_memory_context.py 拆分一；G1/短期摘要/隔离/仓储 mock 见各主题文件）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from tests.memory._store import InMemoryMemoryStore
from venagent.memory.errors import (
    MemoryConfirmationInvalid,
    MemoryDisableNotPersisted,
    MemoryInvalidCursor,
    MemoryUnauthorized,
    MemoryUnsafeContent,
    MemoryUnsupported,
)
from venagent.memory.long_term.facts import MemoryFact, MemorySource
from venagent.memory.ports import MemoryStoreError as StoreError
from venagent.memory.service import MemoryService
from venagent.ownership.models import Actor, OwnerRecord, SessionRecord
from venagent.repo.inmemory import (
    InMemoryOwnershipStore as MemoryOwnershipStore,
)
from venagent.repo.inmemory import InMemoryPlatformState as MemoryState

NOW = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)

def test_command_authorization_is_bound_to_active_session_and_epoch(memory_service) -> None:
    service, _store, actor, state = memory_service()
    auth = service.command_authorization(actor)

    assert auth.owner_id == actor.owner_id
    assert auth.authorization_epoch == 3
    assert auth.run_id is None
    assert auth.source_kind == "command"

    state.owners[actor.owner_id] = OwnerRecord(actor.owner_id, "user", "active", 4)
    with pytest.raises(MemoryUnauthorized):
        service.status(auth)

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

def test_secret_and_preference_are_never_persisted(memory_service, run_memory_auth) -> None:
    service, _store, actor, _state = memory_service()
    auth = service.command_authorization(actor)

    with pytest.raises(MemoryUnsafeContent):
        service.remember(
            auth,
            "记住，我的密码：secret-123",
            source_ref="message:secret",
            source_order=1,
            explicit=True,
        )
    run_auth = run_memory_auth(service, actor)
    assert not service.enqueue_extraction(
        run_auth,
        "我住在杭州，密码：secret-123",
        source_ref="message:secret-queue",
        source_order=2,
    )
    assert service.status(service.command_authorization(actor)).pending == 0

def test_natural_remember_splits_once_and_partially_saves_mixed_message(memory_service, mixed_extractor, execution_authorization) -> None:
    _unused, store, actor, state = memory_service()
    content = "请记住，我叫林舟，我喜欢乌龙茶"
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
        extractor=mixed_extractor(prefix_length=4),
    )

    outcome = service.process_natural_intent(
        execution_authorization(service, actor),
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

def test_ordinary_mixed_message_is_filtered_after_async_extraction(memory_service, mixed_extractor, run_memory_auth) -> None:
    _unused, store, actor, state = memory_service()
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
        extractor=mixed_extractor(prefix_length=0),
    )
    auth = run_memory_auth(service, actor)

    assert service.enqueue_extraction(
        auth,
        "我叫林舟，我喜欢乌龙茶",
        source_ref="message:mixed-async",
        source_order=1,
    )
    assert service.process_pending_jobs() == 1

    facts = store.active_facts(actor.owner_id, "default")
    assert [(fact.slot, fact.fact) for fact in facts] == [("name", "我叫林舟")]

def test_natural_forget_returns_authoritative_delete_outcome(memory_service, execution_authorization) -> None:
    service, store, actor, _state = memory_service()
    remembered = service.remember(
        service.command_authorization(actor, action="write"),
        "我叫林舟",
        source_ref="message:remembered-name",
        source_order=1,
        explicit=True,
    )
    assert remembered is not None

    outcome = service.process_natural_intent(
        execution_authorization(service, actor),
        "忘记我叫林舟",
        source_ref="message:forget-name",
        source_order=2,
    )

    assert outcome is not None and outcome.status == "deleted"
    assert store.active_facts(actor.owner_id, "default") == ()

def test_special_category_and_third_party_policy_are_applied_before_storage(memory_service) -> None:
    service, _store, actor, _state = memory_service()
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

def test_list_cursor_is_owner_bound_and_tamper_evident(memory_service) -> None:
    service, store, actor, _state = memory_service()
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

def test_source_reference_cannot_cross_owner_authorization_scope(memory_service) -> None:
    _service_instance, store, actor, _state = memory_service()
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

def test_delete_all_confirmation_is_single_use_and_rechecks_state(memory_service) -> None:
    service, store, actor, _state = memory_service()
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

def test_multi_fact_source_revocation_requires_confirmation(memory_service) -> None:
    service, store, actor, _state = memory_service()
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

def test_explicit_remember_reports_success_after_authoritative_commit(memory_service, execution_authorization) -> None:
    service, store, actor, _state = memory_service()

    result = service.process_natural_intent(
        execution_authorization(service, actor),
        "记住，我叫小维",
        source_ref="message:authoritative-commit",
        source_order=1,
    )

    assert result is not None and result.status == "saved"
    assert len(store.active_facts(actor.owner_id, "default")) == 1

def test_owner_tombstone_is_retained_until_graph_purge_converges(memory_service) -> None:
    service, store, actor, state = memory_service()
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

def test_disable_store_failure_still_stops_current_process_injection(memory_service) -> None:
    class FailingDisableStore(InMemoryMemoryStore):
        def set_enabled(self, owner_id, enabled, now):
            if not enabled:
                raise StoreError("injected setting failure")
            return super().set_enabled(owner_id, enabled, now)

    _unused, _store, actor, state = memory_service()
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

def test_explicit_remember_store_failure_returns_immediate_safe_result(memory_service, execution_authorization) -> None:
    class FailingWriteStore(InMemoryMemoryStore):
        def save_fact(self, fact, source, now):
            raise StoreError("secret database detail")

    _unused, _store, actor, state = memory_service()
    service = MemoryService(
        FailingWriteStore(durable=True),
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )

    result = service.process_natural_intent(
        execution_authorization(service, actor),
        "记住，我住在杭州",
        source_ref="message:failing-natural-write",
        source_order=1,
    )

    assert result is not None
    assert result.status == "unavailable"
    assert "secret" not in " ".join(result.reason_codes)

def test_background_retry_is_bounded_and_exposes_only_safe_error_summary(memory_service, run_memory_auth) -> None:
    class FailingWriteStore(InMemoryMemoryStore):
        recovered = False

        def save_fact(self, fact, source, now):
            if not self.recovered:
                raise StoreError(f"raw fact must not leak: {fact.fact}")
            return super().save_fact(fact, source, now)

    current = [NOW]
    _unused, _store, actor, state = memory_service()
    store = FailingWriteStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: current[0],
    )
    auth = run_memory_auth(service, actor)
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

def test_authoritative_read_failure_omits_long_term_memory(memory_service) -> None:
    class FailingReadStore(InMemoryMemoryStore):
        def active_facts(self, owner_id, tenant_id):
            raise StoreError("injected authoritative read failure")

    _unused, _store, actor, state = memory_service()
    service = MemoryService(
        FailingReadStore(durable=True),
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )

    assert service.context_blocks(service.command_authorization(actor), "杭州") == ()