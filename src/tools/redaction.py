"""模型、聊天与日志边界的脱敏与截断。"""

from __future__ import annotations

import json
import re
from typing import Any

SENSITIVE_KEY_MARKERS = (
    "apikey",
    "api_key",
    "token",
    "password",
    "secret",
    "authorization",
    "cookie",
    "credential",
    "private_key",
    "access_key",
)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_KEY_MARKERS)


def redact_value(value: Any, *, key: str = "") -> Any:
    if _is_sensitive_key(key):
        return "***"
    if isinstance(value, dict):
        return {str(k): redact_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    return value


def redact_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): redact_value(value, key=str(key))
        for key, value in arguments.items()
    }


_SECRET_TEXT = re.compile(
    r"(?i)(api[_-]?key|token|password|secret|authorization|cookie|credential)"
    r"(\s*[=:]\s*|\"\s*:\s*\")([^\s,;\"}]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


def redact_text(content: str) -> str:
    content = _BEARER.sub("Bearer ***", content)
    return _SECRET_TEXT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}***", content
    )


def redacted_json(arguments: dict[str, Any], max_bytes: int = 2048) -> str:
    return truncate_content(
        json.dumps(redact_arguments(arguments), ensure_ascii=False, sort_keys=True),
        max_bytes,
    )


def truncate_content(content: str, max_bytes: int = 4096) -> str:
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content
    return encoded[:max_bytes].decode("utf-8", errors="ignore") + "\n…[已截断]"
