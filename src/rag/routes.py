"""M08 检索路抽象：dense（Milvus）/ keyword（ES）/ graph（Neo4j，P3 后半接）。

每路独立可空；检索后统一回查 PG（真相源）回填 chunk 原文与文档溯源。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..document.ports import DocumentStore

DENSE_ROUTE = "dense"
KEYWORD_ROUTE = "keyword"
GRAPH_ROUTE = "graph"


class RouteUnavailable(RuntimeError):
    """该路当前不可用（连接失败/未配置），由 hybrid 层降级处理。"""


@dataclass(frozen=True)
class RouteHit:
    chunk_id: int
    content: str
    parent_content: str | None
    document_id: str
    title: str | None
    section: str | None
    chunk_idx: int
    score: float
    route: str


class RetrievalRoute(Protocol):
    def search(self, owner_id: str, query: str, *, top_k: int) -> tuple[RouteHit, ...]: ...


class DenseRoute:
    """Milvus cosine 向量召回：embed 查询 → search → PG 回查。"""

    def __init__(
        self,
        store: DocumentStore,
        client: Any,
        embedding: Any,
        *,
        collection: str,
        top_k: int = 10,
    ) -> None:
        self._store = store
        self._client = client
        self._embedding = embedding
        self._collection = collection
        self._top_k = top_k

    def search(self, owner_id: str, query: str, *, top_k: int) -> tuple[RouteHit, ...]:
        if self._client is None:
            raise RouteUnavailable("milvus is unavailable")
        vectors = self._embedding.embed((query,))
        results = self._client.search(
            collection_name=self._collection,
            data=[list(vectors[0])],
            limit=top_k,
            output_fields=["id"],
            filter=f"owner_id == '{owner_id}'",
        )
        ids = [int(hit["id"]) for hit in results[0]]
        return self._resolve(owner_id, ids, results[0])

    def _resolve(
        self, owner_id: str, ids: list[int], raw: list[Any]
    ) -> tuple[RouteHit, ...]:
        rows = self._store.resolve_chunks(owner_id, ids)
        by_id = {row[0].id: row for row in rows}
        score_by_id = {int(hit["id"]): float(hit["distance"]) for hit in raw}
        hits: list[RouteHit] = []
        for chunk_id in ids:
            row = by_id.get(chunk_id)
            if row is None:
                continue
            chunk, title = row
            hits.append(
                RouteHit(
                    chunk_id=chunk_id,
                    content=chunk.content,
                    parent_content=chunk.parent_content,
                    document_id=chunk.document_id,
                    title=title,
                    section=chunk.section,
                    chunk_idx=chunk.chunk_idx,
                    score=score_by_id.get(chunk_id, 0.0),
                    route=DENSE_ROUTE,
                )
            )
        return tuple(hits)


class KeywordRoute:
    """Elasticsearch BM25 召回：match content → _id=pg_id → PG 回查。"""

    def __init__(
        self,
        store: DocumentStore,
        client: Any,
        *,
        index: str,
        top_k: int = 10,
    ) -> None:
        self._store = store
        self._client = client
        self._index = index
        self._top_k = top_k

    def search(self, owner_id: str, query: str, *, top_k: int) -> tuple[RouteHit, ...]:
        if self._client is None:
            raise RouteUnavailable("elasticsearch is unavailable")
        response = self._client.search(
            index=self._index,
            query={
                "bool": {
                    "must": [{"match": {"content": query}}],
                    "filter": [{"term": {"owner_id": owner_id}}],
                }
            },
            size=top_k,
        )
        hits = response["hits"]["hits"]
        ids = [int(hit["_id"]) for hit in hits]
        return self._resolve(owner_id, ids, hits)

    def _resolve(
        self, owner_id: str, ids: list[int], hits: list[dict[str, Any]]
    ) -> tuple[RouteHit, ...]:
        rows = self._store.resolve_chunks(owner_id, ids)
        by_id = {row[0].id: row for row in rows}
        score_by_id = {int(hit["_id"]): float(hit["_score"]) for hit in hits}
        found: list[RouteHit] = []
        for chunk_id in ids:
            row = by_id.get(chunk_id)
            if row is None:
                continue
            chunk, title = row
            found.append(
                RouteHit(
                    chunk_id=chunk_id,
                    content=chunk.content,
                    parent_content=chunk.parent_content,
                    document_id=chunk.document_id,
                    title=title,
                    section=chunk.section,
                    chunk_idx=chunk.chunk_idx,
                    score=score_by_id.get(chunk_id, 0.0),
                    route=KEYWORD_ROUTE,
                )
            )
        return tuple(found)


class GraphRoute:
    """KG 路：LLM 实体抽取（白名单校验）→ 子图召回 pg_id → PG 回查。

    kg_store 为空时视为不可用；APOC 缺失由 RagKgStore 自动降级一跳。
    """

    def __init__(
        self,
        store: DocumentStore,
        kg_store: Any | None,
        extractor: Any | None,
        *,
        max_hops: int = 2,
    ) -> None:
        self._store = store
        self._kg_store = kg_store
        self._extractor = extractor
        self._max_hops = max_hops

    def search(self, owner_id: str, query: str, *, top_k: int) -> tuple[RouteHit, ...]:
        if self._kg_store is None or self._extractor is None:
            raise RouteUnavailable("graph route is unavailable")
        try:
            extraction = self._extractor.extract(query)
        except Exception:
            raise RouteUnavailable("graph extraction failed") from None
        seeds = [entity.name for entity in extraction.entities]
        if not seeds:
            return ()
        scored = self._kg_store.search(
            owner_id, seeds, max_hops=self._max_hops
        )
        if not scored:
            return ()
        ids = list(scored.keys())
        rows = self._store.resolve_chunks(owner_id, ids)
        hits: list[RouteHit] = []
        for chunk, title in rows:
            if chunk.id is None:
                continue
            hits.append(
                RouteHit(
                    chunk_id=chunk.id,
                    content=chunk.content,
                    parent_content=chunk.parent_content,
                    document_id=chunk.document_id,
                    title=title,
                    section=chunk.section,
                    chunk_idx=chunk.chunk_idx,
                    score=scored.get(chunk.id, 0.0),
                    route=GRAPH_ROUTE,
                )
            )
        hits.sort(key=lambda item: (-item.score, item.chunk_id))
        return tuple(hits[:top_k])


def build_routes(
    store: DocumentStore,
    *,
    milvus_client: Any | None,
    milvus_collection: str,
    embedding: Any | None,
    es_client: Any | None,
    es_index: str,
    kg_store: Any | None = None,
    kg_extractor: Any | None = None,
    kg_max_hops: int = 2,
    top_k: int = 10,
) -> dict[str, RetrievalRoute | None]:
    """装配三路；缺 client 的路为 None（模式静态定档与查询期降级共用）。"""
    return {
        DENSE_ROUTE: (
            DenseRoute(
                store,
                milvus_client,
                embedding,
                collection=milvus_collection,
                top_k=top_k,
            )
            if milvus_client is not None and embedding is not None
            else None
        ),
        KEYWORD_ROUTE: (
            KeywordRoute(store, es_client, index=es_index, top_k=top_k)
            if es_client is not None
            else None
        ),
        GRAPH_ROUTE: (
            GraphRoute(
                store,
                kg_store,
                kg_extractor,
                max_hops=kg_max_hops,
            )
            if kg_store is not None and kg_extractor is not None
            else None
        ),
    }
