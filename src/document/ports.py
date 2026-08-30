"""M08 文档库领域端口：documents / versions / chunks 三份协议（per-owner）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

DocumentStatus = Literal[
    "uploaded", "parsing", "chunking", "indexing", "ready", "failed", "deleted"
]
DocumentSource = Literal["agent_generated", "user_upload"]


@dataclass(frozen=True)
class DocumentRecord:
    """一份文档的当前状态与进度（索引进度 = indexed_count/chunk_count）。"""

    document_id: str
    owner_id: str
    title: str
    doc_type: str = "note"
    source: DocumentSource = "agent_generated"
    status: DocumentStatus = "uploaded"
    failure_reason: str | None = None
    chunk_count: int = 0
    indexed_count: int = 0
    created_by: str = "agent"
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class DocumentVersion:
    """不可变内容版本；重传 = 新版本 + 重新 Ingest。"""

    version_id: str
    document_id: str
    owner_id: str
    version: int
    content_md: str
    summary: str | None = None
    metadata: dict | None = None
    doc_hash: str = ""
    created_at: datetime | None = None


@dataclass(frozen=True)
class RagChunk:
    """small-to-big 子块：content 为子块，parent_content 检索回填优先。"""

    id: int | None = None
    owner_id: str = ""
    document_id: str = ""
    version_id: str = ""
    chunk_idx: int = 0
    content: str = ""
    parent_content: str | None = None
    section: str | None = None
    doc_hash: str = ""
    created_at: datetime | None = None


class DocumentStore(Protocol):
    """文档库持久化协议（owner_id 全链携带，跨 owner 一律空结果）。"""

    durable: bool = True

    def create_document(self, record: DocumentRecord) -> DocumentRecord: ...

    def create_version(self, version: DocumentVersion) -> DocumentVersion: ...

    def upsert_chunks(self, owner_id: str, chunks: list[RagChunk]) -> int: ...

    def update_document_status(
        self,
        owner_id: str,
        document_id: str,
        status: DocumentStatus,
        *,
        failure_reason: str | None = None,
        chunk_count: int | None = None,
        indexed_count: int | None = None,
    ) -> DocumentRecord | None: ...

    def get_document(self, owner_id: str, document_id: str) -> DocumentRecord | None: ...

    def list_documents(
        self,
        owner_id: str,
        *,
        status: DocumentStatus | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> tuple[DocumentRecord, ...]: ...

    def get_version(
        self, owner_id: str, version_id: str
    ) -> DocumentVersion | None: ...

    def latest_version(
        self, owner_id: str, document_id: str
    ) -> DocumentVersion | None: ...

    def chunks_by_doc_hash(
        self, owner_id: str, doc_hash: str
    ) -> tuple[RagChunk, ...]: ...

    def chunks_by_document(
        self, owner_id: str, document_id: str
    ) -> tuple[RagChunk, ...]: ...

    def resolve_chunks(
        self, owner_id: str, chunk_ids: list[int]
    ) -> tuple[tuple[RagChunk, str | None], ...]:
        """按 pg id 批量回查 chunk 与所属文档标题（检索侧回填溯源）。"""

    def delete_document(
        self, owner_id: str, document_id: str, now: datetime
    ) -> bool: ...

    def purge_document(
        self, owner_id: str, document_id: str
    ) -> tuple[int, ...]:
        """硬删：先删 chunk 返回其自增 id（供外部索引级联删除），再删文档。"""


class DocumentStoreError(RuntimeError):
    """文档库持久化错误（HTTP 层映射 5xx）。"""
