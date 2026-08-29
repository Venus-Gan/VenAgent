"""按严格配置选择 LLM adapter 并构造 Agent runtime。"""

from collections.abc import Mapping

from ..agent.ports import MessageInvoker
from ..agent.runtime import build_local_model
from ..config.loader import AppConfig, load_config
from .config import (
    PROVIDER,
    LLMConfigurationError,
    ModelFactoryRegistry,
    settings_from_config,
    settings_from_environment,
)
from .providers import default_model_factories, model_factory_kwargs


def build_runtime_model(
    config: AppConfig | Mapping[str, str] | None = None,
    model_factories: ModelFactoryRegistry | None = None,
) -> MessageInvoker:
    # 先确定 provider，再由 registry 选择对应 adapter；不根据模型名称猜测厂商。
    # 这样业务层只依赖统一的 MessageInvoker，不感知 OpenAI、Azure、Anthropic 或 Gemini。
    if isinstance(config, AppConfig):
        settings = settings_from_config(config.llm)
    elif config is None:
        settings = settings_from_config(load_config().llm)
    else:
        # Mapping 是无文件测试入口，不能被本机 config.yaml 或进程环境污染。
        settings = settings_from_environment(config)
    if settings is None:
        # 没有完整真实模型配置时使用离线模型，避免未配置状态触发网络请求。
        return build_local_model()
    registry = model_factories or default_model_factories()
    factory = registry.get(settings.provider)
    if factory is None:
        raise LLMConfigurationError(f"{PROVIDER}={settings.provider} 缺少模型 adapter")
    try:
        model = factory(**model_factory_kwargs(settings))
    except Exception:
        raise LLMConfigurationError(
            f"无法装配 {settings.provider} 模型 adapter"
        ) from None
    return model


def build_memory_extractor_model(
    config: AppConfig,
    main_model: MessageInvoker,
    model_factories: ModelFactoryRegistry | None = None,
) -> MessageInvoker:
    """复用对话模型，或从已校验的 extractor override 构造独立模型。"""
    if not config.memory_extractor.configured:
        return main_model
    extractor_config = config.model_copy(
        update={"llm": config.memory_extractor.as_llm_config(config.llm)}
    )
    return build_runtime_model(extractor_config, model_factories)
