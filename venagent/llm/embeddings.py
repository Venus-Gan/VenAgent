"""通用 `/embeddings` HTTP adapter 与严格响应校验。"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

from ..config import EmbeddingConfig


class EmbeddingError(RuntimeError):
    """稳定技术错误；不携带请求原文、凭据或响应向量。"""


EmbeddingRequest = Callable[[str, Mapping[str, str], Mapping[str, Any], float], Any]


class HttpEmbeddingClient:
    def __init__(
        self,
        config: EmbeddingConfig,
        *,
        request: EmbeddingRequest | None = None,
    ) -> None:
        if not config.enabled:
            raise ValueError("embedding configuration is disabled")
        self._config = config
        self._request = request or _httpx_request

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise EmbeddingError("embedding input is invalid")
        headers = {
            "Authorization": f"Bearer {self._config.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        payload = {"model": self._config.model, "input": list(texts)}
        response: Any = None
        for attempt in range(self._config.max_retries + 1):
            try:
                response = self._request(
                    self._config.api_url,
                    headers,
                    payload,
                    self._config.timeout,
                )
                return _parse_embedding_response(response, len(texts))
            except Exception as exc:
                if attempt >= self._config.max_retries:
                    raise EmbeddingError("embedding request failed") from exc
        raise EmbeddingError("embedding request failed")


def _httpx_request(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout: float,
) -> Any:
    import httpx

    response = httpx.post(url, headers=dict(headers), json=dict(payload), timeout=timeout)
    response.raise_for_status()
    return response.json()


def _parse_embedding_response(raw: Any, expected_count: int) -> tuple[tuple[float, ...], ...]:
    if hasattr(raw, "json") and callable(raw.json):
        raw = raw.json()
    if not isinstance(raw, Mapping):
        raise EmbeddingError("embedding response is invalid")
    data = raw.get("data")
    if not isinstance(data, list) or len(data) != expected_count:
        raise EmbeddingError("embedding response count mismatch")
    ordered: list[tuple[float, ...] | None] = [None] * expected_count
    dimension: int | None = None
    for item in data:
        if not isinstance(item, Mapping) or set(item) - {"index", "embedding", "object"}:
            raise EmbeddingError("embedding response item is invalid")
        index, vector = item.get("index"), item.get("embedding")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < expected_count:
            raise EmbeddingError("embedding response index is invalid")
        if ordered[index] is not None or not isinstance(vector, list) or not vector:
            raise EmbeddingError("embedding response vector is invalid")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in vector
        ):
            raise EmbeddingError("embedding response vector is invalid")
        normalized = tuple(float(value) for value in vector)
        dimension = len(normalized) if dimension is None else dimension
        if len(normalized) != dimension:
            raise EmbeddingError("embedding response dimensions mismatch")
        ordered[index] = normalized
    if any(item is None for item in ordered):
        raise EmbeddingError("embedding response order is invalid")
    return tuple(item for item in ordered if item is not None)
