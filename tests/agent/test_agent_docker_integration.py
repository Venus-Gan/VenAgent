"""M06 真 Docker 3 件套集成测试（单点、环境门控）。

- 仅当 VENAGENT_RUN_DOCKER_INTEGRATION=1 时运行（@pytest.mark.integration +
  skipif 环境门控），并临时置 VENAGENT_SANDBOX_DISABLED=0。
- 清理断言全部经公开接口：stop_run 后 capability(...).ready 为 False，
  且重新 start_run(allow_create=False, generation_id=...) 返回 not-ready
  （等价断言「容器已销毁」，不再触碰私有 _existing_container/_containers）。
- docker generation mismatch 契约由 test_agent_sandbox_lifecycle.py 的
  语义容器丢失测试单点覆盖，不再注入 _containers 私有状态。
"""

from __future__ import annotations

import asyncio
import os

import pytest

from src.sandbox.docker import DockerSandboxRuntime
from src.skills.catalog import SkillCatalog
from src.skills.manifest import SkillFile, SkillManifest, digest_sha256
from src.tools.models import ToolDescriptor

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("VENAGENT_RUN_DOCKER_INTEGRATION") != "1",
        reason="set VENAGENT_RUN_DOCKER_INTEGRATION=1 to run real Docker integration",
    ),
]


def _exec_descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        tool_id="exec_command",
        public_name="exec_command",
        source="native",
        description="exec",
        input_schema={},
        risk="safe",
    )


async def _assert_container_destroyed(
    sandbox: DockerSandboxRuntime, run_id: str, generation_id: str
) -> None:
    """公开 rediscovery：stop 后容器已销毁，不允许创建的 start 返回 not-ready。"""
    capability = await sandbox.start_run(
        run_id, allow_create=False, generation_id=generation_id
    )
    assert not capability.ready


def test_real_docker_sandbox_create_execute_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VENAGENT_SANDBOX_DISABLED", "0")

    async def scenario() -> None:
        image = os.environ.get("VENAGENT_SANDBOX_IMAGE", "ubuntu:22.04")
        sandbox = DockerSandboxRuntime(image=image)
        generation = "integration-gen"
        capability = await sandbox.start_run(
            "integration-run", allow_create=True, generation_id=generation
        )
        assert capability.ready
        result = await sandbox.exec_command(
            _exec_descriptor(),
            {
                "command": "sh",
                "args": [
                    "-c",
                    "printf integration-ok; printf integration-warning >&2",
                ],
            },
            run_id="integration-run",
        )
        assert result.status == "success"
        assert "integration-ok" in result.content
        assert "integration-warning" in result.content
        await sandbox.stop_run("integration-run")
        assert not sandbox.capability("integration-run").ready
        await _assert_container_destroyed(sandbox, "integration-run", generation)

    asyncio.run(scenario())


def test_real_docker_timeout_and_cancellation_destroy_uncertain_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VENAGENT_SANDBOX_DISABLED", "0")

    async def scenario() -> None:
        image = os.environ.get("VENAGENT_SANDBOX_IMAGE", "ubuntu:22.04")
        descriptor = _exec_descriptor()
        timeout_sandbox = DockerSandboxRuntime(
            image=image, exec_timeout_seconds=0.2
        )
        timeout_generation = "integration-timeout-gen"
        capability = await timeout_sandbox.start_run(
            "integration-timeout",
            allow_create=True,
            generation_id=timeout_generation,
        )
        assert capability.ready
        result = await timeout_sandbox.exec_command(
            descriptor,
            {"command": "sleep", "args": ["2"]},
            run_id="integration-timeout",
        )
        assert result.status == "error"
        assert result.error == "command_timeout"
        await timeout_sandbox.stop_run("integration-timeout")
        assert not timeout_sandbox.capability("integration-timeout").ready
        await _assert_container_destroyed(
            timeout_sandbox, "integration-timeout", timeout_generation
        )

        cancel_sandbox = DockerSandboxRuntime(image=image)
        cancel_generation = "integration-cancel-gen"
        capability = await cancel_sandbox.start_run(
            "integration-cancel",
            allow_create=True,
            generation_id=cancel_generation,
        )
        assert capability.ready
        task = asyncio.create_task(
            cancel_sandbox.exec_command(
                descriptor,
                {"command": "sleep", "args": ["30"]},
                run_id="integration-cancel",
            )
        )
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not cancel_sandbox.capability("integration-cancel").ready
        await _assert_container_destroyed(
            cancel_sandbox, "integration-cancel", cancel_generation
        )

    asyncio.run(scenario())


def test_real_docker_materializes_bound_skill_files_read_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("VENAGENT_SANDBOX_DISABLED", "0")
    instructions = b"# Script helper\n"
    script = b"printf skill-materialized-ok\n"
    manifest = SkillManifest(
        skill_id="script-helper",
        name="Script helper",
        version="1.0.0",
        description="Runs a bounded helper",
        digest_sha256=digest_sha256(instructions),
        source_url="test://script-helper",
        files=(SkillFile("scripts/analyze.sh", digest_sha256(script)),),
    )
    catalog = SkillCatalog(root=tmp_path / "skills")
    installed = catalog.install(
        manifest,
        manifest.digest_sha256,
        files={"SKILL.md": instructions, "scripts/analyze.sh": script},
    )
    catalog.bind_run("integration-skill", ("script-helper",))

    async def scenario() -> None:
        image = os.environ.get("VENAGENT_SANDBOX_IMAGE", "ubuntu:22.04")
        sandbox = DockerSandboxRuntime(image=image)
        generation = "integration-skill-gen"
        capability = await sandbox.start_run(
            "integration-skill", allow_create=True, generation_id=generation
        )
        assert capability.ready
        try:
            packages = catalog.materializations_for_run("integration-skill")
            assert await sandbox.materialize_skills("integration-skill", packages)
            descriptor = _exec_descriptor()
            script_path = (
                "/workspace/.venagent/skills/script-helper/"
                f"{installed.package_digest}/scripts/analyze.sh"
            )
            result = await sandbox.exec_command(
                descriptor,
                {"command": "sh", "args": [script_path]},
                run_id="integration-skill",
            )
            assert result.status == "success"
            assert "skill-materialized-ok" in result.content
            overwrite = await sandbox.exec_command(
                descriptor,
                {
                    "command": "sh",
                    "args": ["-c", f"printf hacked >> {script_path}"],
                },
                run_id="integration-skill",
            )
            assert overwrite.status == "error"
        finally:
            await sandbox.stop_run("integration-skill")
        assert not sandbox.capability("integration-skill").ready
        await _assert_container_destroyed(sandbox, "integration-skill", generation)

    asyncio.run(scenario())