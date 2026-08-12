"""PostgreSQL 行到平台 feature 模型的纯映射。

映射集中在 adapter 边界，业务层因此不需要知道 psycopg row 的列名细节。
"""

from __future__ import annotations

from typing import Any

from ...agent.runs import AgentRun
from ...conversation.models import Conversation, ConversationMessage


def conversation_from_row(row: Any) -> Conversation:
    return Conversation(
        conversation_id=str(row["conversation_id"]),
        owner_id=str(row["owner_id"]),
        owner_kind=str(row["owner_kind"]),
        lifecycle_state=str(row["lifecycle_state"]),
        title=str(row["title"]),
        title_source=str(row["title_source"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_successful_at=row.get("last_successful_at"),
    )


def message_from_row(row: Any) -> ConversationMessage:
    return ConversationMessage(
        message_id=str(row["message_id"]),
        conversation_id=str(row["conversation_id"]),
        owner_id=str(row["owner_id"]),
        role=str(row["role"]),
        content=str(row["content"]),
        sequence=int(row["sequence"]),
        created_at=row["created_at"],
        client_request_id=_optional_str(row.get("client_request_id")),
        source_run_id=_optional_str(row.get("source_run_id")),
        reply_to_message_id=_optional_str(row.get("reply_to_message_id")),
    )


def agent_run_from_row(row: Any) -> AgentRun:
    return AgentRun(
        run_id=str(row["run_id"]),
        conversation_id=str(row["conversation_id"]),
        owner_id=str(row["owner_id"]),
        input_message_id=str(row["input_message_id"]),
        grant_id=str(row["grant_id"]),
        status=str(row["status"]),
        runtime_contract_version=int(row["runtime_contract_version"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        output_message_id=_optional_str(row.get("output_message_id")),
        retry_of_run_id=_optional_str(row.get("retry_of_run_id")),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        cancel_requested_at=row.get("cancel_requested_at"),
        terminal_reason_code=_optional_str(row.get("terminal_reason_code")),
        terminal_message=_optional_str(row.get("terminal_message")),
        phase=_optional_str(row.get("phase")),
        completed_nodes=int(row.get("completed_nodes") or 0),
        total_nodes=int(row.get("total_nodes") or 1),
        claimed_by=_optional_str(row.get("claimed_by")),
        claim_token=_optional_str(row.get("claim_token")),
        lease_expires_at=row.get("lease_expires_at"),
        execution_attempt=int(row.get("execution_attempt") or 0),
    )


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)
