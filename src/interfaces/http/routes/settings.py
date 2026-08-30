"""设置 HTTP routes：LLM 连接配置读写（config.yaml 为唯一文件源）。

D5/D6/D9：界面只做 LLM 连接（provider/key/model/URL + 协议 + 思考强度）；
GET 掩码敏感字段（只回 configured 布尔）；PUT 全量校验后原子写盘，
敏感空值保持现有；owner 可写、guest 403。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from ....config import AppConfig, ConfigError, load_config
from ....config.loader import CONFIG_FILENAME, get_runtime_config
from ....ownership.errors import AccountRequired
from ....ownership.service import OwnershipService
from ..auth import current_actor, require_origin
from ..errors import ApiError, ownership_api_error

# D9 思考强度集中映射表：UI 三档 → provider 原生参数。
THINKING_BUDGETS = {"low": 4096, "medium": 16384, "high": 32768}
REASONING_EFFORT_LEVELS = {"low": "minimal", "medium": "medium", "high": "high"}
THINKING_LEVELS = {"none", "low", "medium", "high"}

# 设置界面支持的协议三选一：Anthropic 原生 / OpenAI Responses / Chat Completions。
SUPPORTED_UI_PROVIDERS = {"anthropic", "openai", "openai_compatible"}
SUPPORTED_API_MODES = {"chat_completions", "responses"}

# Anthropic thinking 需要 max_tokens 预留输出空间；budget 本身按 D9 表映射。
_THINKING_TYPE = "enabled"


class SettingsError(ValueError):
    """设置请求不合法；不含秘密值。"""


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SettingsLlmRequest(_ApiModel):
    provider: str
    api_key: str = ""
    model: str
    base_url: str | None = None
    api_mode: str | None = None
    thinking_level: str = "none"

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        if value not in SUPPORTED_UI_PROVIDERS:
            raise ValueError("provider 必须为 anthropic、openai 或 openai_compatible")
        return value

    @field_validator("api_mode")
    @classmethod
    def validate_api_mode(cls, value: str | None) -> str | None:
        if value is not None and value not in SUPPORTED_API_MODES:
            raise ValueError("api_mode 必须为 chat_completions 或 responses")
        return value

    @field_validator("thinking_level")
    @classmethod
    def validate_thinking_level(cls, value: str) -> str:
        if value not in THINKING_LEVELS:
            raise ValueError("thinking_level 必须为 none、low、medium 或 high")
        return value


class LlmSettingsResponse(_ApiModel):
    provider: str
    model: str
    base_url: str | None = None
    api_mode: str | None = None
    api_key_configured: bool
    thinking_level: str


class SettingsResponse(_ApiModel):
    llm: LlmSettingsResponse


def _apply_thinking(
    llm: dict[str, object],
    *,
    provider: str,
    api_mode: str | None,
    thinking_level: str,
) -> None:
    """D9：按 provider 把 UI 三档写入原生参数；协议不支持时明确拒绝。"""
    if provider == "anthropic":
        # Anthropic 原生 adapter 通过 extra_body.thinking 传递 extended thinking。
        llm["reasoning_effort"] = None
        extra = dict(llm.get("extra_body") or {})
        if thinking_level == "none":
            extra.pop("thinking", None)
        else:
            extra["thinking"] = {
                "type": _THINKING_TYPE,
                "budget_tokens": THINKING_BUDGETS[thinking_level],
            }
        llm["extra_body"] = extra or None
        return
    # OpenAI 系：Responses 协议支持 reasoning_effort；Chat Completions 无思考。
    extra = dict(llm.get("extra_body") or {})
    extra.pop("thinking", None)
    llm["extra_body"] = extra or None
    if thinking_level == "none":
        llm["reasoning_effort"] = None
        return
    if api_mode != "responses":
        raise SettingsError(
            "chat_completions 协议不支持思考强度，请改用 responses 或 anthropic"
        )
    llm["reasoning_effort"] = REASONING_EFFORT_LEVELS[thinking_level]


def _merged_llm(current: AppConfig, request: SettingsLlmRequest) -> dict[str, object]:
    """把界面字段合并进现有 llm 区块；api_key 空保持现有，其余字段覆盖。"""
    llm = _plain(current.llm.model_dump())
    llm["provider"] = request.provider
    llm["model"] = request.model
    if request.api_key:
        llm["api_key"] = request.api_key
    llm["base_url"] = request.base_url or None
    if request.provider != current.llm.provider:
        # provider 切换时清除不兼容字段，避免残留配置触发 strict 校验失败。
        for key in (
            "azure_endpoint",
            "azure_deployment",
            "api_version",
            "endpoint_url",
        ):
            llm.pop(key, None)
    if request.provider == "anthropic":
        # strict 模型不允许 None；api_mode 仅对 OpenAI 系生效，Anthropic 装配会忽略它。
        llm["api_mode"] = "chat_completions"
    else:
        llm["api_mode"] = request.api_mode or "chat_completions"
    _apply_thinking(
        llm,
        provider=request.provider,
        api_mode=llm["api_mode"],
        thinking_level=request.thinking_level,
    )
    return llm


def _load_current(project_root: Path) -> AppConfig:
    try:
        return load_config(project_root=project_root)
    except ConfigError as exc:
        raise ApiError(400, "settings_invalid", str(exc)) from None


def _plain(value: object) -> object:
    """把 SecretStr 展开为真实值（pydantic 2.11+ 的 model_dump 会掩码为 ****）。"""
    from pydantic import SecretStr

    if isinstance(value, SecretStr):
        return value.get_secret_value()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _write_config(updated: AppConfig, project_root: Path) -> None:
    """AppConfig 全量校验后原子写盘（临时文件 + rename）；写后失效缓存。"""
    payload = _plain(updated.model_dump())
    path = project_root / CONFIG_FILENAME
    fd, temp_path = tempfile.mkstemp(
        dir=project_root, prefix=".config.yaml.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
    get_runtime_config.cache_clear()


def _settings_response(config: AppConfig) -> SettingsResponse:
    llm = config.llm
    thinking_level = _detect_thinking_level(llm)
    return SettingsResponse(
        llm=LlmSettingsResponse(
            provider=llm.provider,
            model=llm.model,
            base_url=llm.base_url,
            api_mode=llm.api_mode,
            api_key_configured=bool(llm.api_key.get_secret_value()),
            thinking_level=thinking_level,
        )
    )


def _detect_thinking_level(llm) -> str:
    """从原生参数反解 UI 三档；无法识别视为 none。"""
    if llm.reasoning_effort:
        for level, native in REASONING_EFFORT_LEVELS.items():
            if llm.reasoning_effort == native:
                return level
        return "none"
    extra = llm.extra_body or {}
    thinking = extra.get("thinking")
    if isinstance(thinking, dict):
        budget = thinking.get("budget_tokens")
        for level, value in THINKING_BUDGETS.items():
            if budget == value:
                return level
    return "none"


def register_settings_routes(
    app: FastAPI,
    ownership: OwnershipService,
    config: AppConfig,
    *,
    project_root: Path | None = None,
) -> None:
    root = project_root or Path.cwd()

    @app.get("/api/settings", response_model=SettingsResponse)
    def get_settings(request: Request) -> SettingsResponse:
        current_actor(request, ownership)
        return _settings_response(_load_current(root))

    @app.put("/api/settings", response_model=SettingsResponse)
    def put_settings(
        payload: SettingsLlmRequest, request: Request
    ) -> SettingsResponse:
        require_origin(request, config)
        actor = current_actor(request, ownership)
        if actor.kind != "user":
            raise ownership_api_error(AccountRequired())
        current = _load_current(root)
        try:
            merged = {**_plain(current.model_dump()), "llm": _merged_llm(current, payload)}
            updated = AppConfig.model_validate(merged)
        except ValidationError as exc:
            fields = ", ".join(
                ".".join(map(str, item["loc"])) for item in exc.errors()
            )
            raise ApiError(400, "settings_invalid", f"配置无效：{fields}") from None
        except SettingsError as exc:
            raise ApiError(400, "settings_invalid", str(exc)) from None
        try:
            _write_config(updated, root)
        except OSError as exc:
            raise ApiError(500, "settings_write_failed", "配置写盘失败") from exc
        return _settings_response(updated)
