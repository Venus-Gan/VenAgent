"""PostgreSQL 持久化集成：重启存活契约（原 test_persistence.py 拆分二）。

- 重建 schema 后 agent run / memory 确认与脱敏 / 异步提取任务 / checkpointer 快照 /
  G1 图召回 / FastAPI run 在运行时重启后均存活；
- 真实 PG + Neo4j，全部 `@pytest.mark.integration`；共用装配在 tests/repo/conftest.py。"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from venagent.__main__ import _configure_event_loop_policy
from venagent.agent.graph import compile_agent_graph, run_config
from venagent.agent.runs import AgentRunLifecycle
from venagent.agent.state import FinalAnswer, RunState, TaskInput
from venagent.interfaces.http.app import create_app
from venagent.memory.errors import MemoryConfirmationInvalid
from venagent.memory.graph_memory import GraphMemory
from venagent.memory.long_term.facts import MemoryFact, MemorySource
from venagent.memory.ports import GraphProjectionStatus
from venagent.memory.service import MemoryService
from venagent.memory.short_term import MemorySummary
from venagent.platform.postgresql.migrations import SCHEMA_VERSION
from venagent.platform.runtime import DATABASE_URL


@pytest.mark.integration
def test_postgres_rebuild_and_agent_run_survive_runtime_restart(
    postgres_database_url: str,
    persistence_runtime,
    create_run,
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
    first = persistence_runtime({DATABASE_URL: database_url})
    actor, conversation, created = create_run(first, now, "重启前")
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

    second = persistence_runtime({DATABASE_URL: database_url})
    restored = second.store.get_run(actor.owner_id, created.run_id)
    messages = second.store.messages(actor.owner_id, conversation.conversation_id)
    second.close()

    assert restored is not None and restored.status == "succeeded"
    assert [item.content for item in messages] == ["重启前", "完成"]

@pytest.mark.integration
def test_postgres_memory_confirmation_and_redaction_survive_restart(
    postgres_database_url: str,
    neo4j_graph_store,
    persistence_runtime,
    ownership_service,
    clear_neo4j_owner,
) -> None:
    graph_store, driver, graph_database = neo4j_graph_store
    first = persistence_runtime({DATABASE_URL: postgres_database_url})
    actor = (
        ownership_service(first).register("memory-user", "correct-horse-battery-staple").actor
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

    second = persistence_runtime({DATABASE_URL: postgres_database_url})
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
    clear_neo4j_owner(driver, graph_database, actor.owner_id)

@pytest.mark.integration
def test_postgres_async_extraction_job_survives_restart_and_is_idempotent(
    postgres_database_url: str,
    persistence_runtime,
    ownership_service,
) -> None:
    now = datetime.now(timezone.utc)
    first = persistence_runtime({DATABASE_URL: postgres_database_url})
    actor = (
        ownership_service(first)
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

    second = persistence_runtime({DATABASE_URL: postgres_database_url})
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

@pytest.mark.integration
def test_postgres_async_checkpointer_supports_ainvoke_and_aget_state(
    postgres_database_url: str,
    persistence_runtime,
) -> None:
    _configure_event_loop_policy()

    async def scenario() -> None:
        runtime = persistence_runtime({DATABASE_URL: postgres_database_url})
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

@pytest.mark.integration
def test_postgres_g1_path_recall_survives_restart_and_forget(
    postgres_database_url: str,
    neo4j_graph_store,
    persistence_runtime,
    ownership_service,
    clear_neo4j_owner,
) -> None:
    graph_store, driver, graph_database = neo4j_graph_store
    first = persistence_runtime({DATABASE_URL: postgres_database_url})
    ownership = ownership_service(first)
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

    second = persistence_runtime({DATABASE_URL: postgres_database_url})
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
        clear_neo4j_owner(driver, graph_database, actor.owner_id)
        ownership_service(second).finish_deletion(actor.owner_id)
        second.close()

@pytest.mark.integration
def test_postgres_fastapi_run_succeeds_and_checkpoint_survives_restart(
    postgres_database_url: str,
    persistence_runtime,
    fixed_streaming_model,
) -> None:
    _configure_event_loop_policy()
    first = persistence_runtime({DATABASE_URL: postgres_database_url})
    app = create_app(fixed_streaming_model(), persistence_runtime=first)
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
        second = persistence_runtime({DATABASE_URL: postgres_database_url})
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