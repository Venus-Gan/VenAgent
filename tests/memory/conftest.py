"""tests/memory 共用装配（D5）：把原 test_memory_context.py 文件尾私有 helper 工厂
收编为 conftest fixture，六个主题文件就近复用。

- memory_service：装配 (service, store, actor, state)，state 可变供生命周期/owner 过渡测试修改；
- run_memory_auth / execution_authorization：run 面记忆授权/执行授权工厂；
- mixed_extractor：确定性混合消息提取器（自然记忆候选）；
- message：会话消息工厂；
- save_recall_fact / recall_edge / injected_graph_snapshot：G1 召回测试的仓储预置工厂。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import pytest

from tests.memory._store import InMemoryMemoryStore
from venagent.memory.graph_memory import MemoryEdge
from venagent.memory.long_term.facts import MemoryFact, MemorySource
from venagent.memory.model_adapters import StructuredMemoryExtractor
from venagent.memory.ports import G1GraphSnapshot
from venagent.memory.recall import MemoryAuthorization
from venagent.memory.service import MemoryService
from venagent.ownership.models import (
    Actor,
    ExecutionAuthorization,
    OwnerRecord,
    SessionRecord,
)
from venagent.repo.inmemory import (
    InMemoryOwnershipStore as MemoryOwnershipStore,
)
from venagent.repo.inmemory import InMemoryPlatformState as MemoryState

NOW = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def memory_service() -> Callable[
    [], tuple[MemoryService, InMemoryMemoryStore, Actor, MemoryState]
]:
    """返回共享记忆服务装配工厂；state 可变，供测试就地推进生命周期。"""

    def _service() -> tuple[MemoryService, InMemoryMemoryStore, Actor, MemoryState]:
        owner_id = "11111111-1111-1111-1111-111111111111"
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
        service = MemoryService(
            store, ownership, cursor_secret="x" * 32, clock=lambda: NOW
        )
        actor = Actor(owner_id, "user", session_id, "alice", "durable")
        return service, store, actor, state

    return _service


@pytest.fixture
def run_memory_auth() -> Callable[
    [MemoryService, Actor], MemoryAuthorization
]:
    """run 面记忆授权（action=manage）工厂。"""

    def _build(
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

    return _build


@pytest.fixture
def execution_authorization() -> Callable[
    [MemoryService, Actor], ExecutionAuthorization
]:
    """run 面执行授权工厂。"""

    def _build(
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

    return _build


@pytest.fixture
def mixed_extractor() -> Callable[[int], StructuredMemoryExtractor]:
    """确定性混合消息提取器：固定姓名 + 饮料偏好两个候选。"""

    def _build(*, prefix_length: int) -> StructuredMemoryExtractor:
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

    return _build


@pytest.fixture
def message() -> Callable[..., Any]:
    """会话消息工厂（sequence 决定 id/NOW 时间戳）。"""

    def _build(auth: MemoryAuthorization, sequence: int, role: str, content: str):
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
                f"20000000-0000-0000-0001-{sequence:012d}"
                if role == "assistant"
                else None
            ),
            reply_to_message_id=(
                f"00000000-0000-0000-0001-{sequence - 1:012d}"
                if role == "assistant"
                else None
            ),
        )

    return _build


@pytest.fixture
def save_recall_fact() -> Callable[..., MemoryFact]:
    """把一条活动 long-term 事实直接写入临时仓储并返回保存结果。"""

    def _build(
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

    return _build


@pytest.fixture
def recall_edge() -> Callable[..., MemoryEdge]:
    """按两个事实生成 FOLLOWS/SIMILAR 类测试边。"""

    def _build(
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

    return _build


@pytest.fixture
def injected_graph_snapshot() -> Callable[..., G1GraphSnapshot]:
    """构造带 revision/generation/registry 版本的图快照（边就地套版本）。"""

    def _build(
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

    return _build