"""M08 多查询三路 RRF 检索（对齐 AGI-saber rrf/rewrite 语义）。

- 查询内 RRF：score = Σ w/(k+rank+1)，k=60，dense/keyword w=1.0、graph w=0.3；
- 跨查询二级 RRF：每条改写查询独立并发三路召回，按 chunk content 聚合键做二级 RRF；
- 查询期逐路降级：失败路进 degraded 标记，不静默吞错；
- 可选 LLM listwise rerank（失败回退原序）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ..config import RagConfig
from .routes import (
    DENSE_ROUTE,
    GRAPH_ROUTE,
    KEYWORD_ROUTE,
    RouteHit,
    RouteUnavailable,
)

Mode = Literal["hybrid", "semantic", "keyword", "unavailable"]


@dataclass(frozen=True)
class CitationSource:
    chunk_id: int
    document_id: str
    title: str | None
    section: str | None
    chunk_idx: int
    chunk_content: str
    parent_content: str | None
    score: float
    route: str


@dataclass(frozen=True)
class RagResult:
    question: str
    answer: str | None = None
    sources: tuple[CitationSource, ...] = ()
    mode: Mode = "unavailable"
    degraded: tuple[str, ...] = ()
    reranked: bool = False


class HybridSearchService:
    def __init__(
        self,
        routes: dict[str, object],
        config: RagConfig,
        *,
        rewriter: object | None = None,
        reranker: object | None = None,
    ) -> None:
        self._routes = routes
        self._config = config
        self._rewriter = rewriter
        self._reranker = reranker

    @property
    def mode(self) -> Mode:
        return _static_mode(self._routes)

    def search(
        self,
        owner_id: str,
        query: str,
        *,
        history: Sequence[str] | None = None,
        top_k: int | None = None,
    ) -> RagResult:
        if self.mode == "unavailable":
            return RagResult(question=query)
        top_k = top_k or self._config.top_k
        per_route_k = (
            max(2 * top_k, 10)
            if self._reranker is None
            else 4 * top_k
        )
        queries = self._rewritten_queries(query, history)
        degraded: set[str] = set()
        per_query: list[tuple[RouteHit, ...]] = []
        for item in queries:
            per_query.append(
                self._retrieve(owner_id, item, top_k=per_route_k, degraded=degraded)
            )
        ranked = _cross_query_rrf(per_query, self._config.rrf_constant_k)
        reranked = False
        if self._reranker is not None and len(ranked) > 1:
            scored = self._reranker.rerank(
                query,
                [item.content for item in ranked],
                self._config.rerank_preview_len,
            )
            if scored is not None:
                ranked = _apply_rerank(ranked, scored)
                reranked = True
        sources = tuple(
            _citation(item) for item in ranked[:top_k]
        )
        return RagResult(
            question=query,
            sources=sources,
            mode=self.mode,
            degraded=tuple(sorted(degraded)),
            reranked=reranked,
        )

    def _rewritten_queries(
        self, query: str, history: Sequence[str] | None
    ) -> list[str]:
        if self._rewriter is None or not self._config.rewrite_enabled:
            return [query]
        try:
            rewritten = self._rewriter.rewrite(query, history or ())
        except Exception:
            return [query]
        if not rewritten or not all(isinstance(item, str) and item for item in rewritten):
            return [query]
        return rewritten

    def _retrieve(
        self,
        owner_id: str,
        query: str,
        *,
        top_k: int,
        degraded: set[str],
    ) -> tuple[RouteHit, ...]:
        hits: list[RouteHit] = []
        for name in (DENSE_ROUTE, KEYWORD_ROUTE, GRAPH_ROUTE):
            route = self._routes.get(name)
            if route is None:
                continue
            try:
                hits.extend(route.search(owner_id, query, top_k=top_k))
            except RouteUnavailable:
                degraded.add(name)
            except Exception:
                degraded.add(name)
        return tuple(hits)


def _static_mode(routes: dict[str, object]) -> Mode:
    available = {name for name, route in routes.items() if route is not None}
    if DENSE_ROUTE in available and KEYWORD_ROUTE in available:
        return "hybrid"
    if KEYWORD_ROUTE in available:
        return "keyword"
    if DENSE_ROUTE in available:
        return "semantic"
    return "unavailable"


def _cross_query_rrf(
    per_query: Sequence[tuple[RouteHit, ...]],
    k: int,
) -> list[RouteHit]:
    """查询内 RRF 合并各路 → 跨查询按 chunk content 聚合二级 RRF。"""
    ranked_by_query: list[list[RouteHit]] = []
    for hits in per_query:
        if not hits:
            ranked_by_query.append([])
            continue
        ranked_by_query.append(_query_rrf(hits, k))
    buckets: dict[str, list[tuple[int, int]]] = {}
    items_by_content: dict[str, RouteHit] = {}
    for query_index, ranked in enumerate(ranked_by_query):
        for rank, hit in enumerate(ranked):
            key = hit.content
            items_by_content.setdefault(key, hit)
            buckets.setdefault(key, []).append((query_index, rank))
    merged: list[tuple[RouteHit, float]] = []
    for key, positions in buckets.items():
        score = sum(1.0 / (k + rank + 1) for _query, rank in positions)
        merged.append((items_by_content[key], score))
    merged.sort(key=lambda item: (-item[1], item[0].chunk_id))
    return [hit for hit, _score in merged]


def _query_rrf(hits: Sequence[RouteHit], k: int) -> list[RouteHit]:
    """查询内三路 RRF：按 chunk_id 聚合，score=Σ w/(k+rank+1)。"""
    weights = {
        DENSE_ROUTE: 1.0,
        KEYWORD_ROUTE: 1.0,
        GRAPH_ROUTE: 0.3,
    }
    ranked_by_route: dict[str, list[RouteHit]] = {}
    for hit in hits:
        ranked_by_route.setdefault(hit.route, []).append(hit)
    for route, items in ranked_by_route.items():
        items.sort(key=lambda item: (-item.score, item.chunk_id))
    scores: dict[int, float] = {}
    best: dict[int, RouteHit] = {}
    for route, items in ranked_by_route.items():
        weight = weights.get(route, 1.0)
        for rank, hit in enumerate(items):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + weight / (
                k + rank + 1
            )
            if hit.chunk_id not in best:
                best[hit.chunk_id] = hit
    merged = sorted(
        best.values(), key=lambda item: (-scores[item.chunk_id], item.chunk_id)
    )
    return merged


def _apply_rerank(
    items: list[RouteHit], scored: list[tuple[int, float]]
) -> list[RouteHit]:
    """LLM score 主排（score/10 归一），RRF score 作为稳定 tiebreak。"""
    by_index = {index: score for index, score in scored if index >= 0}
    ordered = sorted(
        enumerate(items),
        key=lambda pair: (
            -(by_index.get(pair[0], -1.0)),
            pair[0],
        ),
    )
    return [item for _index, item in ordered]


def _citation(hit: RouteHit) -> CitationSource:
    return CitationSource(
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        title=hit.title,
        section=hit.section,
        chunk_idx=hit.chunk_idx,
        chunk_content=hit.content,
        parent_content=hit.parent_content,
        score=hit.score,
        route=hit.route,
    )
