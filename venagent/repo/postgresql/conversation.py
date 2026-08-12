"""PostgreSQL conversation adapter。

这里只负责 conversation 表及其消息查询；run 状态机位于 ``runs.py``，两者共享
同一个连接池，由上层 facade 组合，避免每个 feature 各自创建数据库入口。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from ...conversation.errors import (
    AnonymousLimitExceeded,
    ConversationNotFound,
)
from ...conversation.models import Conversation, ConversationMessage
from ...conversation.ports import ConversationStoreError as StoreError
from ...ownership.models import Actor
from .conversation_mapping import (
    agent_run_from_row,
    conversation_from_row,
    message_from_row,
)


class _PostgresConversationMixin:
    def create_conversation(self, actor: Actor, now: datetime) -> Conversation:
        conversation_id = str(uuid4())
        try:
            with self._pool.connection() as conn, conn.transaction():
                if actor.kind != "user":
                    counts = conn.execute(
                        """SELECT count(*) FILTER (WHERE lifecycle_state='active') AS live,
                        count(*) FILTER (WHERE created_at>%s-interval '10 minutes') AS recent
                        FROM conversations WHERE owner_id=%s""",
                        (now, actor.owner_id),
                    ).fetchone()
                    if int(counts["live"]) >= 10 or int(counts["recent"]) >= 5:
                        raise AnonymousLimitExceeded
                row = conn.execute(
                    """INSERT INTO conversations
                    (conversation_id,owner_id,owner_kind,created_at,updated_at)
                    SELECT %s,owner_id,kind,%s,%s FROM owners
                    WHERE owner_id=%s AND lifecycle_state='active' RETURNING *""",
                    (conversation_id, now, now, actor.owner_id),
                ).fetchone()
            if row is None:
                raise ConversationNotFound
            return conversation_from_row(row)
        except (ConversationNotFound, AnonymousLimitExceeded):
            raise
        except Exception as exc:
            raise StoreError("unable to create conversation") from exc

    def get_conversation(
        self, owner_id: str, conversation_id: str
    ) -> Conversation | None:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    "SELECT * FROM conversations WHERE owner_id=%s AND conversation_id=%s",
                    (owner_id, conversation_id),
                ).fetchone()
            return None if row is None else conversation_from_row(row)
        except Exception as exc:
            raise StoreError("unable to read conversation") from exc

    def list_conversations(
        self,
        owner_id: str,
        *,
        before: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[Conversation, ...]:
        params: list[Any] = [owner_id]
        where = "owner_id=%s AND lifecycle_state='active'"
        if before is not None:
            where += " AND (updated_at,conversation_id)<(%s,%s)"
            params.extend(before)
        params.append(limit)
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    f"SELECT * FROM conversations WHERE {where} "
                    "ORDER BY updated_at DESC,conversation_id DESC LIMIT %s",
                    params,
                ).fetchall()
            return tuple(conversation_from_row(row) for row in rows)
        except Exception as exc:
            raise StoreError("unable to list conversations") from exc

    def messages(
        self, owner_id: str, conversation_id: str
    ) -> tuple[ConversationMessage, ...]:
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    """SELECT message.* FROM conversation_messages message
                    JOIN conversations conversation USING (conversation_id)
                    WHERE conversation.owner_id=%s AND conversation.conversation_id=%s
                    ORDER BY message.sequence""",
                    (owner_id, conversation_id),
                ).fetchall()
            return tuple(message_from_row(row) for row in rows)
        except Exception as exc:
            raise StoreError("unable to list conversation messages") from exc

    def conversation_runs(self, owner_id: str, conversation_id: str):
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    """SELECT run.* FROM agent_runs run
                    JOIN conversations conversation USING (conversation_id)
                    WHERE conversation.owner_id=%s AND conversation.conversation_id=%s
                    ORDER BY run.created_at,run.run_id""",
                    (owner_id, conversation_id),
                ).fetchall()
            return tuple(agent_run_from_row(row) for row in rows)
        except Exception as exc:
            raise StoreError("unable to list conversation runs") from exc

    def rename_conversation(
        self, owner_id: str, conversation_id: str, title: str, now: datetime
    ) -> Conversation:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """UPDATE conversations SET title=%s,title_source='manual',updated_at=%s
                    WHERE owner_id=%s AND conversation_id=%s AND lifecycle_state='active'
                    RETURNING *""",
                    (title, now, owner_id, conversation_id),
                ).fetchone()
            if row is None:
                raise KeyError(conversation_id)
            return conversation_from_row(row)
        except KeyError:
            raise
        except Exception as exc:
            raise StoreError("unable to rename conversation") from exc

    def mark_conversation_deleting(
        self, owner_id: str, conversation_id: str, now: datetime
    ) -> tuple[str, ...]:
        try:
            with self._pool.connection() as conn, conn.transaction():
                row = conn.execute(
                    """UPDATE conversations SET lifecycle_state='deleting',
                    delete_requested_at=COALESCE(delete_requested_at,%s),updated_at=%s
                    WHERE owner_id=%s AND conversation_id=%s RETURNING conversation_id""",
                    (now, now, owner_id, conversation_id),
                ).fetchone()
                if row is None:
                    return ()
                runs = conn.execute(
                    """UPDATE agent_runs SET cancel_requested_at=COALESCE(cancel_requested_at,%s),
                    updated_at=%s WHERE conversation_id=%s AND status IN
                    ('queued','running','waiting_approval') RETURNING run_id""",
                    (now, now, conversation_id),
                ).fetchall()
            return tuple(str(item["run_id"]) for item in runs)
        except Exception as exc:
            raise StoreError("unable to mark conversation deleting") from exc

    def remove_conversation(self, owner_id: str, conversation_id: str) -> None:
        try:
            with self._pool.connection() as conn:
                conn.execute(
                    "DELETE FROM conversations WHERE owner_id=%s AND conversation_id=%s "
                    "AND lifecycle_state='deleting'",
                    (owner_id, conversation_id),
                )
        except Exception as exc:
            raise StoreError("unable to remove conversation") from exc

    def deleting_conversations(self) -> tuple[tuple[str, str], ...]:
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    """SELECT owner_id,conversation_id FROM conversations
                    WHERE lifecycle_state='deleting'
                    ORDER BY delete_requested_at,conversation_id"""
                ).fetchall()
            return tuple(
                (str(row["owner_id"]), str(row["conversation_id"])) for row in rows
            )
        except Exception as exc:
            raise StoreError("unable to list deleting conversations") from exc

    def owner_conversation_ids(self, owner_id: str) -> tuple[str, ...]:
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    "SELECT conversation_id FROM conversations WHERE owner_id=%s ORDER BY conversation_id",
                    (owner_id,),
                ).fetchall()
            return tuple(str(row["conversation_id"]) for row in rows)
        except Exception as exc:
            raise StoreError("unable to list owner conversations") from exc

    def expired_guest_conversations(self, now: datetime) -> tuple[tuple[str, str], ...]:
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    """SELECT owner_id,conversation_id FROM conversations
                    WHERE owner_kind='guest' AND lifecycle_state='active'
                    AND COALESCE(last_successful_at,created_at)+interval '7 days'<=%s
                    ORDER BY COALESCE(last_successful_at,created_at),conversation_id""",
                    (now,),
                ).fetchall()
            return tuple(
                (str(row["owner_id"]), str(row["conversation_id"])) for row in rows
            )
        except Exception as exc:
            raise StoreError("unable to list expired guest conversations") from exc
