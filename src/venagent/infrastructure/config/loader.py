"""配置来源装配、环境变量白名单和安全脱敏。"""

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, SecretStr as PydanticSecretStr, ValidationError

from .merge import deep_merge
from .models import AppConfig


class ConfigError(ValueError):
    """面向启动边界的安全配置错误，不回显输入值。"""


ENV_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "VENAGENT_LLM__API_URL": ("llm", "api_url"),
    "VENAGENT_LLM__API_KEY": ("llm", "api_key"),
    "VENAGENT_LLM__MODEL": ("llm", "model"),
    "VENAGENT_LLM__TEMPERATURE": ("llm", "temperature"),
    "VENAGENT_EMBEDDING__API_URL": ("embedding", "api_url"),
    "VENAGENT_EMBEDDING__API_KEY": ("embedding", "api_key"),
    "VENAGENT_EMBEDDING__MODEL": ("embedding", "model"),
    "VENAGENT_MILVUS__HOST": ("milvus", "host"),
    "VENAGENT_MILVUS__PORT": ("milvus", "port"),
    "VENAGENT_POSTGRES__HOST": ("postgres", "host"),
    "VENAGENT_POSTGRES__PORT": ("postgres", "port"),
    "VENAGENT_POSTGRES__USER": ("postgres", "user"),
    "VENAGENT_POSTGRES__PASSWORD": ("postgres", "password"),
    "VENAGENT_POSTGRES__DATABASE": ("postgres", "database"),
    "VENAGENT_ELASTICSEARCH__ADDRESSES": ("elasticsearch", "addresses"),
    "VENAGENT_ELASTICSEARCH__USERNAME": ("elasticsearch", "username"),
    "VENAGENT_ELASTICSEARCH__PASSWORD": ("elasticsearch", "password"),
    "VENAGENT_KAFKA__BROKERS": ("kafka", "brokers"),
    "VENAGENT_KAFKA__TOPIC": ("kafka", "topic"),
    "VENAGENT_NEO4J__URI": ("neo4j", "uri"),
    "VENAGENT_NEO4J__USER": ("neo4j", "user"),
    "VENAGENT_NEO4J__PASSWORD": ("neo4j", "password"),
    "VENAGENT_NEO4J__MAX_HOPS": ("neo4j", "max_hops"),
    "VENAGENT_NEO4J__WEIGHT": ("neo4j", "weight"),
    "VENAGENT_NEO4J__ENABLED": ("neo4j", "enabled"),
    "VENAGENT_RAG__CHUNK_SIZE": ("rag", "chunk_size"),
    "VENAGENT_RAG__CHUNK_OVERLAP": ("rag", "chunk_overlap"),
    "VENAGENT_RAG__TOP_K": ("rag", "top_k"),
    "VENAGENT_RAG__RRF_CONSTANT_K": ("rag", "rrf_constant_k"),
    "VENAGENT_RAG__SEMANTIC_WEIGHT": ("rag", "semantic_weight"),
    "VENAGENT_RAG__ENABLE_HYBRID_SEARCH": ("rag", "enable_hybrid_search"),
    "VENAGENT_RAG__MILVUS_DIM": ("rag", "rag_milvus_dim"),
    "VENAGENT_RAG__REWRITE__ENABLED": ("rag", "rewrite", "enabled"),
    "VENAGENT_RAG__REWRITE__NUM_QUERIES": ("rag", "rewrite", "num_queries"),
    "VENAGENT_RAG__RERANK__ENABLED": ("rag", "rerank", "enabled"),
    "VENAGENT_RAG__RERANK__PREVIEW_LEN": ("rag", "rerank", "preview_len"),
    "VENAGENT_MEMORY__SHORT_TERM_MAX_TURNS": ("memory", "short_term_max_turns"),
    "VENAGENT_MEMORY__LONG_TERM_TOP_K": ("memory", "long_term_top_k"),
    "VENAGENT_MEMORY__CONSOLIDATION__SIMILARITY_THRESHOLD": (
        "memory",
        "consolidation",
        "similarity_threshold",
    ),
    "VENAGENT_MEMORY__CONSOLIDATION__DEDUP_THRESHOLD": (
        "memory",
        "consolidation",
        "dedup_threshold",
    ),
    "VENAGENT_MEMORY__CONSOLIDATION__TTL_DAYS": (
        "memory",
        "consolidation",
        "ttl_days",
    ),
    "VENAGENT_MEMORY__CONSOLIDATION__DECAY_RATE": (
        "memory",
        "consolidation",
        "decay_rate",
    ),
    "VENAGENT_MEMORY__CONSOLIDATION__MIN_IMPORTANCE": (
        "memory",
        "consolidation",
        "min_importance",
    ),
    "VENAGENT_MEMORY__CONSOLIDATION__TRIGGER_INTERVAL": (
        "memory",
        "consolidation",
        "trigger_interval",
    ),
    "VENAGENT_HARNESS__MAX_RETRIES": ("harness", "max_retries"),
    "VENAGENT_HARNESS__RETRY_DELAY_MS": ("harness", "retry_delay_ms"),
    "VENAGENT_HARNESS__STEP_TIMEOUT_MS": ("harness", "step_timeout_ms"),
    "VENAGENT_HARNESS__MAX_ITERATIONS": ("harness", "max_iterations"),
    "VENAGENT_GRAPH_RUNTIME__MAX_PARALLEL": ("graph_runtime", "max_parallel"),
    "VENAGENT_GRAPH_RUNTIME__RACE_TIMEOUT_MS": (
        "graph_runtime",
        "race_timeout_ms",
    ),
    "VENAGENT_GRAPH_RUNTIME__ENABLE_RACING": ("graph_runtime", "enable_racing"),
    "VENAGENT_SEARCH__API_KEY": ("search", "api_key"),
    "VENAGENT_SEARCH__API_URL": ("search", "api_url"),
    "VENAGENT_SERVER__PORT": ("server", "port"),
    "VENAGENT_SERVER__CORS_ORIGINS": ("server", "cors_origins"),
    "VENAGENT_SANDBOX__ENABLED": ("sandbox", "enabled"),
    "VENAGENT_SANDBOX__BACKEND": ("sandbox", "backend"),
    "VENAGENT_SANDBOX__IMAGE": ("sandbox", "image"),
    "VENAGENT_SANDBOX__TIMEOUT_MS": ("sandbox", "timeout_ms"),
    "VENAGENT_SANDBOX__MAX_OUTPUT_BYTES": ("sandbox", "max_output_bytes"),
    "VENAGENT_SANDBOX__MEMORY_LIMIT_MB": ("sandbox", "memory_limit_mb"),
    "VENAGENT_SANDBOX__CPU_PERCENT": ("sandbox", "cpu_percent"),
    "VENAGENT_SANDBOX__MAX_PIDS": ("sandbox", "max_pids"),
    "VENAGENT_SANDBOX__NETWORK_DISABLED": ("sandbox", "network_disabled"),
    "VENAGENT_SANDBOX__READONLY_ROOTFS": ("sandbox", "readonly_rootfs"),
    "VENAGENT_SECURITY__MAX_COMMAND_LENGTH": ("security", "max_command_length"),
    "VENAGENT_SECURITY__ALLOWLIST_MODE": ("security", "allowlist_mode"),
    "VENAGENT_SECURITY__ALLOWLIST": ("security", "allowlist"),
}

_BOOL_FIELDS = {
    ("neo4j", "enabled"),
    ("rag", "enable_hybrid_search"),
    ("rag", "rewrite", "enabled"),
    ("rag", "rerank", "enabled"),
    ("graph_runtime", "enable_racing"),
    ("sandbox", "enabled"),
    ("sandbox", "network_disabled"),
    ("sandbox", "readonly_rootfs"),
    ("security", "allowlist_mode"),
}
_INT_FIELDS = {
    ("milvus", "port"),
    ("postgres", "port"),
    ("neo4j", "max_hops"),
    ("rag", "chunk_size"),
    ("rag", "chunk_overlap"),
    ("rag", "top_k"),
    ("rag", "rrf_constant_k"),
    ("rag", "rag_milvus_dim"),
    ("rag", "rewrite", "num_queries"),
    ("rag", "rerank", "preview_len"),
    ("memory", "short_term_max_turns"),
    ("memory", "long_term_top_k"),
    ("memory", "consolidation", "ttl_days"),
    ("memory", "consolidation", "trigger_interval"),
    ("harness", "max_retries"),
    ("harness", "retry_delay_ms"),
    ("harness", "step_timeout_ms"),
    ("harness", "max_iterations"),
    ("graph_runtime", "max_parallel"),
    ("graph_runtime", "race_timeout_ms"),
    ("server", "port"),
    ("sandbox", "timeout_ms"),
    ("sandbox", "max_output_bytes"),
    ("sandbox", "memory_limit_mb"),
    ("sandbox", "cpu_percent"),
    ("sandbox", "max_pids"),
    ("security", "max_command_length"),
}
_FLOAT_FIELDS = {
    ("llm", "temperature"),
    ("neo4j", "weight"),
    ("rag", "semantic_weight"),
    ("memory", "consolidation", "similarity_threshold"),
    ("memory", "consolidation", "dedup_threshold"),
    ("memory", "consolidation", "decay_rate"),
    ("memory", "consolidation", "min_importance"),
}
_LIST_FIELDS = {
    ("elasticsearch", "addresses"),
    ("kafka", "brokers"),
    ("server", "cors_origins"),
    ("security", "allowlist"),
}
_SECRET_KEY_PATTERN = re.compile(
    r"(?:^|_)(?:api[_-]?key|password|token|secret|access[_-]?key|authorization)(?:$|_)",
    re.IGNORECASE,
)

# 加载环境变量
def load_config(
    *,
    shared_path: str | Path | None = None,
    local_path: str | Path | None = None,
    env_file: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
) -> AppConfig:
    """按五层顺序加载配置并返回不可变模型。"""

    process_env = dict(os.environ if environ is None else environ)
    dotenv_path = _resolve_env_file(env_file, process_env)
    dotenv_env = _read_env_file(dotenv_path) if dotenv_path is not None else {}
    # 进程环境变量是更高优先级，覆盖 .env 中的同名值。
    env = {**dotenv_env, **process_env}
    resolved_shared, resolved_local = _resolve_paths(shared_path, local_path, env)
    raw_config = AppConfig().model_dump(mode="python")
    raw_config = deep_merge(raw_config, _read_yaml(resolved_shared))
    if resolved_local != resolved_shared:
        raw_config = deep_merge(raw_config, _read_yaml(resolved_local))
    raw_config = deep_merge(raw_config, _environment_overlay(env))
    raw_config = deep_merge(raw_config, _cli_overlay(cli_overrides or {}))

    try:
        return AppConfig.model_validate(_normalize_sequences(raw_config))
    except ValidationError as error:
        raise ConfigError(_format_validation_error(error)) from None


def redact_config(value: Any) -> Any:
    """递归复制并脱敏配置，不改变输入对象。"""

    if isinstance(value, PydanticSecretStr):
        return "[REDACTED]"
    if isinstance(value, BaseModel):
        redacted = {}
        for field_name, field_info in value.model_fields.items():
            field_value = getattr(value, field_name)
            metadata = field_info.json_schema_extra
            is_secret = isinstance(metadata, Mapping) and metadata.get("secret") is True
            redacted[field_name] = (
                "[REDACTED]" if is_secret else redact_config(field_value)
            )
        return redacted
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]"
            if isinstance(key, str) and _SECRET_KEY_PATTERN.search(key)
            else redact_config(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact_config(item) for item in value)
    if isinstance(value, list):
        return [redact_config(item) for item in value]
    return deepcopy(value)


def _resolve_paths(
    shared_path: str | Path | None,
    local_path: str | Path | None,
    environ: Mapping[str, str],
) -> tuple[Path, Path]:
    root = Path(environ.get("AGI_PROJECT_ROOT", Path.cwd()))
    shared = Path(shared_path) if shared_path else root / "config" / "config.yaml"
    local = (
        Path(local_path)
        if local_path
        else Path(environ.get("AGI_CONFIG", shared.parent / "config.local.yaml"))
    )
    return shared, local


def _resolve_env_file(
    env_file: str | Path | None,
    environ: Mapping[str, str],
) -> Path | None:
    if env_file is not None:
        path = Path(env_file)
        if not path.is_file():
            raise ConfigError(f"cannot read environment file: {path}") from None
        return path
    root = Path(environ.get("AGI_PROJECT_ROOT", Path.cwd()))
    candidate = root / ".env"
    return candidate if candidate.is_file() else None


def _read_env_file(path: Path) -> dict[str, str]:
    try:
        values = dotenv_values(path, interpolate=True, encoding="utf-8")
    except (OSError, ValueError):
        raise ConfigError(f"cannot read environment file: {path}") from None
    return {
        str(key): str(value)
        for key, value in values.items()
        if value is not None
    }


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        raise ConfigError(f"cannot read configuration file: {path}") from None
    if not isinstance(loaded, Mapping):
        raise ConfigError(f"configuration root must be a mapping: {path}")
    return dict(loaded)


def _environment_overlay(environ: Mapping[str, str]) -> dict[str, Any]:
    overlay: dict[str, Any] = {}
    for env_name, path in ENV_FIELD_MAP.items():
        if env_name not in environ:
            continue
        _set_path(overlay, path, _parse_environment_value(path, environ[env_name]))
    return overlay


def _parse_environment_value(path: tuple[str, ...], raw_value: str) -> Any:
    try:
        if path in _BOOL_FIELDS:
            normalized = raw_value.strip().lower()
            if normalized not in {"true", "false"}:
                raise ValueError
            return normalized == "true"
        if path in _INT_FIELDS:
            return int(raw_value)
        if path in _FLOAT_FIELDS:
            return float(raw_value)
        if path in _LIST_FIELDS:
            parsed = json.loads(raw_value)
            if not isinstance(parsed, list) or not all(
                isinstance(item, str) for item in parsed
            ):
                raise ValueError
            return parsed
        return raw_value
    except (TypeError, ValueError, json.JSONDecodeError):
        field_path = ".".join(path)
        raise ConfigError(f"invalid environment value for {field_path}") from None


def _cli_overlay(overrides: Mapping[str, Any]) -> dict[str, Any]:
    overlay: dict[str, Any] = {}
    for key, value in overrides.items():
        if not isinstance(key, str) or not key:
            raise ConfigError("CLI override field name must be non-empty")
        if "." in key:
            _set_path(overlay, tuple(key.split(".")), value)
        elif isinstance(value, Mapping):
            overlay = deep_merge(overlay, {key: dict(value)})
        else:
            overlay[key] = deepcopy(value)
    return overlay


def _set_path(target: dict[str, Any], path: Sequence[str], value: Any) -> None:
    cursor = target
    for key in path[:-1]:
        existing = cursor.get(key)
        if existing is None:
            existing = {}
            cursor[key] = existing
        if not isinstance(existing, dict):
            raise ConfigError(f"configuration override conflicts at {key}")
        cursor = existing
    cursor[path[-1]] = deepcopy(value)


def _format_validation_error(error: ValidationError) -> str:
    details = []
    for issue in error.errors(include_context=False, include_url=False):
        location = ".".join(str(item) for item in issue.get("loc", ())) or "config"
        message = str(issue.get("msg", "invalid"))
        if message.startswith("Value error, "):
            message = message.removeprefix("Value error, ")
        details.append(f"{location}: {message}")
    return "invalid configuration: " + "; ".join(details)


def _normalize_sequences(value: Any) -> Any:
    """把 YAML/env 的 list 转为不可变 tuple，递归复制其他容器。"""

    if isinstance(value, Mapping):
        return {key: _normalize_sequences(item) for key, item in value.items()}
    if isinstance(value, list):
        return tuple(_normalize_sequences(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_normalize_sequences(item) for item in value)
    return value
