"""PostgreSQL `real[]` 派生 memory embedding 索引。"""

from __future__ import annotations

from typing import Any

from ....memory.embedding.index import MemoryIndexRecord
from ....memory.ports import MemoryStoreError as StoreError


class _PostgresIndexMixin:
    def upsert_index(self, record: MemoryIndexRecord) -> None:
        try:
            with self._pool.connection() as conn:
                conn.execute(
                    """INSERT INTO memory_embeddings
                    (memory_id,owner_id,tenant_id,model,index_version,embedding,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (memory_id) DO UPDATE SET
                    owner_id=excluded.owner_id,tenant_id=excluded.tenant_id,
                    model=excluded.model,index_version=excluded.index_version,
                    embedding=excluded.embedding,updated_at=excluded.updated_at""",
                    (
                        record.memory_id,
                        record.owner_id,
                        record.tenant_id,
                        record.model,
                        record.index_version,
                        list(record.vector),
                        record.updated_at,
                    ),
                )
        except Exception as exc:
            raise StoreError("unable to save memory embedding") from exc

    def index_records(
        self, owner_id: str, tenant_id: str, model: str, index_version: str
    ) -> tuple[MemoryIndexRecord, ...]:
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    """SELECT embedding.* FROM memory_embeddings embedding
                    JOIN memory_facts fact ON fact.memory_id=embedding.memory_id
                    WHERE embedding.owner_id=%s AND embedding.tenant_id=%s
                    AND embedding.model=%s AND embedding.index_version=%s
                    AND fact.status='active' ORDER BY embedding.memory_id""",
                    (owner_id, tenant_id, model, index_version),
                ).fetchall()
            return tuple(_index_record(row) for row in rows)
        except Exception as exc:
            raise StoreError("unable to read memory embeddings") from exc

    def delete_index(self, owner_id: str, memory_ids: tuple[str, ...]) -> int:
        if not memory_ids:
            return 0
        try:
            with self._pool.connection() as conn:
                return int(
                    conn.execute(
                        """DELETE FROM memory_embeddings
                        WHERE owner_id=%s AND memory_id=ANY(%s)""",
                        (owner_id, list(memory_ids)),
                    ).rowcount
                )
        except Exception as exc:
            raise StoreError("unable to delete memory embeddings") from exc


def _index_record(row: Any) -> MemoryIndexRecord:
    return MemoryIndexRecord(
        memory_id=str(row["memory_id"]),
        owner_id=str(row["owner_id"]),
        tenant_id=str(row["tenant_id"]),
        model=str(row["model"]),
        index_version=str(row["index_version"]),
        vector=tuple(float(value) for value in row["embedding"]),
        updated_at=row["updated_at"],
    )
