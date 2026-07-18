"""legacy APIConfig/build_deps 到新 Bootstrap 的兼容适配。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from venagent.bootstrap import BootstrapResult
from venagent.bootstrap import DependencyContainer, StagedBootstrapper
from venagent.infrastructure.config import AppConfig, load_config


@dataclass(frozen=True, slots=True)
class LegacyFactories:
    """由 legacy 入口注入的工厂，不让新包反向依赖 ``final``。"""

    infrastructure_factory: Callable[[object], object]
    agent_factory: Callable[[object, object], object]
    runtime_initializer: Callable[[object], object]
    app_factory: Callable[[object, object, object], object]

    def __post_init__(self) -> None:
        for name in (
            "infrastructure_factory",
            "agent_factory",
            "runtime_initializer",
            "app_factory",
        ):
            if not callable(getattr(self, name)):
                raise TypeError(f"{name} must be callable")


def legacy_config_to_app_config(legacy_config: object) -> AppConfig:
    """把 legacy 扁平配置映射为经过 Pydantic 校验的不可变配置。"""

    value = lambda name, default=None: getattr(legacy_config, name, default)
    try:
        return AppConfig(
            llm={
                "api_url": value("llm_api_url", ""),
                "api_key": value("llm_api_key", ""),
                "model": value("llm_model", ""),
                "temperature": value("temperature", 0.7),
            },
            embedding={
                "api_url": value("embedding_api_url", ""),
                "api_key": value("embedding_api_key", ""),
                "model": value("embedding_model", ""),
            },
            milvus={
                "host": value("milvus_host", ""),
                "port": value("milvus_port", 19530),
            },
            postgres={
                "host": value("pg_host", ""),
                "port": value("pg_port", 5432),
                "user": value("pg_user", ""),
                "password": value("pg_password", ""),
                "database": value("pg_database", ""),
            },
            elasticsearch={
                "addresses": tuple(value("es_addresses", ()) or ()),
                "username": value("es_username", ""),
                "password": value("es_password", ""),
            },
            kafka={
                "brokers": tuple(value("kafka_brokers", ()) or ()),
                "topic": value("kafka_topic", ""),
            },
            neo4j={
                "uri": value("neo4j_uri", ""),
                "user": value("neo4j_user", ""),
                "password": value("neo4j_password", ""),
                "max_hops": value("kg_max_hops", 2),
                "weight": value("kg_weight", 0.3),
                "enabled": value("kg_enabled", False),
            },
            rag={
                "chunk_size": value("chunk_size", 200),
                "chunk_overlap": value("chunk_overlap", 50),
                "top_k": value("top_k", 3),
                "rrf_constant_k": value("rrf_constant_k", 60),
                "semantic_weight": value("semantic_weight", 0.7),
                "enable_hybrid_search": value("enable_hybrid_search", False),
                "rag_milvus_dim": value("rag_milvus_dim", 1024),
                "rewrite": {
                    "enabled": value("rag_rewrite_enabled", False),
                    "num_queries": value("rag_rewrite_num_queries", 3),
                },
                "rerank": {
                    "enabled": value("rag_rerank_enabled", False),
                    "preview_len": value("rag_rerank_preview_len", 200),
                },
            },
            memory={
                "short_term_max_turns": value("short_term_max_turns", 5),
                "long_term_top_k": value("long_term_top_k", 3),
                "consolidation": {
                    "similarity_threshold": value(
                        "memory_consolidation_similarity", 0.80
                    ),
                    "dedup_threshold": value("memory_consolidation_dedup", 0.95),
                    "ttl_days": value("memory_consolidation_ttl_days", 30),
                    "decay_rate": value("memory_consolidation_decay_rate", 0.995),
                    "min_importance": value("memory_consolidation_min_import", 0.3),
                    "trigger_interval": value("memory_consolidation_trigger", 5),
                },
            },
            harness={
                "max_retries": value("max_retries", 3),
                "retry_delay_ms": value("retry_delay_ms", 200),
                "step_timeout_ms": value("step_timeout_ms", 5000),
                "max_iterations": value("max_iterations", 5),
            },
            graph_runtime={
                "max_parallel": value("graph_max_parallel", 2),
                "race_timeout_ms": value("graph_race_timeout_ms", 30000),
                "enable_racing": value("graph_enable_racing", True),
            },
            search={
                "api_key": value("search_api_key", ""),
                "api_url": value("search_api_url", ""),
            },
            server={
                "port": int(value("server_port", 8090)),
                "cors_origins": tuple(value("cors_origins", ()) or ()),
            },
            sandbox={
                "enabled": value("sandbox_enabled", False),
                "backend": value("sandbox_backend", "docker"),
                "image": value("sandbox_image", "ubuntu:22.04"),
                "timeout_ms": value("sandbox_timeout_ms", 30000),
                "max_output_bytes": value("sandbox_max_output", 65536),
                "memory_limit_mb": value("sandbox_memory_mb", 256),
                "cpu_percent": value("sandbox_cpu_percent", 50),
                "max_pids": value("sandbox_max_pids", 64),
                "network_disabled": value("sandbox_net_disabled", True),
                "readonly_rootfs": value("sandbox_readonly", True),
            },
            security={
                "max_command_length": value("sec_max_cmd_length", 500),
                "allowlist_mode": value("sec_allowlist_mode", False),
                "allowlist": tuple(value("sec_allowlist", ()) or ()),
            },
        )
    except Exception:
        # 不把 legacy 配置值（尤其是 secret）带入 façade 错误。
        raise ValueError("legacy configuration conversion failed") from None


def app_config_to_legacy_config(
    app_config: AppConfig,
    legacy_config_factory: Callable[[], object],
) -> object:
    """将 canonical 配置转换回 legacy 运行时需要的扁平字段。"""

    legacy = legacy_config_factory()

    def secret(value):
        return value.get_secret_value()

    assignments = {
        "llm_api_url": app_config.llm.api_url,
        "llm_api_key": secret(app_config.llm.api_key),
        "llm_model": app_config.llm.model,
        "temperature": app_config.llm.temperature,
        "embedding_api_url": app_config.embedding.api_url,
        "embedding_api_key": secret(app_config.embedding.api_key),
        "embedding_model": app_config.embedding.model,
        "milvus_host": app_config.milvus.host,
        "milvus_port": app_config.milvus.port,
        "pg_host": app_config.postgres.host,
        "pg_port": app_config.postgres.port,
        "pg_user": app_config.postgres.user,
        "pg_password": secret(app_config.postgres.password),
        "pg_database": app_config.postgres.database,
        "es_addresses": list(app_config.elasticsearch.addresses),
        "es_username": app_config.elasticsearch.username,
        "es_password": secret(app_config.elasticsearch.password),
        "kafka_brokers": list(app_config.kafka.brokers),
        "kafka_topic": app_config.kafka.topic,
        "neo4j_uri": app_config.neo4j.uri,
        "neo4j_user": app_config.neo4j.user,
        "neo4j_password": secret(app_config.neo4j.password),
        "kg_max_hops": app_config.neo4j.max_hops,
        "kg_weight": app_config.neo4j.weight,
        "kg_enabled": app_config.neo4j.enabled,
        "chunk_size": app_config.rag.chunk_size,
        "chunk_overlap": app_config.rag.chunk_overlap,
        "top_k": app_config.rag.top_k,
        "rrf_constant_k": app_config.rag.rrf_constant_k,
        "semantic_weight": app_config.rag.semantic_weight,
        "enable_hybrid_search": app_config.rag.enable_hybrid_search,
        "rag_milvus_dim": app_config.rag.rag_milvus_dim,
        "rag_rewrite_enabled": app_config.rag.rewrite.enabled,
        "rag_rewrite_num_queries": app_config.rag.rewrite.num_queries,
        "rag_rerank_enabled": app_config.rag.rerank.enabled,
        "rag_rerank_preview_len": app_config.rag.rerank.preview_len,
        "short_term_max_turns": app_config.memory.short_term_max_turns,
        "long_term_top_k": app_config.memory.long_term_top_k,
        "memory_consolidation_similarity": app_config.memory.consolidation.similarity_threshold,
        "memory_consolidation_dedup": app_config.memory.consolidation.dedup_threshold,
        "memory_consolidation_ttl_days": app_config.memory.consolidation.ttl_days,
        "memory_consolidation_decay_rate": app_config.memory.consolidation.decay_rate,
        "memory_consolidation_min_import": app_config.memory.consolidation.min_importance,
        "memory_consolidation_trigger": app_config.memory.consolidation.trigger_interval,
        "max_retries": app_config.harness.max_retries,
        "retry_delay_ms": app_config.harness.retry_delay_ms,
        "step_timeout_ms": app_config.harness.step_timeout_ms,
        "max_iterations": app_config.harness.max_iterations,
        "graph_max_parallel": app_config.graph_runtime.max_parallel,
        "graph_race_timeout_ms": app_config.graph_runtime.race_timeout_ms,
        "graph_enable_racing": app_config.graph_runtime.enable_racing,
        "search_api_key": secret(app_config.search.api_key),
        "search_api_url": app_config.search.api_url,
        "server_port": str(app_config.server.port),
        "cors_origins": list(app_config.server.cors_origins),
        "sandbox_enabled": app_config.sandbox.enabled,
        "sandbox_backend": app_config.sandbox.backend,
        "sandbox_image": app_config.sandbox.image,
        "sandbox_timeout_ms": app_config.sandbox.timeout_ms,
        "sandbox_max_output": app_config.sandbox.max_output_bytes,
        "sandbox_memory_mb": app_config.sandbox.memory_limit_mb,
        "sandbox_cpu_percent": app_config.sandbox.cpu_percent,
        "sandbox_max_pids": app_config.sandbox.max_pids,
        "sandbox_net_disabled": app_config.sandbox.network_disabled,
        "sandbox_readonly": app_config.sandbox.readonly_rootfs,
        "sec_max_cmd_length": app_config.security.max_command_length,
        "sec_allowlist_mode": app_config.security.allowlist_mode,
        "sec_allowlist": list(app_config.security.allowlist),
    }
    for name, value in assignments.items():
        setattr(legacy, name, value)
    return legacy


def load_legacy_config(
    legacy_config_factory: Callable[[], object],
    *,
    shared_path: str | Path,
    local_path: str | Path | None = None,
    env_file: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> object:
    """读取 canonical 配置和 `.env`，再返回 legacy 配置对象。"""

    config = load_config(
        shared_path=shared_path,
        local_path=local_path,
        env_file=env_file,
        environ=environ,
    )
    return app_config_to_legacy_config(config, legacy_config_factory)


def build_legacy_dependencies(
    legacy_config: object,
    factories: LegacyFactories,
) -> BootstrapResult:
    """通过新 StagedBootstrapper 构建 legacy 依赖结果。"""

    app_config = legacy_config_to_app_config(legacy_config)

    def create_infrastructure(_config: AppConfig) -> object:
        return factories.infrastructure_factory(legacy_config)

    def create_application(_config: AppConfig, infrastructure: object) -> object:
        agent = None
        try:
            agent = factories.agent_factory(legacy_config, infrastructure)
            factories.runtime_initializer(agent)
            return agent
        except BaseException:
            _close_safely(agent)
            raise

    def create_app(
        _config: AppConfig,
        infrastructure: object,
        agent: object,
    ) -> object:
        return factories.app_factory(legacy_config, infrastructure, agent)

    container = DependencyContainer(
        config=app_config,
        infrastructure_factory=create_infrastructure,
        application_factory=create_application,
        app_factory=create_app,
    )
    return StagedBootstrapper(container).run()


def _close_safely(resource: object | None) -> None:
    close = getattr(resource, "close", None)
    if not callable(close):
        return
    try:
        close()
    except BaseException:
        pass
