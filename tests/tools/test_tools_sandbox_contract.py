"""M06 docker sandbox 公开契约（单点）。

- docker 不可用时干净降级（ready False + reason_code + resource_limits）：本文件单点。
- 镜像缺失时报告 sandbox_image_unavailable 且不启动容器：本文件单点。
  （用测试子类重写 _run_process 计数验证「不启动」，未触碰生产私有状态。）
- 保守默认资源上限：本文件单点。
"""

from __future__ import annotations

import asyncio

from src.sandbox.docker import DockerSandboxRuntime


def test_docker_sandbox_reports_clean_degredation() -> None:
    sandbox = DockerSandboxRuntime(probe=lambda: False)
    capability = sandbox.capability()
    assert capability.ready is False
    assert capability.reason_code == "docker_unavailable"
    assert "network" in dict(capability.resource_limits)


def test_docker_sandbox_reports_missing_image_without_starting_container() -> None:
    class RecordingSandbox(DockerSandboxRuntime):
        def __init__(self) -> None:
            super().__init__(probe=lambda: True, image_probe=lambda: False)
            self.process_calls = 0

        async def _run_process(
            self, _args: list[str], *, timeout: float
        ) -> tuple[int, bytes, bytes]:
            self.process_calls += 1
            return 0, b"", b""

    async def scenario() -> None:
        sandbox = RecordingSandbox()
        capability = await sandbox.start_run("run-missing-image")

        assert capability.ready is False
        assert capability.reason_code == "sandbox_image_unavailable"
        assert sandbox.process_calls == 0

    asyncio.run(scenario())


def test_docker_sandbox_uses_conservative_default_resource_limits() -> None:
    sandbox = DockerSandboxRuntime()

    limits = dict(sandbox.capability().resource_limits)

    assert limits["memory"] == "128m"
    assert limits["cpus"] == "0.5"
    assert limits["pids"] == "32"