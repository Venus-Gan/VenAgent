"""Phase 2 Sprint 05 的 Docker-only sandbox 安全契约测试。"""

from pathlib import Path
import re
import sys
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from venagent.adapters.docker.sandbox import DockerLaunchResult, DockerSandboxAdapter
from venagent.capability.broker import CapabilityBroker
from venagent.capability.catalog import CapabilityCatalog
from venagent.capability.contracts import (
    CapabilityCall,
    CapabilityDescriptor,
    CapabilityErrorCode,
    CapabilityHealthState,
    CapabilityOutcome,
    CapabilityRisk,
    CapabilitySideEffect,
    ServerExecutionContext,
)
from venagent.capability.errors import AdapterUnavailableError
from venagent.capability.invoker import AuthorizedToolInvoker
from venagent.capability.runtime_models import CapabilityAuthorization, CapabilityRegistration
from venagent.core.sandbox.policy import SandboxCommand, SandboxExecutionPolicy


class _FakeDockerLauncher:
    def __init__(self, result: DockerLaunchResult | Exception) -> None:
        self._result = result
        self.specs = []

    def launch(self, spec):
        self.specs.append(spec)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _policy(**overrides) -> SandboxExecutionPolicy:
    defaults = {
        "image": "venagent-sandbox:1.0",
        "allowed_executables": ("python", "echo"),
        "timeout_ms": 3_000,
        "max_output_bytes": 1_024,
        "memory_limit_mb": 128,
        "cpu_percent": 50,
        "max_pids": 32,
        "tmpfs_size_mb": 16,
    }
    return SandboxExecutionPolicy(**(defaults | overrides))


def _descriptor(health: CapabilityHealthState = CapabilityHealthState.AVAILABLE) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id="sandbox.execute",
        contract_version="1.0.0",
        input_schema={
            "type": "object",
            "properties": {
                "argv": {"type": "array"},
                "timeout_ms": {"type": "integer"},
            },
            "required": ["argv"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        risk=CapabilityRisk.CRITICAL,
        side_effect=CapabilitySideEffect.EXECUTE,
        durable=False,
        adapter_id="docker.sandbox",
        health=health,
    )


def _authorization(allowed: bool = True) -> CapabilityAuthorization:
    scope = frozenset({"sandbox.execute"}) if allowed else frozenset()
    return CapabilityAuthorization(
        intent_scope=scope,
        participant_scope=scope,
        deployment_scope=scope,
        user_scope=scope,
        approval_scope=scope,
    )


def _call(parameters: dict[str, object] | None = None) -> CapabilityCall:
    return CapabilityCall(
        call_id=uuid4(),
        capability_id="sandbox.execute",
        contract_version="1.0.0",
        parameters=parameters or {"argv": ["python", "--version"]},
        context=ServerExecutionContext(tenant_id="tenant-1", principal_id="user-1", run_id=uuid4()),
        idempotency_key="sandbox-sprint-05",
    )


def _adapter(launcher: _FakeDockerLauncher, **policy_overrides) -> DockerSandboxAdapter:
    return DockerSandboxAdapter(descriptor=_descriptor(), policy=_policy(**policy_overrides), launcher=launcher)


def _invoker(launcher: _FakeDockerLauncher, *, health: CapabilityHealthState = CapabilityHealthState.AVAILABLE):
    descriptor = _descriptor(health)
    adapter = DockerSandboxAdapter(descriptor=descriptor, policy=_policy(), launcher=launcher)
    catalog = CapabilityCatalog((CapabilityRegistration(descriptor=descriptor, adapter=adapter, health=health),))
    return AuthorizedToolInvoker(catalog), catalog


def test_policy_fails_closed_for_unsafe_or_incomplete_configuration():
    with pytest.raises(ValueError, match="allowed_executables"):
        _policy(allowed_executables=())
    with pytest.raises(ValueError, match="allowed_executables"):
        _policy(allowed_executables="python")
    with pytest.raises(ValueError, match="allowed_executables"):
        _policy(allowed_executables=(7,))
    with pytest.raises(ValueError, match="image"):
        _policy(image=None)
    with pytest.raises(ValueError, match="timeout_ms"):
        _policy(timeout_ms=0)
    with pytest.raises(ValueError, match="workspace"):
        _policy(workspace="/host")
    with pytest.raises(ValueError, match="network"):
        _policy(network_disabled=False)
    with pytest.raises(ValueError, match="backend"):
        _policy(backend="local")


def test_docker_adapter_only_accepts_the_critical_sandbox_execute_descriptor():
    launcher = _FakeDockerLauncher(DockerLaunchResult(exit_code=0, stdout="ok", stderr=""))
    wrong_descriptor = _descriptor().model_copy(update={"capability_id": "document.write"})

    with pytest.raises(ValueError, match="sandbox.execute"):
        DockerSandboxAdapter(descriptor=wrong_descriptor, policy=_policy(), launcher=launcher)


@pytest.mark.parametrize(
    "argv",
    (
        ("sh", "-c", "echo unsafe"),
        ("python", "-c", "x; echo y"),
        ("python", "$(id)"),
        ("python", "../secret"),
        ("python", "/var/run/docker.sock"),
        ("python", "/etc/shadow"),
        ("curl", "https://example.invalid"),
    ),
)
def test_command_rejects_shell_syntax_sensitive_paths_and_unapproved_executables(argv):
    with pytest.raises(ValueError):
        SandboxCommand.from_argv(argv, _policy())


def test_docker_spec_is_docker_only_and_cannot_contain_host_escape_flags():
    command = SandboxCommand.from_argv(("python", "--version"), _policy())
    spec = _policy().build_spec(command)

    assert spec.argv[:3] == ("docker", "run", "--rm")
    assert "--network" in spec.argv and spec.argv[spec.argv.index("--network") + 1] == "none"
    assert "--read-only" in spec.argv
    assert "--security-opt" in spec.argv and "no-new-privileges" in spec.argv
    assert "--cap-drop" in spec.argv and "ALL" in spec.argv
    assert "--workdir" in spec.argv and "/workspace" in spec.argv
    assert "--tmpfs" in spec.argv and "/workspace:rw,noexec,nosuid,size=16m" in spec.argv
    assert not {"--privileged", "--cap-add", "--mount", "-v", "--env", "--env-file", "--pid"}.intersection(spec.argv)
    assert "host" not in spec.argv


def test_docker_adapter_only_delegates_a_compliant_spec_and_returns_redacted_output():
    launcher = _FakeDockerLauncher(
        DockerLaunchResult(exit_code=0, stdout="api_key=sentinel-secret\nready", stderr="", truncated=False)
    )
    result = _adapter(launcher).execute({"argv": ["python", "--version"]})

    assert result == {"exit_code": 0, "stdout": "api_key=[REDACTED]\nready", "truncated": False}
    assert len(launcher.specs) == 1
    assert launcher.specs[0].argv[-3:] == ("venagent-sandbox:1.0", "python", "--version")


def test_unavailable_and_timeout_map_to_stable_capability_results_without_sensitive_details():
    unavailable_invoker, _ = _invoker(_FakeDockerLauncher(AdapterUnavailableError("docker unavailable password=secret")))
    unavailable = unavailable_invoker.invoke(_call(), _authorization())
    timeout_invoker, _ = _invoker(_FakeDockerLauncher(DockerLaunchResult(exit_code=-1, stdout="", stderr="/etc/shadow", timed_out=True)))
    timeout = timeout_invoker.invoke(_call(), _authorization())

    assert unavailable.error_code is CapabilityErrorCode.UNAVAILABLE
    assert timeout.error_code is CapabilityErrorCode.TIMEOUT
    assert "secret" not in str(unavailable)
    assert "shadow" not in str(timeout)


def test_authorization_health_schema_or_policy_denial_never_reaches_launcher():
    launcher = _FakeDockerLauncher(DockerLaunchResult(exit_code=0, stdout="ok", stderr=""))
    invoker, catalog = _invoker(launcher)

    denied = invoker.invoke(_call(), _authorization(allowed=False))
    invalid = invoker.invoke(_call({"argv": "python --version"}), _authorization())
    unavailable = AuthorizedToolInvoker(
        CapabilityCatalog(
            (
                CapabilityRegistration(
                    descriptor=_descriptor(CapabilityHealthState.UNAVAILABLE),
                    adapter=DockerSandboxAdapter(_descriptor(CapabilityHealthState.UNAVAILABLE), _policy(), launcher),
                    health=CapabilityHealthState.UNAVAILABLE,
                ),
            )
        )
    ).invoke(_call(), _authorization())
    policy_denied = invoker.invoke(_call({"argv": ["curl", "https://example.invalid"]}), _authorization())

    assert denied.error_code is CapabilityErrorCode.UNAUTHORIZED
    assert invalid.error_code is CapabilityErrorCode.INVALID_INPUT
    assert unavailable.error_code is CapabilityErrorCode.UNAVAILABLE
    assert policy_denied.error_code is CapabilityErrorCode.ADAPTER_ERROR
    assert launcher.specs == []
    assert catalog.registrations()


def test_new_sandbox_path_has_no_legacy_runtime_shell_or_http_dependency():
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "venagent").rglob("*.py"))

    assert re.search(r"^\s*(?:from|import)\s+final(?:\.|\s|$)", source, re.MULTILINE) is None
    assert "subprocess" not in (ROOT / "src" / "venagent" / "adapters" / "docker" / "sandbox.py").read_text(encoding="utf-8")
    assert "sh -c" not in (ROOT / "src" / "venagent" / "core" / "sandbox" / "policy.py").read_text(encoding="utf-8")
