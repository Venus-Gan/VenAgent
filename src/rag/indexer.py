"""M08 文档索引写入器：PG 真相源 → Milvus（dense 向量）+ ES（keyword BM25）。

上传/重传经 DocumentService 回调本写入器；删除经 purge 返回的 chunk pg_id
级联清两侧索引。任一侧 client 未配置则跳过该路（检索侧由模式静态定档降级）。
写失败向上抛（文档标 failed(index_failed)），删除失败由调用方告警（可观测）。
"""

from __future__ import annotations

from typing import Any

from ..document.ports import RagChunk

_EMBED_BATCH = 16


class RagIndexer:
    """索引写入器：index_chunks 全量写入，delete_chunks 按 pg_id 级联删除。"""

    def __init__(
        self,
        *,
        milvus_client: Any | None = None,
        milvus_collection: str = "rag_chunks",
        dim: int = 2048,
        es_client: Any | None = None,
        es_index: str = "rag_chunks",
        embedding: Any | None = None,
    ) -> None:
        self._milvus = milvus_client
        self._milvus_collection = milvus_collection
        self._dim = dim
        self._es = es_client
        self._es_index = es_index
        self._embedding = embedding
        # 无 milvus 客户端时无需 ensure；有则首次 index_chunks 时惰性建集合。
        self._collection_ready = milvus_client is None

    # ── 写入 ─────────────────────────────────────────────────────────────

    def index_chunks(self, owner_id: str, chunks: list[RagChunk]) -> None:
        """为一批（已落 PG、带自增 id 的）chunk 写两侧索引。

        任一侧未配置即跳过；配置了但写失败向上抛（由 service 标 failed）。
        """
        if not chunks:
            return
        dense = self._milvus is not None and self._embedding is not None
        keyword = self._es is not None
        if not dense and not keyword:
            return
        if dense:
            self._ensure_collection()
            self._write_dense(owner_id, chunks)
        if keyword:
            self._write_keyword(owner_id, chunks)

    def _write_dense(self, owner_id: str, chunks: list[RagChunk]) -> None:
        rows: list[dict[str, Any]] = []
        for start in range(0, len(chunks), _EMBED_BATCH):
            batch = chunks[start : start + _EMBED_BATCH]
            vectors = self._embedding.embed(tuple(item.content for item in batch))
            for chunk, vector in zip(batch, vectors):
                if chunk.id is None:
                    continue
                rows.append(
                    {
                        "id": chunk.id,
                        "owner_id": owner_id,
                        "vector": list(vector),
                    }
                )
        if rows:
            self._milvus.upsert(
                collection_name=self._milvus_collection, data=rows
            )

    def _write_keyword(self, owner_id: str, chunks: list[RagChunk]) -> None:
        self._ensure_es_index()
        for chunk in chunks:
            if chunk.id is None:
                continue
            self._es.index(
                index=self._es_index,
                id=str(chunk.id),
                document={
                    "owner_id": owner_id,
                    "content": chunk.content,
                    "chunk_idx": chunk.chunk_idx,
                    "document_id": chunk.document_id,
                },
            )

    # ── 删除 ─────────────────────────────────────────────────────────────

    def delete_chunks(self, owner_id: str, chunk_ids: list[int]) -> None:
        """按 pg chunk id 级联清两侧索引（milvus 幂等；es 逐条容错 404）。"""
        ids = [item for item in chunk_ids if item is not None]
        if not ids:
            return
        if self._milvus is not None:
            self._milvus.delete(
                collection_name=self._milvus_collection, ids=ids
            )
        if self._es is not None:
            failed = 0
            for chunk_id in ids:
                try:
                    self._es.delete(index=self._es_index, id=str(chunk_id))
                except Exception:
                    # 404（已删）与其他单条失败统一容错：聚合失败可观测。
                    failed += 1
            if failed:
                raise RuntimeError(
                    f"elasticsearch delete failed for {failed} chunk(s)"
                )

    # ── 集合初始化 ───────────────────────────────────────────────────────

    def _ensure_es_index(self) -> None:
        """确保 ES index 存在且 owner_id/document_id 为 keyword。

        dynamic mapping 会把 UUID 型字符串建为 text，导致 term filter
        按精确 token 匹配必然失败；历史残留的 text mapping 直接重建。
        """
        if self._es is None:
            return
        if self._es.indices.exists(index=self._es_index):
            mapping = self._es.indices.get_mapping(index=self._es_index)
            props = mapping[self._es_index]["mappings"].get("properties", {})
            if props.get("owner_id", {}).get("type") == "keyword":
                return
            self._es.indices.delete(index=self._es_index)
        self._es.indices.create(
            index=self._es_index,
            mappings={
                "properties": {
                    "owner_id": {"type": "keyword"},
                    "document_id": {"type": "keyword"},
                    "chunk_idx": {"type": "long"},
                    "content": {"type": "text"},
                }
            },
        )

    def _ensure_collection(self) -> None:
        if self._collection_ready:
            return
        from pymilvus import DataType
        from pymilvus.milvus_client.index import IndexParams

        if not self._milvus.has_collection(self._milvus_collection):
            schema = self._milvus.create_schema(
                auto_id=False, enable_dynamic_field=False
            )
            schema.add_field(
                field_name="id", datatype=DataType.INT64, is_primary=True
            )
            schema.add_field(
                field_name="owner_id", datatype=DataType.VARCHAR, max_length=64
            )
            schema.add_field(
                field_name="vector",
                datatype=DataType.FLOAT_VECTOR,
                dim=self._dim,
            )
            self._milvus.create_collection(
                collection_name=self._milvus_collection, schema=schema
            )
        # 索引缺失则补建（已存在的 collection 可能是无索引残留）。
        existing = {
            str(
                self._milvus.describe_index(
                    self._milvus_collection, name
                ).get("field_name", "")
            )
            for name in self._milvus.list_indexes(self._milvus_collection)
        }
        if "vector" not in existing:
            vector_index = IndexParams()
            vector_index.add_index(
                field_name="vector",
                index_type="IVF_FLAT",
                metric_type="COSINE",
                index_name="vector_idx",
                params={"nlist": 128},
            )
            self._milvus.create_index(self._milvus_collection, vector_index)
        # owner_id 标量过滤不建索引：Milvus 2.4 无索引过滤可用（全扫描），
        # 且 pymilvus 3.x 客户端对 2.4 服务端发送 BITMAP 类型不被识别。
        # 检索前必须加载（pymilvus 3.x 创建后不自动 load；已存在也幂等）。
        self._milvus.load_collection(self._milvus_collection)
        self._collection_ready = True
