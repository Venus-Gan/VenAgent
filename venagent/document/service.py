"""M08 文档库服务：状态机 + 版本化 + small-to-big 切分 + 删除级联。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

from ..config import DocumentConfig, RagConfig
from ..rag.splitter import RecursiveSplitter
from .parser import DocumentParseError, parse_document
from .ports import (
    DocumentRecord,
    DocumentStore,
    DocumentStoreError,
    DocumentVersion,
    RagChunk,
)

LOGGER = logging.getLogger("venagent.document")


class DocumentUploadError(ValueError):
    """上传请求不合法（HTTP 层映射 413/422）。"""

    def __init__(self, message: str, code: str = "document_empty") -> None:
        super().__init__(message)
        self.code = code


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:16]}"


def _doc_hash(content: bytes) -> str:
    return sha256(content).hexdigest()


class DocumentService:
    """文档库单一入口：上传/重传/列表/删除；失败状态可删除重传。"""

    def __init__(
        self,
        store: DocumentStore,
        document_config: DocumentConfig,
        rag_config: RagConfig,
        kg_writer: Callable[..., Any] | None = None,
        indexer: Any | None = None,
    ) -> None:
        self._store = store
        self._document_config = document_config
        self._rag_config = rag_config
        self._kg_writer = kg_writer
        self._indexer = indexer

    # ── 上传与 Ingest ───────────────────────────────────────────────────

    def upload(
        self,
        owner_id: str,
        *,
        filename: str,
        content: bytes,
        title: str | None = None,
        source: str = "user_upload",
        created_by: str = "agent",
    ) -> DocumentRecord:
        self._validate_upload(content)
        document_id = _new_id("doc_")
        now = datetime.now(timezone.utc)
        document = self._store.create_document(
            DocumentRecord(
                document_id=document_id,
                owner_id=owner_id,
                title=title or filename,
                doc_type="text",
                source=source,  # type: ignore[arg-type]
                status="uploaded",
                created_by=created_by,
                created_at=now,
                updated_at=now,
            )
        )
        return self._ingest(document, filename=filename, content=content)

    def reingest(
        self,
        owner_id: str,
        document_id: str,
        *,
        filename: str,
        content: bytes,
    ) -> DocumentRecord:
        """同 document 重传 = 追加不可变版本 + 重新 Ingest（版本化语义）。"""
        self._validate_upload(content)
        document = self._store.get_document(owner_id, document_id)
        if document is None:
            raise DocumentStoreError("document not found")
        return self._ingest(
            document, filename=filename, content=content, next_version=True
        )

    def _validate_upload(self, content: bytes) -> None:
        if len(content) > self._document_config.max_upload_bytes:
            raise DocumentUploadError("上传文档超过 64MB 上限", code="document_too_large")
        if not content:
            raise DocumentUploadError("上传文档为空", code="document_empty")

    def _ingest(
        self,
        document: DocumentRecord,
        *,
        filename: str,
        content: bytes,
        next_version: bool = False,
    ) -> DocumentRecord:
        owner_id = document.owner_id
        document_id = document.document_id
        try:
            parsed = parse_document(filename, content, self._document_config)
        except DocumentParseError as exc:
            return self._fail(owner_id, document_id, exc.reason)
        if not parsed.text.strip():
            return self._fail(owner_id, document_id, "empty")

        previous = (
            self._store.latest_version(owner_id, document_id)
            if next_version
            else None
        )
        version_number = 1 if previous is None else previous.version + 1
        version = self._store.create_version(
            DocumentVersion(
                version_id=_new_id("ver_"),
                document_id=document_id,
                owner_id=owner_id,
                version=version_number,
                content_md=parsed.text,
                doc_hash=_doc_hash(content),
                created_at=datetime.now(timezone.utc),
            )
        )
        self._store.update_document_status(owner_id, document_id, "parsing")
        self._store.update_document_status(owner_id, document_id, "chunking")
        chunks = self._chunk_text(
            parsed.text,
            document_id=document_id,
            owner_id=owner_id,
            doc_hash=version.doc_hash,
            version_id=version.version_id,
        )
        # 版本化：新版本 Ingest 前清掉旧版本 chunks，检索只对应最新版本。
        # 旧版本 chunk 的 pg id 在 upsert 前读取，供索引级联清理。
        previous_chunks = (
            self._store.chunks_by_document(owner_id, document_id)
            if next_version
            else ()
        )
        self._store.upsert_chunks(owner_id, chunks)
        self._store.update_document_status(owner_id, document_id, "indexing")
        stored = self._store.chunks_by_document(owner_id, document_id)
        if self._indexer is not None and stored:
            try:
                self._indexer.index_chunks(owner_id, list(stored))
            except Exception:
                return self._fail(owner_id, document_id, "index_failed")
            if next_version:
                old_ids = [
                    chunk.id
                    for chunk in previous_chunks
                    if chunk.id is not None
                ]
                if old_ids:
                    self._delete_indexed(owner_id, document_id, old_ids)
        self._store.update_document_status(
            owner_id,
            document_id,
            "ready",
            chunk_count=len(stored),
            indexed_count=len(stored),
        )
        self._write_kg(
            owner_id,
            document_id,
            version.content_md,
            [chunk.id for chunk in chunks if chunk.id is not None],
        )
        return self._store.get_document(owner_id, document_id) or document

    def _write_kg(
        self, owner_id: str, document_id: str, text: str, chunk_ids: list[int]
    ) -> None:
        """KG 建图（同步，文档级）；失败仅告警，不阻塞文档状态。"""
        if self._kg_writer is None:
            return
        try:
            self._kg_writer(owner_id, document_id, text, chunk_ids)
        except Exception:
            LOGGER.warning(
                "RAG KG 建图失败（不影响文档）：%s",
                document_id,
                extra={
                    "component": "document",
                    "state": "degraded",
                    "reason_code": "kg_write_failed",
                },
            )

    def _fail(
        self, owner_id: str, document_id: str, reason: str
    ) -> DocumentRecord:
        failed = self._store.update_document_status(
            owner_id, document_id, "failed", failure_reason=reason
        )
        return failed or self._store.get_document(owner_id, document_id)

    def _chunk_text(
        self,
        text: str,
        *,
        document_id: str,
        owner_id: str,
        doc_hash: str,
        version_id: str,
    ) -> list[RagChunk]:
        cfg = self._rag_config
        child_size = cfg.chunk_size
        child_overlap = cfg.chunk_overlap
        parent_size = max(cfg.chunk_size * cfg.parent_multiplier, 600)
        parent_overlap = cfg.chunk_overlap * 2
        parent_splitter = RecursiveSplitter(parent_size, parent_overlap)
        child_splitter = RecursiveSplitter(child_size, child_overlap)

        chunks: list[RagChunk] = []
        index = 0
        created_at = datetime.now(timezone.utc)
        for parent in parent_splitter.split(text):
            for child in child_splitter.split(parent):
                chunks.append(
                    RagChunk(
                        owner_id=owner_id,
                        document_id=document_id,
                        version_id=version_id,
                        chunk_idx=index,
                        content=child,
                        parent_content=parent,
                        section=_first_heading(parent),
                        doc_hash=doc_hash,
                        created_at=created_at,
                    )
                )
                index += 1
        return chunks

    # ── 查询 ────────────────────────────────────────────────────────────

    def get(self, owner_id: str, document_id: str) -> DocumentRecord | None:
        return self._store.get_document(owner_id, document_id)

    def list(
        self,
        owner_id: str,
        *,
        status: str | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> tuple[DocumentRecord, ...]:
        return self._store.list_documents(
            owner_id, status=status, before=before, limit=limit
        )

    def latest_version(
        self, owner_id: str, document_id: str
    ) -> DocumentVersion | None:
        return self._store.latest_version(owner_id, document_id)

    def chunks(self, owner_id: str, document_id: str) -> tuple[RagChunk, ...]:
        return self._store.chunks_by_document(owner_id, document_id)

    # ── 删除 ────────────────────────────────────────────────────────────

    def delete(self, owner_id: str, document_id: str) -> tuple[int, ...]:
        """软删 + 硬删；返回被删 chunk 的 pg id 供外部索引级联（P3 挂接）。"""
        now = datetime.now(timezone.utc)
        if not self._store.delete_document(owner_id, document_id, now):
            raise DocumentStoreError("document not found")
        chunk_ids = self._store.purge_document(owner_id, document_id)
        if self._indexer is not None and chunk_ids:
            self._delete_indexed(owner_id, document_id, list(chunk_ids))
        return chunk_ids

    def _delete_indexed(
        self, owner_id: str, document_id: str, chunk_ids: list[int]
    ) -> None:
        """索引级联删除：失败仅告警（chunk ids 已返回，可观测不静默）。"""
        try:
            self._indexer.delete_chunks(owner_id, chunk_ids)
        except Exception:
            LOGGER.warning(
                "RAG 索引级联删除失败（PG 已删，外部索引可能残留）：%s",
                document_id,
                extra={
                    "component": "document",
                    "state": "degraded",
                    "reason_code": "index_delete_failed",
                },
            )


def _first_heading(parent: str) -> str | None:
    """取父块首个 Markdown 标题文本作为 section 溯源（无标题返回 None）。"""
    for line in parent.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return None
