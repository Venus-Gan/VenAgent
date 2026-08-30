"""M06 Agent 主循环相关契约（公开接口驱动，单点）。

- 节点结果 reducer 幂等/冲突、run_config 线程标识、上下文投影
  确定性/必备块保留/超预算失败：本文件单点（与 runner 无关的纯函数契约）。
- memory 组件超时降级不阻塞回答、自然记忆 outcome 注入回答模型：
  经公开 AgentRuntime + TemporaryConversationRuntimeStore 全流程驱动
  （不再触碰私有 _answer_node）。
- RunState 生命周期字段集合断言（结构断言，规则④）已移除。

注意：facts 落库计数由 tests/memory 单点覆盖，本文件不重复断言。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessageChunk

from tests.memory._store import InMemoryMemoryStore
from venagent.agent.graph import run_config
from venagent.agent.state import NodeOutcome, StateConsistencyError, merge_node_outcomes
from venagent.memory.management import (
    MemoryCapabilityRegistry,
    MemoryCapabilityStatus,
)
from venagent.memory.model_adapters import StructuredMemoryExtractor
from venagent.memory.service import MemoryService
from venagent.ownership.models import Actor, OwnerRecord
from venagent.promptctx import (
    ContextBlock,
    ContextOverflow,
    ContextProjectionService,
    ProjectionPolicy,
    SectionSpec,
)
from venagent.repo.inmemory import (
    InMemoryOwnershipStore as MemoryOwnershipStore,
)
from venagent.repo.inmemory import (
    InMemoryPlatformState as MemoryState,
)


class _AStreamModel:
    """记录最近一次 astream 收到的完整消息，并流式返回固定回答。"""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.messages: tuple = ()

    async def astream(self, messages):
        self.messages = tuple(messages)

        async def _gen():
            yield AIMessageChunk(content=self.answer)

        async for chunk in _gen():
            yield chunk


def test_node_outcome_reducer_is_idempotent_and_rejects_conflicts() -> None:
    original = NodeOutcome(1, "answer", 1, "succeeded", "完成")
    same = NodeOutcome(1, "answer", 1, "succeeded", "完成")
    conflict = NodeOutcome(1, "answer", 1, "failed", "失败")

    assert merge_node_outcomes((original,), (same,)) == (original,)
    with pytest.raises(StateConsistencyError):
        merge_node_outcomes((original,), (conflict,))


def test_run_config_uses_run_id_as_the_only_checkpoint_thread_identity() -> None:
    config = run_config("12f9dfef-6457-4ed3-b9e1-2908bd7b4c49")

    assert config == {
        "configurable": {"thread_id": "12f9dfef-6457-4ed3-b9e1-2908bd7b4c49"}
    }


def test_context_projection_is_deterministic_and_preserves_mandatory_blocks() -> None:
    policy = ProjectionPolicy(
        version="foundation-v1",
        model_role="generator",
        sections=(
            SectionSpec("system", "system_messages", True, 100, 20),
            SectionSpec("conversation", "messages", False, 50, 20),
        ),
    )
    blocks = (
        ContextBlock("b2", "conversation", "conversation", "较早", 5, False, 2),
        ContextBlock("b1", "system", "runtime", "安全规则", 100, True, 2),
        ContextBlock("b3", "conversation", "conversation", "当前请求", 10, False, 2),
    )
    service = ContextProjectionService()

    first = service.project(policy, blocks, input_budget=6)
    second = service.project(policy, tuple(reversed(blocks)), input_budget=6)

    assert first == second
    assert first.system_messages == ("安全规则",)
    assert first.messages == ("当前请求", "较早")


def test_context_projection_fails_when_mandatory_content_exceeds_budget() -> None:
    policy = ProjectionPolicy(
        version="foundation-v1",
        model_role="generator",
        sections=(SectionSpec("system", "system_messages", True, 100, 4),),
    )
    block = ContextBlock("b1", "system", "runtime", "安全规则", 100, True, 5)

    with pytest.raises(ContextOverflow):
        ContextProjectionService().project(policy, (block,), input_budget=4)


def _memory_service(
    *, summary_builder, extractor=None, capability_registry=None
) -> MemoryService:
    owner_id = "11111111-1111-1111-1111-111111111111"
    state = MemoryState(owners={owner_id: OwnerRecord(owner_id, "user", "active", 1)})
    registry = capability_registry or MemoryCapabilityRegistry(
        tuple(
            MemoryCapabilityStatus(component, "healthy", "ready")
            for component in (
                "memory-short-term",
                "memory-long-term",
                "memory-extraction",
                "memory-graph-g1",
            )
        )
    )
    return MemoryService(
        InMemoryMemoryStore(durable=True),
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: datetime(2026, 8, 5, tzinfo=timezone.utc),
        summary_builder=summary_builder,
        extractor=extractor,
        capability_registry=registry,
    )


def test_summary_provider_timeout_omits_summary_without_blocking_answer(
    agent_harness,
) -> None:
    owner_id = "11111111-1111-1111-1111-111111111111"
    registry = MemoryCapabilityRegistry(
        tuple(
            MemoryCapabilityStatus(component, "healthy", "ready")
            for component in (
                "memory-short-term",
                "memory-long-term",
                "memory-extraction",
                "memory-graph-g1",
            )
        )
    )

    def slow_summary(_older, _recent):
        time.sleep(0.05)
        return "不应进入当前请求"

    memory = _memory_service(
        summary_builder=slow_summary,
        capability_registry=registry,
    )
    model = _AStreamModel("回复:当前问题")

    async def scenario() -> None:
        now = datetime.now(timezone.utc)
        store = agent_harness.make_store()
        actor = Actor(owner_id, "temporary_guest", "memory-session")
        conversation = store.create_conversation(actor, now)
        old_run = store.create_run(
            actor, conversation.conversation_id, "旧" * 21_600, str(uuid4()), now
        ).run
        runtime = agent_harness.make_runtime(
            model, store, memory=memory, memory_short_term_deadline=0.001
        )
        try:
            await agent_harness.await_status(store, owner_id, old_run.run_id, "succeeded")
            current_run = store.create_run(
                actor, conversation.conversation_id, "当前问题", str(uuid4()), now
            ).run
            await agent_harness.await_status(
                store, owner_id, current_run.run_id, "succeeded"
            )
        finally:
            await runtime.stop()

        assert "不应进入当前请求" not in str(model.messages)
        assert registry.get("memory-short-term").reason_code == "provider_timeout"

    asyncio.run(scenario())


def test_explicit_natural_memory_outcome_is_given_to_answer_model(
    agent_harness,
) -> None:
    owner_id = "11111111-1111-1111-1111-111111111111"
    content = "请记住，我叫林舟"
    memory = _memory_service(
        summary_builder=None,
        extractor=StructuredMemoryExtractor(
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
                        "confidence": 1.0,
                        "source_span": {"start": 4, "end": 8},
                    }
                ],
            }
        ),
    )
    model = _AStreamModel("已根据真实结果回复")

    async def scenario() -> None:
        now = datetime.now(timezone.utc)
        store = agent_harness.make_store()
        actor = Actor(owner_id, "temporary_guest", "memory-session")
        conversation = store.create_conversation(actor, now)
        run = store.create_run(
            actor, conversation.conversation_id, content, str(uuid4()), now
        ).run
        runtime = agent_harness.make_runtime(model, store, memory=memory)
        try:
            await agent_harness.await_status(store, owner_id, run.run_id, "succeeded")
        finally:
            await runtime.stop()

        assert any("status=saved" in str(item.content) for item in model.messages)

    asyncio.run(scenario())