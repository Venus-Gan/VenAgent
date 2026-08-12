"""VenAgent 唯一 composition root。"""

from dataclasses import dataclass
from typing import Any

from .agent.ports import MessageInvoker, RunStore
from .agent.runtime import MEMORY_LONG_TERM_DEADLINE_SECONDS, AgentRuntime
from .config import AppConfig, get_runtime_config
from .conversation.ports import ConversationStore
from .conversation.service import ConversationService
from .llm.embeddings import HttpEmbeddingClient
from .llm.factory import build_memory_extractor_model, build_runtime_model
from .memory.capabilities import MemoryCapabilityRegistry, MemoryCapabilityStatus
from .memory.command_adapter import MemoryCommandAdapter
from .memory.embedding import MemoryIndex
from .memory.model_adapters import (
    LangChainConflictJudge,
    LangChainMemoryExtractor,
    LangChainSummaryBuilder,
)
from .memory.ports import MemoryStore
from .memory.service import MemoryService
from .ownership.ports import OwnershipStore
from .ownership.service import OwnershipService
from .platform.neo4j import Neo4jRuntime, build_neo4j_runtime
from .platform.observability import (
    InfrastructureState,
    InfrastructureStatus,
    StartupReport,
)
from .platform.runtime import (
    DATABASE_URL,
    PersistenceRuntime,
    PersistenceStatus,
    build_persistence_runtime,
    build_temporary_runtime,
)
from .platform.security import Argon2PasswordHasher, JwtAccessTokenCodec
from .platform.security.tokens import temporary_jwt_secret
from .repo.postgresql import PostgresConversationRuntimeStore, PostgresOwnershipStore
from .repo.postgresql.memory import PostgresMemoryStore
from .repo.temporary import (
    TemporaryConversationRuntimeStore,
    TemporaryOwnershipStore,
    TemporaryPlatformState,
)
from .repo.temporary.memory import TemporaryMemoryStore

EMBEDDING_RECALL_MARGIN_SECONDS = 0.5
MAX_EMBEDDING_RECALL_DEADLINE_SECONDS = 30.5


@dataclass
class Application:
    service: ConversationService
    runtime: AgentRuntime
    ownership: OwnershipService
    memory: MemoryService
    memory_commands: MemoryCommandAdapter
    memory_capabilities: MemoryCapabilityRegistry
    persistence: PersistenceRuntime
    graph: Neo4jRuntime
    config: AppConfig

    async def open(self) -> None:
        await self.persistence.open()
        await self.graph.open()

    async def aclose(self) -> None:
        await self.graph.aclose()
        await self.persistence.aclose()

    def close(self) -> None:
        """释放尚未进入 FastAPI lifespan 的装配资源。"""
        self.graph.close()
        self.persistence.close()

    @property
    def startup_report(self) -> StartupReport:
        return _startup_report(
            self.persistence.status, self.graph, self.memory_capabilities
        )

    @property
    def health(self) -> dict[str, Any]:
        return _health(self.persistence.status, self.graph, self.memory_capabilities)


def build_application(
    model: MessageInvoker | None = None,
    *,
    conversation_service: ConversationService | None = None,
    ownership_service: OwnershipService | None = None,
    persistence_runtime: PersistenceRuntime | None = None,
    config: AppConfig | None = None,
) -> Application:
    config = config or get_runtime_config()
    persistence = persistence_runtime or build_persistence_runtime(
        {DATABASE_URL: config.persistence.database_url.get_secret_value()}
    )
    if (
        persistence.status.mode == "durable"
        and len(config.auth.jwt_secret.get_secret_value().encode("utf-8")) < 32
    ):
        persistence.close()
        persistence = build_temporary_runtime()
    adapters = _build_repository_adapters(persistence)
    service = conversation_service or ConversationService(adapters.conversation)
    ownership = ownership_service or _build_ownership(adapters.ownership, config)
    cursor_secret = config.auth.jwt_secret.get_secret_value() or temporary_jwt_secret()
    main_model = model or build_runtime_model(config)
    extractor_model = build_memory_extractor_model(config, main_model)
    memory_capabilities = _memory_capability_registry(
        persistence.status,
        embedding_configured=config.embedding.enabled,
    )
    graph = build_neo4j_runtime(
        config.neo4j,
        memory_capabilities,
        authority_durable=persistence.status.mode == "durable",
    )
    memory_index = (
        MemoryIndex(
            adapters.memory,
            HttpEmbeddingClient(config.embedding),
            model=config.embedding.model,
        )
        if config.embedding.enabled
        else None
    )
    memory = MemoryService(
        adapters.memory,
        adapters.ownership,
        graph_store=graph.graph_store,
        cursor_secret=cursor_secret,
        capability_registry=memory_capabilities,
        extractor=LangChainMemoryExtractor(extractor_model),
        conflict_judge=LangChainConflictJudge(extractor_model),
        summary_builder=LangChainSummaryBuilder(main_model),
        memory_index=memory_index,
    )
    runtime = AgentRuntime(
        main_model,
        persistence.checkpointer,
        adapters.runs,
        memory=memory,
        memory_long_term_deadline=_memory_long_term_deadline(config),
    )
    return Application(
        service=service,
        runtime=runtime,
        ownership=ownership,
        memory=memory,
        memory_commands=MemoryCommandAdapter(memory),
        memory_capabilities=memory_capabilities,
        persistence=persistence,
        graph=graph,
        config=config,
    )


def _memory_long_term_deadline(config: AppConfig) -> float:
    if not config.embedding.enabled:
        return MEMORY_LONG_TERM_DEADLINE_SECONDS
    provider_budget = (
        config.embedding.timeout * (config.embedding.max_retries + 1)
        + EMBEDDING_RECALL_MARGIN_SECONDS
    )
    return min(provider_budget, MAX_EMBEDDING_RECALL_DEADLINE_SECONDS)


def _startup_report(
    status: PersistenceStatus,
    graph: Neo4jRuntime,
    capabilities: MemoryCapabilityRegistry,
) -> StartupReport:
    return StartupReport(
        mode=status.mode,
        infrastructure=(
            status.infrastructure,
            graph.infrastructure,
            *_memory_infrastructure(capabilities),
        ),
    )


def _health(
    status: PersistenceStatus,
    graph: Neo4jRuntime,
    capabilities: MemoryCapabilityRegistry,
) -> dict[str, Any]:
    health = status.as_health()
    neo4j = graph.infrastructure
    health["infrastructure"][neo4j.component] = {
        "status": neo4j.health_status,
        "state": neo4j.state.value,
        "reason_code": neo4j.reason_code,
    }
    for memory in _memory_infrastructure(capabilities):
        health["infrastructure"][memory.component] = {
            "status": memory.health_status,
            "state": memory.state.value,
            "reason_code": memory.reason_code,
        }
    health["capabilities"]["long_term_memory"] = (
        "available" if status.mode == "durable" else "unavailable"
    )
    return health


def _memory_capability_registry(
    status: PersistenceStatus,
    *,
    embedding_configured: bool = False,
) -> MemoryCapabilityRegistry:
    durable = status.mode == "durable"
    embedding_state = "healthy" if embedding_configured else "disabled"
    embedding_reason = (
        "embedding_configured" if embedding_configured else "embedding_not_configured"
    )
    index_enabled = durable and embedding_configured
    values = (
        MemoryCapabilityStatus(
            "memory-short-term", "healthy", "conversation_context_ready"
        ),
        MemoryCapabilityStatus(
            "memory-embedding", embedding_state, embedding_reason
        ),
        MemoryCapabilityStatus(
            "memory-index",
            "healthy" if index_enabled else "disabled",
            "index_ready"
            if index_enabled
            else (
                "embedding_not_configured"
                if durable
                else "durable_identity_required"
            ),
        ),
        *(
            MemoryCapabilityStatus(
                component,
                "healthy" if durable else "disabled",
                "memory_ready" if durable else "durable_identity_required",
            )
            for component in (
                "memory-long-term",
                "memory-extraction",
                "memory-graph-g1",
            )
        ),
    )
    return MemoryCapabilityRegistry(values)


def _memory_infrastructure(
    capabilities: MemoryCapabilityRegistry,
) -> tuple[InfrastructureStatus, ...]:
    labels = {
        "memory-short-term": "关联图谱召回：完整 turn 与派生摘要",
        "memory-long-term": "长期记忆存储：长期事实与来源存储",
        "memory-extraction": "长期记忆写入：候选提取与事实持久化",
        "memory-embedding": "语义向量服务：事实与查询向量生成",
        "memory-index": "语义记忆索引：派生向量投影与召回",
        "memory-graph-g1": "GraphMemory：事实图与一跳召回",
    }
    state_map = {
        "healthy": InfrastructureState.READY,
        "degraded": InfrastructureState.DEGRADED,
        "recovering": InfrastructureState.DEGRADED,
        "disabled": InfrastructureState.DISABLED,
        "unavailable": InfrastructureState.FAILED,
        "purge_pending": InfrastructureState.DEGRADED,
    }
    return tuple(
        InfrastructureStatus(
            component=item.component,
            state=state_map[item.state],
            reason_code=item.reason_code,
            operator_message=(
                f"{labels[item.component]}可用。"
                if item.state == "healthy"
                else f"{labels[item.component]}状态：{item.reason_code}。"
            ),
            health_status=state_map[item.state].value,
        )
        for item in capabilities.snapshot()
    )


@dataclass(frozen=True)
class _RepositoryAdapters:
    conversation: ConversationStore
    runs: RunStore
    ownership: OwnershipStore
    memory: MemoryStore


def _build_repository_adapters(runtime: PersistenceRuntime) -> _RepositoryAdapters:
    """唯一 adapter 装配点：平台只提供资源，feature adapter 在此绑定。"""

    if runtime.status.mode == "durable":
        pool = runtime.postgresql_pool
        conversation = PostgresConversationRuntimeStore(pool)
        return _RepositoryAdapters(
            conversation=conversation,
            runs=conversation,
            ownership=PostgresOwnershipStore(pool),
            memory=PostgresMemoryStore(pool),
        )

    state = TemporaryPlatformState()
    conversation = TemporaryConversationRuntimeStore(state)
    return _RepositoryAdapters(
        conversation=conversation,
        runs=conversation,
        ownership=TemporaryOwnershipStore(state),
        memory=TemporaryMemoryStore(durable=False),
    )


def _build_ownership(store: OwnershipStore, config: AppConfig) -> OwnershipService:
    configured = config.auth.jwt_secret.get_secret_value()
    secret = (
        configured if len(configured.encode("utf-8")) >= 32 else temporary_jwt_secret()
    )
    return OwnershipService(
        store,
        Argon2PasswordHasher(),
        JwtAccessTokenCodec(
            secret,
            issuer=config.auth.issuer,
            audience=config.auth.audience,
        ),
    )
