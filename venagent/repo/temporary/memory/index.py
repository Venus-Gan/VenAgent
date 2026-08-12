"""temporary 模式的派生 memory embedding 索引。"""

from __future__ import annotations

from threading import RLock

from ....memory.embedding.index import MemoryIndexRecord


class _TemporaryIndexMixin:
    def upsert_index(self, record: MemoryIndexRecord) -> None:
        with self._lock:
            self._index_records[record.memory_id] = record

    def index_records(
        self, owner_id: str, tenant_id: str, model: str, index_version: str
    ) -> tuple[MemoryIndexRecord, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for item in self._index_records.values()
                        if item.owner_id == owner_id
                        and item.tenant_id == tenant_id
                        and item.model == model
                        and item.index_version == index_version
                    ),
                    key=lambda item: item.memory_id,
                )
            )

    def delete_index(self, owner_id: str, memory_ids: tuple[str, ...]) -> int:
        with self._lock:
            targets = tuple(
                memory_id
                for memory_id in memory_ids
                if (record := self._index_records.get(memory_id)) is not None
                and record.owner_id == owner_id
            )
            for memory_id in targets:
                del self._index_records[memory_id]
            return len(targets)


class TemporaryMemoryIndexStore(_TemporaryIndexMixin):
    def __init__(self) -> None:
        self._index_records: dict[str, MemoryIndexRecord] = {}
        self._lock = RLock()
