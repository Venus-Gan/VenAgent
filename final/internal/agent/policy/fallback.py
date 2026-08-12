"""IntentPolicy 使用的纯确定性关键词兼容规则。"""

from __future__ import annotations

from collections.abc import Iterable


DEFAULT_COMPATIBLE_TOOL_NAMES = (
    "search_web",
    "get_time",
    "get_weather",
    "rag_search",
    "write_document",
    "read_document",
    "list_documents",
    "ingest_document",
    "exec_command",
)

_TOOL_TRIGGERS = (
    ("时间", "get_time"),
    ("几点", "get_time"),
    ("现在", "get_time"),
    ("天气", "get_weather"),
    ("搜索", "search_web"),
    ("查找", "search_web"),
    ("查询", "search_web"),
    ("是什么", "search_web"),
    ("知识", "rag_search"),
    ("文档", "rag_search"),
)


def detect_compatible_tool(
    query: str,
    available_tools: Iterable[str] = (),
) -> str | None:
    """按 legacy router 的优先级返回当前策略可识别的工具名。"""
    allowed_tools = frozenset(available_tools) or frozenset(DEFAULT_COMPATIBLE_TOOL_NAMES)
    normalized_query = _normalized_query(query)
    for trigger, tool_name in _TOOL_TRIGGERS:
        if trigger in normalized_query and tool_name in allowed_tools:
            return tool_name
    return None


def has_compatible_tool_intent(query: str) -> bool:
    """判断 query 是否匹配 legacy 的泛化单工具关键词。"""
    normalized_query = _normalized_query(query)
    return any(
        trigger in normalized_query
        for trigger in ("几点", "时间", "天气", "查", "搜索", "是什么")
    )


def has_compatible_workflow_intent(query: str) -> bool:
    """判断 query 是否匹配 legacy 的两个及以上独立工作流类别。"""
    normalized_query = _normalized_query(query)
    matched_categories = (
        ("时间" in normalized_query) or ("几点" in normalized_query),
        "天气" in normalized_query,
        ("总结" in normalized_query) or ("汇总" in normalized_query),
        ("查" in normalized_query) or ("搜索" in normalized_query),
    )
    return sum(matched_categories) >= 2


def _normalized_query(query: str) -> str:
    return query.strip().lower()
