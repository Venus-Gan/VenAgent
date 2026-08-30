"""rewriter/rerank 解析测试（AGI-saber rewrite/rerank JSON 语义迁移）。"""

from __future__ import annotations

from src.rag.rerank import parse_rerank_output
from src.rag.rewriter import parse_rewrite_output


def test_rewrite_accepts_plain_json_array():
    raw = '["原问题", "改写一", "改写二"]'
    assert parse_rewrite_output(raw) == ["原问题", "改写一", "改写二"]


def test_rewrite_tolerates_json_fence():
    raw = '```json\n["原问题", "改写一"]\n```'
    assert parse_rewrite_output(raw) == ["原问题", "改写一"]


def test_rewrite_rejects_invalid_output():
    assert parse_rewrite_output("不是 JSON") is None
    assert parse_rewrite_output('{"key": "value"}') is None
    assert parse_rewrite_output("[]") is None
    assert parse_rewrite_output(None) is None


def test_rewrite_empty_queries_falls_back():
    assert parse_rewrite_output('["  "]') is None


def test_rerank_accepts_scores_object():
    raw = '{"scores": [{"idx": 0, "score": 8}, {"idx": 1, "score": 3}]}'
    assert parse_rerank_output(raw, 2) == [(0, 8.0), (1, 3.0)]


def test_rerank_tolerates_json_fence():
    raw = '```json\n{"scores": [{"idx": 1, "score": 10}]}\n```'
    assert parse_rerank_output(raw, 2) == [(1, 10.0)]


def test_rerank_rejects_invalid_output():
    assert parse_rerank_output("garbage", 2) is None
    assert parse_rerank_output('{"scores": []}', 2) is None
    assert parse_rerank_output('{"scores": [{"idx": 9, "score": 1}]}', 2) is None
    assert parse_rerank_output('{"scores": [{"idx": 0, "score": 11}]}', 2) is None
    assert parse_rerank_output('{"scores": [{"idx": 0}]}', 2) is None
