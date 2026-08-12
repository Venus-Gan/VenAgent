"""PostgreSQL 对话摘要 adapter。"""

from __future__ import annotations

# ruff: noqa: F401
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from psycopg_pool import ConnectionPool

from ....memory.ports import MemoryStoreError as StoreError
from ....memory.short_term import MemorySummary
from .row_mapping import _summary


class _PostgresShortTermMixin:
    def get_summary(self, owner_id: str, conversation_id: str) -> MemorySummary | None:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """SELECT summary.* FROM memory_summaries summary
                    JOIN memory_settings setting ON setting.owner_id=summary.owner_id
                    JOIN conversations conversation
                      ON conversation.conversation_id=summary.conversation_id
                    WHERE summary.owner_id=%s AND summary.conversation_id=%s
                    AND setting.enabled=TRUE AND setting.purge_pending=FALSE
                    AND summary.deletion_generation=setting.deletion_generation
                    AND conversation.lifecycle_state='active'""",
                    (owner_id, conversation_id),
                ).fetchone()
            return None if row is None else _summary(row)
        except Exception as exc:
            raise StoreError("unable to read memory summary") from exc

    def save_summary(self, summary: MemorySummary) -> None:
        try:
            with self._pool.connection() as conn, conn.transaction():
                # 摘要可能早于首条长期事实产生，因此先为活动 owner 建立默认设置行。
                conn.execute(
                    """INSERT INTO memory_settings (owner_id,enabled,updated_at)
                    SELECT owner_id,TRUE,%s FROM owners
                    WHERE owner_id=%s AND lifecycle_state='active'
                    ON CONFLICT (owner_id) DO NOTHING""",
                    (summary.created_at, summary.owner_id),
                )
                conn.execute(
                    """INSERT INTO memory_summaries
                    (summary_id,owner_id,tenant_id,conversation_id,first_message_id,
                     last_message_id,first_sequence,last_sequence,content,strategy_version,
                     source_state_hash,deletion_generation,created_at)
                    SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                    WHERE EXISTS (
                      SELECT 1 FROM memory_settings setting
                      WHERE setting.owner_id=%s AND setting.enabled=TRUE
                      AND setting.purge_pending=FALSE
                      AND setting.deletion_generation=%s)
                    ON CONFLICT (owner_id,conversation_id) DO UPDATE SET
                    summary_id=excluded.summary_id,
                    first_message_id=excluded.first_message_id,
                    last_message_id=excluded.last_message_id,
                    first_sequence=excluded.first_sequence,
                    last_sequence=excluded.last_sequence,
                    content=excluded.content,
                    strategy_version=excluded.strategy_version,
                    source_state_hash=excluded.source_state_hash,
                    deletion_generation=excluded.deletion_generation,
                    created_at=excluded.created_at""",
                    (
                        summary.summary_id,
                        summary.owner_id,
                        summary.tenant_id,
                        summary.conversation_id,
                        summary.first_message_id,
                        summary.last_message_id,
                        summary.first_sequence,
                        summary.last_sequence,
                        summary.content,
                        summary.strategy_version,
                        summary.source_state_hash,
                        summary.deletion_generation,
                        summary.created_at,
                        summary.owner_id,
                        summary.deletion_generation,
                    ),
                )
        except Exception as exc:
            raise StoreError("unable to save memory summary") from exc
