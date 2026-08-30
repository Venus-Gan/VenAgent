"""Sandbox 能力值对象与安全约束。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SandboxCapability:
    provider: Literal["docker"]
    ready: bool
    reason_code: str | None = None
    resource_limits: tuple[tuple[str, str], ...] = ()

    def as_block(self) -> "SandboxCapability":
        """只用于 Prompt/状态投影的只读能力摘要。"""
        return self


DOCKER_RESOURCE_LIMITS = (
    ("network", "none"),
    ("user", "non-root 65534"),
    ("root_fs", "read-only"),
    ("workspace", "tmpfs /workspace"),
    ("tmp", "tmpfs /tmp noexec,nosuid"),
    ("privileged", "false"),
    ("host_namespace", "false"),
    ("docker_socket", "false"),
    ("capabilities", "drop-all"),
)
