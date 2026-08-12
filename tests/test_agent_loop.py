from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from venagent.agent.graph import run_config
from venagent.agent.runs import ActiveRunContext, CancelToken
from venagent.agent.runtime import AgentRuntime
from venagent.agent.state import (
    NodeOutcome,
    RunState,
    StateConsistencyError,
    TaskInput,
    merge_node_outcomes,
)
from venagent.conversation.models import ConversationMessage
from venagent.memory.authorization import MemoryAuthorization
from venagent.memory.capabilities import (
    MemoryCapabilityRegistry,
    MemoryCapabilityStatus,
)
from venagent.memory.long_term.extractor import StructuredMemoryExtractor
from venagent.memory.service import MemoryService
from venagent.ownership.models import ExecutionAuthorization, OwnerRecord
from venagent.promptctx import (
    ContextBlock,
    ContextOverflow,
    ContextProjectionService,
    ProjectionPolicy,
    SectionSpec,
)
from venagent.repo.temporary import (
    TemporaryOwnershipStore as MemoryOwnershipStore,
)
from venagent.repo.temporary import (
    TemporaryPlatformState as MemoryState,
)
from venagent.repo.temporary.memory import TemporaryMemoryStore as InMemoryMemoryStore


def test_run_state_does_not_duplicate_business_lifecycle_status() -> None:
    assert set(RunState.__annotations__) == {
        "task_input",
        "phase",
        "plan",
        "node_outcomes",
        "approval_wait",
        "final_answer",
        "failure",
    }


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


class FixedModel:
    def invoke(self, messages):
        return AIMessage(content=f"回复:{messages[-1].content}")


def test_summary_provider_timeout_omits_summary_without_blocking_answer() -> None:
    now = datetime(2026, 8, 5, tzinfo=timezone.utc)
    owner_id = "11111111-1111-1111-1111-111111111111"
    conversation_id = "22222222-2222-2222-2222-222222222222"
    state = MemoryState(owners={owner_id: OwnerRecord(owner_id, "user", "active", 1)})
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

    memory = MemoryService(
        InMemoryMemoryStore(durable=True),
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: now,
        summary_builder=slow_summary,
        capability_registry=registry,
    )
    auth = MemoryAuthorization(
        owner_id=owner_id,
        tenant_id="default",
        allowed_data_scopes=("owner:memory",),
        allowed_action_classes=("memory.read", "memory.write"),
        authorization_epoch=1,
        source_kind="run",
        action="read",
        run_id="33333333-3333-3333-3333-333333333333",
        conversation_id=conversation_id,
    )
    history = (
        _conversation_message(owner_id, conversation_id, 1, "user", "旧" * 40_000, now),
        _conversation_message(owner_id, conversation_id, 2, "assistant", "旧回答", now),
        _conversation_message(owner_id, conversation_id, 3, "user", "当前问题", now),
    )
    runtime = AgentRuntime(
        FixedModel(),
        InMemorySaver(),
        object(),
        memory=memory,
        memory_short_term_deadline=0.001,
    )
    active = ActiveRunContext(auth.run_id or "", owner_id, "claim", 1, CancelToken())
    answer = runtime._answer_node(auth.run_id or "", active, history, auth)

    result = asyncio.run(
        answer({"task_input": TaskInput(history[-1].message_id, history[-1].content)})
    )

    assert result["final_answer"] is not None
    assert "不应进入当前请求" not in result["final_answer"].content
    assert registry.get("memory-short-term").reason_code == "provider_timeout"


def test_explicit_natural_memory_outcome_is_given_to_answer_model() -> None:
    now = datetime(2026, 8, 5, tzinfo=timezone.utc)
    owner_id = "11111111-1111-1111-1111-111111111111"
    conversation_id = "22222222-2222-2222-2222-222222222222"
    state = MemoryState(owners={owner_id: OwnerRecord(owner_id, "user", "active", 1)})
    store = InMemoryMemoryStore(durable=True)
    content = "请记住，我叫林舟"
    memory = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: now,
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
    execution = ExecutionAuthorization(
        run_id="33333333-3333-3333-3333-333333333333",
        owner_id=owner_id,
        tenant_id="default",
        conversation_id=conversation_id,
        allowed_data_scopes=("owner:memory",),
        allowed_action_classes=("memory.read", "memory.write"),
        authorization_epoch=1,
    )

    class CaptureModel:
        def __init__(self) -> None:
            self.messages = ()

        def invoke(self, messages):
            self.messages = tuple(messages)
            return AIMessage(content="已根据真实结果回复")

    model = CaptureModel()
    message = _conversation_message(
        owner_id, conversation_id, 1, "user", content, now
    )
    runtime = AgentRuntime(model, InMemorySaver(), object(), memory=memory)
    result = asyncio.run(
        runtime._answer_node(
            execution.run_id,
            ActiveRunContext(execution.run_id, owner_id, "claim", 1, CancelToken()),
            (message,),
            memory.run_authorization(execution, action="read"),
            execution,
        )({"task_input": TaskInput(message.message_id, content)})
    )

    assert result["final_answer"].content == "已根据真实结果回复"
    assert any("status=saved" in str(item.content) for item in model.messages)
    assert len(store.active_facts(owner_id, "default")) == 1


def _conversation_message(
    owner_id: str,
    conversation_id: str,
    sequence: int,
    role: str,
    content: str,
    now: datetime,
) -> ConversationMessage:
    return ConversationMessage(
        message_id=f"00000000-0000-0000-0000-{sequence:012d}",
        conversation_id=conversation_id,
        owner_id=owner_id,
        role=role,  # type: ignore[arg-type]
        content=content,
        sequence=sequence,
        created_at=now + timedelta(seconds=sequence),
        client_request_id=(
            f"10000000-0000-0000-0000-{sequence:012d}" if role == "user" else None
        ),
        source_run_id=(
            f"20000000-0000-0000-0000-{sequence:012d}" if role == "assistant" else None
        ),
        reply_to_message_id=(
            f"00000000-0000-0000-0000-{sequence - 1:012d}"
            if role == "assistant"
            else None
        ),
    )
