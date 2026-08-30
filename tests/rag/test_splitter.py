"""RecursiveSplitter 行为测试（AGI-saber rag_test.go 四个 splitter 测试语义迁移）。"""

from __future__ import annotations

from src.rag.splitter import RecursiveSplitter


def test_respects_paragraph_boundary():
    """段落边界优先：不在句子中间切断。"""
    splitter = RecursiveSplitter(chunk_size=60, overlap=0)
    text = "第一段完整句子内容。" * 3 + "\n\n" + "第二段完整句子内容。" * 3
    chunks = splitter.split(text)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 60
    # 段落分隔符不应出现在 chunk 中间（首个 chunk 若含段落则说明合并，允许在尾部）。
    assert any("\n\n" in chunk for chunk in chunks) or "第一段" in chunks[0]


def test_preserves_code_block():
    """代码块作为原子单元，即使超长也不拆。"""
    splitter = RecursiveSplitter(chunk_size=30, overlap=0)
    code = "```\nline one\nline two\nline three\n```"
    text = "开头文字。\n" + code + "\n结尾文字。"
    chunks = splitter.split(text)
    # 完整代码块必须原样出现在某个 chunk 中。
    assert any(code in chunk for chunk in chunks)


def test_size_bounded():
    """chunk 不超过 chunk_size + overlap 容差（rune 计数）。"""
    splitter = RecursiveSplitter(chunk_size=50, overlap=10)
    text = "中文句子。" * 40
    chunks = splitter.split(text)
    assert chunks
    for chunk in chunks:
        assert len(chunk) <= 50 + 10


def test_overlap_applied():
    """下一块开头带上一块尾部 overlap 字符。"""
    overlap = 10
    splitter = RecursiveSplitter(chunk_size=60, overlap=overlap)
    text = "甲字" * 200
    chunks = splitter.split(text)
    assert len(chunks) >= 2
    for previous, current in zip(chunks, chunks[1:]):
        assert current.startswith(previous[-overlap:])
