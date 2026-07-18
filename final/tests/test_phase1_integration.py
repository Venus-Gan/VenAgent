from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def test_legacy_main_build_deps_delegates_to_compat_bootstrap(monkeypatch):
    import main
    from apps.api.compat import LegacyFactories
    from venagent.bootstrap import BootstrapResult
    from venagent.bootstrap.container import BootstrapDependencies
    from venagent.infrastructure.config import AppConfig

    legacy_config = main.default_config()
    captured = {}
    expected = object()

    def fake_build(config, factories):
        captured["config"] = config
        assert isinstance(factories, LegacyFactories)
        return BootstrapResult(
            dependencies=BootstrapDependencies(
                config=AppConfig(),
                infrastructure="infra",
                application="agent",
                app=expected,
            ),
            diagnostics=(),
        )

    monkeypatch.setattr(main, "default_config", lambda: legacy_config)
    monkeypatch.setattr(main, "build_legacy_dependencies", fake_build)

    deps = main.build_deps()

    assert deps.cfg is legacy_config
    assert deps.inf == "infra"
    assert deps.agent == "agent"
    assert deps.app is expected
    assert captured["config"] is legacy_config


def test_app_shell_adopts_built_router_without_copying_runtime_state():
    from types import SimpleNamespace

    from apps.api.main import _adopt_built_app

    shell = SimpleNamespace(
        router="shell-router",
        user_middleware=[],
        exception_handlers={},
        middleware_stack="old-stack",
        state=SimpleNamespace(safe="keep"),
    )
    built = SimpleNamespace(
        router="built-router",
        user_middleware=["middleware"],
        exception_handlers={"error": "handler"},
        state=SimpleNamespace(secret="must-not-copy"),
    )

    _adopt_built_app(shell, built)

    assert shell.router == "built-router"
    assert shell.user_middleware == ["middleware"]
    assert shell.exception_handlers == {"error": "handler"}
    assert shell.middleware_stack is None
    assert shell.state.safe == "keep"
    assert not hasattr(shell.state, "secret")


@pytest.mark.parametrize(
    ("dependency", "expected"),
    [
        ("postgresql", "durable_workflow"),
        ("milvus", "rag"),
        ("elasticsearch", "rag"),
    ],
)
def test_degraded_capability_integration_contract_is_explicit(dependency, expected):
    from venagent.infrastructure.health import CapabilityHealthEvaluator, CapabilityState

    statuses = {
        "llm": "available",
        "postgresql": "connected",
        "milvus": "connected",
        "elasticsearch": "connected",
        "kafka": "connected",
        "neo4j": "connected",
        "sandbox": "available",
    }
    statuses[dependency] = "disconnected"

    capability = CapabilityHealthEvaluator(statuses).evaluate().get(expected)

    assert capability.state is CapabilityState.UNAVAILABLE
    assert capability.reason_code == "DEPENDENCY_UNAVAILABLE"
