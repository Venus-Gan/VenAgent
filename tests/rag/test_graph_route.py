"""GraphRoute 测试：实体抽取 → 子图召回 → PG 回查 → RouteHit。"""

from __future__ import annotations

import pytest

from tests.document._store import InMemoryDocumentStore
from venagent.config import DocumentConfig, RagConfig
from venagent.document.service import DocumentService
from venagent.rag.kg_extract import KgEntity, KgExtraction
from venagent.rag.routes import GRAPH_ROUTE, GraphRoute, RouteUnavailable

OWNER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

CONTENT = "# 火星项目\n\n林舟负责火星项目的轨道计算，常驻杭州。" * 10


class FakeKgStore:
    def __init__(self, scored: dict[int, float] | None = None) -> None:
        self._scored = scored or {}

    def search(self, owner_id, seeds, *, max_hops=2):
        del owner_id, max_hops
        return dict(self._scored)


class FakeExtractor:
    def __init__(self, entities=("林舟", "杭州")) -> None:
        self._entities = entities

    def extract(self, query: str) -> KgExtraction:
        return KgExtraction(
            entities=tuple(
                KgEntity(name, "Location" if name == "杭州" else "Person")
                for name in self._entities
            ),
            relations=(),
        )


@pytest.fixture
def store() -> InMemoryDocumentStore:
    store = InMemoryDocumentStore()
    service = DocumentService(store, DocumentConfig(), RagConfig())
    service.upload(OWNER, filename="project.md", content=CONTENT.encode("utf-8"))
    return store


def _route(store, kg_store, extractor) -> GraphRoute:
    return GraphRoute(store, kg_store, extractor, max_hops=2)


def test_search_resolves_chunks_with_title(store):
    chunks = store.chunks_by_document(OWNER, next(iter(store._documents)))
    target = chunks[0].id
    route = _route(store, FakeKgStore({target: 2.0}), FakeExtractor())
    hits = route.search(OWNER, "林舟在哪个城市", top_k=5)
    assert len(hits) == 1
    hit = hits[0]
    assert hit.route == GRAPH_ROUTE
    assert hit.chunk_id == target
    assert hit.title == "project.md"
    assert hit.score == 2.0


def test_search_skips_unknown_chunk_ids(store):
    route = _route(store, FakeKgStore({999999: 1.0}), FakeExtractor())
    assert route.search(OWNER, "问题", top_k=5) == ()


def test_search_without_seeds_returns_empty(store):
    route = _route(store, FakeKgStore(), FakeExtractor(entities=()))
    assert route.search(OWNER, "问题", top_k=5) == ()


def test_search_without_kg_store_raises_unavailable(store):
    route = _route(store, None, FakeExtractor())
    with pytest.raises(RouteUnavailable):
        route.search(OWNER, "问题", top_k=5)


def test_search_extractor_failure_degrades(store):
    class BrokenExtractor:
        def extract(self, query):
            raise RuntimeError("llm down")

    route = _route(store, FakeKgStore(), BrokenExtractor())
    with pytest.raises(RouteUnavailable):
        route.search(OWNER, "问题", top_k=5)


def test_search_limits_top_k(store):
    chunks = store.chunks_by_document(OWNER, next(iter(store._documents)))
    scored = {chunk.id: float(index) for index, chunk in enumerate(chunks)}
    route = _route(store, FakeKgStore(scored), FakeExtractor())
    hits = route.search(OWNER, "问题", top_k=2)
    assert len(hits) == 2
    assert hits[0].score >= hits[1].score
