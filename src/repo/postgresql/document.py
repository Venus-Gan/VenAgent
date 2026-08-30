"""PostgreSQL 文档库 adapter：documents / versions / chunks（per-owner 全链过滤）。"""

from __future__ import annotations

from datetime import datetime

from psycopg_pool import ConnectionPool

from ...document.ports import (
    DocumentRecord,
    DocumentVersion,
    RagChunk,
)
from ...document.ports import (
    DocumentStoreError as StoreError,
)


def _document(row: dict) -> DocumentRecord:
    return DocumentRecord(
        document_id=str(row["document_id"]),
        owner_id=str(row["owner_id"]),
        title=str(row["title"]),
        doc_type=str(row["doc_type"]),
        source=row["source"],
        status=row["status"],
        failure_reason=row["failure_reason"],
        chunk_count=int(row["chunk_count"]),
        indexed_count=int(row["indexed_count"]),
        created_by=str(row["created_by"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _version(row: dict) -> DocumentVersion:
    return DocumentVersion(
        version_id=str(row["version_id"]),
        document_id=str(row["document_id"]),
        owner_id=str(row["owner_id"]),
        version=int(row["version"]),
        content_md=str(row["content_md"]),
        summary=str(row["summary"]) if row["summary"] else None,
        metadata=row["metadata"],
        doc_hash=str(row["doc_hash"]),
        created_at=row["created_at"],
    )


def _chunk(row: dict) -> RagChunk:
    return RagChunk(
        id=int(row["id"]),
        owner_id=str(row["owner_id"]),
        document_id=str(row["document_id"]),
        version_id=str(row["version_id"]),
        chunk_idx=int(row["chunk_idx"]),
        content=str(row["content"]),
        parent_content=row["parent_content"],
        section=row["section"],
        doc_hash=str(row["doc_hash"]),
        created_at=row["created_at"],
    )


class PostgresDocumentStore:
    durable = True

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def create_document(self, record: DocumentRecord) -> DocumentRecord:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """INSERT INTO rag_documents
                    (document_id, owner_id, title, doc_type, source, status,
                     created_by, created_at, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING *""",
                    (
                        record.document_id,
                        record.owner_id,
                        record.title,
                        record.doc_type,
                        record.source,
                        record.status,
                        record.created_by,
                        record.created_at,
                        record.updated_at,
                    ),
                ).fetchone()
            return _document(row)
        except Exception as exc:
            raise StoreError("unable to create document") from exc

    def create_version(self, version: DocumentVersion) -> DocumentVersion:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """INSERT INTO rag_document_versions
                    (version_id, document_id, owner_id, version, content_md,
                     summary, metadata, doc_hash, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (owner_id, document_id, version) DO NOTHING
                    RETURNING *""",
                    (
                        version.version_id,
                        version.document_id,
                        version.owner_id,
                        version.version,
                        version.content_md,
                        version.summary,
                        (
                            _json_dumps(version.metadata)
                            if version.metadata is not None
                            else None
                        ),
                        version.doc_hash,
                        version.created_at,
                    ),
                ).fetchone()
            return _version(row)
        except Exception as exc:
            raise StoreError("unable to create document version") from exc

    def upsert_chunks(self, owner_id: str, chunks: list[RagChunk]) -> int:
        if not chunks:
            return 0
        try:
            with self._pool.connection() as conn, conn.transaction():
                document_id = chunks[0].document_id
                version_id = chunks[0].version_id
                # 版本化：同 document 旧版本 chunks 只留最新版本。
                conn.execute(
                    """DELETE FROM rag_chunks
                    WHERE owner_id=%s AND document_id=%s AND version_id<>%s""",
                    (owner_id, document_id, version_id),
                )
                with conn.cursor() as cur:
                    cur.executemany(
                        """INSERT INTO rag_chunks
                        (owner_id, document_id, version_id, chunk_idx, content,
                         parent_content, section, doc_hash, created_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (owner_id, document_id, version_id, chunk_idx)
                        DO UPDATE SET content=excluded.content,
                            parent_content=excluded.parent_content,
                            section=excluded.section, doc_hash=excluded.doc_hash""",
                        [
                            (
                                chunk.owner_id,
                                chunk.document_id,
                                chunk.version_id,
                                chunk.chunk_idx,
                                chunk.content,
                                chunk.parent_content,
                                chunk.section,
                                chunk.doc_hash,
                                chunk.created_at,
                            )
                            for chunk in chunks
                        ],
                    )
            return len(chunks)
        except Exception as exc:
            raise StoreError("unable to store document chunks") from exc

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
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """UPDATE rag_documents
                    SET status=%s,
                        failure_reason=%s,
                        chunk_count=COALESCE(%s, chunk_count),
                        indexed_count=COALESCE(%s, indexed_count),
                        updated_at=now()
                    WHERE owner_id=%s AND document_id=%s
                    RETURNING *""",
                    (status, failure_reason, chunk_count, indexed_count,
                     owner_id, document_id),
                ).fetchone()
            return _document(row) if row else None
        except Exception as exc:
            raise StoreError("unable to update document status") from exc

    def get_document(self, owner_id: str, document_id: str) -> DocumentRecord | None:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """SELECT * FROM rag_documents
                    WHERE owner_id=%s AND document_id=%s""",
                    (owner_id, document_id),
                ).fetchone()
            return _document(row) if row else None
        except Exception as exc:
            raise StoreError("unable to read document") from exc

    def list_documents(
        self,
        owner_id: str,
        *,
        status: str | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> tuple[DocumentRecord, ...]:
        try:
            clauses = ["owner_id=%s"]
            params: list[object] = [owner_id]
            if status is not None:
                clauses.append("status=%s")
                params.append(status)
            if before is not None:
                clauses.append("updated_at<%s")
                params.append(before)
            params.append(limit)
            with self._pool.connection() as conn:
                rows = conn.execute(
                    f"""SELECT * FROM rag_documents WHERE {" AND ".join(clauses)}
                    ORDER BY updated_at DESC, document_id LIMIT %s""",
                    params,
                ).fetchall()
            return tuple(_document(row) for row in rows)
        except Exception as exc:
            raise StoreError("unable to list documents") from exc

    def get_version(
        self, owner_id: str, version_id: str
    ) -> DocumentVersion | None:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """SELECT * FROM rag_document_versions
                    WHERE owner_id=%s AND version_id=%s""",
                    (owner_id, version_id),
                ).fetchone()
            return _version(row) if row else None
        except Exception as exc:
            raise StoreError("unable to read document version") from exc

    def latest_version(
        self, owner_id: str, document_id: str
    ) -> DocumentVersion | None:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """SELECT * FROM rag_document_versions
                    WHERE owner_id=%s AND document_id=%s
                    ORDER BY version DESC LIMIT 1""",
                    (owner_id, document_id),
                ).fetchone()
            return _version(row) if row else None
        except Exception as exc:
            raise StoreError("unable to read latest document version") from exc

    def chunks_by_doc_hash(
        self, owner_id: str, doc_hash: str
    ) -> tuple[RagChunk, ...]:
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    """SELECT * FROM rag_chunks
                    WHERE owner_id=%s AND doc_hash=%s
                    ORDER BY chunk_idx""",
                    (owner_id, doc_hash),
                ).fetchall()
            return tuple(_chunk(row) for row in rows)
        except Exception as exc:
            raise StoreError("unable to read chunks") from exc

    def chunks_by_document(
        self, owner_id: str, document_id: str
    ) -> tuple[RagChunk, ...]:
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    """SELECT * FROM rag_chunks
                    WHERE owner_id=%s AND document_id=%s
                    ORDER BY chunk_idx""",
                    (owner_id, document_id),
                ).fetchall()
            return tuple(_chunk(row) for row in rows)
        except Exception as exc:
            raise StoreError("unable to read chunks") from exc

    def resolve_chunks(
        self, owner_id: str, chunk_ids: list[int]
    ) -> tuple[tuple[RagChunk, str | None], ...]:
        if not chunk_ids:
            return ()
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    """SELECT chunk.*, doc.title
                    FROM rag_chunks chunk
                    JOIN rag_documents doc
                      ON doc.owner_id=chunk.owner_id
                     AND doc.document_id=chunk.document_id
                    WHERE chunk.owner_id=%s AND chunk.id = ANY(%s)""",
                    (owner_id, chunk_ids),
                ).fetchall()
            return tuple((_chunk(row), str(row["title"])) for row in rows)
        except Exception as exc:
            raise StoreError("unable to resolve chunks") from exc

    def delete_document(
        self, owner_id: str, document_id: str, now: datetime
    ) -> bool:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """UPDATE rag_documents
                    SET status='deleted', updated_at=%s
                    WHERE owner_id=%s AND document_id=%s AND status<>'deleted'
                    RETURNING document_id""",
                    (now, owner_id, document_id),
                ).fetchone()
            return row is not None
        except Exception as exc:
            raise StoreError("unable to delete document") from exc

    def purge_document(
        self, owner_id: str, document_id: str
    ) -> tuple[int, ...]:
        try:
            with self._pool.connection() as conn, conn.transaction():
                rows = conn.execute(
                    """SELECT id FROM rag_chunks
                    WHERE owner_id=%s AND document_id=%s""",
                    (owner_id, document_id),
                ).fetchall()
                ids = tuple(int(row["id"]) for row in rows)
                conn.execute(
                    """DELETE FROM rag_documents
                    WHERE owner_id=%s AND document_id=%s""",
                    (owner_id, document_id),
                )
                # versions/chunks 由外键 ON DELETE CASCADE 清除。
            return ids
        except Exception as exc:
            raise StoreError("unable to purge document") from exc


def _json_dumps(value: dict) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
