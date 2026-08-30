"""DocumentService 索引回调测试：indexing 状态、失败标 failed、重传/删除级联。"""

from __future__ import annotations

from src.config import DocumentConfig, RagConfig
from src.document.ports import RagChunk
from src.document.service import DocumentService
from tests.document._store import InMemoryDocumentStore

OWNER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

CONTENT = (
    "# 火星项目\n\n"
    "我们负责火星项目的轨道计算与燃料规划。\n"
    "团队分布在杭州与深圳两地，每周同步一次进度。\n"
    "关键里程碑包括 2026 年着陆窗口与 2027 年样本返回。\n"
) * 20


class RecordingIndexer:
    """记录调用面；可注入失败。"""

    def __init__(self, *, fail_index: bool = False) -> None:
        self.indexed: list[list[RagChunk]] = []
        self.deleted: list[list[int]] = []
        self.fail_index = fail_index

    def index_chunks(self, owner_id: str, chunks: list[RagChunk]) -> None:
        if self.fail_index:
            raise RuntimeError("indexer down")
        self.indexed.append(list(chunks))

    def delete_chunks(self, owner_id: str, chunk_ids: list[int]) -> None:
        self.deleted.append(list(chunk_ids))


def _service(indexer: RecordingIndexer | None) -> DocumentService:
    return DocumentService(
        InMemoryDocumentStore(),
        DocumentConfig(),
        RagConfig(),
        indexer=indexer,
    )


def test_upload_indexes_chunks_with_ids_and_ready() -> None:
    indexer = RecordingIndexer()
    service = _service(indexer)
    record = service.upload(
        OWNER_A, filename="project.md", content=CONTENT.encode("utf-8")
    )
    assert record.status == "ready"
    assert record.indexed_count == record.chunk_count
    assert len(indexer.indexed) == 1
    chunks = indexer.indexed[0]
    assert len(chunks) == record.chunk_count
    assert all(chunk.id is not None for chunk in chunks)
    assert all(chunk.owner_id == OWNER_A for chunk in chunks)


def test_index_failure_marks_document_failed() -> None:
    indexer = RecordingIndexer(fail_index=True)
    service = _service(indexer)
    record = service.upload(
        OWNER_A, filename="project.md", content=CONTENT.encode("utf-8")
    )
    assert record.status == "failed"
    assert record.failure_reason == "index_failed"
    # 失败可删除重传。
    service.delete(OWNER_A, record.document_id)


def test_reingest_deletes_old_chunk_ids() -> None:
    indexer = RecordingIndexer()
    service = _service(indexer)
    first = service.upload(
        OWNER_A, filename="project.md", content=CONTENT.encode("utf-8")
    )
    old_ids = [chunk.id for chunk in indexer.indexed[0]]
    indexer.indexed.clear()
    second = service.reingest(
        OWNER_A,
        first.document_id,
        filename="project.md",
        content=("新版本内容。" * 200).encode("utf-8"),
    )
    assert second.status == "ready"
    assert service.latest_version(OWNER_A, first.document_id).version == 2
    assert len(indexer.deleted) == 1
    assert indexer.deleted[0] == old_ids
    assert len(indexer.indexed) == 1
    new_ids = [chunk.id for chunk in indexer.indexed[0]]
    assert set(new_ids).isdisjoint(old_ids)


def test_delete_cascades_to_indexer() -> None:
    indexer = RecordingIndexer()
    service = _service(indexer)
    record = service.upload(
        OWNER_A, filename="project.md", content=CONTENT.encode("utf-8")
    )
    chunk_ids = service.delete(OWNER_A, record.document_id)
    assert tuple(chunk_ids) == tuple(c.id for c in indexer.indexed[0])
    assert indexer.deleted[-1] == list(chunk_ids)


def test_delete_indexer_failure_is_observable_but_returns_ids(
    caplog,
) -> None:
    indexer = RecordingIndexer()
    service = _service(indexer)
    record = service.upload(
        OWNER_A, filename="project.md", content=CONTENT.encode("utf-8")
    )

    class FailingDeleteIndexer(RecordingIndexer):
        def delete_chunks(self, owner_id: str, chunk_ids: list[int]) -> None:
            raise RuntimeError("es down")

    service._indexer = FailingDeleteIndexer()  # noqa: SLF001
    import logging

    with caplog.at_level(logging.WARNING, logger="venagent.document"):
        chunk_ids = service.delete(OWNER_A, record.document_id)
    assert chunk_ids  # PG 已删，ids 照常返回（可观测）
    assert any("索引级联删除失败" in message for message in caplog.messages)


def test_no_indexer_skips_indexing() -> None:
    service = _service(None)
    record = service.upload(
        OWNER_A, filename="project.md", content=CONTENT.encode("utf-8")
    )
    assert record.status == "ready"
    assert record.indexed_count == record.chunk_count
