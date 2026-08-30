"""VenAgent 唯一 composition root。"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent.planning import (
    DocAgent,
    PlanningRuntime,
    ResearchAgent,
    ReviewAgent,
    SubAgentRegistry,
    WriterAgent,
)
from .agent.ports import MessageInvoker, RunStore
from .agent.runtime import MEMORY_LONG_TERM_DEADLINE_SECONDS, AgentRuntime
from .command.mcp_adapter import McpCommandAdapter as McpCommandCommands
from .command.memory_adapter import MemoryCommandAdapter as UnifiedMemoryCommandAdapter
from .command.rag_adapter import RagCommandAdapter
from .command.registry import CommandRegistry
from .config import AppConfig, get_runtime_config
from .conversation.ports import ConversationStore
from .conversation.service import ConversationService
from .document import DocumentService
from .document.ports import DocumentStore as DocumentStorePort
from .llm.embeddings import HttpEmbeddingClient
from .llm.factory import (
    build_memory_extractor_model,
    build_rerank_model,
    build_rewrite_model,
    build_runtime_model,
)
from .mcp.catalog import McpToolCatalog
from .mcp.client import McpClientManager
from .mcp.config import McpConfigStore
from .mcp.executor import McpToolExecutor
from .memory.embedding import MemoryIndex
from .memory.management import (
    MemoryCapabilityRegistry,
    MemoryCapabilityStatus,
    MemoryCommandAdapter,
    MemorySettings,
)
from .memory.model_adapters import (
    LangChainConflictJudge,
    LangChainMemoryExtractor,
    LangChainSummaryBuilder,
)
from .memory.ports import (
    G1RecallSnapshot,
    MemoryStore,
    MemoryStoreError,
)
from .memory.service import MemoryService
from .ownership.authorization import RunAuthorizationPolicy
from .ownership.ports import OwnershipStore
from .ownership.service import OwnershipService
from .platform.es import ESRuntime, build_es_runtime
from .platform.milvus import MilvusRuntime, build_milvus_runtime
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
)
from .platform.security import Argon2PasswordHasher, JwtAccessTokenCodec
from .platform.security.tokens import temporary_jwt_secret
from .rag import (
    HybridSearchService,
    LangChainKgExtractor,
    LangChainQueryRewriter,
    LangChainReranker,
    build_routes,
)
from .repo.inmemory import (
    InMemoryConversationRuntimeStore,
    InMemoryOwnershipStore,
    InMemoryPlatformState,
)
from .repo.neo4j.rag_kg import RagKgStore
from .repo.postgresql import PostgresConversationRuntimeStore, PostgresOwnershipStore
from .repo.postgresql.document import PostgresDocumentStore
from .repo.postgresql.memory import PostgresMemoryStore
from .sandbox.docker import DockerSandboxRuntime
from .skills.catalog import SkillCatalog
from .skills.github import GitHubApiClient
from .skills.hub import SkillHubService
from .tools.approval import ApprovalService
from .tools.artifact_store import FileArtifactStore
from .tools.catalog import ToolCatalog
from .tools.control import ToolControlContext
from .tools.errors import ToolUnavailable
from .tools.exec_command import exec_command_descriptor, execute_exec_command
from .tools.executor import ToolExecutorRouter
from .tools.gateway import ToolGateway
from .tools.invocation_store import (
    EncryptedFileInvocationStore,
    InMemoryInvocationStore,
    decode_invocation_key,
)
from .tools.operation_store import OperationStore
from .tools.policy import DefaultToolPolicy
from .tools.rag_document_tools import (
    execute_list_documents,
    execute_rag_search,
    execute_read_document,
    execute_write_document,
    list_documents_descriptor,
    rag_search_descriptor,
    read_document_descriptor,
    write_document_descriptor,
)
from .tools.state_directory import StateDirectoryLease

logger = logging.getLogger(__name__)

EMBEDDING_RECALL_MARGIN_SECONDS = 0.5
MAX_EMBEDDING_RECALL_DEADLINE_SECONDS = 30.5
DEFAULT_MCP_CONFIG_PATH = Path(__file__).resolve().parent / "mcp" / "mcp-configs" / "mcp-servers.json"


@dataclass
class Application:
    service: ConversationService
    runtime: AgentRuntime
    ownership: OwnershipService
    memory: MemoryService
    memory_commands: MemoryCommandAdapter
    document_service: DocumentService | None
    rag_search: HybridSearchService | None
    command_registry: CommandRegistry
    memory_capabilities: MemoryCapabilityRegistry
    persistence: PersistenceRuntime
    graph: Neo4jRuntime
    milvus: MilvusRuntime
    es: ESRuntime
    config: AppConfig
    tool_control: ToolControlContext
    mcp_store: McpConfigStore
    mcp_manager: McpClientManager
    skill_hub: SkillHubService
    state_directory_lease: StateDirectoryLease | None = None

    async def open(self) -> None:
        if self.state_directory_lease is not None:
            self.state_directory_lease.acquire()
        try:
            await self.persistence.open()
            await self.graph.open()
            await self.milvus.open()
            await self.es.open()
        except BaseException:
            self.es.close()
            self.milvus.close()
            self.graph.close()
            self.persistence.close()
            if self.state_directory_lease is not None:
                self.state_directory_lease.release()
            raise

    async def aclose(self) -> None:
        try:
            await self.es.aclose()
            await self.milvus.aclose()
            await self.graph.aclose()
            await self.persistence.aclose()
        finally:
            if self.state_directory_lease is not None:
                self.state_directory_lease.release()

    def close(self) -> None:
        """释放尚未进入 FastAPI lifespan 的装配资源。"""
        try:
            self.es.close()
            self.milvus.close()
            self.graph.close()
            self.persistence.close()
        finally:
            if self.state_directory_lease is not None:
                self.state_directory_lease.release()

    @property
    def startup_report(self) -> StartupReport:
        return _startup_report(
            self.persistence.status,
            self.graph,
            self.milvus,
            self.es,
            self.memory_capabilities,
        )

    @property
    def health(self) -> dict[str, Any]:
        return _health(
            self.persistence.status,
            self.graph,
            self.milvus,
            self.es,
            self.memory_capabilities,
        )


def build_application(
    model: MessageInvoker | None = None,
    *,
    conversation_service: ConversationService | None = None,
    ownership_service: OwnershipService | None = None,
    persistence_runtime: PersistenceRuntime | None = None,
    config: AppConfig | None = None,
    tool_control: ToolControlContext | None = None,
    mcp_config_store: McpConfigStore | None = None,
    command_registry: CommandRegistry | None = None,
    mcp_manager: McpClientManager | None = None,
    skill_hub: SkillHubService | None = None,
) -> Application:
    config = config or get_runtime_config()
    persistence = persistence_runtime or build_persistence_runtime(
        {DATABASE_URL: config.persistence.database_url.get_secret_value()}
    )
    adapters = _build_repository_adapters(persistence)
    service = conversation_service or ConversationService(adapters.conversation)
    ownership = ownership_service or _build_ownership(adapters.ownership, config)
    cursor_secret = config.auth.jwt_secret.get_secret_value() or temporary_jwt_secret()
    main_model = model or build_runtime_model(config)
    extractor_model = build_memory_extractor_model(config, main_model)
    rewrite_model = build_rewrite_model(config, main_model)
    rerank_model = build_rerank_model(config, main_model)
    memory_capabilities = _memory_capability_registry(
        persistence.status,
        embedding_configured=config.embedding.enabled,
    )
    graph = build_neo4j_runtime(
        config.neo4j,
        memory_capabilities,
        authority_durable=persistence.status.mode == "durable",
    )
    milvus = build_milvus_runtime(
        config.milvus,
        memory_capabilities,
        authority_durable=persistence.status.mode == "durable",
    )
    es = build_es_runtime(
        config.es,
        memory_capabilities,
        authority_durable=persistence.status.mode == "durable",
    )
    embedding_client = (
        HttpEmbeddingClient(config.embedding)
        if config.embedding.enabled
        else None
    )
    kg_extractor = LangChainKgExtractor(main_model)
    document_service = _build_document_service(
        adapters,
        config,
        milvus_client=milvus.client,
        es_client=es.client,
        embedding=embedding_client,
        kg_store=(
            RagKgStore(graph.driver, database=graph.database)
            if graph.driver is not None
            else None
        ),
        kg_extractor=kg_extractor,
    )
    rag_search = _build_rag_search(
        adapters,
        config,
        milvus,
        es,
        graph,
        rewrite_model,
        rerank_model,
        embedding=embedding_client,
        kg_extractor=kg_extractor,
    )
    memory_index = (
        MemoryIndex(
            adapters.memory,
            embedding_client,
            model=config.embedding.model,
        )
        if embedding_client is not None
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
        conversation=adapters.conversation,
        window_messages=config.memory_consolidation.window_messages,
        idle_seconds=config.memory_consolidation.idle_seconds,
        max_input_tokens=config.memory_consolidation.max_input_tokens,
    )
    mcp_store = mcp_config_store or McpConfigStore(DEFAULT_MCP_CONFIG_PATH)
    mcp_store.ensure_defaults()
    mcp_catalog = McpToolCatalog(mcp_store.load())
    mcp_manager = mcp_manager or McpClientManager(
        credentials=dict(config.mcp.credentials),
        allowed_commands=tuple(config.mcp.allowed_commands),
    )
    skill_hub = skill_hub or SkillHubService(
        GitHubApiClient(),
        token=config.github.token.get_secret_value() or None,
    )
    state_directory_lease: StateDirectoryLease | None = None
    if tool_control is None:
        policy = DefaultToolPolicy().as_exposure_policy()
        catalog = ToolCatalog(policy)
        catalog.register(exec_command_descriptor())
        if rag_search is not None:
            catalog.register(
                rag_search_descriptor(available=rag_search.mode != "unavailable")
            )
        if document_service is not None:
            catalog.register(write_document_descriptor())
            catalog.register(list_documents_descriptor())
            catalog.register(read_document_descriptor())
        sandbox = DockerSandboxRuntime(
            image=config.sandbox.image, disabled=config.sandbox.disabled
        )
        state_dir = mcp_store.path.parent / "state"
        if persistence.status.mode == "durable":
            state_directory_lease = StateDirectoryLease(state_dir)
        try:
            approvals = ApprovalService(path=state_dir / "approvals.json")
            operations = OperationStore(path=state_dir / "operations.json")
            artifact_store = FileArtifactStore(state_dir / "artifacts")
            executor_router = ToolExecutorRouter()

            async def native_executor(
                descriptor, arguments, run_id, owner_id=None
            ):
                if descriptor.tool_id == "exec_command":
                    return await execute_exec_command(
                        sandbox, descriptor, arguments, run_id
                    )
                if descriptor.tool_id == "rag_search":
                    return await execute_rag_search(
                        rag_search, descriptor, arguments, run_id, owner_id or ""
                    )
                if descriptor.tool_id == "write_document":
                    return await execute_write_document(
                        document_service, descriptor, arguments, run_id, owner_id or ""
                    )
                if descriptor.tool_id == "list_documents":
                    return await execute_list_documents(
                        document_service, descriptor, arguments, run_id, owner_id or ""
                    )
                if descriptor.tool_id == "read_document":
                    return await execute_read_document(
                        document_service, descriptor, arguments, run_id, owner_id or ""
                    )
                raise ToolUnavailable(descriptor.tool_id)

            executor_router.register("native", native_executor)
            executor_router.register(
                "mcp", McpToolExecutor(mcp_store, mcp_manager)
            )

            gateway = ToolGateway(
                operations=operations,
                approvals=approvals,
                executor=executor_router,
                artifact_store=artifact_store,
                run_authorizer=RunAuthorizationPolicy(adapters.runs).authorize,
                # rag_search 含改写+多路检索+重排多次 LLM 调用，30s 默认值实测不够。
                timeout_seconds=60.0,
            )
            tool_control = ToolControlContext(
                catalog=catalog,
                sandbox=sandbox,
                skills=SkillCatalog(root=state_dir / "skills"),
                gateway=gateway,
                approvals=approvals,
                operations=operations,
                snapshot_path=(
                    state_dir / "run-tool-snapshots.json"
                    if persistence.status.mode == "durable"
                    else None
                ),
                invocations=(
                    EncryptedFileInvocationStore(
                        state_dir / "invocations.json",
                        key=decode_invocation_key(
                            config.invocation.encryption_key.get_secret_value()
                        ),
                    )
                    if persistence.status.mode == "durable"
                    else InMemoryInvocationStore()
                ),
            )
        except BaseException:
            if state_directory_lease is not None:
                state_directory_lease.release()
            raise
    mcp_catalog.register_all(tool_control.catalog)
    tool_control.refresh_servers(
        mcp_store.load(), ready_servers=mcp_manager.ready_servers()
    )
    legacy_memory_commands = MemoryCommandAdapter(memory)
    subagent_registry = SubAgentRegistry()
    subagent_registry.register(ResearchAgent(main_model))
    subagent_registry.register(WriterAgent(main_model))
    subagent_registry.register(ReviewAgent(main_model))
    subagent_registry.register(DocAgent())
    planning_runtime = PlanningRuntime(
        model=main_model,
        tool_control=tool_control,
        registry=subagent_registry,
        rag_search=rag_search,
        planning_config=config.planning,
    )
    runtime = AgentRuntime(
        main_model,
        persistence.checkpointer,
        adapters.runs,
        memory=memory,
        tool_control=tool_control,
        planning=planning_runtime,
        memory_long_term_deadline=_memory_long_term_deadline(config),
    )
    tool_control.gateway.set_event_sink(runtime.publish_tool_event)
    if command_registry is None:
        command_adapters = [
            UnifiedMemoryCommandAdapter(legacy_memory_commands),
            McpCommandCommands(mcp_store, mcp_catalog, mcp_manager.ready_servers),
        ]
        if rag_search is not None:
            command_adapters.insert(0, RagCommandAdapter(rag_search, main_model))
        command_registry = CommandRegistry(*command_adapters)
    return Application(
        service=service,
        runtime=runtime,
        ownership=ownership,
        memory=memory,
        memory_commands=legacy_memory_commands,
        document_service=document_service,
        rag_search=rag_search,
        command_registry=command_registry,
        memory_capabilities=memory_capabilities,
        persistence=persistence,
        graph=graph,
        milvus=milvus,
        es=es,
        config=config,
        tool_control=tool_control,
        mcp_store=mcp_store,
        mcp_manager=mcp_manager,
        skill_hub=skill_hub,
        state_directory_lease=state_directory_lease,
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
    milvus: MilvusRuntime,
    es: ESRuntime,
    capabilities: MemoryCapabilityRegistry,
) -> StartupReport:
    return StartupReport(
        mode=status.mode,
        infrastructure=(
            status.infrastructure,
            graph.infrastructure,
            milvus.infrastructure,
            es.infrastructure,
            *_memory_infrastructure(capabilities),
        ),
    )


def _health(
    status: PersistenceStatus,
    graph: Neo4jRuntime,
    milvus: MilvusRuntime,
    es: ESRuntime,
    capabilities: MemoryCapabilityRegistry,
) -> dict[str, Any]:
    health = status.as_health()
    for runtime in (graph, milvus, es):
        item = runtime.infrastructure
        health["infrastructure"][item.component] = {
            "status": item.health_status,
            "state": item.state.value,
            "reason_code": item.reason_code,
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
        *(
            MemoryCapabilityStatus(
                component,
                "healthy" if durable else "disabled",
                "memory_ready" if durable else "durable_identity_required",
            )
            for component in ("rag-dense", "rag-keyword")
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
        "rag-dense": "RAG dense 检索：文档块向量召回",
        "rag-keyword": "RAG keyword 检索：文档块 BM25 召回",
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
    document: DocumentStorePort | None = None


def _build_document_service(
    adapters: _RepositoryAdapters,
    config: AppConfig,
    *,
    milvus_client: Any | None = None,
    es_client: Any | None = None,
    embedding: Any | None = None,
    kg_store: Any | None = None,
    kg_extractor: Any | None = None,
) -> DocumentService | None:
    """文档库只随 durable 模式装配（PG 是文档与 chunk 的真相源）。

    indexer：PG chunk → Milvus/ES 索引写入（任一侧未配置即跳过该路）；
    kg_writer：文档级实体抽取 → Neo4j KG（失败仅告警，不阻塞文档状态）。
    """
    if adapters.document is None:
        return None
    indexer = None
    if (milvus_client is not None and embedding is not None) or (
        es_client is not None
    ):
        from .rag.indexer import RagIndexer

        indexer = RagIndexer(
            milvus_client=milvus_client,
            milvus_collection=config.milvus.collection,
            dim=config.milvus.dim,
            es_client=es_client,
            es_index=config.es.index,
            embedding=embedding,
        )
    kg_writer = None
    if kg_store is not None and kg_extractor is not None:

        def kg_writer(
            owner_id: str, document_id: str, text: str, chunk_ids: list[int]
        ) -> None:
            extraction = kg_extractor.extract(text)
            if extraction.entities:
                kg_store.write_extraction(
                    owner_id, document_id, extraction, chunk_ids
                )

    return DocumentService(
        adapters.document,
        config.document,
        config.rag,
        kg_writer=kg_writer,
        indexer=indexer,
    )


def _build_rag_search(
    adapters: _RepositoryAdapters,
    config: AppConfig,
    milvus: MilvusRuntime,
    es: ESRuntime,
    graph: Neo4jRuntime,
    rewrite_model: Any,
    rerank_model: Any,
    *,
    embedding: Any | None = None,
    kg_extractor: Any | None = None,
) -> HybridSearchService | None:
    """三路 RRF 检索；文档库/embedding 缺失时返回 None（/rag 命令不注册）。"""
    if adapters.document is None:
        return None
    
    # 查询重写启动校验：提前检测 astream 可用性（避免运行时才暴露配置错误）
    rewriter = None
    if config.rag.rewrite_enabled:
        if not hasattr(rewrite_model, "invoke"):
            logger.warning(
                "RAG query rewrite enabled but rewrite model lacks invoke method, disabling rewrite"
            )
        else:
            rewriter = LangChainQueryRewriter(
                rewrite_model, num_queries=config.rag.rewrite_num_queries
            )
    
    kg_store = (
        RagKgStore(graph.driver, database=graph.database)
        if graph.driver is not None
        else None
    )
    routes = build_routes(
        adapters.document,
        milvus_client=milvus.client,
        milvus_collection=config.milvus.collection,
        embedding=embedding,
        es_client=es.client,
        es_index=config.es.index,
        kg_store=kg_store,
        kg_extractor=kg_extractor,
        kg_max_hops=config.rag.kg_max_hops,
        top_k=max(2 * config.rag.top_k, 10),
    )
    return HybridSearchService(
        routes,
        config.rag,
        rewriter=rewriter,
        reranker=(
            LangChainReranker(rerank_model, preview_len=config.rag.rerank_preview_len)
            if config.rag.rerank_enabled
            else None
        ),
    )


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
            document=PostgresDocumentStore(pool),
        )

    state = InMemoryPlatformState()
    conversation = InMemoryConversationRuntimeStore(state)
    return _RepositoryAdapters(
        conversation=conversation,
        runs=conversation,
        ownership=InMemoryOwnershipStore(state),
        memory=_DisabledMemoryStore(),
        document=None,
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


class _DisabledMemoryStore:
    """非 durable 模式的 MemoryStore 端口占位：读返回安全空值，写显式抛出。"""

    durable = False

    def enabled(self, owner_id):
        del owner_id
        return True

    def settings(self, owner_id):
        del owner_id
        return MemorySettings(
            enabled=True, deletion_generation=0, purge_pending=False
        )

    def authority_revision(self, owner_id, tenant_id):
        del owner_id, tenant_id
        return 0

    def get_fact(self, owner_id, memory_id):
        del owner_id, memory_id
        return None

    def find_active_by_slot(self, owner_id, tenant_id, subject, slot):
        del owner_id, tenant_id, subject, slot
        return None

    def resolve_quarantine(self, owner_id, tenant_id, subject, slot, chosen_fact, now):
        del owner_id, tenant_id, subject, slot, chosen_fact, now
        raise MemoryStoreError("memory is unavailable in temporary mode")

    def save_fact(self, fact, source, now):
        del fact, source, now
        raise MemoryStoreError("memory is unavailable in temporary mode")

    def add_source(self, fact, source, now):
        del fact, source, now
        raise MemoryStoreError("memory is unavailable in temporary mode")

    def replace_fact(self, previous, replacement, source, now):
        del previous, replacement, source, now
        raise MemoryStoreError("memory is unavailable in temporary mode")

    def set_enabled(self, owner_id, enabled, now):
        del owner_id, enabled, now
        raise MemoryStoreError("memory is unavailable in temporary mode")

    def set_index_status(self, owner_id, memory_ids, status, now):
        del owner_id, memory_ids, status, now

    def list_facts(self, owner_id, tenant_id, *, before, limit):
        del owner_id, tenant_id, before, limit
        return ()

    def deactivate_fact(self, owner_id, memory_id, status, now):
        del owner_id, memory_id, status, now
        return False

    def delete_all(self, owner_id, now):
        del owner_id, now
        return 0

    def revoke_source(self, owner_id, source_ref, now):
        del owner_id, source_ref, now
        return 0

    def source_impact(self, owner_id, source_ref):
        del owner_id, source_ref
        return ()

    def issue_confirmation(
        self, owner_id, operation, target_ref, token_hash, state_hash, expires_at, now
    ):
        del owner_id, operation, target_ref, token_hash, state_hash, expires_at, now

    def confirm_delete_all(self, owner_id, token_hash, state_hash, now):
        del owner_id, token_hash, state_hash, now
        return None

    def confirm_revoke_source(self, owner_id, source_ref, token_hash, state_hash, now):
        del owner_id, source_ref, token_hash, state_hash, now
        return None

    def source(self, owner_id, source_ref):
        del owner_id, source_ref
        return None

    def active_facts(self, owner_id, tenant_id):
        del owner_id, tenant_id
        return ()

    def expire_due(self, now):
        del now
        return 0

    def upsert_consolidation_cursor(
        self, owner_id, tenant_id, conversation_id, sequence, now, deletion_generation
    ):
        del owner_id, tenant_id, conversation_id, sequence, now, deletion_generation
        return None

    def get_consolidation_cursor(self, owner_id, tenant_id, conversation_id):
        del owner_id, tenant_id, conversation_id
        return None

    def advance_consolidation_cursor(self, owner_id, conversation_id, sequence, now):
        del owner_id, conversation_id, sequence, now
        return False

    def find_idle_consolidations(self, now, idle_before, limit):
        del now, idle_before, limit
        return ()

    def recall_snapshot(self, owner_id, tenant_id):
        result = G1RecallSnapshot(
            owner_id, tenant_id, self.settings(owner_id), (), (), 0
        )
        del owner_id, tenant_id
        return result

    def get_summary(self, owner_id, conversation_id):
        del owner_id, conversation_id
        return None

    def save_summary(self, summary):
        del summary

    def enqueue_job(self, job):
        del job
        return False

    def claim_jobs(self, now, *, limit):
        del now, limit
        return ()

    def complete_job(self, job_id, claim_token, now):
        del job_id, claim_token, now
        return False

    def retry_job(self, job_id, claim_token, error_code, available_at, now):
        del job_id, claim_token, error_code, available_at, now
        return False

    def cancel_job(self, job_id, claim_token, now):
        del job_id, claim_token, now
        return False

    def requeue_failed(self, owner_id, now):
        del owner_id, now
        return 0

    def finish_purge(self, owner_id, generation, now):
        del owner_id, generation, now
        return False
