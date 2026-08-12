"""Conversation 输入、标识符与自动标题规则。"""

from __future__ import annotations

from uuid import UUID

from .errors import (
    InvalidClientRequestId,
    InvalidConversationId,
    InvalidMessage,
    InvalidTitle,
)

MAX_MESSAGE_BYTES = 32 * 1024
MAX_TITLE_CHARS = 120


def automatic_title(content: str) -> str:
    """从首条用户消息生成稳定、紧凑的默认标题。"""

    compact = " ".join(content.split())
    return compact if len(compact) <= 40 else f"{compact[:40]}..."


def validate_conversation_id(conversation_id: str) -> str:
    if not isinstance(conversation_id, str):
        raise InvalidConversationId
    try:
        parsed = UUID(conversation_id)
    except (ValueError, AttributeError) as exc:
        raise InvalidConversationId from exc
    canonical = str(parsed)
    if canonical != conversation_id:
        raise InvalidConversationId
    return canonical


def validate_client_request_id(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidClientRequestId
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise InvalidClientRequestId from exc
    canonical = str(parsed)
    if canonical != value:
        raise InvalidClientRequestId
    return canonical


def validate_message(message: str) -> str:
    if not isinstance(message, str) or not message.strip():
        raise InvalidMessage
    normalized = message.strip()
    if len(normalized.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise InvalidMessage
    return normalized


def validate_title(title: str) -> str:
    if not isinstance(title, str):
        raise InvalidTitle
    normalized = title.strip()
    if not normalized or len(normalized) > MAX_TITLE_CHARS:
        raise InvalidTitle
    return normalized
