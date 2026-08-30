"""测试专用 in-memory DocumentStore 双（生产代码库不建内存镜像）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.document.ports import (
    DocumentRecord,
    DocumentStoreError,
    DocumentVersion,
    RagChunk,
)


class InMemoryDocumentStore:
    durable = True

    def __init__(self) -> None:
        self._documents: dict[str, DocumentRecord] = {}
        self._versions: dict[str, DocumentVersion] = {}
        self._chunks: dict[int, RagChunk] = {}
        self._next_chunk_id = 1
        self._last_now: datetime | None = None

    def _tick(self) -> datetime:
        """单调递增时钟：镜像 PG now()（每次 status 更新刷新 updated_at）。"""
        now = datetime.now(timezone.utc)
        if self._last_now is not None and now <= self._last_now:
            now = self._last_now + timedelta(microseconds=1)
        self._last_now = now
        return now

    def create_document(self, record: DocumentRecord) -> DocumentRecord:
        self._documents[record.document_id] = record
        return record

    def create_version(self, version: DocumentVersion) -> DocumentVersion:
        self._versions[version.version_id] = version
        return version

    def upsert_chunks(self, owner_id: str, chunks: list[RagChunk]) -> int:
        if not chunks:
            return 0
        document_id = chunks[0].document_id
        version_id = chunks[0].version_id
        # 版本化：同 document 旧版本 chunks 只留最新版本。
        self._chunks = {
            key: chunk
            for key, chunk in self._chunks.items()
            if not (
                chunk.owner_id == owner_id
                and chunk.document_id == document_id
                and chunk.version_id != version_id
            )
        }
        for chunk in chunks:
            row = RagChunk(
                id=self._next_chunk_id,
                owner_id=chunk.owner_id,
                document_id=chunk.document_id,
                version_id=chunk.version_id,
                chunk_idx=chunk.chunk_idx,
                content=chunk.content,
                parent_content=chunk.parent_content,
                section=chunk.section,
                doc_hash=chunk.doc_hash,
                created_at=chunk.created_at or datetime.now(),
            )
            self._chunks[row.id] = row
            self._next_chunk_id += 1
        return len(chunks)

    def update_document_status(
        self,
        owner_id: str,
        document_id: str,
        status: str,
        *,
        failure_reason: str | None = None,
        chunk_count: int | None = None,
        indexed_count: int | None = None,
    ) -> DocumentRecord | None:
        record = self._documents.get(document_id)
        if record is None or record.owner_id != owner_id:
            return None
        updated = DocumentRecord(
            document_id=record.document_id,
            owner_id=record.owner_id,
            title=record.title,
            doc_type=record.doc_type,
            source=record.source,
            status=status,  # type: ignore[arg-type]
            failure_reason=(
                failure_reason
                if failure_reason is not None
                else record.failure_reason
            ),
            chunk_count=(
                chunk_count if chunk_count is not None else record.chunk_count
            ),
            indexed_count=(
                indexed_count
                if indexed_count is not None
                else record.indexed_count
            ),
            created_by=record.created_by,
            created_at=record.created_at,
            updated_at=self._tick(),
        )
        self._documents[document_id] = updated
        return updated

    def get_document(self, owner_id: str, document_id: str) -> DocumentRecord | None:
        record = self._documents.get(document_id)
        if record is None or record.owner_id != owner_id:
            return None
        return record

    def list_documents(
        self,
        owner_id: str,
        *,
        status: str | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> tuple[DocumentRecord, ...]:
        items = [
            record
            for record in self._documents.values()
            if record.owner_id == owner_id
            and (status is None or record.status == status)
            and (before is None or (record.updated_at or datetime.min) < before)
        ]
        items.sort(key=lambda item: (item.updated_at or datetime.min), reverse=True)
        return tuple(items[:limit])

    def get_version(
        self, owner_id: str, version_id: str
    ) -> DocumentVersion | None:
        version = self._versions.get(version_id)
        if version is None or version.owner_id != owner_id:
            return None
        return version

    def latest_version(
        self, owner_id: str, document_id: str
    ) -> DocumentVersion | None:
        candidates = [
            version
            for version in self._versions.values()
            if version.owner_id == owner_id and version.document_id == document_id
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda version: version.version)

    def chunks_by_doc_hash(
        self, owner_id: str, doc_hash: str
    ) -> tuple[RagChunk, ...]:
        return tuple(
            sorted(
                (
                    chunk
                    for chunk in self._chunks.values()
                    if chunk.owner_id == owner_id and chunk.doc_hash == doc_hash
                ),
                key=lambda chunk: chunk.chunk_idx,
            )
        )

    def chunks_by_document(
        self, owner_id: str, document_id: str
    ) -> tuple[RagChunk, ...]:
        return tuple(
            sorted(
                (
                    chunk
                    for chunk in self._chunks.values()
                    if chunk.owner_id == owner_id
                    and chunk.document_id == document_id
                ),
                key=lambda chunk: chunk.chunk_idx,
            )
        )

    def resolve_chunks(
        self, owner_id: str, chunk_ids: list[int]
    ) -> tuple[tuple[RagChunk, str | None], ...]:
        found = [
            self._chunks[chunk_id]
            for chunk_id in chunk_ids
            if chunk_id in self._chunks
            and self._chunks[chunk_id].owner_id == owner_id
        ]
        return tuple(
            (
                chunk,
                self._documents.get(chunk.document_id).title
                if chunk.document_id in self._documents
                else None,
            )
            for chunk in found
        )

    def delete_document(
        self, owner_id: str, document_id: str, now: datetime
    ) -> bool:
        record = self._documents.get(document_id)
        if record is None or record.owner_id != owner_id or record.status == "deleted":
            return False
        updated = DocumentRecord(
            document_id=record.document_id,
            owner_id=record.owner_id,
            title=record.title,
            doc_type=record.doc_type,
            source=record.source,
            status="deleted",
            failure_reason=record.failure_reason,
            chunk_count=record.chunk_count,
            indexed_count=record.indexed_count,
            created_by=record.created_by,
            created_at=record.created_at,
            updated_at=now,
        )
        self._documents[document_id] = updated
        return True

    def purge_document(self, owner_id: str, document_id: str) -> tuple[int, ...]:
        ids = tuple(
            chunk.id
            for chunk in self._chunks.values()
            if chunk.owner_id == owner_id and chunk.document_id == document_id
        )
        self._chunks = {
            key: chunk
            for key, chunk in self._chunks.items()
            if not (
                chunk.owner_id == owner_id and chunk.document_id == document_id
            )
        }
        self._versions = {
            key: version
            for key, version in self._versions.items()
            if not (
                version.owner_id == owner_id
                and version.document_id == document_id
            )
        }
        self._documents.pop(document_id, None)
        return ids


class FailingDocumentStore(InMemoryDocumentStore):
    """删除路径失败注入：验证 service 抛 DocumentStoreError。"""

    def purge_document(self, owner_id: str, document_id: str) -> tuple[int, ...]:
        raise DocumentStoreError("purge failed")
