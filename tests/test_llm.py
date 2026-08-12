import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from venagent.config import load_config
from venagent.llm.config import (
    ANTHROPIC,
    AZURE_OPENAI,
    GOOGLE_GENAI,
    OPENAI,
    OPENAI_COMPATIBLE,
    LLMConfigurationError,
    settings_from_environment,
)
from venagent.llm.factory import build_memory_extractor_model, build_runtime_model
from venagent.llm.providers import default_model_factories, model_factory_kwargs


class RecordingModel:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def invoke(self, messages):
        return AIMessage(content="真实模型适配器回复")


def complete_environment(provider: str = OPENAI_COMPATIBLE) -> dict[str, str]:
    environment = {
        "LLM_PROVIDER": provider,
        "LLM_API_KEY": "test-only-value",
        "LLM_MODEL": "test-model",
    }
    if provider == OPENAI_COMPATIBLE:
        environment["LLM_BASE_URL"] = "https://provider.invalid/v1"
    elif provider == AZURE_OPENAI:
        environment.update(
            {
                "LLM_AZURE_ENDPOINT": "https://example.openai.azure.com/",
                "LLM_AZURE_DEPLOYMENT": "test-deployment",
                "LLM_API_VERSION": "2025-01-01-preview",
            }
        )
    return environment


def recording_registry(created: list[tuple[str, RecordingModel]]):
    def factory(provider):
        def create(**kwargs):
            model = RecordingModel(**kwargs)
            created.append((provider, model))
            return model

        return create

    return {
        provider: factory(provider)
        for provider in (
            OPENAI,
            OPENAI_COMPATIBLE,
            AZURE_OPENAI,
            ANTHROPIC,
            GOOGLE_GENAI,
        )
    }


def test_empty_environment_uses_offline_local_model():
    model = build_runtime_model({"LLM_MODEL": "   "})

    assert model.invoke([HumanMessage(content="你好")]).text == "我收到了：你好"


def test_memory_extractor_factory_uses_model_only_override(tmp_path: Path) -> None:
    config = load_config(
        environ={
            **complete_environment(),
            "MEMORY_EXTRACTOR_MODEL": "extractor-model",
        },
        project_root=tmp_path,
    )
    created: list[tuple[str, RecordingModel]] = []
    main = RecordingModel(model="chat-model")

    extractor = build_memory_extractor_model(
        config,
        main,
        model_factories=recording_registry(created),
    )

    assert extractor is created[0][1]
    assert created[0][1].kwargs["model"] == "extractor-model"
    assert created[0][1].kwargs["api_key"] == "test-only-value"


def test_explicit_mapping_does_not_read_project_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "LLM_PROVIDER=openai_compatible\nLLM_BASE_URL=https://local.invalid/v1\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    created = []

    model = build_runtime_model(
        complete_environment(ANTHROPIC),
        model_factories=recording_registry(created),
    )

    assert model.invoke([HumanMessage(content="你好")]).text == "真实模型适配器回复"
    assert created[0][0] == ANTHROPIC


@pytest.mark.parametrize(
    "environment,missing_key",
    [
        ({"LLM_MODEL": "test-model"}, "LLM_PROVIDER"),
        (
            {
                "LLM_PROVIDER": OPENAI,
                "LLM_MODEL": "test-model",
            },
            "LLM_API_KEY",
        ),
        (
            {
                "LLM_PROVIDER": OPENAI,
                "LLM_API_KEY": "test-only-value",
            },
            "LLM_MODEL",
        ),
    ],
)
def test_partial_environment_fails_fast(environment, missing_key):
    with pytest.raises(LLMConfigurationError, match=missing_key):
        settings_from_environment(environment)


def test_unknown_namespaced_field_is_rejected():
    environment = complete_environment()
    environment["LLM_TEMPRATURE"] = "0.5"

    with pytest.raises(LLMConfigurationError, match="TEMPRATURE"):
        settings_from_environment(environment)


@pytest.mark.parametrize(
    "provider",
    [OPENAI, OPENAI_COMPATIBLE, AZURE_OPENAI, ANTHROPIC, GOOGLE_GENAI],
)
def test_provider_registry_selects_native_factory_without_network(provider):
    created = []
    model = build_runtime_model(
        complete_environment(provider),
        model_factories=recording_registry(created),
    )

    assert model.invoke([HumanMessage(content="你好")]).text == "真实模型适配器回复"
    assert created[0][0] == provider


def test_openai_compatible_maps_all_typed_parameters():
    environment = complete_environment()
    environment.update(
        {
            "LLM_API_MODE": "responses",
            "LLM_REASONING_EFFORT": "high",
            "LLM_TEMPERATURE": "0.25",
            "LLM_MAX_TOKENS": "2048",
            "LLM_TIMEOUT": "45.5",
            "LLM_MAX_RETRIES": "4",
            "LLM_VERBOSITY": "medium",
            "LLM_EXTRA_BODY_JSON": '{"thinking":{"type":"enabled"}}',
        }
    )

    settings = settings_from_environment(environment)

    assert settings is not None
    assert model_factory_kwargs(settings) == {
        "model": "test-model",
        "api_key": "test-only-value",
        "base_url": "https://provider.invalid/v1",
        "default_headers": {"User-Agent": "VenAgent/0.1"},
        "streaming": True,
        "use_responses_api": True,
        "reasoning_effort": "high",
        "temperature": 0.25,
        "max_tokens": 2048,
        "request_timeout": 45.5,
        "max_retries": 4,
        "verbosity": "medium",
        "extra_body": {"thinking": {"type": "enabled"}},
    }


def test_unset_optional_parameters_are_not_sent():
    settings = settings_from_environment(complete_environment())

    assert settings is not None
    assert model_factory_kwargs(settings) == {
        "model": "test-model",
        "api_key": "test-only-value",
        "base_url": "https://provider.invalid/v1",
        "default_headers": {"User-Agent": "VenAgent/0.1"},
        "use_responses_api": False,
    }


@pytest.mark.parametrize(
    "mode,endpoint,expected_root",
    [
        (
            "chat_completions",
            "https://provider.invalid/api/v4/chat/completions/",
            "https://provider.invalid/api/v4",
        ),
        (
            "responses",
            "https://provider.invalid/v1/responses",
            "https://provider.invalid/v1",
        ),
    ],
)
def test_full_endpoint_is_normalized_to_matching_api_root(
    mode,
    endpoint,
    expected_root,
):
    environment = complete_environment()
    environment.pop("LLM_BASE_URL")
    environment["LLM_API_MODE"] = mode
    environment["LLM_ENDPOINT_URL"] = endpoint

    settings = settings_from_environment(environment)

    assert settings is not None
    assert settings.base_url == expected_root


def test_endpoint_must_match_api_mode():
    environment = complete_environment()
    environment.pop("LLM_BASE_URL")
    environment["LLM_API_MODE"] = "responses"
    environment["LLM_ENDPOINT_URL"] = "https://provider.invalid/v1/chat/completions"

    with pytest.raises(LLMConfigurationError, match="API_MODE"):
        settings_from_environment(environment)


def test_root_and_endpoint_are_mutually_exclusive():
    environment = complete_environment()
    environment["LLM_ENDPOINT_URL"] = "https://provider.invalid/v1/chat/completions"

    with pytest.raises(LLMConfigurationError, match="不能同时配置"):
        settings_from_environment(environment)


@pytest.mark.parametrize(
    "url",
    [
        "provider.invalid/v1",
        "ftp://provider.invalid/v1",
        "https://user:pass@provider.invalid/v1",
        "https://provider.invalid/v1?token=value",
        "https://provider.invalid/v1#fragment",
    ],
)
def test_invalid_or_credential_bearing_url_is_rejected(url):
    environment = complete_environment()
    environment["LLM_BASE_URL"] = url

    with pytest.raises(LLMConfigurationError, match="BASE_URL"):
        settings_from_environment(environment)


def test_openai_official_does_not_require_a_custom_url():
    settings = settings_from_environment(complete_environment(OPENAI))

    assert settings is not None
    assert settings.base_url is None


def test_azure_uses_native_adapter_parameters():
    settings = settings_from_environment(complete_environment(AZURE_OPENAI))

    assert settings is not None
    assert model_factory_kwargs(settings) == {
        "model": "test-model",
        "api_key": "test-only-value",
        "azure_endpoint": "https://example.openai.azure.com",
        "azure_deployment": "test-deployment",
        "api_version": "2025-01-01-preview",
    }


@pytest.mark.parametrize("provider", [ANTHROPIC, GOOGLE_GENAI])
@pytest.mark.parametrize(
    "key,value",
    [
        ("LLM_REASONING_EFFORT", "high"),
        ("LLM_VERBOSITY", "high"),
    ],
)
def test_native_non_openai_provider_rejects_unmapped_typed_parameters(
    provider,
    key,
    value,
):
    environment = complete_environment(provider)
    environment[key] = value

    with pytest.raises(LLMConfigurationError, match=key):
        settings_from_environment(environment)


def test_anthropic_receives_native_thinking_and_remaining_extensions():
    environment = complete_environment(ANTHROPIC)
    environment["LLM_EXTRA_BODY_JSON"] = (
        '{"thinking":{"type":"adaptive"},"custom_option":true}'
    )

    settings = settings_from_environment(environment)

    assert settings is not None
    kwargs = model_factory_kwargs(settings)
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["model_kwargs"] == {"custom_option": True}


def test_google_receives_native_thinking_and_remaining_extensions():
    environment = complete_environment(GOOGLE_GENAI)
    environment["LLM_EXTRA_BODY_JSON"] = (
        '{"thinking_config":{"thinking_budget":1024},"include_thoughts":true,"custom_option":true}'
    )

    settings = settings_from_environment(environment)

    assert settings is not None
    kwargs = model_factory_kwargs(settings)
    assert kwargs["thinking_config"] == {"thinking_budget": 1024}
    assert kwargs["include_thoughts"] is True
    assert kwargs["model_kwargs"] == {"custom_option": True}


@pytest.mark.parametrize(
    "raw",
    ["not-json", "[]", '"text"', "1", "null"],
)
def test_extra_body_requires_json_object(raw):
    environment = complete_environment()
    environment["LLM_EXTRA_BODY_JSON"] = raw

    with pytest.raises(LLMConfigurationError, match="JSON object"):
        settings_from_environment(environment)


@pytest.mark.parametrize("reserved", ["model", "messages", "Authorization"])
def test_extra_body_cannot_override_reserved_fields(reserved):
    environment = complete_environment()
    environment["LLM_EXTRA_BODY_JSON"] = json.dumps({reserved: "forbidden"})

    with pytest.raises(LLMConfigurationError, match="保留字段"):
        settings_from_environment(environment)


@pytest.mark.parametrize(
    "key,value",
    [
        ("LLM_TEMPERATURE", "nan"),
        ("LLM_TEMPERATURE", "2.1"),
        ("LLM_MAX_TOKENS", "0"),
        ("LLM_MAX_RETRIES", "-1"),
        ("LLM_TIMEOUT", "0"),
        ("LLM_VERBOSITY", "extreme"),
    ],
)
def test_invalid_typed_parameter_fails_fast(key, value):
    environment = complete_environment()
    environment[key] = value

    with pytest.raises(LLMConfigurationError, match=key):
        settings_from_environment(environment)


def test_configuration_errors_do_not_include_api_key_value():
    secret = "super-secret-test-value"
    environment = complete_environment()
    environment["LLM_API_KEY"] = secret
    environment["LLM_TEMPERATURE"] = "invalid"

    with pytest.raises(LLMConfigurationError) as captured:
        settings_from_environment(environment)

    assert secret not in str(captured.value)


def test_factory_failures_are_wrapped_without_secret_values():
    secret = "super-secret-test-value"
    environment = complete_environment()
    environment["LLM_API_KEY"] = secret

    def failing_factory(**kwargs):
        raise RuntimeError(f"failed with {kwargs['api_key']}")

    with pytest.raises(LLMConfigurationError) as captured:
        build_runtime_model(
            environment,
            model_factories={OPENAI_COMPATIBLE: failing_factory},
        )

    assert secret not in str(captured.value)


@pytest.mark.parametrize(
    "provider",
    [OPENAI, OPENAI_COMPATIBLE, AZURE_OPENAI, ANTHROPIC, GOOGLE_GENAI],
)
def test_default_provider_factories_construct_without_network(provider):
    settings = settings_from_environment(complete_environment(provider))

    assert settings is not None
    model = default_model_factories()[provider](**model_factory_kwargs(settings))
    assert model is not None


def test_example_environment_documents_llm_without_real_secret():
    example = Path(__file__).parents[1] / ".env.example"
    content = example.read_text(encoding="utf-8")

    assert "LLM_API_KEY=" in content
    assert "所有 LLM_* 留空时使用无网络本地模型" in content
    assert "config.yaml" not in content
    assert "sk-" not in content
