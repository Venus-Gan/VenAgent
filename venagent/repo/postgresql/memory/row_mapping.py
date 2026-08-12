"""PostgreSQL memory 行到 feature 模型的纯映射。"""

from __future__ import annotations

# ruff: noqa: F401
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from psycopg_pool import ConnectionPool

from ....memory.jobs import MemoryJob
from ....memory.long_term.facts import MemoryFact, MemorySource
from ....memory.short_term import MemorySummary


def _source(row: Any) -> MemorySource:
    return MemorySource(
        str(row["source_ref"]),
        str(row["owner_id"]),
        str(row["tenant_id"]),
        str(row["source_kind"]),
        str(row["conversation_id"]) if row["conversation_id"] else None,
        int(row["source_order"]),
        row["created_at"],
        bool(row["active"]),
    )


def _summary(row: Any) -> MemorySummary:
    return MemorySummary(
        str(row["summary_id"]),
        str(row["owner_id"]),
        str(row["tenant_id"]),
        str(row["conversation_id"]),
        str(row["first_message_id"]),
        str(row["last_message_id"]),
        int(row["first_sequence"]),
        int(row["last_sequence"]),
        str(row["content"]),
        str(row["strategy_version"]),
        str(row["source_state_hash"]),
        int(row["deletion_generation"]),
        row["created_at"],
    )


def _job(row: Any) -> MemoryJob:
    return MemoryJob(
        str(row["job_id"]),
        str(row["idempotency_key"]),
        str(row["owner_id"]),
        str(row["tenant_id"]),
        str(row["operation"]),  # type: ignore[arg-type]
        str(row["source_ref"]) if row["source_ref"] else None,
        str(row["source_kind"]) if row["source_kind"] else None,
        str(row["run_id"]) if row["run_id"] else None,
        str(row["conversation_id"]) if row["conversation_id"] else None,
        int(row["source_order"]),
        str(row["content"]),
        int(row["authorization_epoch"]),
        int(row["deletion_generation"]),
        str(row["status"]),  # type: ignore[arg-type]
        int(row["attempts"]),
        int(row["max_attempts"]),
        row["available_at"],
        row["created_at"],
        int(row.get("target_revision", 0)),
        str(row.get("registry_version", "m05-g1-v1")),
        str(row["claim_token"]) if row.get("claim_token") else None,
        str(row["memory_id"]) if row.get("memory_id") else None,
    )


def _ids_hash(values: tuple[str, ...]) -> str:
    return sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()
