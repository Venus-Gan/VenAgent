"""PostgreSQL 长期事实、来源、设置与删除 adapter。"""

from __future__ import annotations

# ruff: noqa: F401
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from psycopg_pool import ConnectionPool

from ....memory.long_term.facts import MemoryFact, MemorySource
from ....memory.management import MemorySettings
from ....memory.ports import G1RecallSnapshot
from ....memory.ports import MemoryStoreError as StoreError
from .row_mapping import _ids_hash, _source


class _PostgresLongTermMixin:
    def enabled(self, owner_id: str) -> bool:
        return self.settings(owner_id).enabled

    def settings(self, owner_id: str) -> MemorySettings:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """SELECT setting.*,
                    (SELECT count(*) FROM memory_jobs job WHERE job.owner_id=%s
                     AND job.status IN ('pending','running')) AS pending_jobs,
                    (SELECT count(*) FROM memory_jobs job WHERE job.owner_id=%s
                     AND job.status='failed') AS failed_jobs,
                    (SELECT count(*) FROM memory_facts fact WHERE fact.owner_id=%s
                     AND fact.status='active' AND fact.index_status<>'ready')
                     AS index_pending,
                    (SELECT count(*) FROM memory_jobs job WHERE job.owner_id=%s
                     AND job.operation IN ('project','purge')
                     AND job.status IN ('pending','running')) AS graph_pending,
                    (SELECT count(*) FROM memory_jobs job WHERE job.owner_id=%s
                     AND job.operation IN ('project','purge')
                     AND job.status='failed') AS graph_failed
                    FROM memory_settings setting WHERE setting.owner_id=%s""",
                    (owner_id, owner_id, owner_id, owner_id, owner_id, owner_id),
                ).fetchone()
                if row is None:
                    counts = conn.execute(
                        """SELECT
                        (SELECT count(*) FROM memory_jobs WHERE owner_id=%s
                         AND status IN ('pending','running')) AS pending_jobs,
                        (SELECT count(*) FROM memory_jobs WHERE owner_id=%s
                         AND status='failed') AS failed_jobs,
                        (SELECT count(*) FROM memory_facts WHERE owner_id=%s
                         AND status='active' AND index_status<>'ready') AS index_pending,
                        (SELECT count(*) FROM memory_jobs WHERE owner_id=%s
                         AND operation IN ('project','purge')
                         AND status IN ('pending','running')) AS graph_pending,
                        (SELECT count(*) FROM memory_jobs WHERE owner_id=%s
                         AND operation IN ('project','purge')
                         AND status='failed') AS graph_failed""",
                        (owner_id, owner_id, owner_id, owner_id, owner_id),
                    ).fetchone()
                    return MemorySettings(
                        enabled=True,
                        deletion_generation=0,
                        purge_pending=False,
                        pending_jobs=int(counts["pending_jobs"]),
                        failed_jobs=int(counts["failed_jobs"]),
                        index_pending=int(counts["index_pending"]),
                        graph_pending=int(counts["graph_pending"]),
                        graph_failed=int(counts["graph_failed"]),
                    )
            return MemorySettings(
                enabled=bool(row["enabled"]),
                deletion_generation=int(row["deletion_generation"]),
                purge_pending=bool(row["purge_pending"]),
                pending_jobs=int(row["pending_jobs"]),
                failed_jobs=int(row["failed_jobs"]),
                index_pending=int(row["index_pending"]),
                last_error_code=(
                    str(row["last_error_code"]) if row["last_error_code"] else None
                ),
                graph_pending=int(row["graph_pending"]),
                graph_failed=int(row["graph_failed"]),
            )
        except Exception as exc:
            raise StoreError("unable to read memory setting") from exc

    def set_enabled(self, owner_id: str, enabled: bool, now: datetime) -> None:
        try:
            with self._pool.connection() as conn, conn.transaction():
                row = conn.execute(
                    """SELECT enabled,purge_pending FROM memory_settings
                    WHERE owner_id=%s FOR UPDATE""",
                    (owner_id,),
                ).fetchone()
                if enabled and row is not None and bool(row["purge_pending"]):
                    raise StoreError("memory purge is pending")
                changed = row is None or bool(row["enabled"]) != enabled
                conn.execute(
                    """INSERT INTO memory_settings (owner_id,enabled,updated_at)
                    VALUES (%s,%s,%s) ON CONFLICT (owner_id) DO UPDATE
                    SET enabled=excluded.enabled,updated_at=excluded.updated_at""",
                    (owner_id, enabled, now),
                )
                if changed:
                    tenants = conn.execute(
                        """SELECT tenant_id FROM memory_facts WHERE owner_id=%s
                        UNION SELECT tenant_id FROM memory_sources WHERE owner_id=%s""",
                        (owner_id, owner_id),
                    ).fetchall()
                    for tenant in tenants or ({"tenant_id": "default"},):
                        self._bump_projection_in_connection(
                            conn, owner_id, str(tenant["tenant_id"]), now
                        )
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError("unable to update memory setting") from exc

    def set_index_status(
        self, owner_id: str, memory_ids: tuple[str, ...], status: str, now: datetime
    ) -> None:
        if not memory_ids:
            return
        try:
            with self._pool.connection() as conn:
                conn.execute(
                    """UPDATE memory_facts SET index_status=%s,updated_at=%s
                    WHERE owner_id=%s AND memory_id=ANY(%s) AND status='active'""",
                    (status, now, owner_id, list(memory_ids)),
                )
        except Exception as exc:
            raise StoreError("unable to update memory index status") from exc

    def list_facts(
        self,
        owner_id: str,
        tenant_id: str,
        *,
        before: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[MemoryFact, ...]:
        predicate = ""
        params: list[Any] = [owner_id, tenant_id]
        if before is not None:
            predicate = "AND (updated_at,memory_id)<(%s,%s)"
            params.extend(before)
        params.append(limit)
        return self._facts(
            f"""SELECT * FROM memory_facts WHERE owner_id=%s AND tenant_id=%s
            AND status='active' {predicate}
            ORDER BY updated_at DESC,memory_id DESC LIMIT %s""",
            tuple(params),
        )

    def get_fact(self, owner_id: str, memory_id: str) -> MemoryFact | None:
        rows = self._facts(
            "SELECT * FROM memory_facts WHERE owner_id=%s AND memory_id=%s",
            (owner_id, memory_id),
        )
        return rows[0] if rows else None

    def find_active_by_slot(
        self, owner_id: str, tenant_id: str, subject: str, slot: str
    ) -> MemoryFact | None:
        rows = self._facts(
            """SELECT * FROM memory_facts WHERE owner_id=%s AND tenant_id=%s
            AND subject=%s AND slot=%s AND status='active'
            ORDER BY updated_at DESC,memory_id DESC LIMIT 1""",
            (owner_id, tenant_id, subject, slot),
        )
        return rows[0] if rows else None

    def resolve_quarantine(
        self,
        owner_id: str,
        tenant_id: str,
        subject: str,
        slot: str,
        chosen_fact: str,
        now: datetime,
    ) -> int:
        del chosen_fact
        try:
            with self._pool.connection() as conn:
                return int(
                    conn.execute(
                        """UPDATE memory_facts SET status='superseded',updated_at=%s
                        WHERE owner_id=%s AND tenant_id=%s AND subject=%s AND slot=%s
                        AND status='quarantine'""",
                        (now, owner_id, tenant_id, subject, slot),
                    ).rowcount
                )
        except Exception as exc:
            raise StoreError("unable to resolve quarantined memory") from exc

    def save_fact(
        self, fact: MemoryFact, source: MemorySource, now: datetime
    ) -> MemoryFact:
        try:
            with self._pool.connection() as conn, conn.transaction():
                self._insert_source(conn, source)
                self._insert_fact(conn, fact)
                self._link_source(conn, fact.memory_id, source.source_ref)
                if fact.active:
                    self._bump_projection_in_connection(
                        conn, fact.owner_id, fact.tenant_id, now
                    )
            return fact
        except Exception as exc:
            raise StoreError("unable to save memory fact") from exc

    def add_source(
        self, fact: MemoryFact, source: MemorySource, now: datetime
    ) -> MemoryFact:
        try:
            with self._pool.connection() as conn, conn.transaction():
                self._insert_source(conn, source)
                self._link_source(conn, fact.memory_id, source.source_ref)
                conn.execute(
                    "UPDATE memory_facts SET updated_at=%s WHERE memory_id=%s",
                    (now, fact.memory_id),
                )
                self._bump_projection_in_connection(
                    conn, fact.owner_id, fact.tenant_id, now
                )
            refreshed = self.get_fact(fact.owner_id, fact.memory_id)
            if refreshed is None:
                raise StoreError("memory fact disappeared")
            return refreshed
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError("unable to link memory source") from exc

    def replace_fact(
        self,
        previous: MemoryFact,
        replacement: MemoryFact,
        source: MemorySource,
        now: datetime,
    ) -> MemoryFact:
        try:
            with self._pool.connection() as conn, conn.transaction():
                changed = conn.execute(
                    """UPDATE memory_facts SET status='superseded',updated_at=%s
                    WHERE owner_id=%s AND memory_id=%s AND status='active'""",
                    (now, previous.owner_id, previous.memory_id),
                ).rowcount
                if changed != 1:
                    raise StoreError("memory fact is no longer active")
                self._insert_source(conn, source)
                self._insert_fact(conn, replacement)
                self._link_source(conn, replacement.memory_id, source.source_ref)
                self._bump_projection_in_connection(
                    conn, replacement.owner_id, replacement.tenant_id, now
                )
            return replacement
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError("unable to replace memory fact") from exc

    def deactivate_fact(
        self, owner_id: str, memory_id: str, status: str, now: datetime
    ) -> bool:
        try:
            with self._pool.connection() as conn, conn.transaction():
                row = conn.execute(
                    """UPDATE memory_facts SET status=%s,subject='',slot='',fact='',
                    sensitivity='redacted',updated_at=%s
                    WHERE owner_id=%s AND memory_id=%s AND status='active'
                    RETURNING tenant_id""",
                    (status, now, owner_id, memory_id),
                ).fetchone()
                if row is not None:
                    self._bump_projection_in_connection(
                        conn, owner_id, str(row["tenant_id"]), now
                    )
            return row is not None
        except Exception as exc:
            raise StoreError("unable to deactivate memory fact") from exc

    def delete_all(self, owner_id: str, now: datetime) -> int:
        try:
            with self._pool.connection() as conn, conn.transaction():
                return self._delete_all_in_connection(conn, owner_id, now)
        except Exception as exc:
            raise StoreError("unable to delete owner memories") from exc

    def revoke_source(self, owner_id: str, source_ref: str, now: datetime) -> int:
        try:
            with self._pool.connection() as conn, conn.transaction():
                source_changed = conn.execute(
                    """UPDATE memory_sources SET active=FALSE,revoked_at=%s
                    WHERE owner_id=%s AND source_ref=%s AND active=TRUE""",
                    (now, owner_id, source_ref),
                ).rowcount
                if not source_changed:
                    return 0
                rows = conn.execute(
                    """SELECT fact.memory_id,fact.tenant_id FROM memory_facts fact
                    JOIN memory_fact_sources link ON link.memory_id=fact.memory_id
                    WHERE fact.owner_id=%s AND fact.status='active'
                    AND link.source_ref=%s""",
                    (owner_id, source_ref),
                ).fetchall()
                affected_tenants = {str(row["tenant_id"]) for row in rows}
                for row in rows:
                    memory_id = str(row["memory_id"])
                    remaining = conn.execute(
                        """SELECT count(*) AS count FROM memory_fact_sources link
                        JOIN memory_sources source ON source.source_ref=link.source_ref
                        WHERE link.memory_id=%s AND source.active=TRUE""",
                        (memory_id,),
                    ).fetchone()
                    if int(remaining["count"]) == 0:
                        conn.execute(
                            """UPDATE memory_facts SET status='deleted',subject='',slot='',
                            fact='',sensitivity='redacted',updated_at=%s
                            WHERE memory_id=%s""",
                            (now, memory_id),
                        )
                for tenant_id in affected_tenants:
                    self._bump_projection_in_connection(
                        conn, owner_id, tenant_id, now
                    )
            return len(rows)
        except Exception as exc:
            raise StoreError("unable to revoke memory source") from exc

    def source(self, owner_id: str, source_ref: str) -> MemorySource | None:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    "SELECT * FROM memory_sources WHERE owner_id=%s AND source_ref=%s",
                    (owner_id, source_ref),
                ).fetchone()
            return None if row is None else _source(row)
        except Exception as exc:
            raise StoreError("unable to read memory source") from exc

    def source_impact(self, owner_id: str, source_ref: str) -> tuple[str, ...]:
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    """SELECT fact.memory_id,fact.tenant_id FROM memory_facts fact
                    JOIN memory_fact_sources link ON link.memory_id=fact.memory_id
                    JOIN memory_sources source ON source.source_ref=link.source_ref
                    WHERE fact.owner_id=%s AND fact.status='active'
                    AND source.source_ref=%s AND source.active=TRUE
                    ORDER BY fact.memory_id""",
                    (owner_id, source_ref),
                ).fetchall()
            return tuple(str(row["memory_id"]) for row in rows)
        except Exception as exc:
            raise StoreError("unable to inspect memory source") from exc

    def issue_confirmation(
        self,
        owner_id: str,
        operation: str,
        target_ref: str,
        token_hash: str,
        state_hash: str,
        expires_at: datetime,
        now: datetime,
    ) -> None:
        try:
            with self._pool.connection() as conn:
                conn.execute(
                    """INSERT INTO memory_confirmations
                    (token_hash,owner_id,operation,target_ref,state_hash,expires_at,created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        token_hash,
                        owner_id,
                        operation,
                        target_ref,
                        state_hash,
                        expires_at,
                        now,
                    ),
                )
        except Exception as exc:
            raise StoreError("unable to issue memory confirmation") from exc

    def confirm_delete_all(
        self, owner_id: str, token_hash: str, state_hash: str, now: datetime
    ) -> int | None:
        try:
            with self._pool.connection() as conn, conn.transaction():
                if not self._consume_confirmation(
                    conn, owner_id, "delete-all", "*", token_hash, state_hash, now
                ):
                    return None
                rows = conn.execute(
                    """SELECT memory_id FROM memory_facts
                    WHERE owner_id=%s AND status='active' ORDER BY memory_id FOR UPDATE""",
                    (owner_id,),
                ).fetchall()
                if (
                    _ids_hash(tuple(str(row["memory_id"]) for row in rows))
                    != state_hash
                ):
                    return None
                return self._delete_all_in_connection(conn, owner_id, now)
        except Exception as exc:
            raise StoreError("unable to confirm memory deletion") from exc

    def confirm_revoke_source(
        self,
        owner_id: str,
        source_ref: str,
        token_hash: str,
        state_hash: str,
        now: datetime,
    ) -> int | None:
        try:
            with self._pool.connection() as conn, conn.transaction():
                if not self._consume_confirmation(
                    conn,
                    owner_id,
                    "revoke-source",
                    source_ref,
                    token_hash,
                    state_hash,
                    now,
                ):
                    return None
                rows = conn.execute(
                    """SELECT fact.memory_id FROM memory_facts fact
                    JOIN memory_fact_sources link ON link.memory_id=fact.memory_id
                    JOIN memory_sources source ON source.source_ref=link.source_ref
                    WHERE fact.owner_id=%s AND fact.status='active'
                    AND source.source_ref=%s AND source.active=TRUE
                    ORDER BY fact.memory_id FOR UPDATE OF fact""",
                    (owner_id, source_ref),
                ).fetchall()
                if (
                    _ids_hash(tuple(str(row["memory_id"]) for row in rows))
                    != state_hash
                ):
                    return None
                return self._revoke_source_in_connection(
                    conn, owner_id, source_ref, now, rows
                )
        except Exception as exc:
            raise StoreError("unable to confirm source revocation") from exc

    def active_facts(self, owner_id: str, tenant_id: str) -> tuple[MemoryFact, ...]:
        return self._facts(
            """SELECT * FROM memory_facts WHERE owner_id=%s AND tenant_id=%s
            AND status='active' ORDER BY created_at,memory_id""",
            (owner_id, tenant_id),
        )

    def authority_revision(self, owner_id: str, tenant_id: str) -> int:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """SELECT authority_revision FROM memory_graph_authority
                    WHERE owner_id=%s AND tenant_id=%s""",
                    (owner_id, tenant_id),
                ).fetchone()
            return int(row["authority_revision"]) if row else 0
        except Exception as exc:
            raise StoreError("unable to read memory authority revision") from exc

    def recall_snapshot(self, owner_id: str, tenant_id: str) -> G1RecallSnapshot:
        try:
            with self._pool.connection() as conn, conn.transaction():
                conn.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                setting_row = conn.execute(
                    "SELECT * FROM memory_settings WHERE owner_id=%s", (owner_id,)
                ).fetchone()
                settings = (
                    MemorySettings(True, 0, False)
                    if setting_row is None
                    else MemorySettings(
                        enabled=bool(setting_row["enabled"]),
                        deletion_generation=int(setting_row["deletion_generation"]),
                        purge_pending=bool(setting_row["purge_pending"]),
                        last_error_code=(
                            str(setting_row["last_error_code"])
                            if setting_row["last_error_code"]
                            else None
                        ),
                    )
                )
                fact_rows = conn.execute(
                    """SELECT * FROM memory_facts WHERE owner_id=%s
                    AND tenant_id=%s AND status='active'
                    ORDER BY created_at,memory_id""",
                    (owner_id, tenant_id),
                ).fetchall()
                source_rows = conn.execute(
                    """SELECT * FROM memory_sources WHERE owner_id=%s
                    AND tenant_id=%s AND active=TRUE ORDER BY source_ref""",
                    (owner_id, tenant_id),
                ).fetchall()
                authority = conn.execute(
                    """SELECT authority_revision FROM memory_graph_authority
                    WHERE owner_id=%s AND tenant_id=%s""",
                    (owner_id, tenant_id),
                ).fetchone()
                return G1RecallSnapshot(
                    owner_id=owner_id,
                    tenant_id=tenant_id,
                    settings=settings,
                    facts=tuple(self._fact(conn, row) for row in fact_rows),
                    sources=tuple(_source(row) for row in source_rows),
                    authority_revision=(
                        int(authority["authority_revision"]) if authority else 0
                    ),
                )
        except Exception as exc:
            raise StoreError("unable to capture memory recall snapshot") from exc

    def _delete_all_in_connection(
        self, conn: Any, owner_id: str, now: datetime
    ) -> int:
        tenants = conn.execute(
            """SELECT tenant_id FROM memory_facts WHERE owner_id=%s
            UNION SELECT tenant_id FROM memory_sources WHERE owner_id=%s""",
            (owner_id, owner_id),
        ).fetchall()
        count = conn.execute(
            """UPDATE memory_facts SET status='deleted',subject='',slot='',fact='',
            sensitivity='redacted',updated_at=%s
            WHERE owner_id=%s AND status IN ('active','quarantine')""",
            (now, owner_id),
        ).rowcount
        setting = conn.execute(
            """INSERT INTO memory_settings
            (owner_id,enabled,deletion_generation,purge_pending,updated_at)
            VALUES (%s,FALSE,1,TRUE,%s) ON CONFLICT (owner_id) DO UPDATE
            SET enabled=FALSE,
                deletion_generation=memory_settings.deletion_generation+1,
                purge_pending=TRUE,updated_at=excluded.updated_at
            RETURNING deletion_generation""",
            (owner_id, now),
        ).fetchone()
        generation = int(setting["deletion_generation"])
        for tenant in tenants or ({"tenant_id": "default"},):
            self._enqueue_purge_in_connection(
                conn, owner_id, str(tenant["tenant_id"]), generation, now
            )
        return int(count)

    def _facts(self, query: str, params: tuple[Any, ...]) -> tuple[MemoryFact, ...]:
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(query, params).fetchall()
                return tuple(self._fact(conn, row) for row in rows)
        except Exception as exc:
            raise StoreError("unable to read memory facts") from exc

    @staticmethod
    def _consume_confirmation(
        conn: Any,
        owner_id: str,
        operation: str,
        target_ref: str,
        token_hash: str,
        state_hash: str,
        now: datetime,
    ) -> bool:
        row = conn.execute(
            """SELECT * FROM memory_confirmations WHERE token_hash=%s FOR UPDATE""",
            (token_hash,),
        ).fetchone()
        if (
            row is None
            or str(row["owner_id"]) != owner_id
            or str(row["operation"]) != operation
            or str(row["target_ref"]) != target_ref
            or str(row["state_hash"]) != state_hash
            or row["consumed_at"] is not None
            or row["expires_at"] <= now
        ):
            return False
        conn.execute(
            "UPDATE memory_confirmations SET consumed_at=%s WHERE token_hash=%s",
            (now, token_hash),
        )
        return True

    def _revoke_source_in_connection(
        self,
        conn: Any,
        owner_id: str,
        source_ref: str,
        now: datetime,
        rows: list[Any],
    ) -> int:
        changed = conn.execute(
            """UPDATE memory_sources SET active=FALSE,revoked_at=%s
            WHERE owner_id=%s AND source_ref=%s AND active=TRUE""",
            (now, owner_id, source_ref),
        ).rowcount
        if not changed:
            return 0
        for row in rows:
            memory_id = str(row["memory_id"])
            remaining = conn.execute(
                """SELECT count(*) AS count FROM memory_fact_sources link
                JOIN memory_sources source ON source.source_ref=link.source_ref
                WHERE link.memory_id=%s AND source.active=TRUE""",
                (memory_id,),
            ).fetchone()
            if int(remaining["count"]) == 0:
                conn.execute(
                    """UPDATE memory_facts SET status='deleted',subject='',slot='',fact='',
                    sensitivity='redacted',updated_at=%s
                    WHERE memory_id=%s""",
                    (now, memory_id),
                )
        for tenant_id in {str(row["tenant_id"]) for row in rows}:
            self._bump_projection_in_connection(conn, owner_id, tenant_id, now)
        return len(rows)

    @staticmethod
    def _fact(conn: Any, row: Any) -> MemoryFact:
        refs = conn.execute(
            """SELECT link.source_ref FROM memory_fact_sources link
            JOIN memory_sources source ON source.source_ref=link.source_ref
            WHERE link.memory_id=%s AND source.active=TRUE ORDER BY link.source_ref""",
            (row["memory_id"],),
        ).fetchall()
        return MemoryFact(
            str(row["memory_id"]),
            str(row["owner_id"]),
            str(row["tenant_id"]),
            str(row["subject"]),
            str(row["slot"]),
            str(row["fact"]),
            str(row["status"]),  # type: ignore[arg-type]
            tuple(str(item["source_ref"]) for item in refs),
            row["created_at"],
            row["updated_at"],
            row["valid_until"],
            str(row["supersedes_id"]) if row["supersedes_id"] else None,
            str(row["sensitivity"]),
            str(row["index_status"]),  # type: ignore[arg-type]
        )

    @staticmethod
    def _insert_source(conn: Any, source: MemorySource) -> None:
        conn.execute(
            """INSERT INTO memory_sources
            (source_ref,owner_id,tenant_id,source_kind,conversation_id,source_order,
             active,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (source_ref) DO NOTHING""",
            (
                source.source_ref,
                source.owner_id,
                source.tenant_id,
                source.source_kind,
                source.conversation_id,
                source.source_order,
                source.active,
                source.created_at,
            ),
        )

    @staticmethod
    def _insert_fact(conn: Any, fact: MemoryFact) -> None:
        conn.execute(
            """INSERT INTO memory_facts
            (memory_id,owner_id,tenant_id,subject,slot,fact,status,valid_until,
             supersedes_id,sensitivity,index_status,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                fact.memory_id,
                fact.owner_id,
                fact.tenant_id,
                fact.subject,
                fact.slot,
                fact.fact,
                fact.status,
                fact.valid_until,
                fact.supersedes_id,
                fact.sensitivity,
                fact.index_status,
                fact.created_at,
                fact.updated_at,
            ),
        )

    @staticmethod
    def _link_source(conn: Any, memory_id: str, source_ref: str) -> None:
        conn.execute(
            """INSERT INTO memory_fact_sources (memory_id,source_ref)
            VALUES (%s,%s) ON CONFLICT DO NOTHING""",
            (memory_id, source_ref),
        )
