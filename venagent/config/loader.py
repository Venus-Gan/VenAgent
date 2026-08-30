"""严格配置加载：config.yaml（唯一文件源）< 显式进程环境白名单覆盖。

- `config.yaml` 是唯一文件源（D3/D8 决策：不引入 config.local.yaml，.env 已删除）。
- 配置文件全量 fail-fast：未知键 / 类型错误 → `ConfigError`（不静默忽略）。
- 进程环境只放行 `ENV_FIELDS` 白名单（避免宿主环境意外透传）；含 `__` 的
  未知键显式报错。
- 自举：`config.yaml` 缺失时从 `config.example.yaml` 复制生成（D10）；
  空敏感字段 = 安全降级，不拒绝启动。
"""

from __future__ import annotations

import json
import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import ValidationError

from .models import (  # noqa: F401  # 保持旧 import 路径（venagent.config.loader.*）兼容
    AppConfig,
    AuthConfig,
    ConfigError,
    DocumentConfig,
    EmbeddingConfig,
    ESConfig,
    GithubConfig,
    InvocationConfig,
    LLMConfig,
    LLMProfileOverride,
    McpConfig,
    MemoryConsolidationConfig,
    MemoryExtractorConfig,
    MilvusConfig,
    Neo4jConfig,
    PersistenceConfig,
    RagConfig,
    RerankModelOverride,
    RewriteModelOverride,
    SandboxConfig,
    ServerConfig,
)

CONFIG_FILENAME = "config.yaml"
EXAMPLE_FILENAME = "config.example.yaml"


# 只有列在此处的环境变量才能覆盖配置，避免把宿主环境意外透传给运行时。
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
    "SANDBOX__IMAGE": ("sandbox", "image"),
    "SANDBOX__DISABLED": ("sandbox", "disabled"),
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
    "MILVUS__ENABLED": ("milvus", "enabled"),
    "MILVUS__URI": ("milvus", "uri"),
    "MILVUS__USER": ("milvus", "user"),
    "MILVUS_PASSWORD": ("milvus", "password"),
    "MILVUS__COLLECTION": ("milvus", "collection"),
    "MILVUS__DIM": ("milvus", "dim"),
    "ES__ENABLED": ("es", "enabled"),
    "ES__URI": ("es", "uri"),
    "ES__USER": ("es", "user"),
    "ES_PASSWORD": ("es", "password"),
    "ES__INDEX": ("es", "index"),
    "AUTH__ISSUER": ("auth", "issuer"),
    "AUTH__AUDIENCE": ("auth", "audience"),
    "JWT_SECRET": ("auth", "jwt_secret"),
    "AUTH__COOKIE_SECURE": ("auth", "cookie_secure"),
    "AUTH__ALLOWED_ORIGINS_JSON": ("auth", "allowed_origins"),
    "VENAGENT_INVOCATION_ENCRYPTION_KEY": ("invocation", "encryption_key"),
    "GITHUB_TOKEN": ("github", "token"),
    "VENAGENT_MCP_ALLOWED_COMMANDS": ("mcp", "allowed_commands"),
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
        f"REWRITE_MODEL_{name}": ("rewrite_model", key)
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
        f"RERANK_MODEL_{name}": ("rerank_model", key)
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
    """加载一次配置快照；测试传入 environ 时模拟显式进程环境覆盖。"""
    root = project_root or Path.cwd()
    process = dict(os.environ if environ is None else environ)
    yaml_data = _load_yaml_file(root / CONFIG_FILENAME)
    overlay = _environment_overlay(process)
    merged = _merge_overlay(yaml_data, overlay)
    try:
        return AppConfig.model_validate(merged)
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, item["loc"])) for item in exc.errors())
        raise ConfigError(f"配置无效：{fields}") from None


@lru_cache(maxsize=1)
def get_runtime_config() -> AppConfig:
    """生产进程共享同一快照，避免 CLI 与装配重复读取配置文件。"""
    return load_config()


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        # 自举：缺失时从模板复制生成（D10）；模板也不存在则安全默认。
        example = path.parent / EXAMPLE_FILENAME
        if example.is_file():
            shutil.copyfile(example, path)
        else:
            return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError("配置无效：config.yaml 顶层必须是映射")
    return raw


def _environment_overlay(source: Mapping[str, str]) -> dict[str, Any]:
    overlay: dict[str, Any] = {}
    for name, raw in source.items():
        if "__" in name and name not in ENV_FIELDS:
            raise ConfigError(f"未知环境覆盖键：{name}")
        path = ENV_FIELDS.get(name)
        if path is not None and raw.strip():
            _set(overlay, path, _parse(path, raw))
    return overlay


def _merge_overlay(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """进程环境覆盖 config.yaml（浅覆盖到嵌套区块）。"""
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = {**existing, **value}
        else:
            merged[key] = value
    return merged


def _parse(path: tuple[str, ...], raw: str) -> Any:
    try:
        if path in {
            ("auth", "cookie_secure"),
            ("persistence", "enabled"),
            ("neo4j", "enabled"),
            ("sandbox", "disabled"),
            ("milvus", "enabled"),
            ("es", "enabled"),
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
        if path == ("mcp", "allowed_commands"):
            items = [item.strip() for item in raw.split(",") if item.strip()]
            if not items:
                raise ValueError
            return items
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
