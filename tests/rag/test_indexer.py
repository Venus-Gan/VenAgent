"""RagIndexer 测试：Milvus/ES 双写、集合惰性创建、删除级联与失败传播。"""

from __future__ import annotations

import pytest

from venagent.document.ports import RagChunk
from venagent.rag.indexer import RagIndexer

DIM = 8


class FakeSchema:
    def __init__(self) -> None:
        self.fields: list[tuple[str, object, dict]] = []

    def add_field(
        self, field_name: str, datatype: object, **kwargs: object
    ) -> None:
        self.fields.append((field_name, datatype, kwargs))


class FakeMilvus:
    def __init__(self, fail_upsert: bool = False) -> None:
        self.rows: dict[int, dict] = {}
        self.create_calls = 0
        self.created: str | None = None
        self.deleted: list[int] = []
        self.fail_upsert = fail_upsert
        self.indexes: list[dict] = []
        self.load_calls = 0

    def has_collection(self, name: str) -> bool:
        return self.created is not None

    def create_schema(self, auto_id: bool, enable_dynamic_field: bool) -> FakeSchema:
        return FakeSchema()

    def create_collection(self, collection_name: str, schema: object) -> None:
        self.create_calls += 1
        self.created = collection_name

    def create_index(
        self, collection_name: str, index_params: object
    ) -> None:
        for param in index_params:
            self.indexes.append(
                {
                    "field_name": param.field_name,
                    "index_name": param.index_name,
                }
            )

    def list_indexes(self, collection_name: str) -> list[str]:
        return [item["index_name"] for item in self.indexes]

    def describe_index(self, collection_name: str, index_name: str) -> dict:
        for item in self.indexes:
            if item["index_name"] == index_name:
                return {"field_name": item["field_name"]}
        return {}

    def load_collection(self, collection_name: str) -> None:
        self.load_calls += 1

    def upsert(self, collection_name: str, data: list[dict]) -> None:
        if self.fail_upsert:
            raise RuntimeError("milvus unavailable")
        for row in data:
            self.rows[row["id"]] = row

    def delete(self, collection_name: str, ids: list[int]) -> None:
        self.deleted.extend(ids)


class FakeES:
    def __init__(self, fail_delete: bool = False) -> None:
        self.docs: dict[str, dict] = {}
        self.deleted: list[str] = []
        self.fail_delete = fail_delete
        self.indices = _FakeESIndices()

    def index(self, index: str, id: str, document: dict) -> None:
        self.docs[id] = document

    def delete(self, index: str, id: str) -> None:
        if self.fail_delete:
            raise RuntimeError("es unavailable")
        self.deleted.append(id)


class _FakeESIndices:
    """indices.* 面：exists/get_mapping/delete/create 记录调用。"""

    def __init__(self) -> None:
        self.exists_result = True
        self.owner_type = "keyword"
        self.create_calls = 0
        self.delete_calls = 0

    def exists(self, index: str) -> bool:
        return self.exists_result

    def get_mapping(self, index: str) -> dict:
        return {
            index: {
                "mappings": {
                    "properties": {"owner_id": {"type": self.owner_type}}
                }
            }
        }

    def delete(self, index: str) -> None:
        self.delete_calls += 1

    def create(self, index: str, mappings: dict) -> None:
        self.create_calls += 1


class FakeEmbedding:
    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim
        self.calls = 0

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        self.calls += 1
        return tuple(
            tuple(float(i + j) for j in range(self.dim)) for i in range(len(texts))
        )


def _chunks(n: int = 3, *, start_id: int = 1) -> list[RagChunk]:
    return [
        RagChunk(
            id=start_id + i,
            owner_id="owner-1",
            document_id="doc-1",
            version_id="ver-1",
            chunk_idx=i,
            content=f"chunk content {i}",
            parent_content="parent",
            section="S1",
            doc_hash="h",
        )
        for i in range(n)
    ]


def test_index_chunks_writes_both_sides() -> None:
    milvus = FakeMilvus()
    es = FakeES()
    indexer = RagIndexer(
        milvus_client=milvus,
        milvus_collection="rag_chunks",
        dim=DIM,
        es_client=es,
        es_index="rag_chunks",
        embedding=FakeEmbedding(),
    )
    chunks = _chunks()
    indexer.index_chunks("owner-1", chunks)

    assert set(milvus.rows) == {1, 2, 3}
    assert milvus.rows[1]["owner_id"] == "owner-1"
    assert len(milvus.rows[1]["vector"]) == DIM
    assert es.docs["1"]["owner_id"] == "owner-1"
    assert es.docs["1"]["content"] == "chunk content 0"
    assert es.docs["1"]["chunk_idx"] == 0
    assert es.docs["1"]["document_id"] == "doc-1"


def test_collection_created_lazily_once() -> None:
    milvus = FakeMilvus()
    indexer = RagIndexer(
        milvus_client=milvus,
        milvus_collection="rag_chunks",
        dim=DIM,
        embedding=FakeEmbedding(),
    )
    indexer.index_chunks("owner-1", _chunks())
    indexer.index_chunks("owner-1", _chunks(start_id=10))
    assert milvus.create_calls == 1
    assert milvus.created == "rag_chunks"


def test_keyword_only_when_milvus_missing() -> None:
    es = FakeES()
    indexer = RagIndexer(
        es_client=es, es_index="rag_chunks", embedding=FakeEmbedding()
    )
    indexer.index_chunks("owner-1", _chunks())
    assert len(es.docs) == 3


def test_dense_only_when_es_missing() -> None:
    milvus = FakeMilvus()
    indexer = RagIndexer(
        milvus_client=milvus,
        milvus_collection="rag_chunks",
        dim=DIM,
        embedding=FakeEmbedding(),
    )
    indexer.index_chunks("owner-1", _chunks())
    assert set(milvus.rows) == {1, 2, 3}


def test_no_clients_is_noop() -> None:
    indexer = RagIndexer()
    indexer.index_chunks("owner-1", _chunks())
    indexer.delete_chunks("owner-1", [1, 2, 3])


def test_empty_chunks_is_noop() -> None:
    milvus = FakeMilvus()
    es = FakeES()
    indexer = RagIndexer(
        milvus_client=milvus,
        milvus_collection="rag_chunks",
        dim=DIM,
        es_client=es,
        es_index="rag_chunks",
        embedding=FakeEmbedding(),
    )
    indexer.index_chunks("owner-1", [])
    assert milvus.create_calls == 0
    assert es.docs == {}


def test_delete_chunks_cascades_both_sides() -> None:
    milvus = FakeMilvus()
    es = FakeES()
    indexer = RagIndexer(
        milvus_client=milvus,
        milvus_collection="rag_chunks",
        dim=DIM,
        es_client=es,
        es_index="rag_chunks",
        embedding=FakeEmbedding(),
    )
    indexer.delete_chunks("owner-1", [1, 2, 3])
    assert sorted(milvus.deleted) == [1, 2, 3]
    assert sorted(es.deleted) == ["1", "2", "3"]


def test_es_delete_all_failed_raises() -> None:
    es = FakeES(fail_delete=True)
    indexer = RagIndexer(es_client=es, es_index="rag_chunks")
    with pytest.raises(RuntimeError, match="elasticsearch delete failed"):
        indexer.delete_chunks("owner-1", [1, 2])


def test_milvus_upsert_failure_propagates() -> None:
    milvus = FakeMilvus(fail_upsert=True)
    indexer = RagIndexer(
        milvus_client=milvus,
        milvus_collection="rag_chunks",
        dim=DIM,
        embedding=FakeEmbedding(),
    )
    with pytest.raises(RuntimeError, match="milvus unavailable"):
        indexer.index_chunks("owner-1", _chunks())


def test_es_index_recreated_when_owner_mapping_is_text() -> None:
    es = FakeES()
    es.indices.owner_type = "text"  # dynamic mapping 历史残留
    indexer = RagIndexer(es_client=es, es_index="rag_chunks")
    indexer.index_chunks("owner-1", _chunks())
    assert es.indices.delete_calls == 1
    assert es.indices.create_calls == 1
    assert len(es.docs) == 3


def test_es_index_kept_when_mapping_is_keyword() -> None:
    es = FakeES()
    indexer = RagIndexer(es_client=es, es_index="rag_chunks")
    indexer.index_chunks("owner-1", _chunks())
    assert es.indices.delete_calls == 0
    assert es.indices.create_calls == 0
    assert len(es.docs) == 3


def test_embedding_batched() -> None:
    embedding = FakeEmbedding()
    milvus = FakeMilvus()
    indexer = RagIndexer(
        milvus_client=milvus,
        milvus_collection="rag_chunks",
        dim=DIM,
        embedding=embedding,
    )
    # 17 chunks → 2 批（16 + 1）。
    indexer.index_chunks("owner-1", _chunks(n=17))
    assert embedding.calls == 2
    assert len(milvus.rows) == 17
