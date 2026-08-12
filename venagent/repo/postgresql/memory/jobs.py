"""PostgreSQL memory 后台任务队列 adapter。"""

from __future__ import annotations

# ruff: noqa: F401
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from psycopg_pool import ConnectionPool

from ....memory.jobs import MemoryJob
from ....memory.ports import MemoryStoreError as StoreError
from .row_mapping import _job


class _PostgresJobsMixin:
    def enqueue_job(self, job: MemoryJob) -> bool:
        try:
            with self._pool.connection() as conn:
                changed = conn.execute(
                    """INSERT INTO memory_jobs
                    (job_id,idempotency_key,owner_id,tenant_id,operation,source_ref,memory_id,
                     source_kind,run_id,conversation_id,source_order,content,authorization_epoch,
                     deletion_generation,target_revision,registry_version,claim_token,status,
                     attempts,max_attempts,available_at,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (idempotency_key) DO NOTHING""",
                    (
                        job.job_id,
                        job.idempotency_key,
                        job.owner_id,
                        job.tenant_id,
                        job.operation,
                        job.source_ref,
                        job.memory_id,
                        job.source_kind,
                        job.run_id,
                        job.conversation_id,
                        job.source_order,
                        job.content,
                        job.authorization_epoch,
                        job.deletion_generation,
                        job.target_revision,
                        job.registry_version,
                        job.claim_token,
                        job.status,
                        job.attempts,
                        job.max_attempts,
                        job.available_at,
                        job.created_at,
                        job.created_at,
                    ),
                ).rowcount
            return changed == 1
        except Exception as exc:
            raise StoreError("unable to enqueue memory job") from exc

    def claim_jobs(self, now: datetime, *, limit: int) -> tuple[MemoryJob, ...]:
        try:
            with self._pool.connection() as conn, conn.transaction():
                rows = conn.execute(
                    """SELECT job.* FROM memory_jobs job
                    JOIN owners owner ON owner.owner_id=job.owner_id
                    LEFT JOIN conversations conversation
                      ON conversation.conversation_id=job.conversation_id
                    WHERE job.status IN ('pending','running') AND job.available_at<=%s
                    AND (owner.lifecycle_state='active'
                         OR (owner.lifecycle_state='deleting' AND job.operation='purge'))
                    AND (job.conversation_id IS NULL
                         OR conversation.lifecycle_state='active')
                    ORDER BY job.available_at,job.created_at,job.job_id
                    FOR UPDATE OF job SKIP LOCKED LIMIT %s""",
                    (now, limit),
                ).fetchall()
                claimed: list[MemoryJob] = []
                for row in rows:
                    updated = conn.execute(
                        """UPDATE memory_jobs SET status='running',attempts=attempts+1,
                        available_at=%s,claim_token=%s,updated_at=%s
                        WHERE job_id=%s RETURNING *""",
                        (
                            now + timedelta(seconds=30),
                            str(uuid4()),
                            now,
                            row["job_id"],
                        ),
                    ).fetchone()
                    claimed.append(_job(updated))
                return tuple(claimed)
        except Exception as exc:
            raise StoreError("unable to claim memory jobs") from exc

    def complete_job(self, job_id: str, claim_token: str, now: datetime) -> bool:
        return self._update_job_terminal(job_id, claim_token, "succeeded", now)

    def retry_job(
        self,
        job_id: str,
        claim_token: str,
        error_code: str,
        available_at: datetime,
        now: datetime,
    ) -> bool:
        try:
            with self._pool.connection() as conn, conn.transaction():
                row = conn.execute(
                    """SELECT owner_id,operation,attempts,max_attempts FROM memory_jobs
                    WHERE job_id=%s AND status='running' AND claim_token=%s FOR UPDATE""",
                    (job_id, claim_token),
                ).fetchone()
                if row is None:
                    return False
                graph_job = str(row["operation"]) in {"project", "purge"}
                exhausted = (
                    not graph_job
                    and int(row["attempts"]) >= int(row["max_attempts"])
                )
                conn.execute(
                    """UPDATE memory_jobs SET status=%s,last_error_code=%s,
                    available_at=%s,claim_token=NULL,updated_at=%s WHERE job_id=%s""",
                    (
                        "failed" if exhausted else "pending",
                        error_code,
                        available_at,
                        now,
                        job_id,
                    ),
                )
                conn.execute(
                    """INSERT INTO memory_settings (owner_id,last_error_code,updated_at)
                    VALUES (%s,%s,%s) ON CONFLICT (owner_id) DO UPDATE SET
                    last_error_code=excluded.last_error_code,
                    updated_at=excluded.updated_at""",
                    (row["owner_id"], error_code, now),
                )
                return True
        except Exception as exc:
            raise StoreError("unable to retry memory job") from exc

    def cancel_job(self, job_id: str, claim_token: str, now: datetime) -> bool:
        return self._update_job_terminal(job_id, claim_token, "cancelled", now)

    def requeue_failed(self, owner_id: str, now: datetime) -> int:
        try:
            with self._pool.connection() as conn, conn.transaction():
                changed = conn.execute(
                    """UPDATE memory_jobs job SET status='pending',attempts=0,
                    available_at=%s,last_error_code=NULL,updated_at=%s
                    FROM memory_settings setting
                    WHERE job.owner_id=%s AND job.status='failed'
                    AND setting.owner_id=job.owner_id AND setting.enabled=TRUE
                    AND setting.purge_pending=FALSE
                    AND job.deletion_generation=setting.deletion_generation""",
                    (now, now, owner_id),
                ).rowcount
                if changed:
                    conn.execute(
                        """UPDATE memory_settings SET last_error_code=NULL,updated_at=%s
                        WHERE owner_id=%s""",
                        (now, owner_id),
                    )
                return int(changed)
        except Exception as exc:
            raise StoreError("unable to replay failed memory jobs") from exc

    def finish_purge(self, owner_id: str, generation: int, now: datetime) -> bool:
        try:
            with self._pool.connection() as conn, conn.transaction():
                row = conn.execute(
                    """SELECT deletion_generation,purge_pending FROM memory_settings
                    WHERE owner_id=%s FOR UPDATE""",
                    (owner_id,),
                ).fetchone()
                if (
                    row is None
                    or int(row["deletion_generation"]) != generation
                    or not bool(row["purge_pending"])
                ):
                    return False
                conn.execute(
                    "DELETE FROM memory_summaries WHERE owner_id=%s",
                    (owner_id,),
                )
                conn.execute(
                    """DELETE FROM memory_fact_sources link USING memory_facts fact
                    WHERE link.memory_id=fact.memory_id AND fact.owner_id=%s
                    AND fact.status IN ('deleted','expired')""",
                    (owner_id,),
                )
                conn.execute(
                    """DELETE FROM memory_sources source WHERE source.owner_id=%s
                    AND NOT EXISTS (SELECT 1 FROM memory_fact_sources link
                                    WHERE link.source_ref=source.source_ref)""",
                    (owner_id,),
                )
                conn.execute(
                    """UPDATE memory_jobs SET status='cancelled',content='',updated_at=%s
                    WHERE owner_id=%s AND deletion_generation<%s
                    AND status IN ('pending','running')""",
                    (now, owner_id, generation),
                )
                conn.execute(
                    """UPDATE memory_settings SET purge_pending=FALSE,updated_at=%s
                    WHERE owner_id=%s""",
                    (now, owner_id),
                )
                return True
        except Exception as exc:
            raise StoreError("unable to finish memory purge") from exc

    def expire_due(self, now: datetime) -> int:
        try:
            with self._pool.connection() as conn, conn.transaction():
                rows = conn.execute(
                    """UPDATE memory_facts SET status='expired',subject='',slot='',fact='',
                    sensitivity='redacted',updated_at=%s
                    WHERE status IN ('active','quarantine')
                    AND valid_until IS NOT NULL AND valid_until<=%s
                    RETURNING memory_id,owner_id,tenant_id""",
                    (now, now),
                ).fetchall()
                for owner_id, tenant_id in {
                    (row["owner_id"], row["tenant_id"]) for row in rows
                }:
                    self._bump_projection_in_connection(
                        conn, owner_id, tenant_id, now
                    )
                return len(rows)
        except Exception as exc:
            raise StoreError("unable to expire memory facts") from exc

    def _update_job_terminal(
        self, job_id: str, claim_token: str, status: str, now: datetime
    ) -> bool:
        try:
            with self._pool.connection() as conn:
                changed = conn.execute(
                    """UPDATE memory_jobs SET status=%s,content='',updated_at=%s
                    ,claim_token=NULL WHERE job_id=%s AND status='running'
                    AND claim_token=%s""",
                    (status, now, job_id, claim_token),
                ).rowcount
                return changed == 1
        except Exception as exc:
            raise StoreError("unable to update memory job") from exc

    def _bump_projection_in_connection(
        self, conn: Any, owner_id: Any, tenant_id: str, now: datetime
    ) -> int:
        authority = conn.execute(
            """INSERT INTO memory_graph_authority
            (owner_id,tenant_id,authority_revision,updated_at)
            VALUES (%s,%s,1,%s)
            ON CONFLICT (owner_id,tenant_id) DO UPDATE SET
            authority_revision=memory_graph_authority.authority_revision+1,
            updated_at=excluded.updated_at
            RETURNING authority_revision""",
            (owner_id, tenant_id, now),
        ).fetchone()
        revision = int(authority["authority_revision"])
        setting = conn.execute(
            "SELECT deletion_generation FROM memory_settings WHERE owner_id=%s",
            (owner_id,),
        ).fetchone()
        owner = conn.execute(
            "SELECT authorization_epoch FROM owners WHERE owner_id=%s", (owner_id,)
        ).fetchone()
        if owner is None:
            raise StoreError("memory owner disappeared during projection enqueue")
        generation = int(setting["deletion_generation"]) if setting else 0
        conn.execute(
            """UPDATE memory_jobs SET status='cancelled',content='',updated_at=%s
            WHERE owner_id=%s AND tenant_id=%s AND operation='project'
            AND status='pending' AND target_revision<%s""",
            (now, owner_id, tenant_id, revision),
        )
        conn.execute(
            """INSERT INTO memory_jobs
            (job_id,idempotency_key,owner_id,tenant_id,operation,source_order,content,
             authorization_epoch,deletion_generation,target_revision,registry_version,
             status,attempts,max_attempts,available_at,created_at,updated_at)
            VALUES (%s,%s,%s,%s,'project',0,'',%s,%s,%s,'m05-g1-v1',
                    'pending',0,3,%s,%s,%s)
            ON CONFLICT (idempotency_key) DO NOTHING""",
            (
                str(uuid4()),
                f"project:{owner_id}:{tenant_id}:{revision}",
                owner_id,
                tenant_id,
                int(owner["authorization_epoch"]),
                generation,
                revision,
                now,
                now,
                now,
            ),
        )
        return revision

    def _enqueue_purge_in_connection(
        self,
        conn: Any,
        owner_id: Any,
        tenant_id: str,
        generation: int,
        now: datetime,
    ) -> int:
        revision = self._bump_projection_in_connection(
            conn, owner_id, tenant_id, now
        )
        conn.execute(
            """UPDATE memory_jobs SET status='cancelled',updated_at=%s
            WHERE owner_id=%s AND tenant_id=%s AND operation='project'
            AND target_revision=%s AND status='pending'""",
            (now, owner_id, tenant_id, revision),
        )
        owner = conn.execute(
            "SELECT authorization_epoch FROM owners WHERE owner_id=%s", (owner_id,)
        ).fetchone()
        conn.execute(
            """INSERT INTO memory_jobs
            (job_id,idempotency_key,owner_id,tenant_id,operation,source_order,content,
             authorization_epoch,deletion_generation,target_revision,registry_version,
             status,attempts,max_attempts,available_at,created_at,updated_at)
            VALUES (%s,%s,%s,%s,'purge',0,'',%s,%s,%s,'m05-g1-v1',
                    'pending',0,3,%s,%s,%s)
            ON CONFLICT (idempotency_key) DO NOTHING""",
            (
                str(uuid4()),
                f"purge:{owner_id}:{tenant_id}:{generation}",
                owner_id,
                tenant_id,
                int(owner["authorization_epoch"]),
                generation,
                revision,
                now,
                now,
                now,
            ),
        )
        return revision
