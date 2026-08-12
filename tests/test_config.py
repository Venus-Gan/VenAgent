from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from venagent import bootstrap
from venagent.config import ConfigError, load_config
from venagent.platform.runtime import DATABASE_URL, build_persistence_runtime


def test_safe_defaults_do_not_enable_external_services(tmp_path: Path):
    config = load_config(project_root=tmp_path, environ={})

    assert config.server.port == 8090
    assert config.persistence.enabled is False
    assert config.persistence.database_url.get_secret_value() == ""
    assert config.neo4j.enabled is False
    assert config.neo4j.password.get_secret_value() == ""
    assert config.llm.provider == ""


def test_explicit_environment_populates_all_application_sections(tmp_path: Path):
    config = load_config(
        project_root=tmp_path,
        environ={
            "SERVER__PORT": "8200",
            "PERSISTENCE__ENABLED": "true",
            "PERSISTENCE__HOST": "db.example",
            "PERSISTENCE__PORT": "5433",
            "PERSISTENCE__DATABASE": "venagent/dev",
            "PERSISTENCE__USER": "app user",
            "POSTGRES_PASSWORD": "pa:ss/@?",
            "NEO4J__ENABLED": "true",
            "NEO4J__URI": "neo4j+s://graph.example:7687",
            "NEO4J__DATABASE": "venagent",
            "NEO4J__USER": "graph-user",
            "NEO4J_PASSWORD": "graph-secret",
            "NEO4J__READ_TIMEOUT": "0.2",
            "AUTH__ISSUER": "test-issuer",
            "AUTH__AUDIENCE": "test-client",
            "AUTH__COOKIE_SECURE": "1",
            "AUTH__ALLOWED_ORIGINS_JSON": '["https://example.test"]',
        },
    )

    assert config.server.port == 8200
    assert config.auth.issuer == "test-issuer"
    assert config.auth.audience == "test-client"
    assert config.auth.cookie_secure is True
    assert config.auth.allowed_origins == ["https://example.test"]
    assert config.persistence.database_url.get_secret_value() == (
        "postgresql://app%20user:pa%3Ass%2F%40%3F@db.example:5433/venagent%2Fdev"
    )
    assert config.neo4j.enabled is True
    assert config.neo4j.uri == "neo4j+s://graph.example:7687"
    assert config.neo4j.database == "venagent"
    assert config.neo4j.user == "graph-user"
    assert config.neo4j.password.get_secret_value() == "graph-secret"
    assert config.neo4j.read_timeout == 0.2


def test_process_environment_overrides_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / ".env").write_text(
        "# 本地文件提供较低优先级的值。\nSERVER__PORT=8100\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "venagent.config.loader.os.environ",
        {"SERVER__PORT": "8200"},
    )

    config = load_config(project_root=tmp_path)

    assert config.server.port == 8200


def test_blank_environment_values_are_treated_as_unset(tmp_path: Path):
    config = load_config(
        project_root=tmp_path,
        environ={
            "PERSISTENCE__ENABLED": "   ",
            "LLM_API_KEY": "",
        },
    )

    assert config.persistence.enabled is False
    assert config.llm.api_key.get_secret_value() == ""


@pytest.mark.parametrize(
    ("environment", "field"),
    [
        ({"PERSISTENCE__ENABLED": "sometimes"}, "persistence.enabled"),
        ({"PERSISTENCE__PORT": "many"}, "persistence.port"),
        ({"NEO4J__READ_TIMEOUT": "slow"}, "neo4j.read_timeout"),
        ({"AUTH__ALLOWED_ORIGINS_JSON": "{}"}, "auth.allowed_origins"),
    ],
)
def test_invalid_environment_types_fail_without_echoing_values(
    tmp_path: Path, environment: dict[str, str], field: str
):
    secret_marker = "must-not-appear"
    environment = {
        **environment,
        "POSTGRES_PASSWORD": secret_marker,
        "NEO4J_PASSWORD": secret_marker,
    }

    with pytest.raises(ConfigError) as caught:
        load_config(project_root=tmp_path, environ=environment)

    assert field in str(caught.value)
    assert secret_marker not in str(caught.value)


def test_normal_application_startup_passes_configured_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = load_config(
        project_root=tmp_path,
        environ={
            "PERSISTENCE__ENABLED": "true",
            "POSTGRES_PASSWORD": "test-password",
        },
    )
    captured: dict[str, str] = {}

    def fake_persistence_runtime(environment: dict[str, str]):
        captured.update(environment)
        return build_persistence_runtime({})

    class FixedModel:
        def invoke(self, _messages):
            return AIMessage(content="ok")

    monkeypatch.setattr(
        bootstrap, "build_persistence_runtime", fake_persistence_runtime
    )
    monkeypatch.setattr(bootstrap, "build_runtime_model", lambda _config: FixedModel())

    application = bootstrap.build_application(config=config)

    assert captured == {
        DATABASE_URL: config.persistence.database_url.get_secret_value()
    }
    application.close()


def test_unknown_nested_environment_override_fails_fast(tmp_path: Path):
    with pytest.raises(ConfigError, match="SERVER__TYPO"):
        load_config(project_root=tmp_path, environ={"SERVER__TYPO": "value"})


def test_memory_extractor_model_only_inherits_main_profile(tmp_path: Path) -> None:
    config = load_config(
        environ={
            "LLM_PROVIDER": "openai",
            "LLM_API_KEY": "main-secret",
            "LLM_MODEL": "chat-model",
            "MEMORY_EXTRACTOR_MODEL": "cheap-model",
        },
        project_root=tmp_path,
    )

    resolved = config.memory_extractor.as_llm_config(config.llm)

    assert resolved.provider == "openai"
    assert resolved.model == "cheap-model"
    assert resolved.api_key.get_secret_value() == "main-secret"


def test_memory_extractor_model_only_requires_a_main_profile(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(
            environ={"MEMORY_EXTRACTOR_MODEL": "cheap-model"},
            project_root=tmp_path,
        )


def test_embedding_profile_is_all_or_none_and_secret_safe(tmp_path: Path) -> None:
    config = load_config(
        environ={
            "EMBEDDING_API_URL": "https://provider.invalid/v1/embeddings",
            "EMBEDDING_API_KEY": "embedding-secret",
            "EMBEDDING_MODEL": "embedding-model",
        },
        project_root=tmp_path,
    )

    assert config.embedding.enabled is True
    with pytest.raises(ConfigError) as captured:
        load_config(
            environ={
                "EMBEDDING_API_URL": (
                    "https://embedding-secret@provider.invalid/v1/embeddings"
                ),
                "EMBEDDING_API_KEY": "embedding-secret",
                "EMBEDDING_MODEL": "embedding-model",
            },
            project_root=tmp_path,
        )
    assert "embedding-secret" not in str(captured.value)


def test_embedding_profile_controls_agent_memory_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FixedModel:
        def invoke(self, _messages):
            return AIMessage(content="ok")

    monkeypatch.setattr(
        bootstrap, "build_runtime_model", lambda _config: FixedModel()
    )
    disabled = load_config(project_root=tmp_path, environ={})
    enabled = load_config(
        project_root=tmp_path,
        environ={
            "EMBEDDING_API_URL": "https://provider.invalid/v1/embeddings",
            "EMBEDDING_API_KEY": "embedding-secret",
            "EMBEDDING_MODEL": "embedding-model",
            "EMBEDDING_TIMEOUT": "2",
            "EMBEDDING_MAX_RETRIES": "1",
        },
    )
    capped = enabled.model_copy(
        update={
            "embedding": enabled.embedding.model_copy(
                update={"timeout": 120.0, "max_retries": 10}
            )
        }
    )

    disabled_app = bootstrap.build_application(config=disabled)
    enabled_app = bootstrap.build_application(config=enabled)
    try:
        assert disabled_app.runtime._memory_long_term_deadline == pytest.approx(0.15)
        assert enabled_app.runtime._memory_long_term_deadline == pytest.approx(4.5)
        assert bootstrap._memory_long_term_deadline(capped) == pytest.approx(30.5)
    finally:
        disabled_app.close()
        enabled_app.close()
