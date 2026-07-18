from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from config.config import APIConfig, default_config
from venagent.infrastructure.config import AppConfig


def test_legacy_config_is_explicitly_mapped_to_immutable_app_config():
    from apps.api.compat import legacy_config_to_app_config

    legacy = APIConfig()
    legacy.llm_api_url = "https://llm.invalid"
    legacy.llm_api_key = "sentinel-secret"
    legacy.llm_model = "test-model"
    legacy.server_port = "8123"
    legacy.cors_origins = ["https://client.invalid"]

    mapped = legacy_config_to_app_config(legacy)

    assert isinstance(mapped, AppConfig)
    assert mapped.llm.api_url == "https://llm.invalid"
    assert mapped.llm.api_key.get_secret_value() == "sentinel-secret"
    assert mapped.server.port == 8123
    assert mapped.server.cors_origins == ("https://client.invalid",)
    assert "sentinel-secret" not in repr(mapped)


def test_legacy_bootstrap_uses_new_staged_container_and_preserves_order():
    from apps.api.compat import LegacyFactories, build_legacy_dependencies

    events = []

    class Resource:
        def close(self):
            events.append("close")

    infrastructure = Resource()
    agent = Resource()

    result = build_legacy_dependencies(
        APIConfig(),
        LegacyFactories(
            infrastructure_factory=lambda _cfg: events.append("infra") or infrastructure,
            agent_factory=lambda _cfg, _inf: events.append("agent") or agent,
            runtime_initializer=lambda _agent: events.append("runtime"),
            app_factory=lambda _cfg, _inf, _agent: events.append("app") or object(),
        ),
    )

    assert isinstance(result.dependencies.config, AppConfig)
    assert events == ["infra", "agent", "runtime", "app"]


def test_legacy_bootstrap_closes_partial_agent_when_runtime_fails():
    from apps.api.compat import LegacyFactories, build_legacy_dependencies

    events = []

    class Resource:
        def __init__(self, name):
            self.name = name

        def close(self):
            events.append(f"close:{self.name}")

    infrastructure = Resource("infra")
    agent = Resource("agent")

    from venagent.bootstrap import BootstrapError, BootstrapStage

    with pytest.raises(BootstrapError) as error_info:
        build_legacy_dependencies(
            APIConfig(),
            LegacyFactories(
                infrastructure_factory=lambda _cfg: infrastructure,
                agent_factory=lambda _cfg, _inf: agent,
                runtime_initializer=lambda _agent: (_ for _ in ()).throw(
                    RuntimeError("secret=sentinel")
                ),
                app_factory=lambda *_: object(),
            ),
        )

    assert error_info.value.stage is BootstrapStage.APPLICATION
    assert "sentinel" not in str(error_info.value)
    assert events == ["close:agent", "close:infra"]


def test_default_config_fails_fast_for_explicit_unreadable_file(tmp_path):
    missing = tmp_path / "missing.yaml"

    with pytest.raises(ValueError, match="cannot read configuration file"):
        default_config(str(missing))
