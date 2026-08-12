"""结构化记忆候选 schema 与严格响应校验。"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from typing import Any

from .policy import FactCandidate

EXTRACTOR_SCHEMA_VERSION = "m05-extractor-v1"
MAX_CANDIDATES = 16
_TOP_LEVEL_FIELDS = {"schema_version", "candidates"}
_CANDIDATE_FIELDS = {
    "subject",
    "slot",
    "value",
    "fact",
    "assertion_mode",
    "temporal_scope",
    "confidence",
    "source_span",
    "sensitivity",
}
_ASSERTION_MODES = {"statement", "correction", "question", "negation", "hypothesis", "quote"}
_TEMPORAL_SCOPES = {"current", "historical", "temporary", "unknown"}


class ExtractionOutputError(ValueError):
    """外部模型输出不满足严格 schema；错误不包含原始内容。"""


class StructuredMemoryExtractor:
    """把一个文本响应 provider 收敛为确定的候选列表。"""

    def __init__(self, response_provider: Callable[[str], Any]) -> None:
        self._response_provider = response_provider

    def extract(self, content: str) -> tuple[FactCandidate, ...]:
        return parse_extraction_output(self._response_provider(content), content)


def parse_extraction_output(raw: Any, source: str) -> tuple[FactCandidate, ...]:
    payload = _as_mapping(raw)
    if set(payload) != _TOP_LEVEL_FIELDS:
        raise ExtractionOutputError("extractor output fields are invalid")
    if payload.get("schema_version") != EXTRACTOR_SCHEMA_VERSION:
        raise ExtractionOutputError("extractor schema version is invalid")
    values = payload.get("candidates")
    if not isinstance(values, list) or len(values) > MAX_CANDIDATES:
        raise ExtractionOutputError("extractor candidates are invalid")
    return tuple(_candidate(item, source) for item in values)


def _as_mapping(raw: Any) -> Mapping[str, Any]:
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            raise ExtractionOutputError("extractor output is not JSON") from None
    elif isinstance(raw, Mapping):
        value = raw
    else:
        text = getattr(raw, "text", None)
        if not isinstance(text, str):
            raise ExtractionOutputError("extractor output is not textual")
        return _as_mapping(text)
    if not isinstance(value, Mapping):
        raise ExtractionOutputError("extractor output is not an object")
    return value


def _candidate(raw: Any, source: str) -> FactCandidate:
    if not isinstance(raw, Mapping) or not set(raw).issubset(_CANDIDATE_FIELDS):
        raise ExtractionOutputError("extractor candidate fields are invalid")
    required = {
        "subject",
        "slot",
        "value",
        "fact",
        "assertion_mode",
        "temporal_scope",
        "confidence",
        "source_span",
    }
    if not required.issubset(raw):
        raise ExtractionOutputError("extractor candidate is incomplete")
    subject = _bounded_text(raw["subject"], 80)
    slot = _bounded_text(raw["slot"], 80)
    value = _bounded_text(raw["value"], 240)
    fact = _bounded_text(raw["fact"], 320)
    mode = raw["assertion_mode"]
    temporal = raw["temporal_scope"]
    confidence = raw["confidence"]
    if mode not in _ASSERTION_MODES or temporal not in _TEMPORAL_SCOPES:
        raise ExtractionOutputError("extractor candidate classification is invalid")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ExtractionOutputError("extractor confidence is invalid")
    confidence = float(confidence)
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ExtractionOutputError("extractor confidence is invalid")
    span = raw["source_span"]
    if not isinstance(span, Mapping) or set(span) != {"start", "end"}:
        raise ExtractionOutputError("extractor source span is invalid")
    start, end = span["start"], span["end"]
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or start < 0
        or end <= start
        or end > len(source)
        or not source[start:end].strip()
        or value not in source[start:end]
        or source[start:end] != fact
    ):
        raise ExtractionOutputError("extractor source span is invalid")
    sensitivity = raw.get("sensitivity", "normal")
    if not isinstance(sensitivity, str) or not sensitivity.strip():
        raise ExtractionOutputError("extractor sensitivity is invalid")
    return FactCandidate(
        subject=subject,
        slot=slot,
        fact=fact,
        sensitivity=sensitivity.strip(),
        value=value,
        assertion_mode=mode,
        temporal_scope=temporal,
        confidence=confidence,
        source_span=(start, end),
    )


def _bounded_text(value: Any, maximum: int) -> str:
    if not isinstance(value, str):
        raise ExtractionOutputError("extractor text field is invalid")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ExtractionOutputError("extractor text field is invalid")
    return normalized
