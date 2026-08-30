"""AppConfig 定义（P6 决策：配置模型与加载器分离）。

本模块只定义配置结构与校验规则，不负责读取文件/环境；
读取与合并语义在 `loader.py`。敏感字段一律 `SecretStr`，
校验错误只暴露字段路径，绝不回显秘密值。
"""

from __future__ import annotations

import math
from typing import Any, ClassVar
from urllib.parse import quote, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
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


class LLMProfileOverride(_StrictModel):
    """可选 LLM profile 覆盖段基类：留空复用主模型 / 只填 model 继承连接配置 / 独立 profile。"""

    _profile_label: ClassVar[str]

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
    def _validate_profile(self) -> "LLMProfileOverride":
        if not self.configured:
            return self
        if not self.model:
            raise ValueError(f"{self._profile_label}.model")
        if self.independent and (not self.provider or not self.api_key.get_secret_value()):
            raise ValueError(f"{self._profile_label} requires provider and api_key")
        return self


class RewriteModelOverride(LLMProfileOverride):
    """M08 RAG 查询改写模型覆盖（照 memory_extractor 三档语义）。"""

    _profile_label: ClassVar[str] = "rewrite_model"


class RerankModelOverride(LLMProfileOverride):
    """M08 RAG 精排模型覆盖（照 memory_extractor 三档语义）。"""

    _profile_label: ClassVar[str] = "rerank_model"


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


class MemoryConsolidationConfig(_StrictModel):
    """M05 沉淀式写入：攒批延迟写参数（D1/D7）。

    隐式记忆不再逐条抽取；用户消息先推进对话游标，攒满 ``window_messages``
    或静默超过 ``idle_seconds`` 后才入队一次 consolidate 任务抽取整窗。
    """

    window_messages: int = Field(default=5, ge=1)
    idle_seconds: int = Field(default=600, ge=60)
    max_input_tokens: int = Field(default=4000, ge=1000)


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


class SandboxConfig(_StrictModel):
    image: str = "ubuntu:22.04"
    # D1：VENAGENT_SANDBOX_DISABLED 迁入；True 时沙箱能力整体关闭（探测短路）。
    disabled: bool = False

    @field_validator("image")
    @classmethod
    def _validate_image(cls, value: str) -> str:
        if not value.strip() or any(char.isspace() for char in value):
            raise ValueError("sandbox.image")
        return value


class PersistenceConfig(_StrictModel):
    """PostgreSQL 连接参数；密码始终以秘密字段承载。"""

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


class MilvusConfig(_StrictModel):
    """M08 RAG dense 路：Milvus 向量存储（照 AGI-saber milvus 语义）。"""

    enabled: bool = False
    uri: str = "http://127.0.0.1:19530"
    user: str = ""
    password: SecretStr = SecretStr("")
    collection: str = "rag_chunks"
    dim: int = Field(default=2048, ge=1, le=65536)
    index_params: dict[str, Any] = Field(
        default_factory=lambda: {
            "index_type": "IVF_FLAT",
            "metric_type": "L2",  # 对齐 AGI-saber ragchunk.go:339（欧氏距离）
            "nlist": 128,
        }
    )
    timeout: float = Field(default=2.0, gt=0, le=30)


class ESConfig(_StrictModel):
    """M08 RAG keyword 路：Elasticsearch BM25 存储。"""

    enabled: bool = False
    uri: str = "http://127.0.0.1:9200"
    user: str = ""
    password: SecretStr = SecretStr("")
    index: str = "rag_chunks"
    timeout: float = Field(default=2.0, gt=0, le=30)


class DocumentConfig(_StrictModel):
    """M08 文档库上传与解析限制（照 AGI-saber 语义）。"""

    max_upload_bytes: int = Field(
        default=64 * 1024 * 1024, ge=1024, le=1024 * 1024 * 1024
    )
    max_pdf_pages: int = Field(default=200, ge=1, le=10000)
    # ocr_reject_threshold: 有效字符占比阈值（0.0-1.0），低于此值拒绝为扫描件
    ocr_reject_threshold: float = Field(default=0.3, ge=0.0, le=1.0)


class RagConfig(_StrictModel):
    """M08 三路 RRF 检索参数（配置名沿用 AGI-saber，默认值对齐 config.yaml）。"""

    chunk_size: int = Field(default=200, ge=16, le=100000)
    chunk_overlap: int = Field(default=50, ge=0, le=100000)
    parent_multiplier: int = Field(default=4, ge=1, le=100)
    top_k: int = Field(default=3, ge=1, le=100)
    fetch_k_multiplier: int = Field(default=2, ge=1, le=10)
    rrf_constant_k: int = Field(default=60, ge=1, le=1000)
    kg_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    rewrite_enabled: bool = True
    rewrite_num_queries: int = Field(default=3, ge=1, le=10)
    rerank_enabled: bool = True
    rerank_preview_len: int = Field(default=200, ge=16, le=100000)
    kg_max_hops: int = Field(default=2, ge=1, le=3)


class PlanningConfig(_StrictModel):
    """M07 计划层编排参数（对齐 AGI-saber graph config 实测默认值）。"""

    max_parallel: int = Field(default=2, ge=1, le=16)
    race_timeout_ms: int = Field(default=30000, ge=0, le=600000)
    max_replan: int = Field(default=2, ge=0, le=10)
    replan_append_limit: int = Field(default=3, ge=1, le=10)
    max_plan_nodes: int = Field(default=8, ge=1, le=32)


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


class InvocationConfig(_StrictModel):
    """M06 私有工具调用载荷加密配置。"""

    encryption_key: SecretStr = SecretStr("")

    @property
    def configured(self) -> bool:
        return bool(self.encryption_key.get_secret_value())


class GithubConfig(_StrictModel):
    """D1：GITHUB_TOKEN 迁入；可空 = skill hub 匿名访问（限速更低）。"""

    token: SecretStr = SecretStr("")


class McpConfig(_StrictModel):
    """D1：MCP 客户端面配置迁入。

    - `allowed_commands`: stdio 服务器可执行白名单（原 VENAGENT_MCP_ALLOWED_COMMANDS）。
    - `credentials`: credential_ref / env_refs 的值来源（ref 名 → 秘密值），
      缺键时客户端维持 `mcp_credential_missing` / `mcp_environment_ref_missing` 错误。
    """

    allowed_commands: list[str] = Field(
        default_factory=lambda: ["node", "python", "python3"]
    )
    credentials: dict[str, str] = Field(default_factory=dict)


class AppConfig(_StrictModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    invocation: InvocationConfig = Field(default_factory=InvocationConfig)
    memory_extractor: MemoryExtractorConfig = Field(default_factory=MemoryExtractorConfig)
    rewrite_model: RewriteModelOverride = Field(default_factory=RewriteModelOverride)
    rerank_model: RerankModelOverride = Field(default_factory=RerankModelOverride)
    memory_consolidation: MemoryConsolidationConfig = Field(
        default_factory=MemoryConsolidationConfig
    )
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    github: GithubConfig = Field(default_factory=GithubConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    milvus: MilvusConfig = Field(default_factory=MilvusConfig)
    es: ESConfig = Field(default_factory=ESConfig)
    document: DocumentConfig = Field(default_factory=DocumentConfig)
    rag: RagConfig = Field(default_factory=RagConfig)
    planning: PlanningConfig = Field(default_factory=PlanningConfig)

    @model_validator(mode="after")
    def _validate_extractor_inheritance(self) -> "AppConfig":
        if (
            self.memory_extractor.configured
            and not self.memory_extractor.independent
            and not self.llm.provider
        ):
            raise ValueError("memory_extractor.model requires a configured LLM profile")
        if (
            self.rewrite_model.configured
            and not self.rewrite_model.independent
            and not self.llm.provider
        ):
            raise ValueError("rewrite_model.model requires a configured LLM profile")
        if (
            self.rerank_model.configured
            and not self.rerank_model.independent
            and not self.llm.provider
        ):
            raise ValueError("rerank_model.model requires a configured LLM profile")
        return self
