from __future__ import annotations

import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from venagent.__main__ import _configure_event_loop_policy
from venagent.agent.graph import checkpoint_serializer, compile_agent_graph, run_config
from venagent.agent.runs import AgentRunLifecycle, InvalidRunTransition
from venagent.agent.state import (
    ApprovalItemRef,
    ApprovalWait,
    FinalAnswer,
    NodeOutcome,
    Plan,
    PlanNode,
    RunFailure,
    RunState,
    TaskInput,
)
from venagent.interfaces.http.app import create_app
from venagent.memory.errors import MemoryConfirmationInvalid
from venagent.memory.graph_memory import GraphMemory
from venagent.memory.long_term.facts import MemoryFact, MemorySource
from venagent.memory.ports import GraphProjectionStatus
from venagent.memory.service import MemoryService
from venagent.memory.short_term import MemorySummary
from venagent.ownership.service import OwnershipService
from venagent.platform.postgresql.migrations import SCHEMA_VERSION, migrate_database
from venagent.platform.runtime import DATABASE_URL
from venagent.platform.runtime import build_persistence_runtime as _build_resources
from venagent.platform.security import Argon2PasswordHasher, JwtAccessTokenCodec
from venagent.repo.postgresql import (
    PostgresConversationRuntimeStore,
    PostgresOwnershipStore,
)
from venagent.repo.postgresql.memory import PostgresMemoryStore


def build_persistence_runtime(environment):
    """测试装配仍显式发生在 platform façade 之外。"""

    runtime = _build_resources(environment)
    if runtime.status.mode == "durable":
        pool = runtime.postgresql_pool
        runtime.store = PostgresConversationRuntimeStore(pool)
        runtime.ownership_store = PostgresOwnershipStore(pool)
        runtime.memory_store = PostgresMemoryStore(pool)
    return runtime


@pytest.fixture
def postgres_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    with psycopg.connect(database_url) as connection:
        database_name = connection.execute("SELECT current_database()").fetchone()[0]
    if database_name != "venagent_test":
        pytest.fail("真实集成测试只允许清理隔离数据库 venagent_test")

    migrate_database(database_url)
    with psycopg.connect(database_url) as connection:
        # 只有通过上方数据库名白名单后才允许执行破坏性清理。
        connection.execute("TRUNCATE TABLE owners CASCADE")
    return database_url


def _create_run(runtime, now: datetime, content: str):
    assert runtime.status.mode == "durable"
    ownership = OwnershipService(
        runtime.ownership_store,
        Argon2PasswordHasher(),
        JwtAccessTokenCodec(
            "postgres-test-secret-that-is-at-least-32-bytes-long",
            issuer="venagent",
            audience="venagent-web",
        ),
    )
    actor = ownership.bootstrap_guest().actor
    conversation = runtime.store.create_conversation(actor, now)
    created = runtime.store.create_run(
        actor, conversation.conversation_id, content, str(uuid4()), now
    )
    return actor, conversation, created.run


def _ownership(runtime) -> OwnershipService:
    return OwnershipService(
        runtime.ownership_store,
        Argon2PasswordHasher(),
        JwtAccessTokenCodec(
            "postgres-test-secret-that-is-at-least-32-bytes-long",
            issuer="venagent",
            audience="venagent-web",
        ),
    )


def _clear_neo4j_owner(driver, database: str, owner_id: str) -> None:
    """清除单个真实验收 owner 的图投影，保持其他测试数据不受影响。"""
    with driver.session(database=database) as session:
        session.run(
            """MATCH (memory:M05Memory {owner_id:$owner_id})
            DETACH DELETE memory""",
            owner_id=owner_id,
        ).consume()
        session.run(
            """MATCH (projection:M05GraphProjection {owner_id:$owner_id})
            DETACH DELETE projection""",
            owner_id=owner_id,
        ).consume()


class _FixedStreamingModel:
    async def astream(self, _messages):
        yield AIMessageChunk(content="持久回答")


class _BlockingStreamingModel:
    def __init__(self) -> None:
        self.started = Event()
        self.cancelled = Event()

    async def astream(self, _messages):
        self.started.set()
        try:
            await asyncio.sleep(60)
            yield AIMessageChunk(content="不应到达")
        finally:
            self.cancelled.set()


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


def test_unconfigured_persistence_uses_explicit_temporary_capabilities() -> None:
    runtime = build_persistence_runtime({})

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
    monkeypatch,
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

    runtime = build_persistence_runtime({DATABASE_URL: "postgresql://private"})

    assert runtime.status.mode == "temporary"
    assert runtime.status.reason_code == "persistence_schema_incompatible"
    assert "private" not in runtime.status.infrastructure.operator_message
    serializer = captured["serde"]
    value = TaskInput("00000000-0000-0000-0000-000000000001", "问题")
    assert serializer.loads_typed(serializer.dumps_typed(value)) == value


def test_postgres_rebuild_and_agent_run_survive_runtime_restart(
    postgres_database_url: str,
) -> None:
    database_url = postgres_database_url
    with psycopg.connect(database_url) as connection:
        versions = connection.execute(
            "SELECT version FROM venagent_schema_migrations ORDER BY version"
        ).fetchall()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            ).fetchall()
        }
    assert versions == [(SCHEMA_VERSION,)]
    assert {
        "conversations",
        "conversation_messages",
        "agent_runs",
        "run_grants",
        "memory_summaries",
        "memory_jobs",
    } <= tables
    assert "conversation_turns" not in tables

    now = datetime.now(timezone.utc)
    first = build_persistence_runtime({DATABASE_URL: database_url})
    actor, conversation, created = _create_run(first, now, "重启前")
    claimed = AgentRunLifecycle(first.store).claim_next(
        "worker-a", now, timedelta(seconds=60)
    )
    assert claimed is not None and claimed.run_id == created.run_id
    AgentRunLifecycle(first.store).succeed(
        claimed.run_id,
        claimed.claim_token or "",
        claimed.execution_attempt,
        "完成",
        now,
    )
    first.close()

    second = build_persistence_runtime({DATABASE_URL: database_url})
    restored = second.store.get_run(actor.owner_id, created.run_id)
    messages = second.store.messages(actor.owner_id, conversation.conversation_id)
    second.close()

    assert restored is not None and restored.status == "succeeded"
    assert [item.content for item in messages] == ["重启前", "完成"]


def test_postgres_memory_confirmation_and_redaction_survive_restart(
    postgres_database_url: str,
    neo4j_graph_store,
) -> None:
    graph_store, driver, graph_database = neo4j_graph_store
    first = build_persistence_runtime({DATABASE_URL: postgres_database_url})
    actor = (
        _ownership(first).register("memory-user", "correct-horse-battery-staple").actor
    )
    memory = MemoryService(
        first.memory_store,
        first.ownership_store,
        graph_store=graph_store,
        cursor_secret="postgres-memory-cursor-secret-32-bytes",
    )
    auth = memory.command_authorization(actor)
    name = memory.remember(
        auth,
        "记住，我叫小维",
        source_ref=f"message:{uuid4()}",
        source_order=1,
        explicit=True,
    )
    project = memory.remember(
        auth,
        "我负责小维项目",
        source_ref=f"message:{uuid4()}",
        source_order=2,
        explicit=False,
    )
    token, count = memory.request_delete_all(auth)
    assert name is not None and project is not None and count == 2
    assert memory.process_pending_jobs() == 1
    first.close()

    second = build_persistence_runtime({DATABASE_URL: postgres_database_url})
    restored = MemoryService(
        second.memory_store,
        second.ownership_store,
        graph_store=graph_store,
        cursor_secret="postgres-memory-cursor-secret-32-bytes",
    )
    restored_auth = restored.command_authorization(actor)
    assert restored.confirm_delete_all(restored_auth, token) == 2
    tombstone = second.memory_store.get_fact(actor.owner_id, name.memory_id)
    assert tombstone is not None
    assert (tombstone.subject, tombstone.slot, tombstone.fact) == ("", "", "")
    assert restored.status(restored_auth).purge_pending is True
    assert restored.process_pending_jobs() == 1
    assert restored.status(restored_auth).purge_pending is False
    restored.set_enabled(restored_auth, True)
    with pytest.raises(MemoryConfirmationInvalid):
        restored.confirm_delete_all(restored_auth, token)
    second.close()
    _clear_neo4j_owner(driver, graph_database, actor.owner_id)


def test_postgres_async_extraction_job_survives_restart_and_is_idempotent(
    postgres_database_url: str,
) -> None:
    now = datetime.now(timezone.utc)
    first = build_persistence_runtime({DATABASE_URL: postgres_database_url})
    actor = (
        _ownership(first)
        .register("memory-job-user", "correct-horse-battery-staple")
        .actor
    )
    conversation = first.store.create_conversation(actor, now)
    created = first.store.create_run(
        actor,
        conversation.conversation_id,
        "我住在杭州",
        str(uuid4()),
        now,
    )
    authorization = first.store.authorize_run(created.run.run_id, now)
    memory = MemoryService(
        first.memory_store,
        first.ownership_store,
        cursor_secret="postgres-memory-cursor-secret-32-bytes",
        clock=lambda: now,
    )
    memory_auth = memory.run_authorization(authorization, action="write")
    source_ref = f"message:{created.input_message.message_id}"

    assert memory.enqueue_extraction(
        memory_auth,
        created.input_message.content,
        source_ref=source_ref,
        source_order=created.input_message.sequence,
    )
    assert not memory.enqueue_extraction(
        memory_auth,
        created.input_message.content,
        source_ref=source_ref,
        source_order=created.input_message.sequence,
    )
    summary = MemorySummary(
        str(uuid4()),
        actor.owner_id,
        "default",
        conversation.conversation_id,
        created.input_message.message_id,
        created.input_message.message_id,
        created.input_message.sequence,
        created.input_message.sequence,
        "可重建摘要",
        "test-summary-v1",
        "a" * 64,
        0,
        now,
    )
    first.memory_store.save_summary(summary)
    claimed = first.memory_store.claim_jobs(now, limit=1)
    assert len(claimed) == 1 and claimed[0].attempts == 1
    first.close()

    second = build_persistence_runtime({DATABASE_URL: postgres_database_url})
    restored = MemoryService(
        second.memory_store,
        second.ownership_store,
        cursor_secret="postgres-memory-cursor-secret-32-bytes",
        clock=lambda: now + timedelta(seconds=31),
    )
    assert (
        second.memory_store.get_summary(actor.owner_id, conversation.conversation_id)
        == summary
    )
    assert restored.process_pending_jobs() == 1
    facts = second.memory_store.active_facts(actor.owner_id, "default")
    assert len(facts) == 1 and facts[0].fact == "我住在杭州"
    assert restored.process_pending_jobs() == 0
    second.close()


def test_postgres_async_checkpointer_supports_ainvoke_and_aget_state(
    postgres_database_url: str,
) -> None:
    _configure_event_loop_policy()

    async def scenario() -> None:
        runtime = build_persistence_runtime({DATABASE_URL: postgres_database_url})
        run_id = str(uuid4())

        async def answer(_state: RunState) -> dict[str, object]:
            return {"final_answer": FinalAnswer("完成"), "failure": None}

        await runtime.open()
        graph = compile_agent_graph(answer, runtime.checkpointer)
        initial: RunState = {
            "task_input": TaskInput(str(uuid4()), "问题"),
            "phase": "synthesizing",
            "node_outcomes": (),
            "approval_wait": None,
            "final_answer": None,
            "failure": None,
        }
        try:
            result = await graph.ainvoke(initial, config=run_config(run_id))
            snapshot = await graph.aget_state(run_config(run_id))

            assert result["final_answer"] == FinalAnswer("完成")
            assert snapshot.values["final_answer"] == FinalAnswer("完成")
        finally:
            await runtime.checkpointer.adelete_thread(run_id)
            await runtime.aclose()

    asyncio.run(scenario())


def test_postgres_g1_path_recall_survives_restart_and_forget(
    postgres_database_url: str,
    neo4j_graph_store,
) -> None:
    graph_store, driver, graph_database = neo4j_graph_store
    first = build_persistence_runtime({DATABASE_URL: postgres_database_url})
    ownership = _ownership(first)
    actor = ownership.register(
        "g1-path-acceptance",
        "G1-path-acceptance-Aa1!",
        rate_key="g1-path-test",
    ).actor
    memory = MemoryService(
        first.memory_store,
        first.ownership_store,
        graph_store=graph_store,
        cursor_secret="postgres-test-secret-that-is-at-least-32-bytes-long",
    )
    auth = memory.command_authorization(actor)
    now = datetime.now(timezone.utc)
    seed_source = MemorySource(
        "g1-source:seed",
        actor.owner_id,
        "default",
        "user_message",
        None,
        1,
        now,
    )
    neighbor_source = MemorySource(
        "g1-source:neighbor",
        actor.owner_id,
        "default",
        "user_message",
        None,
        2,
        now + timedelta(seconds=1),
    )
    seed = MemoryFact(
        str(uuid4()),
        actor.owner_id,
        "default",
        "test",
        "seed",
        "abcdexyza",
        "active",
        (seed_source.source_ref,),
        now,
        now,
    )
    neighbor = MemoryFact(
        str(uuid4()),
        actor.owner_id,
        "default",
        "test",
        "neighbor",
        "exyza",
        "active",
        (neighbor_source.source_ref,),
        now + timedelta(seconds=1),
        now + timedelta(seconds=1),
    )
    first.memory_store.save_fact(seed, seed_source, now)
    first.memory_store.save_fact(
        neighbor, neighbor_source, now + timedelta(seconds=1)
    )
    authority_revision = first.memory_store.authority_revision(
        actor.owner_id, "default"
    )
    settings = first.memory_store.settings(actor.owner_id)
    # 直接写入的验收事实不经过写入流水线，因此显式构建同一 revision 的图投影。
    assert GraphMemory(first.memory_store, graph_store).project(
        actor.owner_id,
        "default",
        authority_revision,
        settings.deletion_generation,
    ) is GraphProjectionStatus.APPLIED

    before_restart = memory.context_blocks(auth, "abcde")
    assert tuple(block.block_id for block in before_restart) == (
        f"memory:{seed.memory_id}",
        f"memory:{neighbor.memory_id}",
    )
    first.close()

    second = build_persistence_runtime({DATABASE_URL: postgres_database_url})
    restored = MemoryService(
        second.memory_store,
        second.ownership_store,
        graph_store=graph_store,
        cursor_secret="postgres-test-secret-that-is-at-least-32-bytes-long",
    )
    restored_auth = restored.command_authorization(actor)
    try:
        assert restored.context_blocks(restored_auth, "abcde") == before_restart

        restored.forget(restored_auth, neighbor.memory_id)
        authority_revision = second.memory_store.authority_revision(
            actor.owner_id, "default"
        )
        settings = second.memory_store.settings(actor.owner_id)
        assert GraphMemory(second.memory_store, graph_store).project(
            actor.owner_id,
            "default",
            authority_revision,
            settings.deletion_generation,
        ) is GraphProjectionStatus.APPLIED

        remaining = restored.context_blocks(restored_auth, "abcde")
        assert tuple(block.block_id for block in remaining) == (
            f"memory:{seed.memory_id}",
        )
    finally:
        _clear_neo4j_owner(driver, graph_database, actor.owner_id)
        _ownership(second).finish_deletion(actor.owner_id)
        second.close()


def test_postgres_fastapi_run_succeeds_and_checkpoint_survives_restart(
    postgres_database_url: str,
) -> None:
    _configure_event_loop_policy()
    first = build_persistence_runtime({DATABASE_URL: postgres_database_url})
    app = create_app(_FixedStreamingModel(), persistence_runtime=first)
    origin = {"Origin": "http://localhost:5173"}

    with TestClient(app) as client:
        identity_response = client.post("/api/auth/guest", headers=origin)
        assert identity_response.status_code == 200
        headers = {
            "Authorization": f"Bearer {identity_response.json()['access_token']}"
        }
        conversation = client.post("/api/conversations", headers=headers).json()
        created = client.post(
            f"/api/conversations/{conversation['conversation_id']}/runs",
            headers=headers,
            json={"message": "持久问题", "client_request_id": str(uuid4())},
        )
        assert created.status_code == 202
        run_id = created.json()["run"]["run_id"]

        for _ in range(100):
            run = client.get(f"/api/runs/{run_id}", headers=headers).json()
            if run["status"] in {"succeeded", "failed", "cancelled", "incompatible"}:
                break
            time.sleep(0.02)
        else:
            raise AssertionError("durable run did not reach a terminal state")

        detail = client.get(
            f"/api/conversations/{conversation['conversation_id']}", headers=headers
        ).json()
        assert run["status"] == "succeeded"
        assert [item["content"] for item in detail["messages"]] == [
            "持久问题",
            "持久回答",
        ]

    async def verify_restart() -> None:
        second = build_persistence_runtime({DATABASE_URL: postgres_database_url})
        await second.open()
        try:
            assert await second.checkpointer.aget_tuple(run_config(run_id)) is not None
            messages = second.store.messages(
                identity_response.json()["actor"]["owner_id"],
                conversation["conversation_id"],
            )
            assert [item.content for item in messages] == ["持久问题", "持久回答"]
            await second.checkpointer.adelete_thread(run_id)
        finally:
            await second.aclose()

    asyncio.run(verify_restart())


def test_postgres_worker_observes_cancel_requested_by_another_runtime(
    postgres_database_url: str,
) -> None:
    _configure_event_loop_policy()
    model = _BlockingStreamingModel()
    first = build_persistence_runtime({DATABASE_URL: postgres_database_url})
    second = build_persistence_runtime({DATABASE_URL: postgres_database_url})
    app = create_app(model, persistence_runtime=first)
    origin = {"Origin": "http://localhost:5173"}

    try:
        with TestClient(app) as client:
            identity = client.post("/api/auth/guest", headers=origin).json()
            headers = {"Authorization": f"Bearer {identity['access_token']}"}
            conversation = client.post("/api/conversations", headers=headers).json()
            created = client.post(
                f"/api/conversations/{conversation['conversation_id']}/runs",
                headers=headers,
                json={"message": "跨 runtime 取消", "client_request_id": str(uuid4())},
            ).json()
            run_id = created["run"]["run_id"]
            assert model.started.wait(2)

            requested_at = datetime.now(timezone.utc)
            second.store.request_cancel(
                identity["actor"]["owner_id"], run_id, requested_at
            )
            started = time.perf_counter()
            for _ in range(200):
                run = client.get(f"/api/runs/{run_id}", headers=headers).json()
                if run["status"] == "cancelled":
                    break
                time.sleep(0.01)

            assert run["status"] == "cancelled"
            assert time.perf_counter() - started < 1.5
            assert model.cancelled.wait(1)
    finally:
        second.close()


def test_postgres_concurrent_workers_claim_queued_run_once(
    postgres_database_url: str,
) -> None:
    database_url = postgres_database_url
    now = datetime.now(timezone.utc)
    seed = build_persistence_runtime({DATABASE_URL: database_url})
    _, _, created = _create_run(seed, now, "并发领取")
    seed.close()

    first = build_persistence_runtime({DATABASE_URL: database_url})
    second = build_persistence_runtime({DATABASE_URL: database_url})
    barrier = Barrier(3)

    def claim(runtime, worker_id: str):
        barrier.wait(timeout=5)
        return AgentRunLifecycle(runtime.store).claim_next(
            worker_id, now, timedelta(seconds=60)
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(claim, first, "worker-a")
            second_future = executor.submit(claim, second, "worker-b")
            barrier.wait(timeout=5)
            results = [first_future.result(), second_future.result()]

        claimed = [item for item in results if item is not None]
        assert len(claimed) == 1
        assert claimed[0].run_id == created.run_id
        assert claimed[0].execution_attempt == 1
        assert claimed[0].claim_token is not None

        with psycopg.connect(database_url) as connection:
            row = connection.execute(
                """SELECT status, execution_attempt, claim_token
                FROM agent_runs WHERE run_id=%s""",
                (created.run_id,),
            ).fetchone()
        assert row is not None
        assert row[0] == "running"
        assert row[1] == 1
        assert row[2] is not None
    finally:
        first.close()
        second.close()


def test_postgres_expired_lease_reclaim_fences_stale_worker(
    postgres_database_url: str,
) -> None:
    database_url = postgres_database_url
    now = datetime.now(timezone.utc)
    first = build_persistence_runtime({DATABASE_URL: database_url})
    actor, conversation, created = _create_run(first, now, "接管前")
    first_lifecycle = AgentRunLifecycle(first.store)
    first_claim = first_lifecycle.claim_next("worker-a", now, timedelta(seconds=60))
    assert first_claim is not None
    assert first_claim.run_id == created.run_id
    assert first_claim.claim_token is not None
    assert first_claim.execution_attempt == 1

    with psycopg.connect(database_url) as connection:
        connection.execute(
            """UPDATE agent_runs SET lease_expires_at=now()-interval '1 second'
            WHERE run_id=%s""",
            (created.run_id,),
        )

    second = build_persistence_runtime({DATABASE_URL: database_url})
    second_lifecycle = AgentRunLifecycle(second.store)
    try:
        second_claim = second_lifecycle.claim_next(
            "worker-b", now, timedelta(seconds=60)
        )
        assert second_claim is not None
        assert second_claim.run_id == created.run_id
        assert second_claim.claim_token is not None
        assert second_claim.claim_token != first_claim.claim_token
        assert second_claim.execution_attempt == 2

        with pytest.raises(InvalidRunTransition):
            first.store.heartbeat(
                first_claim.run_id,
                "worker-a",
                first_claim.claim_token,
                first_claim.execution_attempt,
                now,
                timedelta(seconds=60),
            )

        with pytest.raises(InvalidRunTransition):
            first_lifecycle.succeed(
                first_claim.run_id,
                first_claim.claim_token,
                first_claim.execution_attempt,
                "旧 worker 回答",
                now,
            )

        with pytest.raises(InvalidRunTransition):
            first_lifecycle.fail(
                first_claim.run_id,
                first_claim.claim_token,
                first_claim.execution_attempt,
                "stale_worker",
                "旧 worker 失败",
                now,
            )

        current = second.store.get_run(actor.owner_id, created.run_id)
        assert current is not None
        assert current.status == "running"
        assert current.execution_attempt == 2

        succeeded = second_lifecycle.succeed(
            second_claim.run_id,
            second_claim.claim_token,
            second_claim.execution_attempt,
            "新 worker 回答",
            now,
        )
        messages = second.store.messages(actor.owner_id, conversation.conversation_id)

        assert succeeded.status == "succeeded"
        assert [item.content for item in messages] == ["接管前", "新 worker 回答"]
    finally:
        first.close()
        second.close()
