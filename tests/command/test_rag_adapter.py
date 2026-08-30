"""/rag 命令适配器测试（无 LLM 模式：检索结果直出）。"""

from __future__ import annotations

from venagent.command.rag_adapter import RagCommandAdapter
from venagent.ownership.models import Actor
from venagent.rag.hybrid import CitationSource, RagResult

ACTOR = Actor("owner-1", "user", "session-1", "alice", "durable")


def _result(*, mode="hybrid", sources=(), degraded=(), reranked=False):
    return RagResult(
        question="火星项目进展如何？",
        sources=sources,
        mode=mode,
        degraded=degraded,
        reranked=reranked,
    )


def _source(chunk_id=1, title="火星项目.md", section="里程碑"):
    return CitationSource(
        chunk_id=chunk_id,
        document_id="doc-1",
        title=title,
        section=section,
        chunk_idx=0,
        chunk_content="2026 年着陆窗口",
        parent_content="关键里程碑包括 2026 年着陆窗口。",
        score=0.9,
        route="dense",
    )


class FakeSearch:
    def __init__(self, result: RagResult) -> None:
        self._result = result

    def search(self, owner_id, query, **kwargs):
        del owner_id, query, kwargs
        return self._result


def test_matches_only_rag_prefix():
    assert RagCommandAdapter.matches("/rag 问题")
    assert not RagCommandAdapter.matches("/memory list")
    assert not RagCommandAdapter.matches("普通问题")


def test_empty_query_returns_usage():
    adapter = RagCommandAdapter(FakeSearch(_result()), model=None)
    result = adapter.execute(ACTOR, "/rag  ")
    assert result.code == "rag_query_required"
    assert "用法" in result.message


def test_unavailable_mode():
    adapter = RagCommandAdapter(FakeSearch(_result(mode="unavailable")), model=None)
    result = adapter.execute(ACTOR, "/rag 问题")
    assert result.code == "rag_unavailable"


def test_no_result():
    adapter = RagCommandAdapter(FakeSearch(_result(sources=())), model=None)
    result = adapter.execute(ACTOR, "/rag 问题")
    assert result.code == "rag_no_result"
    assert "未找到相关内容" in result.message


def test_ok_composes_citations_and_flags():
    adapter = RagCommandAdapter(
        FakeSearch(_result(sources=(_source(),), degraded=("dense",), reranked=True)),
        model=None,
    )
    result = adapter.execute(ACTOR, "/rag 火星项目进展如何？")
    assert result.code == "rag_ok"
    assert result.kind == "rag_command"
    assert "检索到以下相关内容" in result.message
    assert "检索降级：dense" in result.message
    assert "已重排" in result.message
    assert "[1] 火星项目.md / 里程碑" in result.message


def test_options_returns_rag_entry():
    options = RagCommandAdapter.options()
    assert any(option.command == "/rag <问题>" for option in options)
