"""LLM provider 参数映射与延迟 adapter factories。"""

from typing import Any

from ..agent.ports import MessageInvoker
from .config import (
    ANTHROPIC,
    AZURE_OPENAI,
    GOOGLE_GENAI,
    OPENAI,
    OPENAI_COMPATIBLE,
    RESPONSES,
    LLMConfigurationError,
    LLMSettings,
    ModelFactory,
)


def model_factory_kwargs(settings: LLMSettings) -> dict[str, Any]:
    # 先准备所有 adapter 共用的参数，下面再按 provider 映射到具体 SDK。
    common: dict[str, Any] = {"model": settings.model}
    _set_if_present(common, "temperature", settings.temperature)
    _set_if_present(common, "max_retries", settings.max_retries)
    if settings.provider in {OPENAI, OPENAI_COMPATIBLE}:
        # 两类 OpenAI-family provider 共用 ChatOpenAI；差异主要在 API root 和请求选项。
        kwargs = {
            **common,
            "api_key": settings.api_key,
            # langchain-openai 根据这个开关选择 Responses API 或 Chat Completions API。
            # base_url 仍然是 API root，endpoint 路径由 SDK 自动补上。
            "use_responses_api": settings.api_mode == RESPONSES,
        }
        if settings.provider == OPENAI_COMPATIBLE:
            # 第三方兼容服务沿用 OpenAI SDK，并附带稳定的客户端标识。
            kwargs["default_headers"] = {"User-Agent": "VenAgent/0.1"}
            if settings.api_mode == RESPONSES:
                # 兼容服务使用 Responses API 时，显式打开 SDK 的流式参数。
                kwargs["streaming"] = True
        for key, value in (
            # base_url、超时和模型参数统一交给 SDK，这里不手动拼接 URL。
            ("base_url", settings.base_url),
            ("max_tokens", settings.max_tokens),
            ("request_timeout", settings.timeout),
            ("reasoning_effort", settings.reasoning_effort),
            ("verbosity", settings.verbosity),
            ("extra_body", settings.extra_body),
        ):
            _set_if_present(kwargs, key, value)
        return kwargs
    if settings.provider == AZURE_OPENAI:
        # Azure 使用独立 adapter，因此 endpoint、deployment 和 API version 采用 Azure 参数名。
        kwargs = {
            **common,
            "api_key": settings.api_key,
            "azure_endpoint": settings.azure_endpoint,
            "azure_deployment": settings.azure_deployment,
            "api_version": settings.api_version,
        }
        for key, value in (
            ("max_tokens", settings.max_tokens),
            ("request_timeout", settings.timeout),
            ("reasoning_effort", settings.reasoning_effort),
            ("verbosity", settings.verbosity),
            ("extra_body", settings.extra_body),
        ):
            _set_if_present(kwargs, key, value)
        return kwargs
    if settings.provider == ANTHROPIC:
        # Anthropic adapter 使用原生 Messages API；thinking 等扩展从 extra_body 拆出。
        kwargs = {**common, "api_key": settings.api_key}
        _set_if_present(kwargs, "max_tokens", settings.max_tokens)
        _set_if_present(kwargs, "default_request_timeout", settings.timeout)
        extras = dict(settings.extra_body or {})
        _set_if_present(kwargs, "thinking", extras.pop("thinking", None))
        _set_if_present(kwargs, "model_kwargs", extras or None)
        return kwargs
    if settings.provider == GOOGLE_GENAI:
        # Gemini adapter 使用 google_api_key 和 Gemini 专用 thinking/输出参数。
        kwargs = {**common, "google_api_key": settings.api_key}
        _set_if_present(kwargs, "max_output_tokens", settings.max_tokens)
        _set_if_present(kwargs, "timeout", settings.timeout)
        extras = dict(settings.extra_body or {})
        for key in ("thinking_config", "thinking_budget", "include_thoughts"):
            _set_if_present(kwargs, key, extras.pop(key, None))
        _set_if_present(kwargs, "model_kwargs", extras or None)
        return kwargs
    raise LLMConfigurationError("LLM_PROVIDER 不支持该 provider")


def default_model_factories() -> dict[str, ModelFactory]:
    # 所有支持的 provider 到 LangChain adapter 的注册表。
    # provider 必须显式匹配；model 名称不会触发隐式换 adapter。
    return {
        OPENAI: _build_openai,
        OPENAI_COMPATIBLE: _build_openai,
        AZURE_OPENAI: _build_azure_openai,
        ANTHROPIC: _build_anthropic,
        GOOGLE_GENAI: _build_google_genai,
    }


def _build_openai(**kwargs: Any) -> MessageInvoker:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(**kwargs)


def _build_azure_openai(**kwargs: Any) -> MessageInvoker:
    from langchain_openai import AzureChatOpenAI

    return AzureChatOpenAI(**kwargs)


def _build_anthropic(**kwargs: Any) -> MessageInvoker:
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(**kwargs)


def _build_google_genai(**kwargs: Any) -> MessageInvoker:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(**kwargs)


def _set_if_present(target: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        target[key] = value
