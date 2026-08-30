"""M08 Query Rewrite：LLM 生成 ≥1 条独立查询（含原查询），失败回退原查询。

输出严格 JSON 数组，容忍 ```json fence（对齐 AGI-saber rewriter.go 语义）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

REWRITE_SYSTEM_PROMPT = (
    "你是查询改写助手。请把用户的原始问题改写成 1 到 3 条独立、完整的检索查询，"
    "覆盖原问题的不同侧面；第一条必须是原问题本身。只返回 JSON 字符串数组，"
    "不要包含其他内容。"
)


class RewriteOutputError(ValueError):
    """改写输出不满足 JSON 数组 schema。"""


def parse_rewrite_output(raw: Any) -> list[str] | None:
    """解析 LLM 输出；不满足 schema 返回 None（调用方回退原查询）。"""
    text: str | None = None
    if isinstance(raw, str):
        text = raw
    elif isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    else:
        candidate = getattr(raw, "text", None)
        if isinstance(candidate, str):
            text = candidate
    if text is None:
        return None
    stripped = _FENCE.sub("", text).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, list) or not value:
        return None
    queries = [str(item).strip() for item in value if str(item).strip()]
    return queries or None


class QueryRewriter:
    def __init__(self, response_provider: Any, *, num_queries: int = 3) -> None:
        self._response_provider = response_provider
        self._num_queries = num_queries

    def rewrite(
        self, query: str, history: Sequence[str] | None = None
    ) -> list[str]:
        from langchain_core.messages import HumanMessage, SystemMessage

        history_text = "\n".join(history) if history else ""
        payload = {
            "question": query,
            "num_queries": self._num_queries,
        }
        if history_text:
            payload["history"] = history_text
        try:
            response = self._response_provider(
                (
                    SystemMessage(content=REWRITE_SYSTEM_PROMPT),
                    HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
                )
            )
            queries = parse_rewrite_output(response)
        except Exception:
            return [query]
        if not queries:
            return [query]
        # 兜底：始终追加原查询并去重（对齐 AGI-saber rewriter.go:109-114）
        queries = _dedup_keep_order(queries + [query])
        return queries[: self._num_queries]


class LangChainQueryRewriter(QueryRewriter):
    """把 LangChain 模型收敛为 QueryRewriter（照 M05 适配模式）。

    构造时不绑定 invoke（流式模型可能没有）；执行时探测，缺失回退原查询。
    """

    def __init__(self, model: Any, *, num_queries: int = 3) -> None:
        super().__init__(self._request, num_queries=num_queries)
        self._model = model

    def _request(self, messages: Any) -> str:
        invoke = getattr(self._model, "invoke", None)
        if invoke is None:
            raise RewriteOutputError("model has no invoke")
        return _message_text(invoke(messages))


def _message_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    if isinstance(response, str):
        return response
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    raise RewriteOutputError("rewriter output is not textual")


def _dedup_keep_order(queries: list[str]) -> list[str]:
    """去重保留顺序（对齐 AGI-saber rewriter.go:140-152）。"""
    seen: set[str] = set()
    result: list[str] = []
    for q in queries:
        normalized = q.lower().strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(q)
    return result
