"""M08 LLM listwise rerank：0~10 整数打分，JSON 严格解析，失败回退原序。

对齐 AGI-saber rerank.go：preview 200 字符、{scores:[{idx,score}]} 容忍 fence、
未给分 idx 不丢弃（-1 排尾部）、score/10 归一由 hybrid 层主排。
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

RERANK_SYSTEM_PROMPT = (
    "你是检索结果排序助手。对给定候选片段按与问题的相关性打 0 到 10 的整数分。"
    '只返回 JSON object：{"scores":[{"idx": 0, "score": 8}, ...]}，'
    "必须为每个 idx 给出 score，不要包含其他内容。"
)


class RerankOutputError(ValueError):
    """rerank 输出不满足 schema。"""


def parse_rerank_output(raw: Any, count: int) -> list[tuple[int, float]] | None:
    """解析 {scores:[{idx,score}]}；缺失/非法返回 None（调用方回退原序）。"""
    text: str | None = None
    if isinstance(raw, str):
        text = raw
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
    if not isinstance(value, dict) or not isinstance(value.get("scores"), list):
        return None
    scored: list[tuple[int, float]] = []
    for item in value["scores"]:
        if not isinstance(item, dict) or "idx" not in item or "score" not in item:
            return None
        index = item["idx"]
        score = item["score"]
        if isinstance(index, bool) or isinstance(score, bool):
            return None
        if not isinstance(index, int) or not isinstance(score, (int, float)):
            return None
        if not 0 <= index < count or not 0 <= float(score) <= 10:
            return None
        scored.append((index, float(score)))
    return scored or None


class Reranker:
    def __init__(self, response_provider: Any, *, preview_len: int = 200) -> None:
        self._response_provider = response_provider
        self._preview_len = preview_len

    def rerank(
        self, query: str, candidates: list[str], preview_len: int | None = None
    ) -> list[tuple[int, float]] | None:
        limit = preview_len or self._preview_len
        from langchain_core.messages import HumanMessage, SystemMessage

        payload = {
            "question": query,
            "candidates": [
                {"idx": index, "preview": item[:limit]}
                for index, item in enumerate(candidates)
            ],
        }
        try:
            response = self._response_provider(
                (
                    SystemMessage(content=RERANK_SYSTEM_PROMPT),
                    HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
                )
            )
            scored = parse_rerank_output(response, len(candidates))
        except Exception:
            return None
        return scored


class LangChainReranker(Reranker):
    """把 LangChain 模型收敛为 Reranker（照 M05 适配模式）。

    构造时不绑定 invoke（流式模型可能没有）；执行时探测，缺失回退原序。
    """

    def __init__(self, model: Any, *, preview_len: int = 200) -> None:
        super().__init__(self._request, preview_len=preview_len)
        self._model = model

    def _request(self, messages: Any) -> str:
        invoke = getattr(self._model, "invoke", None)
        if invoke is None:
            raise RerankOutputError("model has no invoke")
        text = getattr(invoke(messages), "text", None)
        if isinstance(text, str):
            return text
        raise RerankOutputError("rerank output is not textual")
