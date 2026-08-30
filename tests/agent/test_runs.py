"""Run lifecycle 底层契约的权威断言（D2 非 M06 归位保留，规则①单点）。

run lifecycle（create/claim/cancel/grant/contract-mismatch/waiting-approval）
在此单点断言；AgentRuntime 的恢复机制（checkpoint 重放、不确定租约、调度并发、
跨进程取消）由 tests/agent/test_commit_recovery.py 单独测试，不再重复本层契约。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.agent.runs import (
    AgentRunLifecycle,
    InvalidRunTransition,
    RunAuthorizationInvalid,
    RunNotFound,
)
from src.conversation.errors import (
    ConversationBusy,
    ConversationNotFound,
    IdempotencyConflict,
)
from src.ownership.models import Actor, OwnerRecord, SessionRecord
from src.repo.inmemory import (
    InMemoryConversationRuntimeStore as MemoryRuntimeStore,
)
from src.repo.inmemory import (
    InMemoryOwnershipStore as MemoryOwnershipStore,
)
from src.repo.inmemory import (
    InMemoryPlatformState as MemoryState,
)

NOW = datetime(2026, 8, 3, tzinfo=timezone.utc)


def actor(owner_id: str = "owner-a") -> Actor:
    return Actor(owner_id, "user", "session-a", "alice", "durable")


def test_create_run_is_atomic_idempotent_and_enforces_single_active_run() -> None:
    store = MemoryRuntimeStore()
    conversation = store.create_conversation(actor(), NOW)
    request_id = str(uuid4())

    first = store.create_run(
        actor(), conversation.conversation_id, "问题", request_id, NOW
    )
    replay = store.create_run(
        actor(), conversation.conversation_id, "问题", request_id, NOW
    )

    assert replay == first
    assert store.messages(actor().owner_id, conversation.conversation_id) == (
        first.input_message,
    )
    with pytest.raises(ConversationBusy):
        store.create_run(
            actor(), conversation.conversation_id, "另一问", str(uuid4()), NOW
        )
    with pytest.raises(IdempotencyConflict):
        store.create_run(actor(), conversation.conversation_id, "篡改", request_id, NOW)
    with pytest.raises(ConversationNotFound):
        store.create_run(
            actor("owner-b"),
            conversation.conversation_id,
            "问题",
            request_id,
            NOW,
        )


def test_claim_uses_fencing_and_stale_worker_cannot_finalize() -> None:
    store = MemoryRuntimeStore()
    conversation = store.create_conversation(actor(), NOW)
    store.create_run(actor(), conversation.conversation_id, "问题", str(uuid4()), NOW)
    lifecycle = AgentRunLifecycle(store)
    claimed = lifecycle.claim_next("worker-a", NOW, timedelta(seconds=60))

    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.execution_attempt == 1
    with pytest.raises(InvalidRunTransition):
        lifecycle.succeed(
            claimed.run_id,
            "wrong-token",
            claimed.execution_attempt,
            "回答",
            NOW,
        )

    finished = lifecycle.succeed(
        claimed.run_id,
        claimed.claim_token or "",
        claimed.execution_attempt,
        "回答",
        NOW,
    )
    messages = store.messages(actor().owner_id, conversation.conversation_id)

    assert finished.status == "succeeded"
    assert finished.output_message_id == messages[-1].message_id
    assert [message.role for message in messages] == ["user", "assistant"]


def test_cancel_request_is_persistent_idempotent_and_owner_scoped() -> None:
    store = MemoryRuntimeStore()
    conversation = store.create_conversation(actor(), NOW)
    run = store.create_run(
        actor(), conversation.conversation_id, "问题", str(uuid4()), NOW
    ).run
    lifecycle = AgentRunLifecycle(store)

    first = lifecycle.request_cancel(actor().owner_id, run.run_id, NOW)
    second = lifecycle.request_cancel(actor().owner_id, run.run_id, NOW)

    assert first.cancel_requested_at == second.cancel_requested_at == NOW
    with pytest.raises(RunNotFound):
        lifecycle.request_cancel("owner-b", run.run_id, NOW)


def test_cancel_terminalization_rejects_a_stale_worker_claim() -> None:
    store = MemoryRuntimeStore()
    conversation = store.create_conversation(actor(), NOW)
    created = store.create_run(
        actor(), conversation.conversation_id, "问题", str(uuid4()), NOW
    )
    lifecycle = AgentRunLifecycle(store)
    first = lifecycle.claim_next("worker-a", NOW, timedelta(seconds=60))
    assert first is not None
    second = lifecycle.claim_next(
        "worker-b", NOW + timedelta(seconds=61), timedelta(seconds=60)
    )
    assert second is not None
    lifecycle.request_cancel(actor().owner_id, created.run.run_id, NOW)

    with pytest.raises(InvalidRunTransition):
        lifecycle.cancel(
            first.run_id,
            "worker-a",
            first.claim_token or "",
            first.execution_attempt,
            "user_cancelled",
            NOW,
        )

    cancelled = lifecycle.cancel(
        second.run_id,
        "worker-b",
        second.claim_token or "",
        second.execution_attempt,
        "user_cancelled",
        NOW,
    )
    assert cancelled.status == "cancelled"


def test_run_grant_is_checked_before_recovered_execution() -> None:
    state = MemoryState()
    store = MemoryRuntimeStore(state)
    ownership = MemoryOwnershipStore(state)
    state.owners[actor().owner_id] = OwnerRecord(
        actor().owner_id, "user", "active", authorization_epoch=4
    )
    state.sessions[actor().session_id] = SessionRecord(
        actor().session_id,
        actor().owner_id,
        "user",
        "refresh-hash",
        NOW + timedelta(days=30),
    )
    conversation = store.create_conversation(actor(), NOW)
    run = store.create_run(
        actor(), conversation.conversation_id, "问题", str(uuid4()), NOW
    ).run

    authorization = store.authorize_run(run.run_id, NOW)
    assert authorization.allowed_action_classes == (
        "model.invoke",
        "memory.read",
        "memory.write",
        "tool.invoke",
    )
    assert authorization.allowed_data_scopes == (
        f"conversation:{conversation.conversation_id}",
        "owner:memory",
    )
    assert authorization.authorization_epoch == 4

    ownership.revoke_session(actor().session_id, NOW)
    assert store.authorize_run(run.run_id, NOW).authorization_epoch == 4

    with pytest.raises(RunAuthorizationInvalid):
        store.authorize_run(run.run_id, NOW + timedelta(days=8))

    state.owners[actor().owner_id] = replace(
        state.owners[actor().owner_id], authorization_epoch=5
    )
    with pytest.raises(RunAuthorizationInvalid):
        store.authorize_run(run.run_id, NOW)


def test_contract_mismatch_has_a_distinct_terminal_state() -> None:
    store = MemoryRuntimeStore()
    conversation = store.create_conversation(actor(), NOW)
    created = store.create_run(
        actor(), conversation.conversation_id, "问题", str(uuid4()), NOW
    )
    store.state.runs[created.run.run_id] = replace(
        created.run, runtime_contract_version=999
    )
    claimed = AgentRunLifecycle(store).claim_next(
        "worker-a", NOW, timedelta(seconds=60)
    )
    assert claimed is not None

    incompatible = AgentRunLifecycle(store).incompatible(
        claimed.run_id,
        claimed.claim_token or "",
        claimed.execution_attempt,
        "版本不兼容",
        NOW,
    )

    assert incompatible.status == "incompatible"
    assert incompatible.terminal_reason_code == "runtime_contract_mismatch"


def test_waiting_approval_cancel_is_atomic_and_idempotent() -> None:
    store = MemoryRuntimeStore()
    conversation = store.create_conversation(actor(), NOW)
    store.create_run(
        actor(), conversation.conversation_id, "问题", str(uuid4()), NOW
    )
    lifecycle = AgentRunLifecycle(store)
    claimed = lifecycle.claim_next("worker-a", NOW, timedelta(seconds=60))
    assert claimed is not None
    waiting = lifecycle.wait_approval(
        claimed.run_id,
        claimed.claim_token or "",
        claimed.execution_attempt,
        NOW,
    )
    assert waiting.status == "waiting_approval"

    cancelled = lifecycle.cancel_waiting_approval(actor().owner_id, waiting.run_id, NOW)
    assert cancelled.status == "cancelled"
    assert cancelled.terminal_reason_code == "user_cancelled"
    assert cancelled.claim_token is None

    # 重复取消幂等。
    again = lifecycle.cancel_waiting_approval(actor().owner_id, waiting.run_id, NOW)
    assert again.status == "cancelled"

    # 已取消的 Run 不能 resume（同契约在此单点断言，不再拆为独立测试）。
    with pytest.raises(InvalidRunTransition):
        lifecycle.resume(waiting.run_id, NOW)
