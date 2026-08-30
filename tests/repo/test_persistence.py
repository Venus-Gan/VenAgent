"""持久化 Unit 契约（原 test_persistence.py 拆分一：非集成单测）。

- checkpoint 序列化只还原已知 run state 类型、拒绝未注册自定义类型；
- 未配置持久化走显式 temporary capabilities；
- schema 校验失败安全降级且不泄漏内部细节。

集成套件（真实 PG/Neo4j，`@pytest.mark.integration`）见
test_persistence_postgres_restart.py 与 test_persistence_postgres_concurrency.py。
共用装配在 tests/repo/conftest.py。
"""

from __future__ import annotations

from dataclasses import dataclass

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from venagent.agent.graph import checkpoint_serializer
from venagent.agent.state import (
    ApprovalItemRef,
    ApprovalWait,
    FinalAnswer,
    NodeOutcome,
    Plan,
    PlanNode,
    RunFailure,
    TaskInput,
)
from venagent.platform.runtime import DATABASE_URL


@dataclass(frozen=True)
class _UnregisteredCheckpointValue:
    value: str


def test_checkpoint_serializer_restores_known_run_state_types() -> None:
    serializer = checkpoint_serializer()
    plan_node = PlanNode("answer", "回答问题")
    approval_item = ApprovalItemRef("answer", "tool:1")
    values = (
        TaskInput("00000000-0000-0000-0000-000000000001", "问题"),
        plan_node,
        Plan(1, "完成回答", (plan_node,)),
        NodeOutcome(1, "answer", 1, "succeeded", "已完成"),
        approval_item,
        ApprovalWait(
            "approval:1",
            1,
            (approval_item,),
            "2026-08-06T00:00:00+00:00",
        ),
        FinalAnswer("完成", ("artifact:1",), ("evidence:1",)),
        RunFailure("model_error", "模型调用失败", True, "answer"),
    )

    assert tuple(
        serializer.loads_typed(serializer.dumps_typed(value)) for value in values
    ) == values


def test_checkpoint_serializer_blocks_unknown_custom_type_reconstruction() -> None:
    permissive = JsonPlusSerializer(allowed_msgpack_modules=True)
    payload = permissive.dumps_typed(_UnregisteredCheckpointValue("blocked"))

    restored = checkpoint_serializer().loads_typed(payload)

    assert restored == {"value": "blocked"}
    assert not isinstance(restored, _UnregisteredCheckpointValue)


def test_unconfigured_persistence_uses_explicit_temporary_capabilities(
    persistence_runtime,
) -> None:
    runtime = persistence_runtime({})

    assert runtime.status.mode == "temporary"
    assert runtime.status.reason_code == "postgresql_not_configured"
    assert runtime.status.as_health()["capabilities"] == {
        "anonymous_chat": "available",
        "account_identity": "unavailable",
        "conversation_persistence": "unavailable",
        "run_execution": "available",
        "restart_recovery": "unavailable",
    }


def test_schema_validation_failure_is_safe_and_does_not_expose_details(
    monkeypatch, persistence_runtime
) -> None:
    from venagent.platform.postgresql import runtime as runtime_module

    captured: dict[str, object] = {}

    class FakePool:
        def __init__(self, *_args, **_kwargs):
            pass

        def open(self, **_kwargs):
            return None

        def close(self):
            return None

    monkeypatch.setattr(runtime_module, "ConnectionPool", FakePool)

    def fake_saver(_pool, *, serde):
        captured["serde"] = serde
        return object()

    monkeypatch.setattr(runtime_module, "PostgresSaver", fake_saver)
    monkeypatch.setattr(
        runtime_module,
        "_validate_schema",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("private detail")),
    )

    runtime = persistence_runtime({DATABASE_URL: "postgresql://private"})

    assert runtime.status.mode == "temporary"
    assert runtime.status.reason_code == "persistence_schema_incompatible"
    assert "private" not in runtime.status.infrastructure.operator_message
    serializer = captured["serde"]
    value = TaskInput("00000000-0000-0000-0000-000000000001", "问题")
    assert serializer.loads_typed(serializer.dumps_typed(value)) == value