"""每个 AgentRun 一个 Docker Sandbox 的生命周期与命令执行。"""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

from ..tools.errors import SandboxUnavailable, ToolSchemaInvalid
from ..tools.models import ToolDescriptor, ToolResult
from .models import DOCKER_RESOURCE_LIMITS, SandboxCapability

Probe = Callable[[], bool]
ImageProbe = Callable[[], bool]


class DockerSandboxRuntime:
    def __init__(
        self,
        *,
        docker_command: str = "docker",
        image: str = "ubuntu:22.04",
        disabled: bool = False,
        probe: Probe | None = None,
        image_probe: ImageProbe | None = None,
        exec_timeout_seconds: float = 30.0,
        memory_limit: str = "128m",
        cpu_limit: str = "0.5",
        pids_limit: int = 32,
        tmpfs_size: str = "16m",
    ) -> None:
        self._docker_command = docker_command
        self._image = image
        # D1：禁用开关来自 config.yaml（sandbox.disabled）；进程环境仍作为回退。
        self._disabled = disabled
        self._probe = probe or self._probe_daemon
        self._image_probe = image_probe
        # Tests with an injected daemon probe do not need a real Docker image.
        self._image_available: bool | None = (
            None if probe is None or image_probe is not None else True
        )
        self._exec_timeout_seconds = exec_timeout_seconds
        self._memory_limit = memory_limit
        self._cpu_limit = cpu_limit
        self._pids_limit = pids_limit
        self._tmpfs_size = tmpfs_size
        self._containers: dict[str, str] = {}
        self._container_generations: dict[str, str] = {}
        self._materialized_skill_digests: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    def capability(self, run_id: str | None = None) -> SandboxCapability:
        daemon_available = bool(self._probe())
        if daemon_available and self._image_available is None:
            self._image_available = self._probe_image()
        image_available = self._image_available is not False
        ready = daemon_available and (
            image_available and (run_id is None or run_id in self._containers)
        )
        reason = None
        if not daemon_available:
            reason = "docker_unavailable"
        elif not image_available:
            reason = "sandbox_image_unavailable"
        elif run_id is not None and run_id not in self._containers:
            reason = "sandbox_not_initialized"
        return SandboxCapability(
            provider="docker",
            ready=ready,
            reason_code=reason,
            resource_limits=(
                *DOCKER_RESOURCE_LIMITS,
                ("memory", self._memory_limit),
                ("cpus", self._cpu_limit),
                ("pids", str(self._pids_limit)),
            ),
        )

    async def start_run(
        self,
        run_id: str,
        *,
        allow_create: bool = True,
        generation_id: str | None = None,
    ) -> SandboxCapability:
        async with self._lock:
            if run_id in self._containers:
                if generation_id is None or self._container_generations.get(run_id) == generation_id:
                    return self.capability(run_id)
                # 已存在不同 generation 的容器，禁止接管；必须明确返回 mismatch。
                return SandboxCapability(
                    provider="docker",
                    ready=False,
                    reason_code="sandbox_generation_mismatch",
                    resource_limits=(
                        *DOCKER_RESOURCE_LIMITS,
                        ("memory", self._memory_limit),
                        ("cpus", self._cpu_limit),
                        ("pids", str(self._pids_limit)),
                    ),
                )
            capability = self.capability(run_id)
            if capability.reason_code in {
                "docker_unavailable",
                "sandbox_image_unavailable",
            }:
                return capability
            existing = await self._existing_container(run_id, generation_id)
            if existing is not None:
                self._containers[run_id] = existing
                if generation_id is not None:
                    self._container_generations[run_id] = generation_id
                return self.capability(run_id)
            if not allow_create:
                return self.capability(run_id)
            name = _container_name(run_id, generation_id)
            args = [
                self._docker_command,
                "run",
                "--detach",
                "--rm",
                "--name",
                name,
                "--label",
                f"venagent.run_id={run_id}",
                "--label",
                f"venagent.sandbox_generation={generation_id or ''}",
                "--label",
                "venagent.managed=true",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--user",
                "65534:65534",
                "--memory",
                self._memory_limit,
                "--cpus",
                self._cpu_limit,
                "--pids-limit",
                str(self._pids_limit),
                "--workdir",
                "/workspace",
                "--tmpfs",
                f"/tmp:rw,noexec,nosuid,size={self._tmpfs_size}",
                "--mount",
                "type=tmpfs,destination=/workspace,tmpfs-size=16777216",
                self._image,
                "sh",
                "-c",
                "while :; do sleep 3600; done",
            ]
            try:
                return_code, _, _ = await self._run_process(args, timeout=20.0)
            except (OSError, asyncio.TimeoutError):
                return self.capability(run_id)
            if return_code == 0:
                self._containers[run_id] = name
                if generation_id is not None:
                    self._container_generations[run_id] = generation_id
            return self.capability(run_id)

    async def _existing_container(
        self, run_id: str, generation_id: str | None = None
    ) -> str | None:
        """Runtime 重启时按容器名、Run 标签和 generation 标签重新识别已有容器。"""
        name = _container_name(run_id, generation_id)
        args = [
            self._docker_command,
            "ps",
            "--all",
            "--filter",
            f"name=^{name}$",
            "--filter",
            f"label=venagent.run_id={run_id}",
        ]
        if generation_id is not None:
            args.extend(["--filter", f"label=venagent.sandbox_generation={generation_id}"])
        args.extend(["--format", "{{.Names}}"])
        try:
            return_code, stdout_bytes, _ = await self._run_process(args, timeout=5.0)
        except (OSError, asyncio.TimeoutError):
            return None
        if return_code != 0:
            return None
        names = stdout_bytes.decode("utf-8", errors="replace").strip().splitlines()
        return names[0] if names else None

    async def stop_run(self, run_id: str) -> None:
        async with self._lock:
            name = self._containers.pop(run_id, None)
            self._container_generations.pop(run_id, None)
            self._materialized_skill_digests.pop(run_id, None)
        if name is None:
            return
        try:
            await self._run_process(
                [self._docker_command, "rm", "--force", name], timeout=10.0
            )
        except (OSError, asyncio.TimeoutError):
            return

    async def materialize_skills(
        self, run_id: str, packages: tuple[Any, ...]
    ) -> bool:
        """把 Run 绑定的声明文件复制为容器内 root 拥有的只读快照。"""
        if not packages:
            return True
        async with self._lock:
            container = self._containers.get(run_id)
            if container is None:
                return False
            completed = self._materialized_skill_digests.setdefault(run_id, set())
            for package in packages:
                package_key = f"{package.skill_id}:{package.package_digest}"
                if package_key in completed:
                    continue
                destination = PurePosixPath(
                    "/workspace/.venagent/skills"
                ) / package.skill_id / package.package_digest
                if not await self._copy_skill_package(
                    container, destination, package.files
                ):
                    return False
                completed.add(package_key)
        return True

    async def _copy_skill_package(
        self,
        container: str,
        destination: PurePosixPath,
        files: tuple[tuple[str, bytes], ...],
    ) -> bool:
        for relative, content in files:
            relative_path = PurePosixPath(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                return False
            target = destination / relative_path
            commands = (
                (
                    [
                        self._docker_command,
                        "exec",
                        "--user",
                        "0:0",
                        container,
                        "mkdir",
                        "-p",
                        str(target.parent),
                    ],
                    None,
                ),
                (
                    [
                        self._docker_command,
                        "exec",
                        "--interactive",
                        "--user",
                        "0:0",
                        container,
                        "tee",
                        str(target),
                    ],
                    content,
                ),
                (
                    [
                        self._docker_command,
                        "exec",
                        "--user",
                        "0:0",
                        container,
                        "chmod",
                        "0444",
                        str(target),
                    ],
                    None,
                ),
            )
            for command, input_bytes in commands:
                try:
                    return_code, _, _ = await self._run_process(
                        command, timeout=10.0, input_bytes=input_bytes
                    )
                except (OSError, asyncio.TimeoutError):
                    return False
                if return_code != 0:
                    return False
        try:
            return_code, _, _ = await self._run_process(
                [
                    self._docker_command,
                    "exec",
                    "--user",
                    "0:0",
                    container,
                    "find",
                    str(destination),
                    "-type",
                    "d",
                    "-exec",
                    "chmod",
                    "0555",
                    "{}",
                    "+",
                ],
                timeout=10.0,
            )
        except (OSError, asyncio.TimeoutError):
            return False
        return return_code == 0

    async def exec_command(
        self,
        descriptor: ToolDescriptor,
        arguments: dict[str, Any],
        *,
        run_id: str,
    ) -> ToolResult:
        if not self.capability(run_id).ready:
            raise SandboxUnavailable
        command = arguments.get("command")
        args = arguments.get("args", [])
        if (
            not isinstance(command, str)
            or not command
            or not isinstance(args, list)
            or any(not isinstance(item, str) for item in args)
        ):
            raise ToolSchemaInvalid
        container = self._containers[run_id]
        docker_args = [
            self._docker_command,
            "exec",
            "--user",
            "65534:65534",
            "--workdir",
            "/workspace",
            container,
            "timeout",
            "--signal=KILL",
            f"{self._exec_timeout_seconds}s",
            command,
            *args,
        ]
        try:
            return_code, stdout_bytes, stderr_bytes = await self._run_process(
                docker_args, timeout=self._exec_timeout_seconds + 2.0
            )
        except asyncio.CancelledError:
            # docker exec 客户端被取消不保证容器内进程同步退出；销毁本代环境，
            # 禁止遗留命令继续运行或被旧 Operation 再次接管。
            await self.stop_run(run_id)
            raise
        except asyncio.TimeoutError:
            # 结果未知时销毁环境，禁止在新容器中继续旧 Operation。
            await self.stop_run(run_id)
            raise SandboxUnavailable from None
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        content = _command_output(stdout, stderr)
        if return_code != 0:
            return ToolResult(
                tool_call_id="",
                operation_id="",
                status="error",
                summary="命令执行失败。",
                content=content[-65536:],
                error=(
                    "command_timeout"
                    if return_code in {124, 137}
                    else "command_failed"
                ),
            )
        return ToolResult(
            tool_call_id="",
            operation_id="",
            status="success",
            summary=content[-1024:] or "命令执行完成。",
            content=content[-262144:],
        )

    async def _run_process(
        self,
        args: list[str],
        *,
        timeout: float,
        input_bytes: bytes | None = None,
    ) -> tuple[int, bytes, bytes]:
        creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(
            subprocess, "CREATE_NO_WINDOW"
        ) else 0
        process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                asyncio.to_thread(process.communicate, input_bytes), timeout=timeout
            )
        except (asyncio.CancelledError, asyncio.TimeoutError):
            process.kill()
            await asyncio.to_thread(process.communicate)
            raise
        return process.returncode or 0, stdout or b"", stderr or b""

    def _probe_daemon(self) -> bool:
        if self._disabled:
            return False
        if os.environ.get("VENAGENT_SANDBOX_DISABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }:
            return False
        try:
            completed = subprocess.run(
                [
                    self._docker_command,
                    "version",
                    "--format",
                    "{{.Server.Version}}",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2.0,
                check=False,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0
                ),
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0

    def _probe_image(self) -> bool:
        if self._image_probe is not None:
            return bool(self._image_probe())
        try:
            completed = subprocess.run(
                [self._docker_command, "image", "inspect", self._image],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5.0,
                check=False,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0
                ),
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0


def _container_name(run_id: str, generation_id: str | None = None) -> str:
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:24]
    if generation_id is None:
        return f"venagent-{digest}"
    generation = hashlib.sha256(generation_id.encode("utf-8")).hexdigest()[:8]
    return f"venagent-{digest}-{generation}"


def _command_output(stdout: str, stderr: str) -> str:
    if not stderr:
        return stdout
    if not stdout:
        return stderr
    separator = "" if stdout.endswith("\n") else "\n"
    return f"{stdout}{separator}[stderr]\n{stderr}"
