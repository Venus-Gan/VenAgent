"""Schema 迁移契约（公开 API）：`migrate_database` 的场景行为与数据保全。

规则 ②/③ 重写：不再导入私有 `_migrate_to_vN`，不锁死任何 SQL 文本；
用假连接把 SQL 归一化文本归约为**语义事件**（建/删表、加列、清历史、记版本、
清 checkpoint），只断言行为结果与数据保全，不断言精确 SQL/Cypher 字符串。
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

import venagent.platform.postgresql.migrations as migrations_module
from venagent.platform import PersistenceError
from venagent.platform.postgresql.migrations import (
    SCHEMA_VERSION,
    migrate_database,
)

MIGRATION_URL = "postgresql://migrate:secret@127.0.0.1/venagent"


class Result:
    def __init__(self, rows=()) -> None:
        if isinstance(rows, dict):
            rows = [rows]
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


def _normalize(query: Any) -> str:
    return " ".join(str(query).split())


def _head(query: Any) -> str:
    return _normalize(query).lower()


class FakeConnection:
    """把每条 SQL 归约为语义事件；只按前缀分类，不用于断言输出文本。"""

    def __init__(self, *, applied_versions: list[int] | None = None) -> None:
        self.applied_versions = list(applied_versions or [])
        self.fact_owners: list[dict[str, str]] = []

        self.locked = False
        self.unlocked = False
        self.history_cleared = False
        self.created_tables: set[str] = set()
        self.dropped_tables: set[str] = set()
        self.deleted_from: set[str] = set()
        self.dropped_indexes: set[str] = set()
        self.created_indexes: set[str] = set()
        self.added_columns: set[tuple[str, str]] = set()
        self.versions_recorded: list[int] = []
        self.authority_revisions: list[int] = []
        self.project_job_params: list[tuple[Any, ...]] = []
        self.index_status_reset = False
        self.stale_projects_cancelled = False

    @contextmanager
    def transaction(self):
        yield

    def execute(self, query: Any, params: Any = None) -> Result:
        normalized = _normalize(query)
        head = _head(query)

        if head.startswith("select pg_advisory_lock"):
            self.locked = True
            return Result()
        if head.startswith("select pg_advisory_unlock"):
            self.unlocked = True
            return Result()
        if head.startswith("select version from venagent_schema_migrations"):
            return Result([{"version": v} for v in self.applied_versions])
        if head.startswith("select thread_id from conversation_threads"):
            return Result()
        if head.startswith("select owner_id,tenant_id from memory_facts"):
            return Result(self.fact_owners)
        if head.startswith("insert into memory_graph_authority"):
            self.authority_revisions.append(1)
            return Result({"authority_revision": 1})
        if head.startswith("select deletion_generation from memory_settings"):
            return Result({"deletion_generation": 2})
        if head.startswith("select authorization_epoch from owners"):
            return Result({"authorization_epoch": 4})

        if head.startswith("update memory_jobs set status='cancelled'"):
            self.stale_projects_cancelled = True
        elif head.startswith("update memory_facts set index_status='ready'"):
            self.index_status_reset = True
        elif head.startswith("insert into venagent_schema_migrations"):
            self.versions_recorded.append(int(params[0]) if params else -1)
        elif head.startswith("insert into memory_jobs"):
            self.project_job_params.append(tuple(params) if params else ())
        elif head.startswith("create table"):
            self.created_tables.add(self._table_of(normalized, "create"))
        elif head.startswith("drop table"):
            self.dropped_tables.add(self._table_of(normalized, "drop"))
        elif head.startswith("drop index"):
            self.dropped_indexes.add(self._index_of(normalized))
        elif head.startswith("create index") or head.startswith("create unique index"):
            self.created_indexes.add(self._index_of(normalized))
        elif "add column if not exists" in normalized.lower():
            match = re.search(
                r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+)", normalized
            )
            if match:
                self.added_columns.add((match.group(1), match.group(2)))
        elif head.startswith("delete from"):
            self.deleted_from.add(self._table_of(normalized, "delete"))
            if head == "delete from venagent_schema_migrations":
                self.history_cleared = True
        return Result()

    @staticmethod
    def _table_of(normalized: str, kind: str) -> str:
        if kind == "create":
            match = re.search(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)", normalized)
        elif kind == "drop":
            match = re.search(r"DROP TABLE (?:IF EXISTS )?(\w+)", normalized)
        else:
            match = re.search(r"DELETE FROM (\w+)", normalized)
        return match.group(1) if match else normalized

    @staticmethod
    def _index_of(normalized: str) -> str:
        match = re.search(
            r"(?:CREATE|DROP) (?:UNIQUE )?INDEX (?:IF (?:NOT )?EXISTS )?(\w+)",
            normalized,
        )
        return match.group(1) if match else normalized


class FakeSaver:
    def __init__(self, *, fail: bool = False) -> None:
        self.deleted: list[str] = []
        self.fail = fail

    def setup(self) -> None:
        pass

    def list(self, config=None):
        del config
        yield SimpleNamespace(
            config={"configurable": {"thread_id": "orphan-checkpoint"}}
        )

    def delete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)
        if self.fail and thread_id == "orphan-checkpoint":
            raise RuntimeError("checkpoint cleanup failed")


class _Connect:
    def __init__(self, connection: FakeConnection, url: str, **kwargs: Any) -> None:
        self.connection = connection
        self.url = url
        self.kwargs = kwargs

    def __enter__(self):
        return self.connection

    def __exit__(self, *exc: Any) -> bool:
        return False


def _build(monkeypatch: pytest.MonkeyPatch, *, applied=(), saver=None):
    connection = FakeConnection(applied_versions=list(applied))
    saver = saver or FakeSaver()
    stub = SimpleNamespace(connect=lambda url, **kw: _Connect(connection, url, **kw))
    monkeypatch.setattr(migrations_module, "psycopg", stub)
    monkeypatch.setattr(
        migrations_module,
        "PostgresSaver",
        lambda _connection, **kwargs: saver,
    )
    return connection, saver


def test_fresh_database_rebuilds_expected_schema_and_clears_old_checkpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _build(monkeypatch)[0]

    migrate_database(MIGRATION_URL)

    assert connection.locked is True
    assert connection.unlocked is True
    assert connection.history_cleared is True
    assert connection.versions_recorded == [SCHEMA_VERSION]
    assert connection.created_tables >= {
        "owners", "users", "auth_sessions", "guest_sessions", "run_grants",
        "conversations", "conversation_messages", "agent_runs", "run_events",
        "run_requests", "memory_settings", "memory_sources", "memory_facts",
        "memory_fact_sources", "memory_embeddings", "memory_graph_authority",
        "memory_summaries", "memory_jobs", "memory_confirmations",
        "memory_consolidation_cursor",
    }
    assert "memory_consolidation_cursor_activity_idx" in connection.created_indexes
    assert "conversation_threads" in connection.dropped_tables
    assert "memory_edges" not in connection.created_tables


def test_fresh_rebuild_checkpoint_failure_leaves_no_target_schema_and_unlocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, saver = _build(monkeypatch, saver=FakeSaver(fail=True))

    with pytest.raises(PersistenceError) as exc_info:
        migrate_database(MIGRATION_URL)

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "checkpoint cleanup failed" in str(exc_info.value.__cause__)
    assert connection.created_tables == {"venagent_schema_migrations"}
    assert "owners" not in connection.created_tables
    assert connection.versions_recorded == []
    assert connection.unlocked is True
    assert saver.deleted == ["orphan-checkpoint"]


def test_applied_v7_cascades_v8_through_v13_preserving_business_and_memory_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, _saver = _build(monkeypatch, applied=[7])
    connection.fact_owners = [{"owner_id": "owner-1", "tenant_id": "default"}]

    migrate_database(MIGRATION_URL)

    assert connection.versions_recorded == [
        8,
        SCHEMA_VERSION,
        SCHEMA_VERSION,
        SCHEMA_VERSION,
        SCHEMA_VERSION,
        SCHEMA_VERSION,
    ]
    assert connection.locked is True and connection.unlocked is True
    # v8：建 authority、加 target_revision、重建投影、丢弃就绪后待重建的边表
    assert "memory_graph_authority" in connection.created_tables
    assert ("memory_jobs", "target_revision") in connection.added_columns
    assert "memory_edges" in connection.dropped_tables
    assert "memory_facts" not in connection.dropped_tables
    assert connection.authority_revisions == [1]
    assert len(connection.project_job_params) == 1
    job = connection.project_job_params[0]  # (job_id, key, owner, tenant, epoch, gen, rev, avail, created, updated)
    assert job[2:7] == (
        "owner-1",
        "default",
        4,  # authorization_epoch
        2,  # deletion_generation
        1,  # target_revision == backfilled authority revision
    )
    assert job[1] == "project:owner-1:default:1"
    assert connection.stale_projects_cancelled is True
    # v9：清 memory_* 数据但绝不碰业务表
    assert ("memory_jobs", "memory_id") in connection.added_columns
    assert {
        "memory_settings", "memory_sources", "memory_facts",
        "memory_fact_sources", "memory_embeddings", "memory_graph_authority",
        "memory_summaries", "memory_jobs", "memory_confirmations",
    } <= connection.deleted_from
    assert "conversations" not in connection.deleted_from
    assert "conversation_messages" not in connection.deleted_from
    assert "owners" not in connection.deleted_from
    # v10：assistant 结构化块 + 可回放事件，对话数据只增强不清
    assert ("conversation_messages", "content_blocks") in connection.added_columns
    assert "run_events" in connection.created_tables
    # v11：Skill 展示字段
    assert ("agent_runs", "selected_skill_id") in connection.added_columns
    assert ("agent_runs", "selected_skill_name") in connection.added_columns
    # v12：RAG 文档库三表
    assert {
        "rag_documents",
        "rag_document_versions",
        "rag_chunks",
    } <= connection.created_tables
    # v13：M05 沉淀游标表 + consolidate 写入面（不新增业务表）
    assert "memory_consolidation_cursor" in connection.created_tables
    assert "memory_consolidation_cursor_activity_idx" in connection.created_indexes


def test_applied_v10_runs_only_v11_through_v13_and_touches_no_business_memory_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _build(monkeypatch, applied=[10])[0]

    migrate_database(MIGRATION_URL)

    assert connection.versions_recorded == [SCHEMA_VERSION] * 3
    assert ("agent_runs", "selected_skill_id") in connection.added_columns
    assert ("agent_runs", "selected_skill_name") in connection.added_columns
    assert "memory_edges" not in connection.dropped_tables
    assert "run_events" not in connection.created_tables
    assert {table for table, _column in connection.added_columns} == {"agent_runs"}
    assert "rag_chunks" in connection.created_tables


def test_newer_schema_version_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build(monkeypatch, applied=[SCHEMA_VERSION + 1])

    with pytest.raises(
        PersistenceError, match="database schema is newer than this VenAgent"
    ):
        migrate_database(MIGRATION_URL)


def test_empty_database_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _build(monkeypatch)

    with pytest.raises(
        PersistenceError,
        match="POSTGRES_PASSWORD is required when PostgreSQL persistence is enabled",
    ):
        migrate_database("")