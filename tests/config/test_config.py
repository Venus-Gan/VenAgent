from pathlib import Path

import pytest
import yaml
from langchain_core.messages import AIMessage

from src import bootstrap
from src.config import ConfigError, load_config
from src.platform.runtime import DATABASE_URL, build_persistence_runtime


def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


# --- config.yaml 是唯一文件源 ---


def test_safe_defaults_do_not_enable_external_services(tmp_path: Path):
    config = load_config(project_root=tmp_path, environ={})

    assert config.server.port == 8090
    assert config.persistence.enabled is False
    assert config.persistence.database_url.get_secret_value() == ""
    assert config.neo4j.enabled is False
    assert config.neo4j.password.get_secret_value() == ""
    assert config.llm.provider == ""
    assert config.sandbox.image == "ubuntu:22.04"
    assert config.sandbox.disabled is False
    assert config.mcp.allowed_commands == ["node", "python", "python3"]
    assert config.mcp.credentials == {}
    assert config.github.token.get_secret_value() == ""


def test_yaml_is_primary_source(tmp_path: Path):
    _write_yaml(tmp_path / "config.yaml", {"server": {"port": 8300}})

    config = load_config(project_root=tmp_path, environ={})

    assert config.server.port == 8300


def test_yaml_populates_all_sections(tmp_path: Path):
    _write_yaml(
        tmp_path / "config.yaml",
        {
            "llm": {"provider": "anthropic", "api_key": "llm-secret", "model": "m"},
            "github": {"token": "gh-token"},
            "mcp": {
                "allowed_commands": ["node"],
                "credentials": {"VENAGENT_MCP_FOO_TOKEN": "foo-secret"},
            },
        },
    )

    config = load_config(project_root=tmp_path, environ={})

    assert config.llm.provider == "anthropic"
    assert config.llm.api_key.get_secret_value() == "llm-secret"
    assert config.github.token.get_secret_value() == "gh-token"
    assert config.mcp.allowed_commands == ["node"]
    assert config.mcp.credentials == {"VENAGENT_MCP_FOO_TOKEN": "foo-secret"}


def test_yaml_unknown_top_level_key_fails_fast(tmp_path: Path):
    _write_yaml(tmp_path / "config.yaml", {"server": {"port": 8300}, "typo": 1})

    with pytest.raises(ConfigError, match="typo"):
        load_config(project_root=tmp_path, environ={})


def test_yaml_unknown_nested_key_fails_fast(tmp_path: Path):
    _write_yaml(
        tmp_path / "config.yaml", {"server": {"port": 8300, "not_a_field": 1}}
    )

    with pytest.raises(ConfigError, match="server.not_a_field"):
        load_config(project_root=tmp_path, environ={})


def test_memory_consolidation_defaults_and_overrides(tmp_path: Path):
    config = load_config(project_root=tmp_path, environ={})

    block = config.memory_consolidation
    assert (block.window_messages, block.idle_seconds, block.max_input_tokens) == (
        5,
        600,
        4000,
    )

    _write_yaml(
        tmp_path / "config.yaml",
        {"memory_consolidation": {"window_messages": 8, "idle_seconds": 900}},
    )
    config = load_config(project_root=tmp_path, environ={})
    assert config.memory_consolidation.window_messages == 8
    assert config.memory_consolidation.idle_seconds == 900
    assert config.memory_consolidation.max_input_tokens == 4000


def test_memory_consolidation_out_of_range_fails_fast(tmp_path: Path):
    for bad in (
        {"window_messages": 0},
        {"window_messages": -1},
        {"idle_seconds": 59},
        {"max_input_tokens": 999},
    ):
        _write_yaml(tmp_path / "config.yaml", {"memory_consolidation": bad})
        with pytest.raises(ConfigError):
            load_config(project_root=tmp_path, environ={})


def test_memory_consolidation_unknown_key_fails_fast(tmp_path: Path):
    _write_yaml(
        tmp_path / "config.yaml",
        {"memory_consolidation": {"window_messages": 5, "bogus": 1}},
    )

    with pytest.raises(ConfigError, match="memory_consolidation"):
        load_config(project_root=tmp_path, environ={})


def test_yaml_type_error_fails_fast_without_echoing_values(tmp_path: Path):
    _write_yaml(
        tmp_path / "config.yaml",
        {"llm": {"api_key": "must-not-appear", "model": "m"}, "server": {"port": "many"}},
    )

    with pytest.raises(ConfigError) as caught:
        load_config(project_root=tmp_path, environ={})

    assert "server.port" in str(caught.value)
    assert "must-not-appear" not in str(caught.value)


def test_yaml_non_mapping_top_level_fails(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="顶层必须是映射"):
        load_config(project_root=tmp_path, environ={})


def test_bootstrap_copies_example_when_config_missing(tmp_path: Path):
    _write_yaml(
        tmp_path / "config.example.yaml",
        {"server": {"port": 8400}, "sandbox": {"image": "ubuntu:24.04"}},
    )

    config = load_config(project_root=tmp_path, environ={})

    assert (tmp_path / "config.yaml").is_file()
    assert config.server.port == 8400
    assert config.sandbox.image == "ubuntu:24.04"


def test_bootstrap_empty_sensitive_fields_degrade_safely(tmp_path: Path):
    _write_yaml(
        tmp_path / "config.example.yaml",
        {
            "auth": {"jwt_secret": ""},
            "invocation": {"encryption_key": ""},
            "github": {"token": ""},
            "mcp": {"credentials": {}},
        },
    )

    config = load_config(project_root=tmp_path, environ={})

    assert config.auth.jwt_secret.get_secret_value() == ""
    assert config.invocation.configured is False
    assert config.github.token.get_secret_value() == ""
    assert config.mcp.credentials == {}


# --- 进程环境白名单覆盖（env > config.yaml） ---


def test_process_environment_overrides_yaml(tmp_path: Path):
    _write_yaml(tmp_path / "config.yaml", {"server": {"port": 8100}})

    config = load_config(
        project_root=tmp_path, environ={"SERVER__PORT": "8200"}
    )

    assert config.server.port == 8200


def test_yaml_value_survives_without_env_override(tmp_path: Path):
    _write_yaml(tmp_path / "config.yaml", {"server": {"port": 8100}})

    config = load_config(project_root=tmp_path, environ={"LLM_PROVIDER": "openai"})

    assert config.server.port == 8100
    assert config.llm.provider == "openai"


def test_sandbox_image_can_be_overridden_explicitly(tmp_path: Path):
    config = load_config(
        project_root=tmp_path,
        environ={"SANDBOX__IMAGE": "registry.example/venagent-sandbox@sha256:abc"},
    )

    assert config.sandbox.image == "registry.example/venagent-sandbox@sha256:abc"


def test_sandbox_disabled_env_override(tmp_path: Path):
    config = load_config(project_root=tmp_path, environ={"SANDBOX__DISABLED": "true"})

    assert config.sandbox.disabled is True


def test_mcp_allowed_commands_env_comma_list(tmp_path: Path):
    config = load_config(
        project_root=tmp_path,
        environ={"VENAGENT_MCP_ALLOWED_COMMANDS": "node, python3"},
    )

    assert config.mcp.allowed_commands == ["node", "python3"]


def test_github_token_env_override(tmp_path: Path):
    config = load_config(project_root=tmp_path, environ={"GITHUB_TOKEN": "env-token"})

    assert config.github.token.get_secret_value() == "env-token"


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


def test_milvus_es_env_enablement_parses_bools(tmp_path: Path):
    """MILVUS__ENABLED/ES__ENABLED 走 bool 解析（strict 模型拒绝字符串）。"""
    config = load_config(
        project_root=tmp_path,
        environ={
            "MILVUS__ENABLED": "true",
            "MILVUS__URI": "http://127.0.0.1:19531",
            "ES__ENABLED": "1",
            "ES__URI": "http://127.0.0.1:9201",
        },
    )
    assert config.milvus.enabled is True
    assert config.milvus.uri == "http://127.0.0.1:19531"
    assert config.es.enabled is True
    assert config.es.uri == "http://127.0.0.1:9201"


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


def test_unknown_nested_environment_override_fails_fast(tmp_path: Path):
    with pytest.raises(ConfigError, match="SERVER__TYPO"):
        load_config(project_root=tmp_path, environ={"SERVER__TYPO": "value"})


# --- bootstrap 装配集成 ---


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


# --- memory_extractor / embedding profile ---


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


@pytest.mark.parametrize("section", ["rewrite_model", "rerank_model"])
def test_override_model_only_inherits_main_profile(tmp_path: Path, section: str) -> None:
    config = load_config(
        environ={
            "LLM_PROVIDER": "openai",
            "LLM_API_KEY": "main-secret",
            "LLM_MODEL": "chat-model",
            f"{section.upper()}_MODEL": "cheap-model",
        },
        project_root=tmp_path,
    )

    resolved = getattr(config, section).as_llm_config(config.llm)

    assert resolved.provider == "openai"
    assert resolved.model == "cheap-model"
    assert resolved.api_key.get_secret_value() == "main-secret"


@pytest.mark.parametrize("section", ["rewrite_model", "rerank_model"])
def test_override_model_only_requires_a_main_profile(tmp_path: Path, section: str) -> None:
    with pytest.raises(ConfigError):
        load_config(
            environ={f"{section.upper()}_MODEL": "cheap-model"},
            project_root=tmp_path,
        )


@pytest.mark.parametrize("section", ["rewrite_model", "rerank_model"])
@pytest.mark.parametrize(
    "section_data",
    [
        {"provider": "openai", "api_key": "secret"},  # configured 缺 model
        {"model": "m", "provider": "openai"},  # independent 缺 api_key
        {"model": "m", "base_url": "https://provider.invalid/v1"},  # independent 缺 provider/api_key
    ],
)
def test_override_profile_validation(
    tmp_path: Path, section: str, section_data: dict[str, object]
) -> None:
    _write_yaml(tmp_path / "config.yaml", {section: section_data})

    with pytest.raises(ConfigError):
        load_config(project_root=tmp_path, environ={})


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


# --- 敏感字段：config.yaml 为源，env 可覆盖 ---


def test_invocation_encryption_key_from_yaml(tmp_path: Path) -> None:
    import base64

    key = base64.b64encode(b"k" * 32).decode()
    _write_yaml(
        tmp_path / "config.yaml",
        {"invocation": {"encryption_key": key}},
    )

    config = load_config(project_root=tmp_path, environ={})

    assert config.invocation.encryption_key.get_secret_value() == key


def test_invocation_encryption_key_process_env_overrides_yaml(
    tmp_path: Path,
) -> None:
    import base64

    yaml_key = base64.b64encode(b"a" * 32).decode()
    process_key = base64.b64encode(b"b" * 32).decode()
    _write_yaml(
        tmp_path / "config.yaml",
        {"invocation": {"encryption_key": yaml_key}},
    )

    config = load_config(
        project_root=tmp_path,
        environ={"VENAGENT_INVOCATION_ENCRYPTION_KEY": process_key},
    )

    assert config.invocation.encryption_key.get_secret_value() == process_key
