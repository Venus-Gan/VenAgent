from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from venagent.platform.postgresql.migrations import (
    _migrate_to_v5,
    _migrate_to_v8,
    _migrate_to_v9,
)


class Result:
    def __init__(self, rows=()) -> None:
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self) -> None:
        self.version_recorded = False
        self.history_cleared = False
        self.created_runtime_tables = False
        self.created_memory_tables = False
        self.unlocked = False
        self.queries: list[str] = []

    def execute(self, query, params=None):
        del params
        normalized = " ".join(str(query).split())
        self.queries.append(normalized)
        if normalized.startswith("SELECT thread_id FROM conversation_threads"):
            return Result(({"thread_id": "00000000-0000-0000-0000-000000000001"},))
        if normalized.startswith("CREATE TABLE conversations"):
            self.created_runtime_tables = True
        if normalized.startswith("CREATE TABLE memory_facts"):
            self.created_memory_tables = True
        if normalized.startswith("INSERT INTO venagent_schema_migrations"):
            self.version_recorded = True
        if normalized == "DELETE FROM venagent_schema_migrations":
            self.history_cleared = True
        if normalized.startswith("SELECT pg_advisory_unlock"):
            self.unlocked = True
        return Result()

    @contextmanager
    def transaction(self):
        yield


class FakeSaver:
    def __init__(self, *, fail: bool = False) -> None:
        self.deleted: list[str] = []
        self.fail = fail

    def list(self, config):
        assert config is None
        yield SimpleNamespace(
            config={"configurable": {"thread_id": "orphan-checkpoint"}}
        )

    def delete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)
        if self.fail and thread_id == "orphan-checkpoint":
            raise RuntimeError("checkpoint cleanup failed")


def test_v5_rebuild_clears_old_checkpoints_before_creating_target_schema() -> None:
    connection = FakeConnection()
    saver = FakeSaver()

    _migrate_to_v5(connection, saver)

    assert saver.deleted == [
        "00000000-0000-0000-0000-000000000001",
        "orphan-checkpoint",
    ]
    assert connection.created_runtime_tables is True
    assert connection.created_memory_tables is True
    assert connection.history_cleared is True
    assert connection.version_recorded is True
    assert connection.unlocked is True


def test_v5_cleanup_failure_does_not_create_or_record_target_schema() -> None:
    connection = FakeConnection()

    with pytest.raises(RuntimeError, match="checkpoint cleanup failed"):
        _migrate_to_v5(connection, FakeSaver(fail=True))

    assert connection.created_runtime_tables is False
    assert connection.version_recorded is False
    assert connection.unlocked is True


class V7Connection(FakeConnection):
    def execute(self, query, params=None):
        normalized = " ".join(str(query).split())
        result = super().execute(query, params)
        if normalized.startswith("SELECT owner_id,tenant_id FROM memory_facts"):
            return Result(({"owner_id": "owner-1", "tenant_id": "default"},))
        if normalized.startswith("INSERT INTO memory_graph_authority"):
            return Result(({"authority_revision": 1},))
        if normalized.startswith("SELECT deletion_generation FROM memory_settings"):
            return Result(({"deletion_generation": 2},))
        if normalized.startswith("SELECT authorization_epoch FROM owners"):
            return Result(({"authorization_epoch": 4},))
        return result


def test_v8_forward_migration_preserves_facts_and_replaces_only_edge_projection() -> None:
    connection = V7Connection()

    _migrate_to_v8(connection)

    assert any("ADD COLUMN IF NOT EXISTS target_revision" in query for query in connection.queries)
    assert any("INSERT INTO memory_jobs" in query for query in connection.queries)
    assert "DROP TABLE IF EXISTS memory_edges" in connection.queries
    assert all("DROP TABLE IF EXISTS memory_facts" not in query for query in connection.queries)
    assert all("TRUNCATE" not in query for query in connection.queries)
    assert connection.history_cleared is True
    assert connection.version_recorded is True
    assert connection.unlocked is True


def test_v9_clears_only_memory_data_and_creates_dense_index_schema() -> None:
    connection = FakeConnection()

    _migrate_to_v9(connection)

    assert any("CREATE TABLE IF NOT EXISTS memory_embeddings" in query for query in connection.queries)
    assert any("ADD COLUMN IF NOT EXISTS memory_id" in query for query in connection.queries)
    deleted_tables = {
        query.removeprefix("DELETE FROM ")
        for query in connection.queries
        if query.startswith("DELETE FROM ")
    }
    assert {
        "memory_confirmations",
        "memory_fact_sources",
        "memory_embeddings",
        "memory_jobs",
        "memory_summaries",
        "memory_sources",
        "memory_facts",
        "memory_graph_authority",
        "memory_settings",
    }.issubset(deleted_tables)
    assert "owners" not in deleted_tables
    assert "conversations" not in deleted_tables
    assert connection.history_cleared is True
    assert connection.version_recorded is True
    assert connection.unlocked is True
