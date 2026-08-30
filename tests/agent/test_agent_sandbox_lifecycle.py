"""M06 Sandbox 惰性创建与生命周期契约（公开接口驱动，单点）。

- 纯文本 run 不创建 sandbox、终态后 stop：本文件 HTTP 面单点。
- 惰性创建：mcp-only 不创建；warn exec 仅审批后创建；容器丢失后
  不重新创建（ensure_sandbox 返回 False）。
- 其余 sandbox 行为（docker unavailable 暴露降级、提示文案）同样单点。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.memory import InMemorySaver

from venagent.agent.graph import run_config
from venagent.interfaces.http.app import create_app
from venagent.platform.runtime import build_persistence_runtime
from venagent.promptctx.source_constraints import sandbox_constraints_block
from venagent.sandbox.docker import DockerSandboxRuntime
from venagent.sandbox.models import SandboxCapability
from venagent.tools.models import Operation

ORIGIN = {"Origin": "http://localhost:5173"}


class _SemanticSandbox:
    """一个 run 最多一个 generation 容器；可模拟容器丢失。"""

    def __init__(self) -> None:
        self.created: list[tuple[str, str | None]] = []
        self.ready: set[tuple[str, str | None]] = set()

    async def start_run(
        self,
        run_id: str,
        *,
        allow_create: bool = True,
        generation_id: str | None = None,
    ) -> SandboxCapability:
        key = (run_id, generation_id)
        if key in self.ready:
            return SandboxCapability(provider="docker", ready=True, reason_code=None)
        if not allow_create:
            return SandboxCapability(
                provider="docker",
                ready=False,
                reason_code="sandbox_not_initialized",
            )
        self.created.append(key)
        self.ready.add(key)
        return SandboxCapability(provider="docker", ready=True, reason_code=None)

    async def stop_run(self, run_id: str) -> None:
        self.ready = {key for key in self.ready if key[0] != run_id}

    def lose_container(self, run_id: str, generation_id: str | None) -> None:
        self.ready.discard((run_id, generation_id))

    def capability(self, run_id: str | None = None) -> SandboxCapability:
        return SandboxCapability(provider="docker", ready=True, reason_code=None)


def test_runtime_does_not_create_sandbox_for_plain_text_run_and_stops_on_terminal() -> None:
    class RecordingSandbox:
        def __init__(self) -> None:
            self.starts: list[str] = []
            self.stops: list[str] = []

        async def start_run(
            self,
            run_id: str,
            *,
            allow_create: bool = True,
            generation_id: str | None = None,
        ) -> SandboxCapability:
            self.starts.append(run_id)
            return self.capability(run_id)

        async def stop_run(self, run_id: str) -> None:
            self.stops.append(run_id)

        def capability(self, run_id: str | None = None) -> SandboxCapability:
            return SandboxCapability(provider="docker", ready=True, reason_code=None)

    sandbox = RecordingSandbox()

    class LifecycleModel:
        async def astream(self, _messages):
            yield AIMessageChunk(content="完成")

    from venagent.skills.catalog import SkillCatalog
    from venagent.tools.approval import ApprovalService
    from venagent.tools.catalog import ToolCatalog
    from venagent.tools.control import ToolControlContext
    from venagent.tools.gateway import ToolGateway
    from venagent.tools.operation_store import OperationStore
    from venagent.tools.policy import ToolExposurePolicy

    policy = ToolExposurePolicy(policy_version="test", allowed_tool_ids=())
    operations = OperationStore()
    approvals = ApprovalService()
    control = ToolControlContext(
        catalog=ToolCatalog(policy),
        sandbox=sandbox,  # type: ignore[arg-type]
        skills=SkillCatalog(),
        gateway=ToolGateway(operations=operations, approvals=approvals),
        approvals=approvals,
        operations=operations,
    )
    app = create_app(
        LifecycleModel(),
        persistence_runtime=build_persistence_runtime({}),
        tool_control=control,
    )
    with TestClient(app) as client:
        identity = client.post("/api/auth/guest", headers=ORIGIN).json()
        headers = {"Authorization": f"Bearer {identity['access_token']}"}
        conversation = client.post("/api/conversations", headers=headers).json()
        created = client.post(
            f"/api/conversations/{conversation['conversation_id']}/runs",
            headers=headers,
            json={"message": "你好", "client_request_id": str(uuid4())},
        ).json()
        run_id = created["run"]["run_id"]
        for _ in range(100):
            run = client.get(f"/api/runs/{run_id}", headers=headers).json()
            if run["status"] == "succeeded":
                break
            time.sleep(0.01)

    assert sandbox.starts == []
    assert run_id in sandbox.stops


def test_lazy_sandbox_prompt_allows_exec_command_to_trigger_provisioning() -> None:
    capability = SandboxCapability(
        provider="docker",
        ready=False,
        reason_code="sandbox_not_initialized",
    )
    block = sandbox_constraints_block(capability)
    assert "Sandbox 状态：可按需创建" in block.content
    assert "调用 exec_command" in block.content
    assert "Sandbox 状态：不可用" not in block.content


def test_docker_unavailable_removes_exec_command_from_model_schemas(
    agent_harness,
) -> None:
    async def scenario() -> None:
        control, _ = agent_harness.make_tool_control(
            descriptors=(agent_harness.exec_descriptor("warn"),),
            sandbox=DockerSandboxRuntime(probe=lambda: False),
            available_servers=frozenset(),
        )
        snapshot = await control.start_run("run-d")
        tools = control.model_tools("run-d")
        assert snapshot.by_id("exec_command").exposed is False
        assert all(tool["name"] != "exec_command" for tool in tools)

    asyncio.run(scenario())


def test_mcp_only_run_does_not_create_sandbox(agent_harness) -> None:
    async def scenario() -> None:
        store = agent_harness.make_store()
        actor, run_id = agent_harness.create_test_run(store)
        sandbox = agent_harness.FakeSandbox()
        control, calls = agent_harness.make_tool_control(sandbox=sandbox)
        model = agent_harness.ToolCallingModel(
            (
                {
                    "id": "call_mcp",
                    "name": "tavily_search",
                    "args": '{"query":"x"}',
                    "index": 0,
                },
            )
        )
        runtime = agent_harness.make_runtime(
            model, store, tool_control=control
        )
        try:
            await agent_harness.await_status(
                store, actor.owner_id, run_id, "succeeded"
            )
        finally:
            await runtime.stop()

        assert calls == [{"query": "x"}]
        assert sandbox.started == []

    asyncio.run(scenario())


def test_warn_exec_creates_sandbox_only_after_approval(agent_harness) -> None:
    async def scenario() -> None:
        store = agent_harness.make_store()
        actor, run_id = agent_harness.create_test_run(store)
        sandbox = agent_harness.FakeSandbox()
        control, calls = agent_harness.make_tool_control(
            descriptors=(agent_harness.exec_descriptor("warn"),),
            sandbox=sandbox,
            available_servers=frozenset(),
            risk_overrides=((agent_harness.exec_descriptor("warn").tool_id, "warn"),),
        )
        model = agent_harness.ToolCallingModel(
            (
                {
                    "id": "call_warn_sandbox",
                    "name": "exec_command",
                    "args": '{"command":"safe-cmd"}',
                    "index": 0,
                },
            )
        )
        runtime = agent_harness.make_runtime(
            model, store, tool_control=control
        )
        try:
            await agent_harness.await_status(
                store, actor.owner_id, run_id, "waiting_approval"
            )
            assert sandbox.started == []
            operation = control.operations.list_by_run(run_id)[0]
            assert operation.approval_id is not None
            runtime.decide_approval(actor.owner_id, operation.approval_id, True)
            await agent_harness.await_status(
                store, actor.owner_id, run_id, "succeeded"
            )
            assert calls == [{"command": "safe-cmd"}]
            assert sandbox.started == [run_id]
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_safe_exec_creates_sandbox_and_executes_once(agent_harness) -> None:
    async def scenario() -> None:
        store = agent_harness.make_store()
        actor, run_id = agent_harness.create_test_run(store)
        sandbox = _SemanticSandbox()
        control, calls = agent_harness.make_tool_control(
            descriptors=(agent_harness.exec_descriptor("safe"),),
            sandbox=sandbox,
            available_servers=frozenset(),
            risk_overrides=((agent_harness.exec_descriptor("safe").tool_id, "safe"),),
        )
        saver = InMemorySaver()
        model = agent_harness.ToolCallingModel(
            (
                {
                    "id": "call_safe",
                    "name": "exec_command",
                    "args": '{"command":"echo ok"}',
                    "index": 0,
                },
            )
        )
        runtime = agent_harness.make_runtime(
            model, store, tool_control=control, checkpointer=saver
        )
        try:
            await agent_harness.await_status(
                store, actor.owner_id, run_id, "succeeded"
            )
        finally:
            await runtime.stop()

        assert calls == [{"command": "echo ok"}]
        assert len(sandbox.created) == 1
        assert sandbox.created[0][0] == run_id
        values = saver.get_tuple(run_config(run_id)).checkpoint["channel_values"]
        assert values["final_answer"].content == "最终回答"

    asyncio.run(scenario())


def test_semantic_sandbox_approves_warn_only_after_approval(agent_harness) -> None:
    async def scenario() -> None:
        store = agent_harness.make_store()
        actor, run_id = agent_harness.create_test_run(store)
        sandbox = _SemanticSandbox()
        control, calls = agent_harness.make_tool_control(
            descriptors=(agent_harness.exec_descriptor("warn"),),
            sandbox=sandbox,
            available_servers=frozenset(),
            risk_overrides=((agent_harness.exec_descriptor("warn").tool_id, "warn"),),
        )
        model = agent_harness.ToolCallingModel(
            (
                {
                    "id": "call_sem",
                    "name": "exec_command",
                    "args": '{"command":"echo ok"}',
                    "index": 0,
                },
            )
        )
        runtime = agent_harness.make_runtime(
            model, store, tool_control=control
        )
        try:
            await agent_harness.await_status(
                store, actor.owner_id, run_id, "waiting_approval"
            )
            assert sandbox.created == []
            operation = control.operations.list_by_run(run_id)[0]
            runtime.decide_approval(actor.owner_id, operation.approval_id, True)
            await agent_harness.await_status(
                store, actor.owner_id, run_id, "succeeded"
            )
            assert calls == [{"command": "echo ok"}]
            assert len(sandbox.created) == 1
            assert sandbox.created[0][0] == run_id
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_semantic_sandbox_invalid_after_container_loss(agent_harness) -> None:
    async def scenario() -> None:
        sandbox = _SemanticSandbox()
        control, _ = agent_harness.make_tool_control(
            descriptors=(agent_harness.exec_descriptor("safe"),),
            sandbox=sandbox,
            available_servers=frozenset(),
            risk_overrides=((agent_harness.exec_descriptor("safe").tool_id, "safe"),),
        )
        await control.start_run("run-loss")
        operation_key = "exec_command:call_loss"
        now = datetime.now(timezone.utc)
        operation = Operation(
            operation_id="op-loss",
            run_id="run-loss",
            owner_id="owner-1",
            tool_call_id="call_loss",
            operation_key=operation_key,
            tool_id="exec_command",
            status="running",
            risk="safe",
            created_at=now,
            updated_at=now,
        )
        control.operations.save(operation)
        first = await control.ensure_sandbox("run-loss", "call_loss", operation_key)
        assert first is True
        operation = control.operations.find_operation(
            "run-loss", "call_loss", operation_key
        )
        assert operation is not None
        sandbox.lose_container("run-loss", operation.sandbox_generation_id)
        second = await control.ensure_sandbox("run-loss", "call_loss", operation_key)
        assert second is False
        assert len(sandbox.created) == 1

    asyncio.run(scenario())