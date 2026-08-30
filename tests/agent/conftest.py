"""tests/agent/ 共用装配（D5：模块 conftest 收编对象装配 factory）。

工具闭环与恢复测试全部经 AgentRuntime 公开接口（start/stop/decide_approval）
与 TemporaryConversationRuntimeStore 公开方法驱动，不触碰
runtime._tool_nodes/_answer_node 等私有符号。
"""

from __future__ import annotations

import asyncio
import types
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.memory import InMemorySaver

from src.agent.graph import checkpoint_serializer
from src.agent.runs import AgentRun
from src.agent.runtime import AgentRuntime
from src.ownership.models import Actor
from src.repo.inmemory import (
    InMemoryConversationRuntimeStore as MemoryRuntimeStore,
)
from src.sandbox.models import SandboxCapability
from src.skills.catalog import SkillCatalog
from src.tools.approval import ApprovalService
from src.tools.catalog import ToolCatalog
from src.tools.control import ToolControlContext
from src.tools.gateway import ToolGateway
from src.tools.models import ToolDescriptor, ToolResult
from src.tools.operation_store import OperationStore
from src.tools.policy import ToolExposurePolicy


def _mcp_descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        tool_id="tavily_search",
        public_name="tavily_search",
        source="mcp",
        description="搜索",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        server_id="tavily",
        risk="safe",
    )


def _exec_descriptor(risk: str = "warn") -> ToolDescriptor:
    return ToolDescriptor(
        tool_id="exec_command",
        public_name="exec_command",
        source="native",
        description="执行命令",
        input_schema={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
        risk=risk,  # type: ignore[arg-type]
    )


class _FakeSandbox:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready
        self.started: list[str] = []

    async def start_run(
        self,
        run_id: str,
        *,
        allow_create: bool = True,
        generation_id: str | None = None,
    ) -> SandboxCapability:
        self.started.append(run_id)
        return self.capability(run_id)

    async def stop_run(self, run_id: str) -> None:
        return None

    def capability(self, run_id: str | None = None) -> SandboxCapability:
        return SandboxCapability(
            provider="docker",
            ready=self.ready,
            reason_code=None if self.ready else "docker_unavailable",
        )


class _ToolCallingModel:
    """第一次返回工具调用，第二次返回最终文本（记录第二次收到的消息）。"""

    def __init__(
        self,
        tool_call_chunks: tuple[dict[str, Any], ...],
        final_text: str = "最终回答",
    ) -> None:
        self.tool_call_chunks = tool_call_chunks
        self.final_text = final_text
        self.calls = 0
        self.bound_tools: tuple[dict[str, Any], ...] = ()
        self.second_messages: tuple[Any, ...] = ()

    def bind_tools(self, tools: tuple[dict[str, Any], ...]) -> "_ToolCallingModel":
        self.bound_tools = tuple(tools)
        return self

    async def astream(self, messages):
        self.calls += 1
        if self.calls == 1:
            if self.tool_call_chunks:
                yield AIMessageChunk(
                    content="",
                    tool_call_chunks=list(self.tool_call_chunks),
                )
            else:
                yield AIMessageChunk(content="无工具回答")
        else:
            self.second_messages = tuple(messages)
            yield AIMessageChunk(content=self.final_text)


def _make_tool_control(
    *,
    descriptors: tuple[ToolDescriptor, ...] = (_mcp_descriptor(),),
    sandbox: Any = None,
    executor: Any = None,
    available_servers: frozenset[str] = frozenset({"tavily"}),
    risk_overrides: tuple[tuple[str, str], ...] = (),
) -> tuple[ToolControlContext, list[dict[str, Any]]]:
    allowed = tuple(item.tool_id for item in descriptors)
    policy = ToolExposurePolicy(
        policy_version="test",
        allowed_tool_ids=allowed,
        risk_overrides=risk_overrides,
    )
    catalog = ToolCatalog(policy)
    catalog.register_many(descriptors)
    if sandbox is None:
        sandbox = _FakeSandbox()
    calls: list[dict[str, Any]] = []

    async def default_executor(
        _descriptor: ToolDescriptor,
        arguments: dict[str, Any],
        _run_id: str,
    ) -> ToolResult:
        calls.append(arguments)
        return ToolResult(
            tool_call_id="",
            operation_id="",
            status="success",
            summary="ok",
            content="ok",
        )

    operations = OperationStore()
    approvals = ApprovalService()
    gateway = ToolGateway(
        operations=operations,
        approvals=approvals,
        executor=executor or default_executor,
    )
    control = ToolControlContext(
        catalog=catalog,
        sandbox=sandbox,  # type: ignore[arg-type]
        skills=SkillCatalog(),
        gateway=gateway,
        approvals=approvals,
        operations=operations,
        available_servers=available_servers,
    )
    return control, calls


def _make_store() -> MemoryRuntimeStore:
    return MemoryRuntimeStore()


def _create_test_run(
    store: MemoryRuntimeStore, text: str = "你好"
) -> tuple[Actor, str]:
    actor = Actor(str(uuid4()), "temporary_guest", str(uuid4()))
    now = datetime.now(timezone.utc)
    conversation = store.create_conversation(actor, now)
    created = store.create_run(
        actor, conversation.conversation_id, text, str(uuid4()), now
    )
    return actor, created.run.run_id


def _make_runtime(
    model: Any,
    store: MemoryRuntimeStore,
    *,
    tool_control: ToolControlContext | None = None,
    memory: Any = None,
    worker_id: str = "test-worker",
    checkpointer: Any = None,
    **kwargs: Any,
) -> AgentRuntime:
    if checkpointer is None:
        checkpointer = InMemorySaver(serde=checkpoint_serializer())
    runtime = AgentRuntime(
        model,
        checkpointer,
        store,
        memory=memory,
        tool_control=tool_control,
        worker_id=worker_id,
        **kwargs,
    )
    runtime.start()
    return runtime


async def _await_status(
    store: MemoryRuntimeStore,
    owner_id: str,
    run_id: str,
    status: str,
    *,
    timeout: float = 3.0,
) -> AgentRun:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        run = store.get_run(owner_id, run_id)
        if run is not None and run.status == status:
            return run
        await asyncio.sleep(0.01)
    run = store.get_run(owner_id, run_id)
    if run is None:
        raise AssertionError(f"run {run_id} 未找到")
    raise AssertionError(
        f"run {run_id} 状态 {run.status!r} != {status!r}（超时 {timeout}s）"
    )


@pytest.fixture
def agent_harness() -> types.SimpleNamespace:
    """公开接口驱动的工具闭环测试装配入口（全部经公开符号驱动）。"""
    return types.SimpleNamespace(
        mcp_descriptor=_mcp_descriptor,
        exec_descriptor=_exec_descriptor,
        FakeSandbox=_FakeSandbox,
        ToolCallingModel=_ToolCallingModel,
        make_tool_control=_make_tool_control,
        make_store=_make_store,
        create_test_run=_create_test_run,
        make_runtime=_make_runtime,
        await_status=_await_status,
    )