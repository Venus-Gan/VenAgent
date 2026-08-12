"""按完整 turn 选择 conversation 短期上下文。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Protocol
from uuid import uuid4

from ..conversation.models import ConversationMessage
from ..promptctx.context import conservative_token_count
from .long_term.policy import contains_secret, extract_candidate

SUMMARY_STRATEGY_VERSION = "deterministic-turn-summary-v1"


@dataclass(frozen=True)
class MemorySummary:
    summary_id: str
    owner_id: str
    tenant_id: str
    conversation_id: str
    first_message_id: str
    last_message_id: str
    first_sequence: int
    last_sequence: int
    content: str
    strategy_version: str
    source_state_hash: str
    deletion_generation: int
    created_at: datetime


@dataclass(frozen=True)
class ConversationTurn:
    messages: tuple[ConversationMessage, ...]
    token_count: int


class SummaryBuilder(Protocol):
    def __call__(
        self,
        older: tuple[ConversationMessage, ...],
        recent: tuple[ConversationMessage, ...],
    ) -> str: ...


def select_recent_turns(
    messages: tuple[ConversationMessage, ...], *, token_budget: int
) -> tuple[ConversationMessage, ...]:
    """只保留预算内最近完整 turn，绝不从 turn 中间截断。"""
    turns = _turns(messages)
    selected: list[ConversationTurn] = []
    total = 0
    for turn in reversed(turns):
        if total + turn.token_count > token_budget:
            break
        selected.append(turn)
        total += turn.token_count
    return tuple(message for turn in reversed(selected) for message in turn.messages)


def split_recent_turns(
    messages: tuple[ConversationMessage, ...], *, token_budget: int
) -> tuple[tuple[ConversationMessage, ...], tuple[ConversationMessage, ...]]:
    recent = select_recent_turns(messages, token_budget=token_budget)
    recent_ids = {item.message_id for item in recent}
    older = tuple(item for item in messages if item.message_id not in recent_ids)
    return recent, older


def build_summary(
    owner_id: str,
    tenant_id: str,
    conversation_id: str,
    older: tuple[ConversationMessage, ...],
    recent: tuple[ConversationMessage, ...],
    *,
    deletion_generation: int,
    now,
    builder: SummaryBuilder | None = None,
) -> MemorySummary | None:
    if not older:
        return None
    ordered = tuple(sorted(older, key=lambda item: item.sequence))
    state_hash = _summary_state_hash(ordered, recent)
    try:
        content = (builder or deterministic_summary)(ordered, recent).strip()
    except Exception:
        return None
    if not content or contains_secret(content) or len(content.encode("utf-8")) > 8192:
        return None
    return MemorySummary(
        summary_id=str(uuid4()),
        owner_id=owner_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        first_message_id=ordered[0].message_id,
        last_message_id=ordered[-1].message_id,
        first_sequence=ordered[0].sequence,
        last_sequence=ordered[-1].sequence,
        content=content,
        strategy_version=SUMMARY_STRATEGY_VERSION,
        source_state_hash=state_hash,
        deletion_generation=deletion_generation,
        created_at=now,
    )


def deterministic_summary(
    older: tuple[ConversationMessage, ...],
    recent: tuple[ConversationMessage, ...],
) -> str:
    """生成可重建摘要，并压制已被近期用户事实纠正的旧片段。"""
    latest_slots = {
        (candidate.subject, candidate.slot): candidate.fact
        for message in sorted((*older, *recent), key=lambda item: item.sequence)
        if message.role == "user"
        if (candidate := extract_candidate(message.content)) is not None
    }
    lines: list[str] = []
    for turn in _turns(older):
        user_message = turn.messages[0]
        candidate = extract_candidate(user_message.content)
        if (
            candidate is not None
            and (candidate.subject, candidate.slot) in latest_slots
            and latest_slots[(candidate.subject, candidate.slot)] != candidate.fact
        ):
            continue
        for message in turn.messages:
            role = "用户" if message.role == "user" else "助手"
            compact = " ".join(message.content.split())[:240]
            if compact:
                lines.append(f"{role}：{compact}")
    return "\n".join(lines)


def summary_matches(
    summary: MemorySummary,
    messages: tuple[ConversationMessage, ...],
    deletion_generation: int,
) -> bool:
    if summary.deletion_generation != deletion_generation:
        return False
    covered = tuple(
        item
        for item in sorted(messages, key=lambda value: value.sequence)
        if summary.first_sequence <= item.sequence <= summary.last_sequence
    )
    recent = tuple(item for item in messages if item.sequence > summary.last_sequence)
    return (
        bool(covered)
        and _summary_state_hash(covered, recent) == summary.source_state_hash
    )


def _source_state_hash(messages: tuple[ConversationMessage, ...]) -> str:
    payload = "\n".join(
        f"{item.message_id}|{item.sequence}|{item.role}|{sha256(item.content.encode('utf-8')).hexdigest()}"
        for item in messages
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _summary_state_hash(
    covered: tuple[ConversationMessage, ...],
    recent: tuple[ConversationMessage, ...],
) -> str:
    return sha256(
        f"{_source_state_hash(covered)}|{_source_state_hash(recent)}".encode("utf-8")
    ).hexdigest()


def _turns(messages: tuple[ConversationMessage, ...]) -> tuple[ConversationTurn, ...]:
    values: list[list[ConversationMessage]] = []
    current: list[ConversationMessage] = []
    for message in sorted(messages, key=lambda item: item.sequence):
        if message.role == "user":
            if current:
                values.append(current)
            current = [message]
        elif current:
            current.append(message)
    if current:
        values.append(current)
    return tuple(
        ConversationTurn(
            tuple(items),
            sum(conservative_token_count(item.content) for item in items),
        )
        for items in values
    )
