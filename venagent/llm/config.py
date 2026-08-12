"""LLM 环境配置解析与严格校验。"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..agent.ports import MessageInvoker
from ..config.loader import LLMConfig

ENV_PREFIX = "LLM_"

PROVIDER = f"{ENV_PREFIX}PROVIDER"
API_KEY = f"{ENV_PREFIX}API_KEY"
MODEL = f"{ENV_PREFIX}MODEL"
BASE_URL = f"{ENV_PREFIX}BASE_URL"
ENDPOINT_URL = f"{ENV_PREFIX}ENDPOINT_URL"
API_MODE = f"{ENV_PREFIX}API_MODE"
AZURE_ENDPOINT = f"{ENV_PREFIX}AZURE_ENDPOINT"
AZURE_DEPLOYMENT = f"{ENV_PREFIX}AZURE_DEPLOYMENT"
API_VERSION = f"{ENV_PREFIX}API_VERSION"
REASONING_EFFORT = f"{ENV_PREFIX}REASONING_EFFORT"
TEMPERATURE = f"{ENV_PREFIX}TEMPERATURE"
MAX_TOKENS = f"{ENV_PREFIX}MAX_TOKENS"
TIMEOUT = f"{ENV_PREFIX}TIMEOUT"
MAX_RETRIES = f"{ENV_PREFIX}MAX_RETRIES"
VERBOSITY = f"{ENV_PREFIX}VERBOSITY"
EXTRA_BODY_JSON = f"{ENV_PREFIX}EXTRA_BODY_JSON"

OPENAI = "openai"
# 官方 OpenAI API，使用 langchain-openai 的 ChatOpenAI adapter。
OPENAI_COMPATIBLE = "openai_compatible"
# 第三方 OpenAI-compatible 服务共用 ChatOpenAI adapter，通过 base_url 指定 API root。
AZURE_OPENAI = "azure_openai"
# Azure OpenAI 使用独立的 AzureChatOpenAI adapter 和 deployment/version 字段。
ANTHROPIC = "anthropic"
# Anthropic 原生 Messages API 使用 ChatAnthropic adapter，不走 OpenAI URL 规则。
GOOGLE_GENAI = "google_genai"
# Google Gemini 原生 API 使用 ChatGoogleGenerativeAI adapter，不走 OpenAI URL 规则。

CHAT_COMPLETIONS = "chat_completions"
RESPONSES = "responses"

SUPPORTED_PROVIDERS = {
    OPENAI,
    OPENAI_COMPATIBLE,
    AZURE_OPENAI,
    ANTHROPIC,
    GOOGLE_GENAI,
}
# api_mode 表示 OpenAI-family SDK 采用的请求协议；它不要求配置完整 endpoint URL。
# 原生 Azure、Anthropic、Gemini adapter 不使用这个字段，校验层会拒绝该组合。
SUPPORTED_API_MODES = {CHAT_COMPLETIONS, RESPONSES}
SUPPORTED_VERBOSITY = {"low", "medium", "high"}

KNOWN_ENVIRONMENT_KEYS = {
    PROVIDER,
    API_KEY,
    MODEL,
    BASE_URL,
    ENDPOINT_URL,
    API_MODE,
    AZURE_ENDPOINT,
    AZURE_DEPLOYMENT,
    API_VERSION,
    REASONING_EFFORT,
    TEMPERATURE,
    MAX_TOKENS,
    TIMEOUT,
    MAX_RETRIES,
    VERBOSITY,
    EXTRA_BODY_JSON,
}

EXTRA_BODY_RESERVED_KEYS = {
    "api_key",
    "api_version",
    "authorization",
    "azure_deployment",
    "azure_endpoint",
    "base_url",
    "endpoint_url",
    "max_output_tokens",
    "max_retries",
    "max_tokens",
    "messages",
    "model",
    "provider",
    "reasoning_effort",
    "request_timeout",
    "stream",
    "temperature",
    "timeout",
    "use_responses_api",
    "verbosity",
}


class LLMConfigurationError(ValueError):
    """不包含凭据值的稳定 LLM 配置错误。"""


@dataclass(frozen=True)
class LLMSettings:
    """经过严格校验、可直接映射到 provider adapter 的配置。"""

    provider: str
    api_key: str
    model: str
    api_mode: str | None = None
    base_url: str | None = None
    azure_endpoint: str | None = None
    azure_deployment: str | None = None
    api_version: str | None = None
    reasoning_effort: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float | None = None
    max_retries: int | None = None
    verbosity: str | None = None
    extra_body: dict[str, Any] | None = None


ModelFactory = Callable[..., MessageInvoker]
ModelFactoryRegistry = Mapping[str, ModelFactory]


def settings_from_config(config: LLMConfig) -> LLMSettings | None:
    """把统一配置对象转换为既有 provider 校验输入，集中保留 adapter 规则。"""
    # .env 与显式环境最终收敛为同一组 LLM_* 语义，再做 provider 校验。
    values: dict[str, str] = {}
    mapping = {
        PROVIDER: config.provider,
        API_KEY: config.api_key.get_secret_value(),
        MODEL: config.model,
        API_MODE: config.api_mode,
        BASE_URL: config.base_url,
        ENDPOINT_URL: config.endpoint_url,
        AZURE_ENDPOINT: config.azure_endpoint,
        AZURE_DEPLOYMENT: config.azure_deployment,
        API_VERSION: config.api_version,
        REASONING_EFFORT: config.reasoning_effort,
        TEMPERATURE: config.temperature,
        MAX_TOKENS: config.max_tokens,
        TIMEOUT: config.timeout,
        MAX_RETRIES: config.max_retries,
        VERBOSITY: config.verbosity,
        EXTRA_BODY_JSON: json.dumps(config.extra_body)
        if config.extra_body is not None
        else None,
    }
    for key, value in mapping.items():
        # api_mode 只有真实 LLM 被配置时才算意图，避免默认值破坏离线模式。
        if value not in (None, "") and (
            key != API_MODE or config.provider in {OPENAI, OPENAI_COMPATIBLE}
        ):
            values[key] = str(value)
    return settings_from_environment(values)


def settings_from_environment(
    environment: Mapping[str, str] | None = None,
) -> LLMSettings | None:
    """解析配置；只有完全空配置才选择离线模型。"""
    source = environment if environment is not None else os.environ
    configured = _configured_values(source)
    if not configured:
        return None

    unknown = sorted(set(configured) - KNOWN_ENVIRONMENT_KEYS)
    if unknown:
        raise LLMConfigurationError(f"不支持的 LLM 配置字段：{unknown[0]}")

    provider = _required(configured, PROVIDER)
    if provider not in SUPPORTED_PROVIDERS:
        raise LLMConfigurationError(f"{PROVIDER} 不支持该 provider")

    api_key = _required(configured, API_KEY)
    model = _required(configured, MODEL)
    api_mode: str | None = None
    base_url: str | None = None
    azure_endpoint: str | None = None
    azure_deployment: str | None = None
    api_version: str | None = None

    if provider in {OPENAI, OPENAI_COMPATIBLE}:
        # OpenAI 与 OpenAI-compatible 都由 langchain-openai 装配。
        # 前者可省略自定义 API root，后者必须提供 base_url 或 endpoint_url。
        _forbid(configured, AZURE_ENDPOINT, AZURE_DEPLOYMENT, API_VERSION)
        # 未显式填写时使用 Chat Completions；Responses 需要由上游服务明确支持。
        api_mode = configured.get(API_MODE, CHAT_COMPLETIONS)
        if api_mode not in SUPPORTED_API_MODES:
            raise LLMConfigurationError(
                f"{API_MODE} 必须是 chat_completions 或 responses"
            )
        base_url = _openai_base_url(configured, api_mode, provider)
    elif provider == AZURE_OPENAI:
        # Azure 有自己的 endpoint/deployment/version 组合，不复用 OpenAI-family 的
        # base_url/api_mode 配置，避免把不同 adapter 的请求规则混在一起。
        _forbid(configured, BASE_URL, ENDPOINT_URL, API_MODE)
        azure_endpoint = _validated_url(
            AZURE_ENDPOINT,
            _required(configured, AZURE_ENDPOINT),
        )
        azure_deployment = _required(configured, AZURE_DEPLOYMENT)
        api_version = _required(configured, API_VERSION)
    else:
        # Anthropic 与 Gemini 走各自原生 adapter；它们的 provider-specific 扩展
        # 通过 extra_body 传递，不能套用 OpenAI 的 URL 或 api_mode 规则。
        _forbid(
            configured,
            BASE_URL,
            ENDPOINT_URL,
            API_MODE,
            AZURE_ENDPOINT,
            AZURE_DEPLOYMENT,
            API_VERSION,
        )

    reasoning_effort = configured.get(REASONING_EFFORT)
    verbosity = configured.get(VERBOSITY)
    if verbosity is not None and verbosity not in SUPPORTED_VERBOSITY:
        raise LLMConfigurationError(f"{VERBOSITY} 必须是 low、medium 或 high")
    if provider in {ANTHROPIC, GOOGLE_GENAI}:
        _forbid(configured, REASONING_EFFORT, VERBOSITY)

    return LLMSettings(
        provider=provider,
        api_key=api_key,
        model=model,
        api_mode=api_mode,
        base_url=base_url,
        azure_endpoint=azure_endpoint,
        azure_deployment=azure_deployment,
        api_version=api_version,
        reasoning_effort=reasoning_effort,
        temperature=_optional_float(configured, TEMPERATURE, minimum=0, maximum=2),
        max_tokens=_optional_int(configured, MAX_TOKENS, minimum=1),
        timeout=_optional_float(configured, TIMEOUT, minimum=0, exclusive_minimum=True),
        max_retries=_optional_int(configured, MAX_RETRIES, minimum=0),
        verbosity=verbosity,
        extra_body=_optional_json_object(configured),
    )


def _configured_values(source: Mapping[str, str]) -> dict[str, str]:
    configured: dict[str, str] = {}
    for key, raw_value in source.items():
        if not key.startswith(ENV_PREFIX):
            continue
        if not isinstance(raw_value, str):
            raise LLMConfigurationError(f"{key} 必须是字符串")
        value = raw_value.strip()
        if value:
            configured[key] = value
    return configured


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key)
    if value is None:
        raise LLMConfigurationError(f"缺少必需配置：{key}")
    return value


def _forbid(values: Mapping[str, str], *keys: str) -> None:
    for key in keys:
        if key in values:
            raise LLMConfigurationError(f"当前 provider 不支持配置：{key}")


def _openai_base_url(
    values: Mapping[str, str],
    api_mode: str,
    provider: str,
) -> str | None:
    # 此函数只处理 OpenAI 与 OpenAI-compatible 两类 adapter。SDK 需要 API root；
    # endpoint_url 是给需要填写完整 endpoint 的调用方提供的便利写法，下面会
    # 校验协议后去掉 /chat/completions 或 /responses 后缀。
    base = values.get(BASE_URL)
    endpoint = values.get(ENDPOINT_URL)
    if base is not None and endpoint is not None:
        # 两种表达方式只能选一种，避免 root 与 endpoint 互相覆盖。
        raise LLMConfigurationError(f"{BASE_URL} 与 {ENDPOINT_URL} 不能同时配置")
    if provider == OPENAI_COMPATIBLE and base is None and endpoint is None:
        raise LLMConfigurationError(
            f"{OPENAI_COMPATIBLE} 必须配置 {BASE_URL} 或 {ENDPOINT_URL}"
        )
    if base is not None:
        # base_url 已经是 SDK 所需的 root，由 SDK 自动拼接具体 API 路径。
        return _validated_url(BASE_URL, base)
    if endpoint is None:
        return None

    normalized = _validated_url(ENDPOINT_URL, endpoint)
    # endpoint_url 必须与 api_mode 对应；这里只做规范化，实际请求仍由 OpenAI SDK 发起。
    suffix = "/chat/completions" if api_mode == CHAT_COMPLETIONS else "/responses"
    parsed = urlsplit(normalized)
    if not parsed.path.endswith(suffix):
        raise LLMConfigurationError(f"{ENDPOINT_URL} 与 {API_MODE} 不匹配")
    root_path = parsed.path[: -len(suffix)].rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, root_path, "", ""))


def _validated_url(key: str, value: str) -> str:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        raise LLMConfigurationError(f"{key} 不是有效 URL") from None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LLMConfigurationError(f"{key} 必须是绝对 http/https URL")
    if parsed.username is not None or parsed.password is not None:
        raise LLMConfigurationError(f"{key} 不允许包含 userinfo")
    if parsed.query or parsed.fragment:
        raise LLMConfigurationError(f"{key} 不允许包含 query 或 fragment")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _optional_float(
    values: Mapping[str, str],
    key: str,
    *,
    minimum: float,
    maximum: float | None = None,
    exclusive_minimum: bool = False,
) -> float | None:
    raw = values.get(key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise LLMConfigurationError(f"{key} 必须是数字") from None
    if not math.isfinite(value):
        raise LLMConfigurationError(f"{key} 必须是有限数字")
    below = value <= minimum if exclusive_minimum else value < minimum
    if below or (maximum is not None and value > maximum):
        limit = f"{minimum}..{maximum}" if maximum is not None else f"> {minimum}"
        raise LLMConfigurationError(f"{key} 超出允许范围：{limit}")
    return value


def _optional_int(
    values: Mapping[str, str],
    key: str,
    *,
    minimum: int,
) -> int | None:
    raw = values.get(key)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise LLMConfigurationError(f"{key} 必须是整数") from None
    if value < minimum:
        raise LLMConfigurationError(f"{key} 必须大于等于 {minimum}")
    return value


def _optional_json_object(values: Mapping[str, str]) -> dict[str, Any] | None:
    raw = values.get(EXTRA_BODY_JSON)
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise LLMConfigurationError(
            f"{EXTRA_BODY_JSON} 必须是合法 JSON object"
        ) from None
    if not isinstance(parsed, dict):
        raise LLMConfigurationError(f"{EXTRA_BODY_JSON} 必须是 JSON object")
    conflict = next(
        (key for key in parsed if key.casefold() in EXTRA_BODY_RESERVED_KEYS),
        None,
    )
    if conflict is not None:
        raise LLMConfigurationError(f"{EXTRA_BODY_JSON} 包含保留字段：{conflict}")
    return parsed
