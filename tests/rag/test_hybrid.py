"""HybridSearchService 测试：RRF 权重 / 二级 RRF / 逐路降级 / rerank 应用。"""

from __future__ import annotations

from venagent.config import RagConfig
from venagent.rag.hybrid import HybridSearchService
from venagent.rag.routes import (
    DENSE_ROUTE,
    GRAPH_ROUTE,
    KEYWORD_ROUTE,
    RouteHit,
    RouteUnavailable,
)


def _hit(
    chunk_id: int,
    content: str,
    route: str,
    *,
    score: float = 1.0,
    document_id: str = "doc-1",
    title: str = "标题",
    section: str | None = None,
    chunk_idx: int = 0,
) -> RouteHit:
    return RouteHit(
        chunk_id=chunk_id,
        content=content,
        parent_content=content,
        document_id=document_id,
        title=title,
        section=section,
        chunk_idx=chunk_idx,
        score=score,
        route=route,
    )


class FakeRoute:
    def __init__(self, hits: dict[str, list[RouteHit]] | None = None) -> None:
        self._hits = hits or {}

    def search(self, owner_id: str, query: str, *, top_k: int) -> tuple[RouteHit, ...]:
        del owner_id
        return tuple(self._hits.get(query, ())[:top_k])


class FailingRoute:
    def search(self, owner_id: str, query: str, *, top_k: int) -> tuple[RouteHit, ...]:
        del owner_id, query, top_k
        raise RouteUnavailable("route down")


def _service(routes=None, **kwargs) -> HybridSearchService:
    return HybridSearchService(routes or {}, RagConfig(), **kwargs)


def test_mode_static_classification():
    assert _service({DENSE_ROUTE: FakeRoute(), KEYWORD_ROUTE: FakeRoute()}).mode == "hybrid"
    assert _service({KEYWORD_ROUTE: FakeRoute()}).mode == "keyword"
    assert _service({DENSE_ROUTE: FakeRoute()}).mode == "semantic"
    assert _service({}).mode == "unavailable"


def test_unavailable_returns_empty_result():
    result = _service({}).search("owner", "问题")
    assert result.mode == "unavailable"
    assert result.sources == ()


def test_query_rrf_prefers_shared_chunk():
    """同一 chunk 在两路都命中时 RRF 分数更高（rank 0+0）。"""
    dense = FakeRoute(
        {"问题": [_hit(1, "甲", DENSE_ROUTE, score=0.9), _hit(2, "乙", DENSE_ROUTE, score=0.8)]}
    )
    keyword = FakeRoute(
        {"问题": [_hit(2, "乙", KEYWORD_ROUTE, score=8.0), _hit(3, "丙", KEYWORD_ROUTE, score=7.0)]}
    )
    service = _service({DENSE_ROUTE: dense, KEYWORD_ROUTE: keyword})
    result = service.search("owner", "问题", top_k=3)
    ids = [source.chunk_id for source in result.sources]
    assert ids[0] == 2  # 两路都命中的 chunk 排第一
    assert result.mode == "hybrid"
    assert result.degraded == ()


def test_query_reroute_degradation_is_recorded():
    """dense 路失败 → 结果降级标记，keyword 路照常返回。"""
    keyword = FakeRoute(
        {"问题": [_hit(3, "丙", KEYWORD_ROUTE, score=7.0)]}
    )
    service = _service(
        {DENSE_ROUTE: FailingRoute(), KEYWORD_ROUTE: keyword}
    )
    result = service.search("owner", "问题", top_k=3)
    assert result.mode == "hybrid"  # 静态定档不变
    assert result.degraded == (DENSE_ROUTE,)
    assert [source.chunk_id for source in result.sources] == [3]


def test_all_routes_down_returns_no_sources():
    service = _service({DENSE_ROUTE: FailingRoute(), KEYWORD_ROUTE: FailingRoute()})
    result = service.search("owner", "问题")
    assert result.sources == ()
    assert set(result.degraded) == {DENSE_ROUTE, KEYWORD_ROUTE}


def test_cross_query_second_level_rrf():
    """改写后两条查询：跨查询按 content 聚合，双查询命中的 chunk 优先。"""

    class Rewriter:
        def rewrite(self, query, history):
            return ["原问题", "改写问题"]

    dense = FakeRoute(
        {
            "原问题": [_hit(1, "甲", DENSE_ROUTE)],
            "改写问题": [_hit(1, "甲", DENSE_ROUTE), _hit(2, "乙", DENSE_ROUTE)],
        }
    )
    service = _service(
        {DENSE_ROUTE: dense},
        rewriter=Rewriter(),
    )
    result = service.search("owner", "原问题", top_k=3)
    ids = [source.chunk_id for source in result.sources]
    assert ids[0] == 1  # 两条查询都命中
    assert 2 in ids


def test_rewrite_failure_falls_back_to_original():
    class BrokenRewriter:
        def rewrite(self, query, history):
            raise RuntimeError("llm down")

    dense = FakeRoute({"原问题": [_hit(1, "甲", DENSE_ROUTE)]})
    service = _service({DENSE_ROUTE: dense}, rewriter=BrokenRewriter())
    result = service.search("owner", "原问题")
    assert [source.chunk_id for source in result.sources] == [1]


def test_rerank_reorders_by_llm_score():
    dense = FakeRoute(
        {"问题": [_hit(1, "甲", DENSE_ROUTE), _hit(2, "乙", DENSE_ROUTE)]}
    )

    class Reranker:
        def rerank(self, query, candidates, preview_len):
            return [(0, 1.0), (1, 9.0)]

    service = _service({DENSE_ROUTE: dense}, reranker=Reranker())
    result = service.search("owner", "问题", top_k=3)
    assert result.reranked is True
    assert [source.chunk_id for source in result.sources] == [2, 1]


def test_rerank_failure_keeps_original_order():
    dense = FakeRoute(
        {"问题": [_hit(1, "甲", DENSE_ROUTE), _hit(2, "乙", DENSE_ROUTE)]}
    )

    class BrokenReranker:
        def rerank(self, query, candidates, preview_len):
            return None

    service = _service({DENSE_ROUTE: dense}, reranker=BrokenReranker())
    result = service.search("owner", "问题", top_k=3)
    assert result.reranked is False
    assert [source.chunk_id for source in result.sources] == [1, 2]


def test_graph_route_weight_applied():
    """graph 路命中 rank0 得 0.3/(k+1)，dense 命中 rank0 得 1/(k+1) → dense 优先。"""
    dense = FakeRoute({"问题": [_hit(1, "甲", DENSE_ROUTE)]})
    graph = FakeRoute({"问题": [_hit(2, "乙", GRAPH_ROUTE)]})
    service = _service({DENSE_ROUTE: dense, GRAPH_ROUTE: graph})
    result = service.search("owner", "问题", top_k=3)
    assert [source.chunk_id for source in result.sources] == [1, 2]
    assert result.sources[0].route == DENSE_ROUTE
    assert result.sources[1].route == GRAPH_ROUTE


def test_top_k_limits_sources():
    dense = FakeRoute(
        {"问题": [_hit(i, f"内容{i}", DENSE_ROUTE) for i in range(1, 8)]}
    )
    service = _service({DENSE_ROUTE: dense})
    result = service.search("owner", "问题", top_k=2)
    assert len(result.sources) == 2
