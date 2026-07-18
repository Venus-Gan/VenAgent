from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "final" / "config" / "config.yaml"
COMPOSE_PATH = ROOT / "final" / "docker-compose.yml"
GITIGNORE_PATH = ROOT / "final" / ".gitignore"


def test_tracked_config_contains_no_service_passwords():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["postgres"]["password"] == ""
    assert config["elasticsearch"]["password"] == ""
    assert config["neo4j"]["password"] == ""


def test_compose_requires_external_service_credentials():
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "${POSTGRES_PASSWORD:?" in compose
    assert "${MINIO_ACCESS_KEY:?" in compose
    assert "${MINIO_SECRET_KEY:?" in compose
    assert "${NEO4J_PASSWORD:?" in compose
    assert "aiagent123" not in compose
    assert "minioadmin" not in compose
    assert "password123" not in compose


def test_local_secret_files_are_ignored():
    gitignore = GITIGNORE_PATH.read_text(encoding="utf-8")

    assert "config/config.local.yaml" in gitignore
    assert ".env" in gitignore
    assert ".env.*" in gitignore
