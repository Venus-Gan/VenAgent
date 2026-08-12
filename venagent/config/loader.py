"""严格环境配置加载：安全默认值 < .env < 显式进程环境。"""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlsplit

from dotenv import dotenv_values
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    model_validator,
)


class ConfigError(ValueError):
    """配置错误只暴露字段路径，绝不回显秘密值。"""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class LLMConfig(_StrictModel):
    provider: str = ""
    api_key: SecretStr = SecretStr("")
    model: str = ""
    api_mode: str = "chat_completions"
    base_url: str | None = None
    endpoint_url: str | None = None
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


class MemoryExtractorConfig(_StrictModel):
    """可选的结构化记忆 extractor profile。"""

    provider: str = ""
    api_key: SecretStr = SecretStr("")
    model: str = ""
    api_mode: str = "chat_completions"
    base_url: str | None = None
    endpoint_url: str | None = None
    azure_endpoint: str | None = None
    azure_deployment: str | None = None
    api_version: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float | None = None
    max_retries: int | None = None
    extra_body: dict[str, Any] | None = None

    @property
    def configured(self) -> bool:
        return any(
            (
                self.provider,
                self.api_key.get_secret_value(),
                self.model,
                self.base_url,
                self.endpoint_url,
                self.azure_endpoint,
                self.azure_deployment,
                self.api_version,
                self.temperature is not None,
                self.max_tokens is not None,
                self.timeout is not None,
                self.max_retries is not None,
                self.extra_body is not None,
            )
        )

    @property
    def independent(self) -> bool:
        """是否提供了超出 model-only 继承模式的独立连接配置。"""
        return any(
            (
                self.provider,
                self.api_key.get_secret_value(),
                self.base_url,
                self.endpoint_url,
                self.azure_endpoint,
                self.azure_deployment,
                self.api_version,
                self.temperature is not None,
                self.max_tokens is not None,
                self.timeout is not None,
                self.max_retries is not None,
                self.extra_body is not None,
            )
        )

    def as_llm_config(self, main: LLMConfig) -> LLMConfig:
        """解析为主模型复用或独立 profile，供 llm 层统一校验。"""
        if not self.configured:
            return main
        if not self.independent:
            return main.model_copy(update={"model": self.model})
        return LLMConfig(
            provider=self.provider,
            api_key=self.api_key,
            model=self.model,
            api_mode=self.api_mode,
            base_url=self.base_url,
            endpoint_url=self.endpoint_url,
            azure_endpoint=self.azure_endpoint,
            azure_deployment=self.azure_deployment,
            api_version=self.api_version,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            max_retries=self.max_retries,
            extra_body=self.extra_body,
        )

    @model_validator(mode="after")
    def _validate_profile(self) -> "MemoryExtractorConfig":
        if not self.configured:
            return self
        if not self.model:
            raise ValueError("memory_extractor.model")
        if self.independent and (not self.provider or not self.api_key.get_secret_value()):
            raise ValueError("memory_extractor requires provider and api_key")
        return self


class EmbeddingConfig(_StrictModel):
    """通用 embedding 技术配置；全空表示显式 disabled。"""

    api_url: str = ""
    api_key: SecretStr = SecretStr("")
    model: str = ""
    timeout: float = Field(default=10.0, gt=0, le=120)
    max_retries: int = Field(default=2, ge=0, le=10)

    @property
    def configured(self) -> bool:
        return bool(self.api_url or self.api_key.get_secret_value() or self.model)

    @property
    def enabled(self) -> bool:
        return bool(self.api_url and self.api_key.get_secret_value() and self.model)

    @model_validator(mode="after")
    def _validate_endpoint(self) -> "EmbeddingConfig":
        values = (self.api_url, self.api_key.get_secret_value(), self.model)
        if not any(values):
            return self
        if not all(values):
            raise ValueError("embedding requires api_url, api_key and model")
        try:
            parsed = urlsplit(self.api_url)
            _ = parsed.port
        except ValueError:
            raise ValueError("embedding.api_url") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.rstrip("/").endswith("/embeddings")
        ):
            raise ValueError("embedding.api_url")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("embedding.timeout")
        return self


class ServerConfig(_StrictModel):
    port: int = Field(default=8090, ge=1, le=65535)


class PersistenceConfig(_StrictModel):
    """PostgreSQL 连接参数；密码始终由秘密环境变量注入。"""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = "venagent"
    user: str = "venagent"
    password: SecretStr = SecretStr("")

    @property
    def database_url(self) -> SecretStr:
        """仅在持久化启用且密码存在时生成可传递给驱动的连接串。"""
        password = self.password.get_secret_value()
        if not self.enabled or not password:
            return SecretStr("")
        user = quote(self.user, safe="")
        encoded_password = quote(password, safe="")
        database = quote(self.database, safe="")
        return SecretStr(
            f"postgresql://{user}:{encoded_password}@{self.host}:{self.port}/{database}"
        )


class Neo4jConfig(_StrictModel):
    enabled: bool = False
    uri: str = "bolt://127.0.0.1:7687"
    database: str = "neo4j"
    user: str = "neo4j"
    password: SecretStr = SecretStr("")
    max_pool_size: int = Field(default=10, ge=1, le=100)
    connection_timeout: float = Field(default=2.0, gt=0, le=30)
    acquisition_timeout: float = Field(default=2.0, gt=0, le=30)
    read_timeout: float = Field(default=0.1, gt=0, le=1)
    write_timeout: float = Field(default=30.0, gt=0, le=120)


class AuthConfig(_StrictModel):
    issuer: str = "venagent"
    audience: str = "venagent-web"
    jwt_secret: SecretStr = SecretStr("")
    cookie_secure: bool = False
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:8090",
            "http://localhost:8090",
        ]
    )


class AppConfig(_StrictModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    memory_extractor: MemoryExtractorConfig = Field(default_factory=MemoryExtractorConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)

    @model_validator(mode="after")
    def _validate_extractor_inheritance(self) -> "AppConfig":
        if (
            self.memory_extractor.configured
            and not self.memory_extractor.independent
            and not self.llm.provider
        ):
            raise ValueError("memory_extractor.model requires a configured LLM profile")
        return self


# 只有列在此处的变量才会影响应用，避免把宿主环境意外透传给运行时。
ENV_FIELDS: dict[str, tuple[str, ...]] = {
    **{
        f"LLM_{name}": ("llm", key)
        for name, key in {
            "PROVIDER": "provider",
            "API_KEY": "api_key",
            "MODEL": "model",
            "API_MODE": "api_mode",
            "BASE_URL": "base_url",
            "ENDPOINT_URL": "endpoint_url",
            "AZURE_ENDPOINT": "azure_endpoint",
            "AZURE_DEPLOYMENT": "azure_deployment",
            "API_VERSION": "api_version",
            "REASONING_EFFORT": "reasoning_effort",
            "TEMPERATURE": "temperature",
            "MAX_TOKENS": "max_tokens",
            "TIMEOUT": "timeout",
            "MAX_RETRIES": "max_retries",
            "VERBOSITY": "verbosity",
            "EXTRA_BODY_JSON": "extra_body",
        }.items()
    },
    "SERVER__PORT": ("server", "port"),
    "PERSISTENCE__ENABLED": ("persistence", "enabled"),
    "PERSISTENCE__HOST": ("persistence", "host"),
    "PERSISTENCE__PORT": ("persistence", "port"),
    "PERSISTENCE__DATABASE": ("persistence", "database"),
    "PERSISTENCE__USER": ("persistence", "user"),
    "POSTGRES_PASSWORD": ("persistence", "password"),
    "NEO4J__ENABLED": ("neo4j", "enabled"),
    "NEO4J__URI": ("neo4j", "uri"),
    "NEO4J__DATABASE": ("neo4j", "database"),
    "NEO4J__USER": ("neo4j", "user"),
    "NEO4J_PASSWORD": ("neo4j", "password"),
    "NEO4J__MAX_POOL_SIZE": ("neo4j", "max_pool_size"),
    "NEO4J__CONNECTION_TIMEOUT": ("neo4j", "connection_timeout"),
    "NEO4J__ACQUISITION_TIMEOUT": ("neo4j", "acquisition_timeout"),
    "NEO4J__READ_TIMEOUT": ("neo4j", "read_timeout"),
    "NEO4J__WRITE_TIMEOUT": ("neo4j", "write_timeout"),
    "AUTH__ISSUER": ("auth", "issuer"),
    "AUTH__AUDIENCE": ("auth", "audience"),
    "JWT_SECRET": ("auth", "jwt_secret"),
    "AUTH__COOKIE_SECURE": ("auth", "cookie_secure"),
    "AUTH__ALLOWED_ORIGINS_JSON": ("auth", "allowed_origins"),
}

ENV_FIELDS.update(
    {
        f"MEMORY_EXTRACTOR_{name}": ("memory_extractor", key)
        for name, key in {
            "PROVIDER": "provider",
            "API_KEY": "api_key",
            "MODEL": "model",
            "API_MODE": "api_mode",
            "BASE_URL": "base_url",
            "ENDPOINT_URL": "endpoint_url",
            "AZURE_ENDPOINT": "azure_endpoint",
            "AZURE_DEPLOYMENT": "azure_deployment",
            "API_VERSION": "api_version",
            "TEMPERATURE": "temperature",
            "MAX_TOKENS": "max_tokens",
            "TIMEOUT": "timeout",
            "MAX_RETRIES": "max_retries",
            "EXTRA_BODY_JSON": "extra_body",
        }.items()
    }
)
ENV_FIELDS.update(
    {
        "EMBEDDING_API_URL": ("embedding", "api_url"),
        "EMBEDDING_API_KEY": ("embedding", "api_key"),
        "EMBEDDING_MODEL": ("embedding", "model"),
        "EMBEDDING_TIMEOUT": ("embedding", "timeout"),
        "EMBEDDING_MAX_RETRIES": ("embedding", "max_retries"),
    }
)


def load_config(
    *, environ: Mapping[str, str] | None = None, project_root: Path | None = None
) -> AppConfig:
    """加载一次配置快照；测试传入 environ 时不读取真实本机 `.env`。"""
    root = project_root or Path.cwd()
    process = dict(os.environ if environ is None else environ)
    dotenv = _read_dotenv(root / ".env") if environ is None else {}
    # 合并只发生在白名单解析之前，避免宿主环境中的无关变量进入配置对象。
    merged_env = {**dotenv, **process}
    try:
        return AppConfig.model_validate(_environment_overlay(merged_env))
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, item["loc"])) for item in exc.errors())
        raise ConfigError(f"配置无效：{fields}") from None


@lru_cache(maxsize=1)
def get_runtime_config() -> AppConfig:
    """生产进程共享同一快照，避免 CLI 与装配重复读取 `.env`。"""
    return load_config()


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    return {str(k): str(v) for k, v in dotenv_values(path).items() if v is not None}


def _environment_overlay(source: Mapping[str, str]) -> dict[str, Any]:
    overlay: dict[str, Any] = {}
    for name, raw in source.items():
        if "__" in name and name not in ENV_FIELDS:
            raise ConfigError(f"未知环境覆盖键：{name}")
        path = ENV_FIELDS.get(name)
        if path is not None and raw.strip():
            _set(overlay, path, _parse(path, raw))
    return overlay


def _parse(path: tuple[str, ...], raw: str) -> Any:
    try:
        if path in {
            ("auth", "cookie_secure"),
            ("persistence", "enabled"),
            ("neo4j", "enabled"),
        }:
            lowered = raw.strip().lower()
            if lowered not in {"true", "false", "1", "0"}:
                raise ValueError
            return lowered in {"true", "1"}
        if path == ("auth", "allowed_origins"):
            data = json.loads(raw)
            if not isinstance(data, list) or not all(
                isinstance(item, str) for item in data
            ):
                raise ValueError
            return data
        if path in {
            ("server", "port"),
            ("persistence", "port"),
            ("neo4j", "max_pool_size"),
        } or path[-1] in {"max_tokens", "max_retries"}:
            return int(raw)
        if path[-1] in {
            "temperature",
            "timeout",
            "connection_timeout",
            "acquisition_timeout",
            "read_timeout",
            "write_timeout",
        }:
            return float(raw)
        if path[-1] == "extra_body":
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError
            return data
        return raw
    except (ValueError, json.JSONDecodeError):
        raise ConfigError(f"环境变量类型无效：{'.'.join(path)}") from None


def _set(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor = target
    for key in path[:-1]:
        cursor = cursor.setdefault(key, {})
    cursor[path[-1]] = value
