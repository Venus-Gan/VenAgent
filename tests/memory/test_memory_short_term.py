"""memory 短期上下文契约：turn 摘要、校正后重建、失败回退、快照不混 provider 恢复（原 test_memory_context.py 拆分三）。"""

from __future__ import annotations

from datetime import datetime, timezone

from src.memory.management import (
    MemoryCapabilityRegistry,
    MemoryCapabilityStatus,
)
from src.memory.service import MemoryService
from src.repo.inmemory import (
    InMemoryOwnershipStore as MemoryOwnershipStore,
)

NOW = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)

def test_short_term_summary_is_rebuildable_and_suppresses_corrected_turn(memory_service, run_memory_auth, message) -> None:
    service, _store, actor, _state = memory_service()
    auth = run_memory_auth(
        service, actor, conversation_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )
    messages = (
        message(auth, 1, "user", "我住在杭州"),
        message(auth, 2, "assistant", "已了解你住在杭州"),
        message(auth, 3, "user", "我负责火星项目"),
        message(auth, 4, "assistant", "项目上下文已记录"),
        message(auth, 5, "user", "我住在苏州"),
        message(auth, 6, "assistant", "已按新地点回答"),
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

def test_short_term_summary_is_rebuilt_after_a_later_correction(memory_service, run_memory_auth, message) -> None:
    service, _store, actor, _state = memory_service()
    auth = run_memory_auth(
        service, actor, conversation_id="abababab-abab-abab-abab-abababababab"
    )
    initial_messages = (
        message(auth, 1, "user", "我住在杭州"),
        message(auth, 2, "assistant", "已了解你住在杭州"),
        message(auth, 3, "user", "我负责火星项目"),
        message(auth, 4, "assistant", "项目上下文已记录"),
    )
    initial = service.summary_blocks(
        auth,
        initial_messages,
        initial_messages[-1].message_id,
        token_budget=8,
    )

    corrected_messages = initial_messages + (
        message(auth, 5, "user", "我住在苏州"),
        message(auth, 6, "assistant", "已按新地点回答"),
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

def test_short_term_summary_failure_falls_back_to_recent_complete_turns(memory_service, run_memory_auth, message) -> None:
    service, store, actor, state = memory_service()
    failing = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
        summary_builder=lambda _older, _recent: (_ for _ in ()).throw(RuntimeError()),
    )
    auth = run_memory_auth(
        failing, actor, conversation_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )
    messages = (
        message(auth, 1, "user", "较早问题"),
        message(auth, 2, "assistant", "较早回答"),
        message(auth, 3, "user", "当前问题"),
        message(auth, 4, "assistant", "当前回答"),
    )

    recent = failing.conversation_context(
        auth, messages, messages[-1].message_id, token_budget=8
    )
    blocks = failing.summary_blocks(
        auth, messages, messages[-1].message_id, token_budget=8
    )

    assert tuple(item.sequence for item in recent) == (3, 4)
    assert blocks == ()

def test_request_snapshot_does_not_mix_provider_recovery(memory_service) -> None:
    service, store, actor, state = memory_service()
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