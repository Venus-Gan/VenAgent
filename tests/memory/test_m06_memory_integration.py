"""M06 自然记忆（natural intent）契约测试——单点保留本文件。

契约（与 tests/agent/test_agent_loop.py 的 natural memory 双写叠测去重后，
本文件只保留「自然意图在公开 run 管线中被处理一次、且不绑定工具」这一面）：
  1. 以「记住」开头的用户消息进入 run 后，memory.process_natural_intent 恰好执行一次；
  2. 该 run 不给模型绑定工具 schema（model.bind_tools 不被调用），
     tool_control.model_tools 也不被调用（自然意图请求绕过工具面）；
  3. 自然意图消息不再进入 enqueue_extraction 自动提取通道；
  4. run 经公开生命周期正常结束（status == "succeeded"）。

所有断言都经公开接口（store.create_run / runtime.start / store.get_run_internal）
与假协作对象的公开计数进行，不触碰 AgentRuntime 的私有符号。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.memory import InMemorySaver

from src.agent.runtime import AgentRuntime
from src.memory.service import NaturalMemoryOutcome
from src.ownership.models import Actor
from src.repo.inmemory import (
    InMemoryConversationRuntimeStore as MemoryRuntimeStore,
)


class _NaturalMemory:
    """最小假 MemoryService：只暴露 natural intent 契约所需的行为。"""

    def __init__(self) -> None:
        self.process_calls = 0
        self.extraction_calls = 0

    @staticmethod
    def natural_intent(content: str) -> str | None:
        return "remember" if content.startswith("记住") else None

    def run_authorization(self, _execution_authorization, **kwargs):
        # 返回 None 表示运行期不注入记忆上下文块，只验证 natural 处理路径。
        return None

    def process_natural_intent(self, *_args, **_kwargs) -> NaturalMemoryOutcome:
        self.process_calls += 1
        return NaturalMemoryOutcome("remember", "saved", saved_count=1)

    def enqueue_extraction(self, *_args, **_kwargs) -> bool:
        self.extraction_calls += 1
        return True

    def record_user_message_for_consolidation(self, *_args, **_kwargs) -> bool:
        # 沉淀式写入改造后 run finalizer 的普通消息路径调用此方法；
        # 本契约只关注自然意图消息，普通消息路径返回 False 即可。
        return False


class _ToolControl:
    """最小假 ToolControlContext：只登记 exec_command 的公开可观察行为。"""

    def __init__(self) -> None:
        self.model_tools_calls = 0

    async def start_run(self, _run_id: str) -> None:
        pass

    async def stop_run(self, _run_id: str) -> None:
        pass

    def collect_blocks(self, *, run_id: str):
        return ()

    def model_tools(self, _run_id: str):
        self.model_tools_calls += 1
        return (
            {
                "type": "function",
                "name": "exec_command",
                "description": "执行命令",
                "parameters": {"type": "object", "properties": {}},
            },
        )


class _Model:
    def __init__(self) -> None:
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tuple(tools)
        return self

    async def astream(self, _messages):
        yield AIMessageChunk(content="模拟回答")


async def _wait_terminal(
    store: MemoryRuntimeStore, run_id: str, *, timeout: float = 5.0
) -> object:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        run = store.get_run_internal(run_id)
        if run is not None and run.terminal:
            return run
        await asyncio.sleep(0.01)
    raise AssertionError(f"run {run_id} did not reach a terminal state")


def test_natural_intent_is_processed_once_without_binding_tools() -> None:
    async def scenario() -> None:
        store = MemoryRuntimeStore()
        actor = Actor(str(uuid4()), "temporary_guest", str(uuid4()))
        now = datetime.now(timezone.utc)
        conversation = store.create_conversation(actor, now)
        created = store.create_run(
            actor,
            conversation.conversation_id,
            "记住，我叫小维",
            str(uuid4()),
            now,
        )
        memory = _NaturalMemory()
        control = _ToolControl()
        model = _Model()
        runtime = AgentRuntime(
            model,
            InMemorySaver(),
            store,
            memory=memory,
            tool_control=control,
            poll_interval=0.001,
        )
        runtime.start()
        try:
            completed = await _wait_terminal(store, created.run.run_id)
        finally:
            await runtime.stop()

        assert completed.status == "succeeded"
        assert memory.process_calls == 1
        assert memory.extraction_calls == 0
        assert model.bound_tools is None
        assert control.model_tools_calls == 0

    asyncio.run(scenario())