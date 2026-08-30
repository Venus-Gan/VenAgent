"""settings 路由：GET 掩码、PUT 原子写盘、思考强度映射、guest 403（D5/D6/D9）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.config import load_config
from src.interfaces.http.app import create_app
from src.ownership.models import Actor

ORIGIN = {"Origin": "http://localhost:5173"}
AUTH_ORIGIN = {"Origin": "http://localhost:5173", "Authorization": "Bearer test-token"}


class UserOwnership:
    """固定返回 user actor 的 stub，绕过真实账号体系测试写路径。"""

    def resolve_access(self, _token: str) -> Actor:
        return Actor(kind="user", owner_id="owner-1", session_id="s-1", mode="durable")


class GuestOwnership:
    def resolve_access(self, _token: str) -> Actor:
        return Actor(kind="guest", owner_id="guest-1", session_id="s-2", mode="temporary")


def _write_example(path: Path) -> None:
    (path / "config.example.yaml").write_text(
        yaml.safe_dump({"server": {"port": 8090}}), encoding="utf-8"
    )


def _app(tmp_path: Path, ownership: object) -> FastAPI:
    _write_example(tmp_path)
    config = load_config(project_root=tmp_path, environ={})
    return create_app(
        config=config,
        ownership_service=ownership,
        persistence_runtime=build_temporary_runtime(),
    )


def build_temporary_runtime():
    from src.platform.runtime import build_persistence_runtime

    return build_persistence_runtime({})


def _put(client: TestClient, payload: dict) -> TestClient:
    return client.put("/api/settings", headers=AUTH_ORIGIN, json=payload)


def test_get_returns_masked_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {"llm": {"provider": "openai", "api_key": "sk-super-secret", "model": "gpt-4o"}}
        ),
        encoding="utf-8",
    )

    with TestClient(_app(tmp_path, UserOwnership())) as client:
        response = client.get("/api/settings", headers=AUTH_ORIGIN)

    assert response.status_code == 200
    body = response.json()["llm"]
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-4o"
    assert body["api_key_configured"] is True
    assert "sk-super-secret" not in response.text


def test_get_without_identity_is_401(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with TestClient(_app(tmp_path, UserOwnership())) as client:
        response = client.get("/api/settings")

    assert response.status_code == 401


def test_guest_cannot_write_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with TestClient(_app(tmp_path, GuestOwnership())) as client:
        response = _put(
            client,
            {"provider": "openai", "model": "gpt-4o", "thinking_level": "none"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_required"


def test_put_writes_config_yaml_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with TestClient(_app(tmp_path, UserOwnership())) as client:
        response = _put(
            client,
            {
                "provider": "openai",
                "api_key": "sk-new-key",
                "model": "gpt-4o-mini",
                "base_url": "https://api.example.invalid/v1",
                "api_mode": "responses",
                "thinking_level": "medium",
            },
        )

    assert response.status_code == 200
    stored = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert stored["llm"]["provider"] == "openai"
    assert stored["llm"]["api_key"] == "sk-new-key"
    assert stored["llm"]["model"] == "gpt-4o-mini"
    assert stored["llm"]["base_url"] == "https://api.example.invalid/v1"
    assert stored["llm"]["api_mode"] == "responses"
    assert stored["llm"]["reasoning_effort"] == "medium"
    # 临时文件必须已清理
    assert list(tmp_path.glob(".config.yaml.*.tmp")) == []


def test_put_blank_api_key_keeps_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {"llm": {"provider": "openai", "api_key": "existing-key", "model": "old"}}
        ),
        encoding="utf-8",
    )
    with TestClient(_app(tmp_path, UserOwnership())) as client:
        response = _put(
            client,
            {"provider": "openai", "api_key": "", "model": "new-model", "thinking_level": "none"},
        )

    assert response.status_code == 200
    stored = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert stored["llm"]["api_key"] == "existing-key"
    assert stored["llm"]["model"] == "new-model"


def test_put_anthropic_thinking_maps_to_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with TestClient(_app(tmp_path, UserOwnership())) as client:
        response = _put(
            client,
            {
                "provider": "anthropic",
                "api_key": "sk-ant",
                "model": "claude",
                "thinking_level": "high",
            },
        )

    assert response.status_code == 200
    stored = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert stored["llm"]["extra_body"]["thinking"] == {
        "type": "enabled",
        "budget_tokens": 32768,
    }
    assert "reasoning_effort" not in stored["llm"] or stored["llm"]["reasoning_effort"] is None


def test_put_anthropic_thinking_none_clears_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "llm": {
                    "provider": "anthropic",
                    "api_key": "sk-ant",
                    "model": "claude",
                    "extra_body": {
                        "thinking": {"type": "enabled", "budget_tokens": 32768}
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    with TestClient(_app(tmp_path, UserOwnership())) as client:
        response = _put(
            client,
            {
                "provider": "anthropic",
                "api_key": "",
                "model": "claude",
                "thinking_level": "none",
            },
        )

    assert response.status_code == 200
    stored = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert stored["llm"]["extra_body"] is None


def test_put_completions_with_thinking_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with TestClient(_app(tmp_path, UserOwnership())) as client:
        response = _put(
            client,
            {
                "provider": "openai",
                "api_key": "sk",
                "model": "gpt-4o",
                "api_mode": "chat_completions",
                "thinking_level": "medium",
            },
        )

    assert response.status_code == 400
    assert "chat_completions" in response.json()["error"]["message"]


def test_put_unknown_provider_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with TestClient(_app(tmp_path, UserOwnership())) as client:
        response = _put(
            client,
            {"provider": "azure_openai", "api_key": "sk", "model": "m"},
        )

    assert response.status_code == 422


def test_put_invalid_thinking_level_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with TestClient(_app(tmp_path, UserOwnership())) as client:
        response = _put(
            client,
            {"provider": "openai", "api_key": "sk", "model": "m", "thinking_level": "extreme"},
        )

    assert response.status_code == 422


def test_put_refreshes_round_trip_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with TestClient(_app(tmp_path, UserOwnership())) as client:
        response = _put(
            client,
            {
                "provider": "openai_compatible",
                "api_key": "sk-x",
                "model": "local",
                "base_url": "https://llm.example.invalid/v1",
                "api_mode": "responses",
                "thinking_level": "low",
            },
        )

    assert response.status_code == 200
    llm = response.json()["llm"]
    assert llm["provider"] == "openai_compatible"
    assert llm["api_mode"] == "responses"
    assert llm["thinking_level"] == "low"
    assert llm["api_key_configured"] is True
