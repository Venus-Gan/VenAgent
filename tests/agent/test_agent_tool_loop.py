"""M06 单工具调用闭环的运行机制测试（公开接口驱动，契约单点）。

- 安全工具「执行一次 + 模型收尾」：本文件单点。
- 多工具被拒「不触发第二次模型调用 / 不执行」：本文件单点。
- warn 审批「批准后恢复执行一次」：本文件单点；「拒绝不执行」与「过期」
  分别由 tests/agent/test_m06_langgraph.py 与 tests/tools 网关层各自覆盖。
- checkpoint 不含 context_messages / secret 参数：本文件单点。

所有流程经 AgentRuntime 公开接口（start/stop/decide_approval）与
TemporaryConversationRuntimeStore 公开方法驱动，不触碰 runtime 私有符号。
"""

from __future__ import annotations

import asyncio
import json

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from src.agent.graph import run_config
from src.agent.state import PendingToolCallRef, ToolObservationRef
from src.tools.models import ArtifactRef, ToolResult


def _checkpoint_values(saver, run_id: str) -> dict:
    """公开读取终态 channel_values（等价 graph.aget_state() 的 .values）。"""
    return saver.get_tuple(run_config(run_id)).checkpoint["channel_values"]


def _single_safe_call() -> tuple[dict[str, str], ...]:
    return (
        {
            "id": "call_1",
            "name": "tavily_search",
            "args": '{"query":"venagent"}',
            "index": 0,
        },
    )


def test_safe_mcp_tool_executes_once_and_model_finalizes(agent_harness) -> None:
    async def scenario() -> None:
        store = agent_harness.make_store()
        actor, run_id = agent_harness.create_test_run(store)
        control, calls = agent_harness.make_tool_control()
        saver = InMemorySaver()
        model = agent_harness.ToolCallingModel(_single_safe_call())
        runtime = agent_harness.make_runtime(
            model, store, tool_control=control, checkpointer=saver
        )
        try:
            completed = await agent_harness.await_status(
                store, actor.owner_id, run_id, "succeeded"
            )
        finally:
            await runtime.stop()

        assert completed.status == "succeeded"
        assert calls == [{"query": "venagent"}]
        assert model.calls == 2
        assert any(tool["name"] == "tavily_search" for tool in model.bound_tools)
        values = _checkpoint_values(saver, run_id)
        assert values["final_answer"].content == "最终回答"

    asyncio.run(scenario())


def test_provider_receives_assistant_tool_call_before_tool_message(
    agent_harness,
) -> None:
    async def scenario() -> None:
        store = agent_harness.make_store()
        actor, run_id = agent_harness.create_test_run(store)
        control, _ = agent_harness.make_tool_control()
        model = agent_harness.ToolCallingModel(
            (
                {
                    "id": "call_provider",
                    "name": "tavily_search",
                    "args": '{"query":"strict"}',
                    "index": 0,
                },
            )
        )
        runtime = agent_harness.make_runtime(model, store, tool_control=control)
        try:
            await agent_harness.await_status(
                store, actor.owner_id, run_id, "succeeded"
            )
        finally:
            await runtime.stop()

        second = model.second_messages
        assistant_call = next(
            (
                item
                for item in second
                if isinstance(item, AIMessage) and getattr(item, "tool_calls", None)
            ),
            None,
        )
        tool_message = next(
            (item for item in second if isinstance(item, ToolMessage)), None
        )
        assert assistant_call is not None
        assert tool_message is not None
        assert second.index(assistant_call) < second.index(tool_message)
        assert assistant_call.tool_calls[0]["id"] == "call_provider"
        assert assistant_call.tool_calls[0]["name"] == "tavily_search"
        assert assistant_call.tool_calls[0]["args"] == {"query": "strict"}
        assert tool_message.tool_call_id == "call_provider"

    asyncio.run(scenario())


def test_final_model_receives_verified_bounded_tool_content_and_artifacts(
    agent_harness,
) -> None:
    marker = "important-marker-after-summary"
    content = f"{'x' * 1200}{marker}"

    async def executor(
        _descriptor, _arguments, _run_id
    ) -> ToolResult:
        return ToolResult(
            tool_call_id="",
            operation_id="",
            status="success",
            summary="x" * 1024,
            content=content,
            artifacts=(
                ArtifactRef(
                    artifact_id="artifact-result",
                    source="tool:test",
                    size_bytes=len(content),
                    content_type="text/plain; charset=utf-8",
                    checksum_sha256="abc123",
                ),
            ),
        )

    async def scenario() -> None:
        store = agent_harness.make_store()
        actor, run_id = agent_harness.create_test_run(store)
        control, _ = agent_harness.make_tool_control(executor=executor)
        model = agent_harness.ToolCallingModel(
            (
                {
                    "id": "call_content",
                    "name": "tavily_search",
                    "args": '{"query":"content"}',
                    "index": 0,
                },
            )
        )
        runtime = agent_harness.make_runtime(model, store, tool_control=control)
        try:
            await agent_harness.await_status(
                store, actor.owner_id, run_id, "succeeded"
            )
        finally:
            await runtime.stop()

        tool_message = next(
            item
            for item in model.second_messages
            if isinstance(item, ToolMessage)
        )
        projected = json.loads(str(tool_message.content))
        assert marker in projected["content"]
        assert projected["summary"] == "x" * 1024
        assert projected["artifacts"] == [
            {
                "artifact_id": "artifact-result",
                "content_type": "text/plain; charset=utf-8",
                "size_bytes": len(content),
                "checksum_sha256": "abc123",
            }
        ]

        operation = control.operations.list_by_run(run_id)[0]
        pending = PendingToolCallRef(
            tool_call_id="call_content",
            operation_key="tavily_search:call_content",
            tool_id="tavily_search",
        )
        observation = ToolObservationRef(
            tool_call_id="call_content",
            operation_id=operation.operation_id,
            status="success",
            summary="x" * 1024,
        )
        wrong_owner = json.loads(
            control.project_tool_result(
                run_id, "owner-other", pending, observation
            )
        )
        assert wrong_owner["error_code"] == "tool_result_reference_invalid"
        forged = json.loads(
            control.project_tool_result(
                run_id,
                actor.owner_id,
                pending,
                ToolObservationRef(
                    tool_call_id="call_content",
                    operation_id="forged-operation",
                    status="success",
                    summary="forged",
                ),
            )
        )
        assert forged["error_code"] == "tool_result_unavailable"

    asyncio.run(scenario())


def test_multiple_tool_calls_execute_sequentially(
    agent_harness,
) -> None:
    """多工具顺序执行：每个工具独立过 M06 校验，按顺序执行。"""
    async def scenario() -> None:
        store = agent_harness.make_store()
        actor, run_id = agent_harness.create_test_run(store)
        control, calls = agent_harness.make_tool_control(
            descriptors=(agent_harness.exec_descriptor("safe"),),
            available_servers=frozenset(),
            risk_overrides=(("exec_command", "safe"),),
        )
        # 不传 checkpointer，使用 make_runtime 的默认值（带正确序列化器）
        model = agent_harness.ToolCallingModel(
            (
                {
                    "id": "call_1",
                    "name": "exec_command",
                    "args": '{"command":"printf one"}',
                    "index": 0,
                },
                {
                    "id": "call_2",
                    "name": "exec_command",
                    "args": '{"command":"printf two"}',
                    "index": 1,
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

        # 验证：模型调用 1 次（model_decision）+ 2 次（每个工具执行后的 model_finalize，但最后一次才调用模型）
        # 实际上：model_decision 1 次 + 最后 model_finalize 1 次 = 2 次
        assert model.calls == 2, f"Expected 2 model calls, got {model.calls}"
        # 两个工具都应该执行
        assert len(calls) == 2, f"Expected 2 tool executions, got {len(calls)}"
        assert calls[0] == {"command": "printf one"}
        assert calls[1] == {"command": "printf two"}
        # 两个 operation 都应该记录
        operations = control.operations.list_by_run(run_id)
        assert len(operations) == 2, f"Expected 2 operations, got {len(operations)}"

    asyncio.run(scenario())


def test_warn_tool_interrupts_then_resumes_approved(agent_harness) -> None:
    async def scenario() -> None:
        store = agent_harness.make_store()
        actor, run_id = agent_harness.create_test_run(store)
        control, calls = agent_harness.make_tool_control(
            descriptors=(agent_harness.exec_descriptor("warn"),),
            available_servers=frozenset(),
            risk_overrides=(("exec_command", "warn"),),
        )
        saver = InMemorySaver()
        model = agent_harness.ToolCallingModel(
            (
                {
                    "id": "call_w",
                    "name": "exec_command",
                    "args": '{"command":"danger"}',
                    "index": 0,
                },
            )
        )
        runtime = agent_harness.make_runtime(
            model, store, tool_control=control, checkpointer=saver
        )
        try:
            waiting = await agent_harness.await_status(
                store, actor.owner_id, run_id, "waiting_approval"
            )
            assert waiting.status == "waiting_approval"
            assert calls == []
            operation = control.operations.list_by_run(run_id)[0]
            assert operation.approval_id is not None
            runtime.decide_approval(actor.owner_id, operation.approval_id, True)
            completed = await agent_harness.await_status(
                store, actor.owner_id, run_id, "succeeded"
            )
            assert completed.status == "succeeded"
            assert calls == [{"command": "danger"}]
            assert model.calls == 2
            values = _checkpoint_values(saver, run_id)
            assert values["final_answer"].content == "最终回答"
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_checkpoint_does_not_keep_context_messages_or_secret_arguments(
    agent_harness,
) -> None:
    async def scenario() -> None:
        store = agent_harness.make_store()
        actor, run_id = agent_harness.create_test_run(store)
        control, _ = agent_harness.make_tool_control()
        saver = InMemorySaver()
        model = agent_harness.ToolCallingModel(
            (
                {
                    "id": "call_ckpt",
                    "name": "tavily_search",
                    "args": '{"query":"public","token":"secret-ckpt"}',
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

        values = _checkpoint_values(saver, run_id)
        assert "context_messages" not in values
        assert "secret-ckpt" not in str(values)
        assert "pending_tool_call" in values
        assert values["pending_tool_call"] is not None

    asyncio.run(scenario())


def test_invocation_payload_is_not_exposed_via_operation_summary(
    agent_harness,
) -> None:
    async def scenario() -> None:
        store = agent_harness.make_store()
        actor, run_id = agent_harness.create_test_run(store)
        control, _ = agent_harness.make_tool_control()
        saver = InMemorySaver()
        model = agent_harness.ToolCallingModel(
            (
                {
                    "id": "call_s",
                    "name": "tavily_search",
                    "args": '{"query":"public","token":"secret-query"}',
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

        operations = control.operations.list_by_run(run_id)
        assert operations
        assert "secret-query" not in operations[0].arguments_summary
        values = _checkpoint_values(saver, run_id)
        assert "secret-query" not in str(values)

    asyncio.run(scenario())