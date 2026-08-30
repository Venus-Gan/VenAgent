"""VenAgent 与官方 LangGraph checkpointer 的显式 schema migrations。"""

from datetime import datetime, timezone
from importlib.metadata import version
from typing import Any
from uuid import uuid4

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row

from ...agent.graph import checkpoint_serializer
from ..errors import PersistenceError

SCHEMA_VERSION = 13
MIGRATION_LOCK_ID = 741_904


def migrate_database(database_url: str) -> None:
    """显式重建当前 schema；应用启动路径绝不调用此函数。"""
    if not isinstance(database_url, str) or not database_url.strip():
        raise PersistenceError(
            "POSTGRES_PASSWORD is required when PostgreSQL persistence is enabled"
        )
    try:
        with psycopg.connect(
            database_url, autocommit=True, prepare_threshold=0, row_factory=dict_row
        ) as conn:
            # 迁移枚举旧 checkpoint 时复用运行期 allowlist，禁止宽松反序列化。
            saver = PostgresSaver(conn, serde=checkpoint_serializer())
            saver.setup()
            _ensure_history(conn)
            applied = _applied_versions(conn)
            if applied and applied[-1] > SCHEMA_VERSION:
                raise PersistenceError("database schema is newer than this VenAgent")
            if not applied:
                _migrate_to_v5(conn, saver)
            else:
                current = applied[-1]
                if current < 8:
                    _migrate_to_v8(conn)
                    current = 8
                if current < 9:
                    _migrate_to_v9(conn)
                    current = 9
                if current < 10:
                    _migrate_to_v10(conn)
                    current = 10
                if current < 11:
                    _migrate_to_v11(conn)
                    current = 11
                if current < SCHEMA_VERSION:
                    _migrate_to_v12(conn)
                    current = 12
                if current < SCHEMA_VERSION:
                    _migrate_to_v13(conn)
    except PersistenceError:
        raise
    except Exception as exc:
        raise PersistenceError("database migration failed") from exc


def _ensure_history(conn: Any) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS venagent_schema_migrations (
        version INTEGER PRIMARY KEY,
        checkpointer_version TEXT NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
    )


def _applied_versions(conn: Any) -> list[int]:
    return [
        int(row["version"])
        for row in conn.execute(
            "SELECT version FROM venagent_schema_migrations ORDER BY version"
        ).fetchall()
    ]


def _migrate_to_v5(conn: Any, saver: PostgresSaver) -> None:
    """清除旧 runtime 数据并建立无兼容包袱的当前 schema。

    函数名作为既有迁移测试入口保留；写入的版本始终取 ``SCHEMA_VERSION``。
    """
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
    try:
        thread_ids: set[str] = set()
        try:
            rows = conn.execute("SELECT thread_id FROM conversation_threads").fetchall()
            thread_ids.update(str(row["thread_id"]) for row in rows)
        except Exception:
            # 新库不存在旧表；checkpoint 仍需按 saver 自身枚举清理。
            pass
        for checkpoint in saver.list(None):
            thread_id = checkpoint.config.get("configurable", {}).get("thread_id")
            if thread_id:
                thread_ids.add(str(thread_id))
        for thread_id in sorted(thread_ids):
            saver.delete_thread(thread_id)

        with conn.transaction():
            for table in (
                "run_events",
                "memory_jobs",
                "memory_summaries",
                "memory_confirmations",
                "memory_fact_sources",
                "memory_sources",
                "memory_facts",
                "memory_settings",
                "run_requests",
                "conversation_messages",
                "agent_runs",
                "run_grants",
                "conversation_turns",
                "conversation_imports",
                "conversations",
                "conversation_threads",
                "auth_sessions",
                "guest_sessions",
                "users",
                "owners",
            ):
                conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

            conn.execute(
                """CREATE TABLE owners (
                owner_id UUID PRIMARY KEY,
                kind TEXT NOT NULL CHECK (kind IN ('guest','user')),
                lifecycle_state TEXT NOT NULL DEFAULT 'active'
                    CHECK (lifecycle_state IN ('active','deleting')),
                authorization_epoch INTEGER NOT NULL DEFAULT 1
                    CHECK (authorization_epoch>0),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                delete_requested_at TIMESTAMPTZ NULL,
                UNIQUE (owner_id,kind))"""
            )
            conn.execute(
                """CREATE TABLE users (
                owner_id UUID PRIMARY KEY,
                owner_kind TEXT NOT NULL DEFAULT 'user' CHECK (owner_kind='user'),
                username_normalized TEXT NOT NULL UNIQUE,
                username_display TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                password_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                FOREIGN KEY (owner_id,owner_kind) REFERENCES owners(owner_id,kind)
                    ON DELETE CASCADE)"""
            )
            for table, owner_column, owner_table in (
                ("auth_sessions", "user_owner_id", "users"),
                ("guest_sessions", "guest_owner_id", "owners"),
            ):
                conn.execute(
                    f"""CREATE TABLE {table} (
                    session_id UUID PRIMARY KEY,
                    {owner_column} UUID NOT NULL REFERENCES {owner_table}(owner_id)
                        ON DELETE CASCADE,
                    refresh_hash TEXT NOT NULL UNIQUE,
                    previous_refresh_hash TEXT NULL UNIQUE,
                    previous_valid_until TIMESTAMPTZ NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    revoked_at TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
                )
            conn.execute(
                """CREATE TABLE conversations (
                conversation_id UUID PRIMARY KEY,
                owner_id UUID NOT NULL,
                owner_kind TEXT NOT NULL CHECK (owner_kind IN ('guest','user')),
                lifecycle_state TEXT NOT NULL DEFAULT 'active'
                    CHECK (lifecycle_state IN ('active','deleting')),
                title TEXT NOT NULL DEFAULT '新对话',
                title_source TEXT NOT NULL DEFAULT 'auto'
                    CHECK (title_source IN ('auto','manual')),
                last_successful_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                delete_requested_at TIMESTAMPTZ NULL,
                FOREIGN KEY (owner_id,owner_kind) REFERENCES owners(owner_id,kind)
                    ON DELETE CASCADE)"""
            )
            conn.execute(
                """CREATE TABLE conversation_messages (
                message_id UUID PRIMARY KEY,
                conversation_id UUID NOT NULL REFERENCES conversations(conversation_id)
                    ON DELETE CASCADE,
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user','assistant')),
                content TEXT NOT NULL,
                content_blocks JSONB NULL,
                sequence INTEGER NOT NULL CHECK (sequence>0),
                client_request_id UUID NULL,
                source_run_id UUID NULL,
                reply_to_message_id UUID NULL REFERENCES conversation_messages(message_id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (conversation_id,sequence),
                CHECK ((role='user' AND client_request_id IS NOT NULL
                        AND source_run_id IS NULL AND reply_to_message_id IS NULL)
                    OR (role='assistant' AND client_request_id IS NULL
                        AND source_run_id IS NOT NULL AND reply_to_message_id IS NOT NULL)))"""
            )
            conn.execute(
                """CREATE TABLE run_grants (
                grant_id UUID PRIMARY KEY,
                run_id UUID NOT NULL UNIQUE,
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                tenant_id TEXT NOT NULL,
                conversation_id UUID NOT NULL REFERENCES conversations(conversation_id)
                    ON DELETE CASCADE,
                allowed_data_scopes JSONB NOT NULL,
                allowed_action_classes JSONB NOT NULL,
                authorization_epoch INTEGER NOT NULL CHECK (authorization_epoch>0),
                requested_by_session_id UUID NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                revoked_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (grant_id,run_id))"""
            )
            conn.execute(
                """CREATE TABLE agent_runs (
                run_id UUID PRIMARY KEY,
                conversation_id UUID NOT NULL REFERENCES conversations(conversation_id)
                    ON DELETE CASCADE,
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                input_message_id UUID NOT NULL REFERENCES conversation_messages(message_id),
                output_message_id UUID NULL REFERENCES conversation_messages(message_id),
                grant_id UUID NOT NULL,
                status TEXT NOT NULL CHECK (status IN
                    ('queued','running','waiting_approval','succeeded','failed','cancelled','incompatible')),
                runtime_contract_version INTEGER NOT NULL CHECK (runtime_contract_version>0),
                retry_of_run_id UUID NULL REFERENCES agent_runs(run_id),
                phase TEXT NULL,
                completed_nodes INTEGER NOT NULL DEFAULT 0 CHECK (completed_nodes>=0),
                total_nodes INTEGER NOT NULL DEFAULT 1 CHECK (total_nodes>0),
                claimed_by TEXT NULL,
                claim_token UUID NULL,
                lease_expires_at TIMESTAMPTZ NULL,
                execution_attempt INTEGER NOT NULL DEFAULT 0 CHECK (execution_attempt>=0),
                selected_skill_id TEXT NULL,
                selected_skill_name TEXT NULL,
                cancel_requested_at TIMESTAMPTZ NULL,
                terminal_reason_code TEXT NULL,
                terminal_message TEXT NULL,
                started_at TIMESTAMPTZ NULL,
                completed_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                FOREIGN KEY (grant_id,run_id) REFERENCES run_grants(grant_id,run_id),
                CHECK ((status='succeeded' AND output_message_id IS NOT NULL
                            AND completed_at IS NOT NULL)
                    OR (status IN ('failed','cancelled','incompatible')
                            AND output_message_id IS NULL AND completed_at IS NOT NULL)
                    OR (status IN ('queued','running','waiting_approval')
                            AND output_message_id IS NULL AND completed_at IS NULL)))"""
            )
            conn.execute(
                """ALTER TABLE conversation_messages ADD CONSTRAINT
                conversation_messages_source_run_fk FOREIGN KEY (source_run_id)
                REFERENCES agent_runs(run_id) ON DELETE CASCADE"""
            )
            conn.execute(
                """CREATE TABLE run_events (
                run_id UUID NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
                sequence BIGINT NOT NULL CHECK (sequence>0),
                event_type TEXT NOT NULL,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (run_id,sequence))"""
            )
            conn.execute(
                """CREATE TABLE run_requests (
                conversation_id UUID NOT NULL REFERENCES conversations(conversation_id)
                    ON DELETE CASCADE,
                client_request_id UUID NOT NULL,
                operation TEXT NOT NULL CHECK (operation IN ('create','retry')),
                payload_hash TEXT NOT NULL CHECK
                    (char_length(payload_hash)=64 AND payload_hash ~ '^[0-9a-f]{64}$'),
                input_message_id UUID NOT NULL REFERENCES conversation_messages(message_id),
                run_id UUID NOT NULL REFERENCES agent_runs(run_id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (conversation_id,client_request_id))"""
            )
            conn.execute(
                """CREATE TABLE memory_settings (
                owner_id UUID PRIMARY KEY REFERENCES owners(owner_id) ON DELETE CASCADE,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                deletion_generation INTEGER NOT NULL DEFAULT 0,
                purge_pending BOOLEAN NOT NULL DEFAULT FALSE,
                last_error_code TEXT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
            )
            conn.execute(
                """CREATE TABLE memory_sources (
                source_ref TEXT PRIMARY KEY,
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                tenant_id TEXT NOT NULL,
                source_kind TEXT NOT NULL CHECK
                    (source_kind IN ('user_message','tool_result','command')),
                conversation_id UUID NULL REFERENCES conversations(conversation_id)
                    ON DELETE SET NULL,
                source_order INTEGER NOT NULL CHECK (source_order>=0),
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                revoked_at TIMESTAMPTZ NULL)"""
            )
            conn.execute(
                """CREATE TABLE memory_facts (
                memory_id UUID PRIMARY KEY,
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                tenant_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                slot TEXT NOT NULL,
                fact TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN
                    ('active','superseded','deleted','expired','quarantine')),
                valid_until TIMESTAMPTZ NULL,
                supersedes_id UUID NULL REFERENCES memory_facts(memory_id),
                sensitivity TEXT NOT NULL DEFAULT 'normal',
                index_status TEXT NOT NULL DEFAULT 'ready'
                    CHECK (index_status IN ('ready','pending','failed')),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
            )
            conn.execute(
                """CREATE TABLE memory_fact_sources (
                memory_id UUID NOT NULL REFERENCES memory_facts(memory_id)
                    ON DELETE CASCADE,
                source_ref TEXT NOT NULL REFERENCES memory_sources(source_ref)
                    ON DELETE CASCADE,
                PRIMARY KEY (memory_id,source_ref))"""
            )
            conn.execute(
                """CREATE TABLE memory_embeddings (
                memory_id UUID PRIMARY KEY REFERENCES memory_facts(memory_id)
                    ON DELETE CASCADE,
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                tenant_id TEXT NOT NULL,
                model TEXT NOT NULL,
                index_version TEXT NOT NULL,
                embedding REAL[] NOT NULL CHECK (cardinality(embedding)>0),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
            )
            conn.execute(
                """CREATE TABLE memory_graph_authority (
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                tenant_id TEXT NOT NULL,
                authority_revision BIGINT NOT NULL DEFAULT 0
                    CHECK (authority_revision>=0),
                registry_version TEXT NOT NULL DEFAULT 'm05-g1-v1',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (owner_id,tenant_id))"""
            )
            conn.execute(
                """CREATE TABLE memory_summaries (
                summary_id UUID PRIMARY KEY,
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                tenant_id TEXT NOT NULL,
                conversation_id UUID NOT NULL REFERENCES conversations(conversation_id)
                    ON DELETE CASCADE,
                first_message_id UUID NOT NULL REFERENCES conversation_messages(message_id)
                    ON DELETE CASCADE,
                last_message_id UUID NOT NULL REFERENCES conversation_messages(message_id)
                    ON DELETE CASCADE,
                first_sequence INTEGER NOT NULL CHECK (first_sequence>0),
                last_sequence INTEGER NOT NULL CHECK (last_sequence>=first_sequence),
                content TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                source_state_hash TEXT NOT NULL CHECK (char_length(source_state_hash)=64),
                deletion_generation INTEGER NOT NULL CHECK (deletion_generation>=0),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (owner_id,conversation_id))"""
            )
            conn.execute(
                """CREATE TABLE memory_consolidation_cursor (
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                tenant_id TEXT NOT NULL,
                conversation_id UUID NOT NULL REFERENCES conversations(conversation_id)
                    ON DELETE CASCADE,
                last_consolidated_sequence BIGINT NOT NULL DEFAULT 0
                    CHECK (last_consolidated_sequence>=0),
                last_message_sequence BIGINT NOT NULL DEFAULT 0
                    CHECK (last_message_sequence>=0),
                last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                deletion_generation INTEGER NOT NULL DEFAULT 0
                    CHECK (deletion_generation>=0),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (owner_id,tenant_id,conversation_id))"""
            )
            conn.execute(
                """CREATE INDEX memory_consolidation_cursor_activity_idx
                ON memory_consolidation_cursor (last_activity_at)"""
            )
            conn.execute(
                """CREATE TABLE memory_jobs (
                job_id UUID PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                tenant_id TEXT NOT NULL,
                operation TEXT NOT NULL CHECK (operation IN
                    ('extract','index','project','purge','quarantine-review','expire','consolidate')),
                source_ref TEXT NULL,
                memory_id UUID NULL REFERENCES memory_facts(memory_id) ON DELETE SET NULL,
                source_kind TEXT NULL CHECK
                    (source_kind IS NULL OR source_kind IN ('user_message','tool_result')),
                run_id UUID NULL REFERENCES agent_runs(run_id) ON DELETE SET NULL,
                conversation_id UUID NULL REFERENCES conversations(conversation_id)
                    ON DELETE CASCADE,
                source_order INTEGER NOT NULL DEFAULT 0 CHECK (source_order>=0),
                content TEXT NOT NULL DEFAULT '',
                authorization_epoch INTEGER NOT NULL CHECK (authorization_epoch>=0),
                deletion_generation INTEGER NOT NULL CHECK (deletion_generation>=0),
                target_revision BIGINT NOT NULL DEFAULT 0 CHECK (target_revision>=0),
                registry_version TEXT NOT NULL DEFAULT 'm05-g1-v1',
                claim_token UUID NULL,
                status TEXT NOT NULL CHECK (status IN
                    ('pending','running','succeeded','failed','cancelled')),
                attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts>=0),
                max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts>0),
                available_at TIMESTAMPTZ NOT NULL,
                last_error_code TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
            )
            conn.execute(
                """CREATE TABLE memory_confirmations (
                token_hash TEXT PRIMARY KEY CHECK (char_length(token_hash)=64),
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                operation TEXT NOT NULL CHECK
                    (operation IN ('delete-all','revoke-source')),
                target_ref TEXT NOT NULL,
                state_hash TEXT NOT NULL CHECK (char_length(state_hash)=64),
                expires_at TIMESTAMPTZ NOT NULL,
                consumed_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
            )
            conn.execute(
                """CREATE UNIQUE INDEX agent_runs_one_active_per_conversation
                ON agent_runs (conversation_id)
                WHERE status IN ('queued','running','waiting_approval')"""
            )
            conn.execute(
                """CREATE UNIQUE INDEX conversation_messages_source_run_unique
                ON conversation_messages (source_run_id) WHERE source_run_id IS NOT NULL"""
            )
            conn.execute(
                """CREATE UNIQUE INDEX conversation_messages_reply_unique
                ON conversation_messages (reply_to_message_id)
                WHERE reply_to_message_id IS NOT NULL"""
            )
            conn.execute(
                """CREATE INDEX conversations_owner_updated_idx
                ON conversations (owner_id,updated_at DESC,conversation_id DESC)
                WHERE lifecycle_state='active'"""
            )
            conn.execute(
                """CREATE INDEX agent_runs_claim_idx
                ON agent_runs (created_at,run_id)
                WHERE status IN ('queued','running')"""
            )
            conn.execute(
                """CREATE INDEX memory_facts_owner_activity_idx
                ON memory_facts (owner_id,tenant_id,updated_at DESC,memory_id DESC)
                WHERE status='active'"""
            )
            conn.execute(
                """CREATE INDEX memory_sources_owner_idx
                ON memory_sources (owner_id,source_ref)"""
            )
            conn.execute(
                """CREATE INDEX memory_jobs_claim_idx
                ON memory_jobs (available_at,created_at,job_id)
                WHERE status IN ('pending','running')"""
            )
            # 当前基线有意拒绝旧 schema；清除旧版本行可让启动校验拒绝缺号历史。
            conn.execute("DELETE FROM venagent_schema_migrations")
            _record_version(conn, SCHEMA_VERSION)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))


def _migrate_to_v8(conn: Any) -> None:
    """Preserve v7 business data while replacing the PostgreSQL edge projection."""
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
    try:
        now = datetime.now(timezone.utc)
        with conn.transaction():
            conn.execute(
                """CREATE TABLE IF NOT EXISTS memory_graph_authority (
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                tenant_id TEXT NOT NULL,
                authority_revision BIGINT NOT NULL DEFAULT 0
                    CHECK (authority_revision>=0),
                registry_version TEXT NOT NULL DEFAULT 'm05-g1-v1',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (owner_id,tenant_id))"""
            )
            conn.execute(
                "ALTER TABLE memory_jobs ADD COLUMN IF NOT EXISTS target_revision "
                "BIGINT NOT NULL DEFAULT 0 CHECK (target_revision>=0)"
            )
            conn.execute(
                "ALTER TABLE memory_jobs ADD COLUMN IF NOT EXISTS registry_version "
                "TEXT NOT NULL DEFAULT 'm05-g1-v1'"
            )
            conn.execute(
                "ALTER TABLE memory_jobs ADD COLUMN IF NOT EXISTS claim_token UUID NULL"
            )
            conn.execute(
                """UPDATE memory_facts SET index_status='ready'
                WHERE status='active' AND index_status<>'ready'"""
            )
            rows = conn.execute(
                """SELECT owner_id,tenant_id FROM memory_facts
                UNION SELECT owner_id,tenant_id FROM memory_sources
                ORDER BY owner_id,tenant_id"""
            ).fetchall()
            for row in rows:
                authority = conn.execute(
                    """INSERT INTO memory_graph_authority
                    (owner_id,tenant_id,authority_revision,updated_at)
                    VALUES (%s,%s,1,%s)
                    ON CONFLICT (owner_id,tenant_id) DO UPDATE SET
                    authority_revision=GREATEST(
                        memory_graph_authority.authority_revision,1),
                    updated_at=excluded.updated_at
                    RETURNING authority_revision""",
                    (row["owner_id"], row["tenant_id"], now),
                ).fetchone()
                revision = int(authority["authority_revision"])
                setting = conn.execute(
                    "SELECT deletion_generation FROM memory_settings WHERE owner_id=%s",
                    (row["owner_id"],),
                ).fetchone()
                generation = int(setting["deletion_generation"]) if setting else 0
                owner = conn.execute(
                    "SELECT authorization_epoch FROM owners WHERE owner_id=%s",
                    (row["owner_id"],),
                ).fetchone()
                conn.execute(
                    """INSERT INTO memory_jobs
                    (job_id,idempotency_key,owner_id,tenant_id,operation,source_order,
                     content,authorization_epoch,deletion_generation,target_revision,
                     registry_version,status,attempts,max_attempts,available_at,
                     created_at,updated_at)
                    VALUES (%s,%s,%s,%s,'project',0,'',%s,%s,%s,'m05-g1-v1',
                            'pending',0,3,%s,%s,%s)
                    ON CONFLICT (idempotency_key) DO NOTHING""",
                    (
                        str(uuid4()),
                        f"project:{row['owner_id']}:{row['tenant_id']}:{revision}",
                        row["owner_id"],
                        row["tenant_id"],
                        int(owner["authorization_epoch"]),
                        generation,
                        revision,
                        now,
                        now,
                        now,
                    ),
                )
            conn.execute(
                """UPDATE memory_jobs SET status='cancelled',content='',updated_at=%s
                WHERE operation='project' AND target_revision=0
                AND status IN ('pending','running','failed')""",
                (now,),
            )
            conn.execute("DROP TABLE IF EXISTS memory_edges")
            conn.execute("DROP INDEX IF EXISTS memory_jobs_claim_idx")
            conn.execute(
                """CREATE INDEX memory_jobs_claim_idx
                ON memory_jobs (available_at,created_at,job_id)
                WHERE status IN ('pending','running')"""
            )
            conn.execute("DELETE FROM venagent_schema_migrations")
            _record_version(conn, 8)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))


def _migrate_to_v9(conn: Any) -> None:
    """清理开发期旧记忆并建立 `real[]` 派生索引。"""
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
    try:
        with conn.transaction():
            conn.execute(
                """CREATE TABLE IF NOT EXISTS memory_embeddings (
                memory_id UUID PRIMARY KEY REFERENCES memory_facts(memory_id)
                    ON DELETE CASCADE,
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                tenant_id TEXT NOT NULL,
                model TEXT NOT NULL,
                index_version TEXT NOT NULL,
                embedding REAL[] NOT NULL CHECK (cardinality(embedding)>0),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
            )
            conn.execute(
                "ALTER TABLE memory_jobs DROP CONSTRAINT IF EXISTS memory_jobs_operation_check"
            )
            conn.execute(
                """ALTER TABLE memory_jobs ADD COLUMN IF NOT EXISTS memory_id UUID NULL
                REFERENCES memory_facts(memory_id) ON DELETE SET NULL"""
            )
            conn.execute(
                """ALTER TABLE memory_jobs ADD CONSTRAINT memory_jobs_operation_check
                CHECK (operation IN ('extract','index','project','purge',
                'quarantine-review','expire','consolidate'))"""
            )
            for table in (
                "memory_confirmations",
                "memory_fact_sources",
                "memory_embeddings",
                "memory_jobs",
                "memory_summaries",
                "memory_sources",
                "memory_facts",
                "memory_graph_authority",
                "memory_settings",
            ):
                conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM venagent_schema_migrations")
            _record_version(conn, SCHEMA_VERSION)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))


def _migrate_to_v10(conn: Any) -> None:
    """增加可回放 RunEvent 与结构化 assistant blocks，保留既有对话。"""
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
    try:
        with conn.transaction():
            conn.execute(
                """ALTER TABLE conversation_messages
                ADD COLUMN IF NOT EXISTS content_blocks JSONB NULL"""
            )
            conn.execute(
                """UPDATE conversation_messages
                SET content_blocks=jsonb_build_array(
                    jsonb_build_object('type','text','text',content))
                WHERE role='assistant' AND content_blocks IS NULL"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS run_events (
                run_id UUID NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
                sequence BIGINT NOT NULL CHECK (sequence>0),
                event_type TEXT NOT NULL,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (run_id,sequence))"""
            )
            conn.execute("DELETE FROM venagent_schema_migrations")
            _record_version(conn, SCHEMA_VERSION)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))


def _migrate_to_v11(conn: Any) -> None:
    """在 agent_runs 持久化 selected_skill_id/name，支持刷新后显示 Skill。"""
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
    try:
        with conn.transaction():
            conn.execute(
                """ALTER TABLE agent_runs
                ADD COLUMN IF NOT EXISTS selected_skill_id TEXT NULL"""
            )
            conn.execute(
                """ALTER TABLE agent_runs
                ADD COLUMN IF NOT EXISTS selected_skill_name TEXT NULL"""
            )
            conn.execute("DELETE FROM venagent_schema_migrations")
            _record_version(conn, SCHEMA_VERSION)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))


def _migrate_to_v12(conn: Any) -> None:
    """M08 RAG 文档库：rag_documents / rag_document_versions / rag_chunks。

    per-owner 隔离（owner_id 全链携带），重传版本化（UNIQUE(document_id,version)），
    chunk 按 (owner_id, doc_hash, chunk_idx) 幂等 upsert（AGI-saber 语义 + 隔离）。
    """
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
    try:
        with conn.transaction():
            conn.execute(
                """CREATE TABLE IF NOT EXISTS rag_documents (
                document_id TEXT PRIMARY KEY,
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                doc_type TEXT NOT NULL DEFAULT 'note',
                source TEXT NOT NULL DEFAULT 'agent_generated' CHECK (source IN
                    ('agent_generated','user_upload')),
                status TEXT NOT NULL DEFAULT 'uploaded' CHECK (status IN
                    ('uploaded','parsing','chunking','indexing','ready','failed','deleted')),
                failure_reason TEXT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0
                    CHECK (chunk_count>=0),
                indexed_count INTEGER NOT NULL DEFAULT 0
                    CHECK (indexed_count>=0),
                created_by TEXT NOT NULL DEFAULT 'agent',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_rag_documents_owner_status
                ON rag_documents (owner_id, status)"""
            )
            # 自愈：早期 v12 约束缺 'deleted'（软删状态），重建约束幂等修复。
            conn.execute(
                "ALTER TABLE rag_documents DROP CONSTRAINT IF EXISTS "
                "rag_documents_status_check"
            )
            conn.execute(
                """ALTER TABLE rag_documents ADD CONSTRAINT rag_documents_status_check
                CHECK (status IN
                    ('uploaded','parsing','chunking','indexing','ready','failed','deleted'))"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS rag_document_versions (
                version_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL
                    REFERENCES rag_documents(document_id) ON DELETE CASCADE,
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                version INTEGER NOT NULL CHECK (version>0),
                content_md TEXT NOT NULL,
                summary TEXT NULL,
                metadata JSONB NULL,
                doc_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (owner_id, document_id, version))"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS rag_chunks (
                id BIGSERIAL PRIMARY KEY,
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                document_id TEXT NOT NULL
                    REFERENCES rag_documents(document_id) ON DELETE CASCADE,
                version_id TEXT NOT NULL
                    REFERENCES rag_document_versions(version_id) ON DELETE CASCADE,
                chunk_idx INTEGER NOT NULL CHECK (chunk_idx>=0),
                content TEXT NOT NULL,
                parent_content TEXT NULL,
                section TEXT NULL,
                doc_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (owner_id, document_id, version_id, chunk_idx))"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_rag_chunks_document
                ON rag_chunks (owner_id, document_id, version_id)"""
            )
            conn.execute("DELETE FROM venagent_schema_migrations")
            _record_version(conn, SCHEMA_VERSION)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))


def _migrate_to_v13(conn: Any) -> None:
    """M05 沉淀式写入：consolidate 任务 + 每对话游标表。

    记忆写入改为攒批延迟：run 结束不再逐条 extract，而是推进
    memory_consolidation_cursor；攒满窗口或静默超时后入队一次 consolidate job。
    """
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
    try:
        with conn.transaction():
            conn.execute(
                "ALTER TABLE memory_jobs DROP CONSTRAINT IF EXISTS "
                "memory_jobs_operation_check"
            )
            conn.execute(
                """ALTER TABLE memory_jobs ADD CONSTRAINT memory_jobs_operation_check
                CHECK (operation IN ('extract','index','project','purge',
                'quarantine-review','expire','consolidate'))"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS memory_consolidation_cursor (
                owner_id UUID NOT NULL REFERENCES owners(owner_id) ON DELETE CASCADE,
                tenant_id TEXT NOT NULL,
                conversation_id UUID NOT NULL REFERENCES conversations(conversation_id)
                    ON DELETE CASCADE,
                last_consolidated_sequence BIGINT NOT NULL DEFAULT 0
                    CHECK (last_consolidated_sequence>=0),
                last_message_sequence BIGINT NOT NULL DEFAULT 0
                    CHECK (last_message_sequence>=0),
                last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                deletion_generation INTEGER NOT NULL DEFAULT 0
                    CHECK (deletion_generation>=0),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (owner_id,tenant_id,conversation_id))"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS memory_consolidation_cursor_activity_idx
                ON memory_consolidation_cursor (last_activity_at)"""
            )
            conn.execute("DELETE FROM venagent_schema_migrations")
            _record_version(conn, SCHEMA_VERSION)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))


def _record_version(conn: Any, schema_version: int) -> None:
    conn.execute(
        """INSERT INTO venagent_schema_migrations (version, checkpointer_version)
        VALUES (%s, %s) ON CONFLICT (version) DO NOTHING""",
        (schema_version, version("langgraph-checkpoint-postgres")),
    )
