"""AgentRuntime 恢复机制测试（D2 非 M06 归位保留 + 规则②公开接口断言）。

run lifecycle 的底层契约（create/claim/cancel/grant/waiting-approval）由
tests/agent/test_runs.py 单点权威断言；本文件只测 runtime 恢复机制本身
（checkpoint 重放、不确定租约、调度并发上限、跨进程取消观察），
全部经由 AgentRuntime 公开接口 start/stop 与 store 公开方法驱动。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.memory import InMemorySaver

from venagent.agent.ports import RunStoreError as StoreError
from venagent.agent.runtime import AgentRuntime
from venagent.ownership.models import Actor
from venagent.repo.inmemory import (
    InMemoryConversationRuntimeStore as MemoryRuntimeStore,
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


def test_completed_checkpoint_replays_finalizer_without_reinvoking_model(
    monkeypatch,
) -> None:
    # 缩短租约使第二个 worker 的 worker loop 能在真实时间内自然接管，
    # 而不是手动 claim_next 抢占（手动抢占会给 run 续上新租约，
    # 第二个 worker 反而永远 claim 不到）。
    from venagent.agent import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "LEASE_DURATION", timedelta(seconds=0.05))

    async def scenario() -> None:
        store = FlakyFinalizerStore()
        actor = Actor(str(uuid4()), "temporary_guest", str(uuid4()))
        now = datetime.now(timezone.utc)
        conversation = store.create_conversation(actor, now)
        created = store.create_run(
            actor, conversation.conversation_id, "继续", str(uuid4()), now
        )
        saver = InMemorySaver()
        model = CountingModel()

        # 首个 worker 消费 claim 并执行到 finalizer（模型已调用一次，
        # 但成功终态提交失败过一次），run 保持 running。
        first_runtime = AgentRuntime(model, saver, store, worker_id="worker-a")
        first_runtime.start()
        try:
            deadline = asyncio.get_running_loop().time() + 2
            while store.fail_once and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.01)
        finally:
            await first_runtime.stop()

        # 短租约已过期，第二个 worker 的 worker loop 会接管同一个 claim，
        # 从 checkpoint 只重放 finalizer（不再次调用模型）。
        second_runtime = AgentRuntime(model, saver, store, worker_id="worker-b")
        second_runtime.start()
        try:
            deadline = asyncio.get_running_loop().time() + 2
            completed = None
            while asyncio.get_running_loop().time() < deadline:
                completed = store.get_run(actor.owner_id, created.run.run_id)
                if completed is not None and completed.status == "succeeded":
                    break
                await asyncio.sleep(0.01)
        finally:
            await second_runtime.stop()

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
        runtime = AgentRuntime(
            DelayedModel(),
            InMemorySaver(),
            store,
            worker_id="worker-a",
        )
        runtime.start()
        try:
            # 等调度器 claim（status: queued -> running），再留余量让
            # 不确定租约执行收敛（心跳失败后绝不伪造终态）。
            deadline = asyncio.get_running_loop().time() + 1
            while asyncio.get_running_loop().time() < deadline:
                current = store.get_run(actor.owner_id, created.run.run_id)
                if current is not None and current.status == "running":
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.15)
        finally:
            await runtime.stop()

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
        model = BlockingModel()
        runtime = AgentRuntime(
            model,
            InMemorySaver(),
            store,
            worker_id="worker-a",
        )
        runtime.start()
        try:
            await asyncio.wait_for(model.started.wait(), 1)

            # 模拟另一进程只写持久化取消请求，不调用任何本地通知。
            store.request_cancel(actor.owner_id, created.run.run_id, now)

            deadline = asyncio.get_running_loop().time() + 2
            cancelled = None
            while asyncio.get_running_loop().time() < deadline:
                cancelled = store.get_run(actor.owner_id, created.run.run_id)
                if cancelled is not None and cancelled.status == "cancelled":
                    break
                await asyncio.sleep(0.01)
        finally:
            await runtime.stop()

        assert cancelled is not None and cancelled.status == "cancelled"
        assert model.cancelled.is_set()

    asyncio.run(scenario())