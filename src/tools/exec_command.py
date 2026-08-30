"""首期 Native `exec_command` 描述符与 Sandbox 执行适配。"""

from __future__ import annotations

from typing import Any

from ..sandbox.docker import DockerSandboxRuntime
from .errors import ToolUnavailable
from .models import ToolDescriptor, ToolResult


def exec_command_descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        tool_id="exec_command",
        public_name="exec_command",
        source="native",
        description="在当前 AgentRun 的 Docker Sandbox 中执行受控命令",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "minLength": 1, "maxLength": 512},
                "args": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 4096},
                    "maxItems": 128,
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        risk="warn",
    )


async def execute_exec_command(
    sandbox: DockerSandboxRuntime,
    descriptor: ToolDescriptor,
    arguments: dict[str, Any],
    run_id: str,
) -> ToolResult:
    # Sandbox 生命周期由 ToolControlContext.start_run 在模型调用前统一建立。
    # 这里只接受已经 ready 的 Run Sandbox，禁止在旧 Operation 中静默重建容器。
    if descriptor.source != "native" or descriptor.tool_id != "exec_command":
        raise ToolUnavailable
    return await sandbox.exec_command(descriptor, arguments, run_id=run_id)
