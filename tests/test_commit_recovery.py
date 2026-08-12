from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.memory import InMemorySaver

from venagent.agent.ports import RunStoreError as StoreError
from venagent.agent.runtime import LEASE_DURATION, AgentRuntime
from venagent.ownership.models import Actor
from venagent.repo.temporary import (
    TemporaryConversationRuntimeStore as MemoryRuntimeStore,
)


class CountingModel:
    def __init__(self) -> None:
        self.calls = 0

    async def astream(self, _messages):
        self.calls += 1
        yield AIMessageChunk(content="已完成")


class FlakyFinalizerStore(MemoryRuntimeStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_once = True

    def succeed_run(self, *args, **kwargs):
        if self.fail_once:
            self.fail_once = False
            raise StoreError("database unavailable")
        return super().succeed_run(*args, **kwargs)


class HeartbeatFailStore(MemoryRuntimeStore):
    def heartbeat(self, *args, **kwargs):
        raise StoreError("database unavailable")


class DelayedModel:
    async def astream(self, _messages):
        await asyncio.sleep(0.05)
        yield AIMessageChunk(content="迟到")


class ConcurrencyModel:
    def __init__(self) -> None:
        self.active = 0
        self.maximum = 0

    async def astream(self, _messages):
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        try:
            await asyncio.sleep(0.08)
            yield AIMessageChunk(content="完成")
        finally:
            self.active -= 1


class BlockingModel:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def astream(self, _messages):
        self.started.set()
        try:
            await asyncio.sleep(60)
            yield AIMessageChunk(content="不应到达")
        finally:
            self.cancelled.set()


def test_completed_checkpoint_replays_finalizer_without_reinvoking_model() -> None:
    async def scenario() -> None:
        store = FlakyFinalizerStore()
        actor = Actor(str(uuid4()), "temporary_guest", str(uuid4()))
        now = datetime.now(timezone.utc)
        conversation = store.create_conversation(actor, now)
        created = store.create_run(
            actor, conversation.conversation_id, "继续", str(uuid4()), now
        )
        first_claim = store.claim_next("worker-a", now, LEASE_DURATION)
        assert first_claim is not None
        model = CountingModel()
        runtime = AgentRuntime(model, InMemorySaver(), store, worker_id="worker-a")

        await runtime._execute(first_claim)
        uncertain = store.get_run(actor.owner_id, created.run.run_id)
        assert uncertain is not None and uncertain.status == "running"

        second_claim = store.claim_next(
            "worker-b", now + LEASE_DURATION + timedelta(seconds=1), LEASE_DURATION
        )
        assert second_claim is not None
        takeover = AgentRuntime(
            model, runtime._checkpointer, store, worker_id="worker-b"
        )
        await takeover._execute(second_claim)

        completed = store.get_run(actor.owner_id, created.run.run_id)
        assert completed is not None and completed.status == "succeeded"
        assert model.calls == 1
        assert [
            item.content
            for item in store.messages(actor.owner_id, conversation.conversation_id)
        ] == ["继续", "已完成"]

    asyncio.run(scenario())


def test_uncertain_lease_does_not_forge_cancelled_terminal(monkeypatch) -> None:
    from venagent.agent import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "HEARTBEAT_INTERVAL_SECONDS", 0.01)

    async def scenario() -> None:
        store = HeartbeatFailStore()
        actor = Actor(str(uuid4()), "temporary_guest", str(uuid4()))
        now = datetime.now(timezone.utc)
        conversation = store.create_conversation(actor, now)
        created = store.create_run(
            actor, conversation.conversation_id, "继续", str(uuid4()), now
        )
        claimed = store.claim_next("worker-a", now, LEASE_DURATION)
        assert claimed is not None
        runtime = AgentRuntime(
            DelayedModel(),
            InMemorySaver(),
            store,
            worker_id="worker-a",
        )

        await runtime._execute(claimed)
        uncertain = store.get_run(actor.owner_id, created.run.run_id)

        assert uncertain is not None
        assert uncertain.status == "running"
        assert uncertain.output_message_id is None

    asyncio.run(scenario())


def test_scheduler_runs_at_most_two_claims_concurrently() -> None:
    async def scenario() -> None:
        store = MemoryRuntimeStore()
        now = datetime.now(timezone.utc)
        actors = [
            Actor(str(uuid4()), "temporary_guest", str(uuid4())) for _ in range(2)
        ]
        run_ids: list[str] = []
        for item in actors:
            conversation = store.create_conversation(item, now)
            created = store.create_run(
                item, conversation.conversation_id, "并行", str(uuid4()), now
            )
            run_ids.append(created.run.run_id)
        model = ConcurrencyModel()
        runtime = AgentRuntime(model, InMemorySaver(), store, poll_interval=0.005)
        runtime.start()
        try:
            deadline = asyncio.get_running_loop().time() + 5
            while asyncio.get_running_loop().time() < deadline:
                runs = [store.get_run_internal(run_id) for run_id in run_ids]
                if all(run is not None and run.terminal for run in runs):
                    break
                await asyncio.sleep(0.01)
        finally:
            await runtime.stop()

        statuses = [store.get_run_internal(run_id).status for run_id in run_ids]
        assert model.maximum == 2
        assert statuses == ["succeeded", "succeeded"]

    asyncio.run(scenario())


def test_persistent_cancel_observer_handles_request_from_another_runtime(
    monkeypatch,
) -> None:
    from venagent.agent import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "CANCEL_OBSERVATION_INTERVAL_SECONDS", 0.01)

    async def scenario() -> None:
        store = MemoryRuntimeStore()
        actor = Actor(str(uuid4()), "temporary_guest", str(uuid4()))
        now = datetime.now(timezone.utc)
        conversation = store.create_conversation(actor, now)
        created = store.create_run(
            actor, conversation.conversation_id, "跨 worker 取消", str(uuid4()), now
        )
        claimed = store.claim_next("worker-a", now, LEASE_DURATION)
        assert claimed is not None
        model = BlockingModel()
        runtime = AgentRuntime(
            model,
            InMemorySaver(),
            store,
            worker_id="worker-a",
        )
        execution = asyncio.create_task(runtime._execute(claimed))
        await asyncio.wait_for(model.started.wait(), 1)

        # 模拟另一进程只写持久请求，不调用当前 runtime.notify_cancel。
        store.request_cancel(actor.owner_id, created.run.run_id, now)
        await asyncio.wait_for(execution, 1)

        cancelled = store.get_run(actor.owner_id, created.run.run_id)
        assert cancelled is not None and cancelled.status == "cancelled"
        assert model.cancelled.is_set()

    asyncio.run(scenario())
