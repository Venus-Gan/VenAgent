"""Stable, no-network cases shared by legacy and future runtime tests."""


BEHAVIOR_CASES = (
    {
        "id": "chat.mock.identity",
        "kind": "chat",
        "input": "你是谁",
        "expected": "mock response is returned without network access",
    },
    {
        "id": "rag.degraded.empty",
        "kind": "rag",
        "input": "知识库问题",
        "expected": "empty knowledge base returns the documented degraded response",
    },
    {
        "id": "tool.catalog.read",
        "kind": "tool",
        "input": {"name": "rag_search", "params": {"query": "测试"}},
        "expected": "tool descriptor preserves name and parameter contract",
    },
    {
        "id": "document.upload.plain_text",
        "kind": "document",
        "input": {"content": "hello rag", "content_type": "text/plain"},
        "expected": "plain text upload preserves parser metadata and document fields",
    },
)
