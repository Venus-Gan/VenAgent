from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from venagent.infrastructure.config import load_config


def test_dotenv_values_enter_whitelisted_config_layer_with_process_override(tmp_path):
    shared = tmp_path / "config.yaml"
    shared.write_text(
        "llm:\n  model: yaml-model\nserver:\n  port: 8100\n",
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text(
        "VENAGENT_LLM__MODEL=dotenv-model\n"
        "VENAGENT_LLM__API_KEY=dotenv-secret\n"
        "VENAGENT_SERVER__PORT=8200\n"
        "VENAGENT_UNKNOWN__FIELD=ignored\n",
        encoding="utf-8",
    )

    config = load_config(
        shared_path=shared,
        env_file=env_file,
        environ={"VENAGENT_LLM__MODEL": "process-model"},
    )

    assert config.llm.model == "process-model"
    assert config.llm.api_key.get_secret_value() == "dotenv-secret"
    assert config.server.port == 8200
    assert not hasattr(config, "unknown")
    assert "dotenv-secret" not in repr(config)


def test_dotenv_file_errors_are_safe_and_fail_fast(tmp_path):
    with pytest.raises(ValueError, match="cannot read environment file"):
        load_config(
            shared_path=tmp_path / "config.yaml",
            env_file=tmp_path / ".env.missing",
        )


def test_legacy_main_loads_dotenv_into_api_config(monkeypatch, tmp_path):
    import main

    project_root = tmp_path / "final"
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text(
        "llm:\n  model: yaml-model\nserver:\n  port: 8100\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "VENAGENT_LLM__MODEL=dotenv-model\nVENAGENT_SERVER__PORT=8200\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "PROJECT_ROOT", str(project_root))

    config = main.default_config()

    assert config.llm_model == "dotenv-model"
    assert config.server_port == "8200"


def test_process_environment_overrides_dotenv_for_legacy_main(monkeypatch, tmp_path):
    import main

    project_root = tmp_path / "final"
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text("llm:\n  model: yaml-model\n", encoding="utf-8")
    (tmp_path / ".env").write_text(
        "VENAGENT_LLM__MODEL=dotenv-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VENAGENT_LLM__MODEL", "process-model")
    monkeypatch.setattr(main, "PROJECT_ROOT", str(project_root))

    config = main.default_config()

    assert config.llm_model == "process-model"


def test_legacy_main_preserves_agi_config_path_selection(monkeypatch, tmp_path):
    import main

    selected = tmp_path / "selected.yaml"
    selected.write_text("llm:\n  model: selected-model\n", encoding="utf-8")
    monkeypatch.setenv("AGI_CONFIG", str(selected))

    config = main.default_config()

    assert config.llm_model == "selected-model"
