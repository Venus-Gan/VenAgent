"""M06 exec_command 执行契约（单点）。

- 未就绪 sandbox 必须拒绝执行且不启动容器：本文件单点。
- 非 sandbox 描述符（mcp）不能触发执行器：本文件单点。
"""

from __future__ import annotations

import asyncio

import pytest

from venagent.tools.errors import SandboxUnavailable, ToolUnavailable
from venagent.tools.exec_command import execute_exec_command
from venagent.tools.models import ToolDescriptor, ToolResult


def test_exec_command_requires_ready_sandbox_and_does_not_start_run(tools_harness) -> None:
    class FakeSandbox:
        def __init__(self) -> None:
            self.started = 0
            self.ready = False

        async def start_run(self, _run_id: str):
            self.started += 1
            self.ready = True
            return None

        async def exec_command(
            self,
            _descriptor: ToolDescriptor,
            _arguments: dict[str, object],
            *,
            run_id: str,
        ) -> ToolResult:
            if not self.ready:
                raise SandboxUnavailable
            assert run_id == "run-ready"
            return ToolResult(
                tool_call_id="",
                operation_id="",
                status="success",
                summary="ok",
                content="ok",
            )

    async def scenario() -> None:
        sandbox = FakeSandbox()
        with pytest.raises(SandboxUnavailable):
            await execute_exec_command(
                sandbox,  # type: ignore[arg-type]
                tools_harness.exec_command(),
                {"command": "echo hi"},
                "run-ready",
            )
        assert sandbox.started == 0
        await sandbox.start_run("run-ready")
        result = await execute_exec_command(
            sandbox,  # type: ignore[arg-type]
            tools_harness.exec_command(),
            {"command": "echo hi"},
            "run-ready",
        )
        assert result.status == "success"
        assert sandbox.started == 1

    asyncio.run(scenario())


def test_non_sandbox_descriptor_cannot_trigger_exec_executor(tools_harness) -> None:
    class FakeSandbox:
        def __init__(self) -> None:
            self.create_count = 0

        async def start_run(self, _run_id: str):
            self.create_count += 1
            return None

    async def scenario() -> None:
        sandbox = FakeSandbox()
        with pytest.raises(ToolUnavailable):
            await execute_exec_command(
                sandbox,  # type: ignore[arg-type]
                tools_harness.mcp_search(),
                {"query": "status"},
                "run-mcp",
            )
        assert sandbox.create_count == 0

    asyncio.run(scenario())