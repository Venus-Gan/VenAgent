"""配置 schema。

该模块只描述可序列化配置，不创建连接、线程、client 或其他运行时对象。
"""

from typing import Annotated, Tuple

from pydantic import BaseModel, ConfigDict, Field, SecretStr as PydanticSecretStr, model_validator


SecretString = Annotated[PydanticSecretStr, Field(json_schema_extra={"secret": True})]


class FrozenConfig(BaseModel):
    """所有配置节点共享的严格、不可变基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class LLMConfig(FrozenConfig):
    api_url: str = ""
    api_key: SecretString = PydanticSecretStr("")
    model: str = ""
    temperature: float = Field(default=0.7, ge=0, le=2)


class EmbeddingConfig(FrozenConfig):
    api_url: str = ""
    api_key: SecretString = PydanticSecretStr("")
    model: str = ""


class MilvusConfig(FrozenConfig):
    host: str = ""
    port: int = Field(default=19530, ge=1, le=65535)


class PostgresConfig(FrozenConfig):
    host: str = ""
    port: int = Field(default=5432, ge=1, le=65535)
    user: str = ""
    password: SecretString = PydanticSecretStr("")
    database: str = ""


class ElasticsearchConfig(FrozenConfig):
    addresses: Tuple[str, ...] = ()
    username: str = ""
    password: SecretString = PydanticSecretStr("")


class KafkaConfig(FrozenConfig):
    brokers: Tuple[str, ...] = ()
    topic: str = ""


class Neo4jConfig(FrozenConfig):
    uri: str = ""
    user: str = ""
    password: SecretString = PydanticSecretStr("")
    max_hops: int = Field(default=2, ge=1)
    weight: float = Field(default=0.3, ge=0, le=1)
    enabled: bool = False


class RewriteConfig(FrozenConfig):
    enabled: bool = False
    num_queries: int = Field(default=3, ge=1)


class RerankConfig(FrozenConfig):
    enabled: bool = False
    preview_len: int = Field(default=200, ge=1)


class RAGConfig(FrozenConfig):
    chunk_size: int = Field(default=200, ge=1)
    chunk_overlap: int = Field(default=50, ge=0)
    top_k: int = Field(default=3, ge=1)
    rrf_constant_k: int = Field(default=60, ge=1)
    semantic_weight: float = Field(default=0.7, ge=0, le=1)
    enable_hybrid_search: bool = False
    rag_milvus_dim: int = Field(default=1024, ge=1)
    rewrite: RewriteConfig = Field(default_factory=RewriteConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)

    @model_validator(mode="after")
    def validate_chunk_window(self) -> "RAGConfig":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("rag.chunk_overlap must be smaller than rag.chunk_size")
        return self


class MemoryConsolidationConfig(FrozenConfig):
    similarity_threshold: float = Field(default=0.80, ge=0, le=1)
    dedup_threshold: float = Field(default=0.95, ge=0, le=1)
    ttl_days: int = Field(default=30, ge=1)
    decay_rate: float = Field(default=0.995, ge=0, le=1)
    min_importance: float = Field(default=0.3, ge=0, le=1)
    trigger_interval: int = Field(default=5, ge=1)


class MemoryConfig(FrozenConfig):
    short_term_max_turns: int = Field(default=5, ge=1)
    long_term_top_k: int = Field(default=3, ge=1)
    consolidation: MemoryConsolidationConfig = Field(default_factory=MemoryConsolidationConfig)


class HarnessConfig(FrozenConfig):
    max_retries: int = Field(default=3, ge=0)
    retry_delay_ms: int = Field(default=200, ge=0)
    step_timeout_ms: int = Field(default=5000, ge=1)
    max_iterations: int = Field(default=5, ge=1)


class GraphRuntimeConfig(FrozenConfig):
    max_parallel: int = Field(default=2, ge=1)
    race_timeout_ms: int = Field(default=30000, ge=1)
    enable_racing: bool = True


class SearchConfig(FrozenConfig):
    api_key: SecretString = PydanticSecretStr("")
    api_url: str = ""


class ServerConfig(FrozenConfig):
    port: int = Field(default=8090, ge=1, le=65535)
    cors_origins: Tuple[str, ...] = ()


class SandboxConfig(FrozenConfig):
    enabled: bool = False
    backend: str = "docker"
    image: str = "ubuntu:22.04"
    timeout_ms: int = Field(default=30000, ge=1)
    max_output_bytes: int = Field(default=65536, ge=1)
    memory_limit_mb: int = Field(default=256, ge=1)
    cpu_percent: int = Field(default=50, ge=1, le=100)
    max_pids: int = Field(default=64, ge=1)
    network_disabled: bool = True
    readonly_rootfs: bool = True


class SecurityConfig(FrozenConfig):
    max_command_length: int = Field(default=500, ge=1)
    allowlist_mode: bool = False
    allowlist: Tuple[str, ...] = ()


class AppConfig(FrozenConfig):
    """完整应用配置；实例化后不允许修改任何层级。"""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    milvus: MilvusConfig = Field(default_factory=MilvusConfig)
    postgres: PostgresConfig = Field(default_factory=PostgresConfig)
    elasticsearch: ElasticsearchConfig = Field(default_factory=ElasticsearchConfig)
    kafka: KafkaConfig = Field(default_factory=KafkaConfig)
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    harness: HarnessConfig = Field(default_factory=HarnessConfig)
    graph_runtime: GraphRuntimeConfig = Field(default_factory=GraphRuntimeConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
