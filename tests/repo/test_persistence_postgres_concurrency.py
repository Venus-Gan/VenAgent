"""PostgreSQL 持久化集成：跨进程租约/领取/取消契约（原 test_persistence.py 拆分三）。

- 另一运行时取消被本工作线程观察到；并发 worker 只领取一次 queued run；
  过期租约被回收并隔离陈旧 worker；resume 不用已返回的连接；
  真实 PG，全部 `@pytest.mark.integration`；共用装配在 tests/repo/conftest.py。"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from src.__main__ import _configure_event_loop_policy
from src.agent.runs import AgentRunLifecycle, InvalidRunTransition
from src.interfaces.http.app import create_app
from src.platform.runtime import DATABASE_URL


@pytest.mark.integration
def test_postgres_worker_observes_cancel_requested_by_another_runtime(
    postgres_database_url: str,
    persistence_runtime,
    blocking_streaming_model,
) -> None:
    _configure_event_loop_policy()
    model = blocking_streaming_model()
    first = persistence_runtime({DATABASE_URL: postgres_database_url})
    second = persistence_runtime({DATABASE_URL: postgres_database_url})
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

@pytest.mark.integration
def test_postgres_concurrent_workers_claim_queued_run_once(
    postgres_database_url: str,
    persistence_runtime,
    create_run,
) -> None:
    database_url = postgres_database_url
    now = datetime.now(timezone.utc)
    seed = persistence_runtime({DATABASE_URL: database_url})
    _, _, created = create_run(seed, now, "并发领取")
    seed.close()

    first = persistence_runtime({DATABASE_URL: database_url})
    second = persistence_runtime({DATABASE_URL: database_url})
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

@pytest.mark.integration
def test_postgres_expired_lease_reclaim_fences_stale_worker(
    postgres_database_url: str,
    persistence_runtime,
    create_run,
) -> None:
    database_url = postgres_database_url
    now = datetime.now(timezone.utc)
    first = persistence_runtime({DATABASE_URL: database_url})
    actor, conversation, created = create_run(first, now, "接管前")
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

    second = persistence_runtime({DATABASE_URL: database_url})
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

@pytest.mark.integration
def test_postgres_resume_run_does_not_use_returned_connection(
    postgres_database_url: str,
    persistence_runtime,
    create_run,
) -> None:
    runtime = persistence_runtime({DATABASE_URL: postgres_database_url})
    try:
        now = datetime(2026, 8, 6, tzinfo=timezone.utc)
        _actor, _conversation, run = create_run(runtime, now, "resume-race")
        lifecycle = AgentRunLifecycle(runtime.store)
        claimed = lifecycle.claim_next("worker-a", now, timedelta(seconds=60))
        assert claimed is not None
        waiting = lifecycle.wait_approval(
            claimed.run_id,
            claimed.claim_token or "",
            claimed.execution_attempt,
            now,
        )
        assert waiting.status == "waiting_approval"
        resumed = lifecycle.resume(run.run_id, now)
        assert resumed.status == "queued"
        with pytest.raises(InvalidRunTransition):
            lifecycle.resume(run.run_id, now)
    finally:
        runtime.close()