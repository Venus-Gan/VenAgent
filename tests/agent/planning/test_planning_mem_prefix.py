"""计划层 mem_prefix 装配单测：记忆/工具状态前缀进入四个 LLM 节点的 SystemMessage。

对齐 AGI-saber memPrefix（每 run 一次统一装配、节点级 prompt 内联保留）；
mem_prefix="" 时与 M07 现状完全一致（零回归护栏）。
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessageChunk

from venagent.agent.planning.factory import build_planning_nodes
from venagent.agent.planning.planner import _invoke
from venagent.agent.planning.replanner import _ask_replanner
from venagent.agent.runtime import AgentRuntime
from venagent.agent.state import Plan, PlanNode, TaskInput
from venagent.promptctx import ContextProjectionService
from venagent.promptctx.context import ContextBlock, conservative_token_count


def _block(block_id: str, category: str, content: str) -> ContextBlock:
    return ContextBlock(
        block_id,
        category,
        "test-src",
        content,
        100,
        False,
        conservative_token_count(content),
    )


class FakeMemory:
    def __init__(
        self,
        long_term: tuple[ContextBlock, ...] = (),
        summary: tuple[ContextBlock, ...] = (),
        snapshot_error: Exception | None = None,
    ) -> None:
        self._long_term = long_term
        self._summary = summary
        self._snapshot_error = snapshot_error
        self.timeouts: list[str] = []

    def capture_snapshot(self, auth, allow_disabled=True):
        if self._snapshot_error is not None:
            raise self._snapshot_error
        return {"snapshot": True}

    def summary_blocks(self, auth, history, message_id, snapshot=None):
        return self._summary

    def context_blocks(self, auth, content, snapshot=None):
        return self._long_term

    def note_provider_timeout(self, provider):
        self.timeouts.append(provider)

    def note_provider_ready(self, provider, reason):
        pass


class FakeToolControl:
    def __init__(self, blocks: tuple[ContextBlock, ...] = ()) -> None:
        self._blocks = blocks

    def collect_blocks(self, *, run_id: str):
        return self._blocks


class CaptureModel:
    """捕获全部 messages 的哑模型（ainvoke / astream / invoke 三种入口）。"""

    def __init__(self, text: str = "ok") -> None:
        self._text = text
        self.calls: list[tuple] = []

    def _capture(self, messages):
        self.calls.append(tuple(messages))

    async def ainvoke(self, messages):
        self._capture(messages)
        return AIMessageChunk(content=self._text)

    async def astream(self, messages):
        self._capture(messages)
        yield AIMessageChunk(content=self._text)

    def invoke(self, messages):
        self._capture(messages)
        return AIMessageChunk(content=self._text)


def _runtime(
    memory: FakeMemory | None = None,
    tool_control: FakeToolControl | None = None,
) -> AgentRuntime:
    return AgentRuntime(
        None, None, None, memory=memory, tool_control=tool_control
    )


def test_planner_invoke_system_prefix():
    """planner LLM 调用：SystemMessage 带 mem_prefix，HumanMessage 不动。"""

    async def run():
        model = CaptureModel('{"action": "direct"}')
        text = await _invoke(model, "任务文本", system_prefix="MEM-PREFIX")
        system, human = model.calls[0]
        assert system.content == "MEM-PREFIX\n\n你只输出 JSON。"
        assert human.content == "任务文本"
        return text

    assert asyncio.run(run()) == '{"action": "direct"}'


def test_planner_invoke_no_prefix_matches_baseline():
    """mem_prefix="" 时 SystemMessage 与 M07 现状一致（零回归护栏）。"""

    async def run():
        model = CaptureModel('{"action": "direct"}')
        await _invoke(model, "任务文本")
        system, _human = model.calls[0]
        assert system.content == "你只输出 JSON。"

    asyncio.run(run())


def test_replanner_ask_system_prefix():
    """replanner LLM 调用：SystemMessage 带 mem_prefix，HumanMessage 含计划快照。"""

    async def run():
        model = CaptureModel('{"action": "done"}')
        plan = Plan(
            revision=1,
            goal="目标",
            nodes=(PlanNode(node_id="n1", objective="a", tool="rag_search"),),
        )
        output = await _ask_replanner(
            model,
            plan,
            (),
            "observation_insufficient",
            (),
            (),
            3,
            frozenset(),
            frozenset(),
            8,
            "MEM-PREFIX",
        )
        system, human = model.calls[0]
        assert system.content.startswith("MEM-PREFIX\n\n")
        assert "你只输出 JSON。" in system.content
        assert "任务目标：目标" in human.content
        return output

    assert asyncio.run(run()).action == "generate"


def test_mem_prefix_includes_memory_and_tool_blocks():
    """正常路径：前缀含长期记忆与工具状态，以 stable-rules 开头。"""

    async def run():
        long_term = _block("lt1", "long_term_memory", "用户偏好：熊猫主题。")
        tool = _block("t1", "tool_status", "工具 exec_command 可用。")
        runtime = _runtime(
            memory=FakeMemory(long_term=(long_term,)),
            tool_control=FakeToolControl((tool,)),
        )
        return await runtime._build_planning_mem_prefix(
            run_id="r1",
            history=(),
            memory_authorization=object(),
            task_input=TaskInput("m1", "任务"),
        )

    prefix = asyncio.run(run())
    # 投影 system_messages 排序（mandatory 先、block_id 字典序升）：output-contract 居首。
    assert prefix.startswith("直接返回面向用户的最终文本")
    assert "你是 VenAgent 的回答节点" in prefix
    assert "用户偏好：熊猫主题" in prefix
    assert "工具 exec_command 可用" in prefix


def test_mem_prefix_degrades_on_snapshot_timeout():
    """记忆快照超时：记忆块置空，工具状态仍保留，超时被记录。"""

    async def run():
        tool = _block("t1", "tool_status", "工具 exec_command 可用。")
        memory = FakeMemory(snapshot_error=asyncio.TimeoutError())
        runtime = _runtime(memory=memory, tool_control=FakeToolControl((tool,)))
        prefix = await runtime._build_planning_mem_prefix(
            run_id="r1",
            history=(),
            memory_authorization=object(),
            task_input=TaskInput("m1", "任务"),
        )
        return prefix, memory.timeouts

    prefix, timeouts = asyncio.run(run())
    assert "工具 exec_command 可用" in prefix
    assert "memory-long-term" in timeouts


def test_mem_prefix_without_memory_tool_control_returns_core_rules():
    """无记忆/无工具时仍返回核心规则前缀（stable/security/output-contract）。"""

    async def run():
        runtime = _runtime()
        return await runtime._build_planning_mem_prefix(
            run_id="r1",
            history=(),
            memory_authorization=None,
            task_input=TaskInput("m1", "任务"),
        )

    prefix = asyncio.run(run())
    assert "你是 VenAgent 的回答节点" in prefix
    assert "直接返回面向用户的最终文本" in prefix


def test_mem_prefix_empty_on_projection_error(monkeypatch):
    """投影整体异常：返回 ""（== 纯节点内联，零回归）。"""

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ContextProjectionService, "project", boom)

    async def run():
        runtime = _runtime()
        return await runtime._build_planning_mem_prefix(
            run_id="r1",
            history=(),
            memory_authorization=None,
            task_input=TaskInput("m1", "任务"),
        )

    assert asyncio.run(run()) == ""


def test_generator_and_rag_answer_system_prefix():
    """generator / rag_answer：SystemMessage 带 mem_prefix，HumanMessage 保持节点专属。"""

    class FakeSnapshot:
        tools = ()

    class FakeToolCtl:
        def snapshot(self, *, run_id):
            return FakeSnapshot()

        def collect_blocks(self, *, run_id):
            return ()

    class FakeSource:
        parent_content = "证据内容"
        chunk_content = None
        title = "文档一"
        document_id = "d1"
        section = "sec1"

    class FakeResult:
        mode = "hybrid"
        sources = (FakeSource(),)
        degraded = ()
        reranked = False

    class FakeRag:
        mode = "hybrid"

        def search(self, owner_id, content):
            return FakeResult()

    class FakeConfig:
        max_plan_nodes = 8
        max_parallel = 1
        race_timeout_ms = 1000
        max_replan = 2
        replan_append_limit = 3

    async def publish(*_args, **_kwargs):
        pass

    async def run():
        model = CaptureModel("好。")
        nodes = build_planning_nodes(
            run_id="r1",
            owner_id="o1",
            model=model,
            tool_control=FakeToolCtl(),
            registry=None,
            rag_search=FakeRag(),
            publish=publish,
            cancel_event=None,
            execution_attempt=0,
            planning_config=FakeConfig(),
            mem_prefix="MEM-PREFIX",
        )
        state = {"task_input": TaskInput("m1", "任务"), "node_outcomes": ()}
        await nodes.generator(state)
        await nodes.rag_answer(state)
        return model.calls

    calls = asyncio.run(run())
    assert len(calls) == 2
    for messages in calls:
        system = messages[0]
        assert system.content.startswith("MEM-PREFIX\n\n")
    assert "观察结果" in calls[0][1].content
    assert "[1] 证据内容" in calls[1][1].content
