"""M05 派生 embedding 索引与 owner 范围余弦召回。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..long_term.facts import MemoryFact

INDEX_VERSION = "m05-dense-v1"


class EmbeddingPort(Protocol):
    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...


@dataclass(frozen=True)
class MemoryIndexRecord:
    memory_id: str
    owner_id: str
    tenant_id: str
    model: str
    index_version: str
    vector: tuple[float, ...]
    updated_at: datetime


@dataclass(frozen=True)
class MemoryIndexMatch:
    memory_id: str
    score: float


class MemoryIndexStore(Protocol):
    def upsert_index(self, record: MemoryIndexRecord) -> None: ...

    def index_records(
        self, owner_id: str, tenant_id: str, model: str, index_version: str
    ) -> tuple[MemoryIndexRecord, ...]: ...

    def delete_index(self, owner_id: str, memory_ids: tuple[str, ...]) -> int: ...


class MemoryIndex:
    """索引只保存派生向量，不拥有事实或生命周期权威。"""

    def __init__(
        self,
        store: MemoryIndexStore,
        embedding: EmbeddingPort,
        *,
        model: str,
        index_version: str = INDEX_VERSION,
    ) -> None:
        if not model.strip():
            raise ValueError("embedding model is required")
        self._store = store
        self._embedding = embedding
        self._model = model.strip()
        self._index_version = index_version

    @property
    def configured(self) -> bool:
        return True

    def project(self, fact: MemoryFact, *, now: datetime) -> None:
        if not fact.active:
            self._store.delete_index(fact.owner_id, (fact.memory_id,))
            return
        vector = self._embedding.embed((fact.fact,))
        if len(vector) != 1:
            raise ValueError("embedding result count mismatch")
        _validate_vector(vector[0])
        self._store.upsert_index(
            MemoryIndexRecord(
                memory_id=fact.memory_id,
                owner_id=fact.owner_id,
                tenant_id=fact.tenant_id,
                model=self._model,
                index_version=self._index_version,
                vector=vector[0],
                updated_at=now,
            )
        )

    def search(
        self, owner_id: str, tenant_id: str, query: str, *, limit: int
    ) -> tuple[MemoryIndexMatch, ...]:
        if limit <= 0 or not query.strip():
            return ()
        vectors = self._embedding.embed((query,))
        if len(vectors) != 1:
            raise ValueError("embedding result count mismatch")
        query_vector = vectors[0]
        _validate_vector(query_vector)
        scored = tuple(
            MemoryIndexMatch(record.memory_id, cosine_similarity(query_vector, record.vector))
            for record in self._store.index_records(
                owner_id, tenant_id, self._model, self._index_version
            )
        )
        return tuple(
            sorted(scored, key=lambda item: (-item.score, item.memory_id))[:limit]
        )

    def remove(self, owner_id: str, memory_ids: tuple[str, ...]) -> int:
        return self._store.delete_index(owner_id, memory_ids)


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    _validate_vector(left)
    _validate_vector(right)
    if len(left) != len(right):
        raise ValueError("embedding dimensions do not match")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("embedding vectors must be non-zero")
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )


def _validate_vector(vector: tuple[float, ...]) -> None:
    if not vector or any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in vector
    ):
        raise ValueError("embedding vector is invalid")
