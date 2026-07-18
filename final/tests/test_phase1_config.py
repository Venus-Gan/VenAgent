import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretStr as PydanticSecretStr, ValidationError

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from venagent.infrastructure.config import (  # noqa: E402
    AppConfig,
    ConfigError,
    load_config,
    redact_config,
)


def test_app_config_is_frozen_and_has_safe_defaults():
    config = AppConfig()

    assert config.llm.api_key.get_secret_value() == ""
    assert config.server.port == 8090
    assert config.sandbox.network_disabled is True

    with pytest.raises(ValidationError):
        config.server = config.server.model_copy(update={"port": 9000})


def test_tracked_shared_template_is_accepted():
    config = load_config(shared_path=ROOT / "final" / "config" / "config.yaml")

    assert config.server.port == 8090
    assert config.llm.api_key.get_secret_value() == ""
    assert config.postgres.password.get_secret_value() == ""


def test_load_config_merges_layers_in_documented_order(tmp_path):
    shared = tmp_path / "config.yaml"
    local = tmp_path / "config.local.yaml"
    shared.write_text(
        """
llm:
  api_key: shared-key
  model: shared-model
rag:
  top_k: 3
  rewrite:
    enabled: true
    num_queries: 2
server:
  port: 8100
elasticsearch:
  addresses: [http://one:9200, http://two:9200]
""",
        encoding="utf-8",
    )
    local.write_text(
        """
llm:
  api_key: local-key
rag:
  rewrite:
    enabled: false
elasticsearch:
  addresses: [http://local:9200]
""",
        encoding="utf-8",
    )

    config = load_config(
        shared_path=shared,
        local_path=local,
        environ={
            "VENAGENT_LLM__MODEL": "env-model",
            "VENAGENT_SERVER__PORT": "8200",
            "VENAGENT_RAG__REWRITE__NUM_QUERIES": "5",
        },
        cli_overrides={"server.port": 8300, "rag.top_k": 9},
    )

    assert config.llm.api_key.get_secret_value() == "local-key"
    assert config.llm.model == "env-model"
    assert config.rag.top_k == 9
    assert config.rag.rewrite.enabled is False
    assert config.rag.rewrite.num_queries == 5
    assert config.server.port == 8300
    assert config.elasticsearch.addresses == ("http://local:9200",)


def test_environment_variables_are_whitelisted_and_parse_types(tmp_path):
    config = load_config(
        shared_path=tmp_path / "missing.yaml",
        environ={
            "VENAGENT_RAG__TOP_K": "8",
            "VENAGENT_SANDBOX__ENABLED": "false",
            "VENAGENT_SERVER__CORS_ORIGINS": '["https://example.test"]',
            "VENAGENT_UNKNOWN__FIELD": "must-be-ignored",
        },
    )

    assert config.rag.top_k == 8
    assert config.sandbox.enabled is False
    assert config.server.cors_origins == ("https://example.test",)
    assert not hasattr(config, "unknown")


def test_unknown_yaml_fields_fail_fast(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("llm:\n  api_keey: typo\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="llm.api_keey"):
        load_config(shared_path=config_path)


def test_type_errors_fail_fast_without_echoing_secret_values(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "postgres:\n  password: 123456\n  port: invalid\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as error:
        load_config(shared_path=config_path)

    assert "postgres.password" in str(error.value)
    assert "123456-secret" not in str(error.value)


def test_invalid_rag_window_is_rejected(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "rag:\n  chunk_size: 100\n  chunk_overlap: 100\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="chunk_overlap"):
        load_config(shared_path=config_path)


def test_unknown_cli_override_fails_fast(tmp_path):
    with pytest.raises(ConfigError, match="server.unknown"):
        load_config(
            shared_path=tmp_path / "missing.yaml",
            cli_overrides={"server.unknown": "value"},
        )


def test_redact_config_removes_secret_values_without_mutating_config():
    config = AppConfig.model_validate(
        {
            "llm": {"api_key": "llm-secret"},
            "postgres": {"password": "db-secret"},
            "search": {"api_key": "search-secret"},
        }
    )

    redacted = redact_config(config)

    assert redacted["llm"]["api_key"] == "[REDACTED]"
    assert redacted["postgres"]["password"] == "[REDACTED]"
    assert redacted["search"]["api_key"] == "[REDACTED]"
    assert config.llm.api_key.get_secret_value() == "llm-secret"
    assert "llm-secret" not in repr(config)
    assert "llm-secret" not in str(config.model_dump())


def test_redact_mapping_covers_secret_like_keys_not_in_the_model():
    redacted = redact_config(
        {
            "safe": "visible",
            "custom_token": "custom-secret",
            "nested": {"client_secret": "another-secret"},
        }
    )

    assert redacted == {
        "safe": "visible",
        "custom_token": "[REDACTED]",
        "nested": {"client_secret": "[REDACTED]"},
    }


def test_field_secret_metadata_drives_redaction_for_nonstandard_names():
    class CredentialConfig(BaseModel):
        model_config = ConfigDict(frozen=True)

        credential: PydanticSecretStr = Field(
            default=PydanticSecretStr(""),
            json_schema_extra={"secret": True},
        )

    redacted = redact_config(CredentialConfig(credential="custom-secret"))

    assert redacted == {"credential": "[REDACTED]"}


def test_default_resolution_uses_explicit_project_root(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "server:\n  port: 8765\n",
        encoding="utf-8",
    )

    config = load_config(environ={"AGI_PROJECT_ROOT": str(tmp_path)})

    assert config.server.port == 8765
