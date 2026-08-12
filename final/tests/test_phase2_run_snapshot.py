"""Phase 2 Sprint 03：业务 Run/Snapshot Port 与 PostgreSQL adapter 契约。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
from uuid import UUID, uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from venagent.adapters.postgres import (  # noqa: E402
    ADDITIVE_RUN_SNAPSHOT_DDLS,
    PostgresRunSnapshotRepository,
)
from venagent.application.ports import (  # noqa: E402
    CreateRunCommand,
    RepositoryErrorCode,
    RunRecord,
    RunScope,
    RunSnapshot,
    RunStatus,
    UpdateRunCommand,
)


class _Session:
    def __init__(self, *, one_rows=(), all_rows=(), execute_results=()):
        self.one_rows = list(one_rows)
        self.all_rows = list(all_rows)
        self.execute_results = list(execute_results)
        self.calls: list[tuple[str, str, tuple[object, ...]]] = []

    def fetch_one(self, statement: str, parameters: tuple[object, ...]):
        self.calls.append(("fetch_one", statement, parameters))
        return self.one_rows.pop(0) if self.one_rows else None

    def fetch_all(self, statement: str, parameters: tuple[object, ...]):
        self.calls.append(("fetch_all", statement, parameters))
        return self.all_rows.pop(0) if self.all_rows else ()

    def execute(self, statement: str, parameters: tuple[object, ...]) -> int:
        self.calls.append(("execute", statement, parameters))
        return self.execute_results.pop(0) if self.execute_results else 1


class _Executor:
    def __init__(self, session: _Session | None = None, *, available: bool = True, failure: Exception | None = None):
        self.session = session or _Session()
        self.available = available
        self.failure = failure
        self.transactions = 0

    def is_available(self) -> bool:
        return self.available

    @contextmanager
    def transaction(self):
        self.transactions += 1
        if self.failure is not None:
            raise self.failure
        yield self.session


def _scope(*, tenant_id: str = "tenant-1", owner_principal_id: str = "user-1") -> RunScope:
    return RunScope(tenant_id=tenant_id, owner_principal_id=owner_principal_id)


def _record(*, run_id: UUID | None = None, scope: RunScope | None = None, version: int = 1) -> RunRecord:
    return RunRecord(
        run_id=run_id or uuid4(),
        scope=scope or _scope(),
        status=RunStatus.RUNNING,
        profile="rag",
        preset_version="preset-v1",
        graph_version="graph-v1",
        policy_version="policy-v1",
        progress={"completed_steps": 1},
        result_summary={"answer": "safe summary"},
        version=version,
        started_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )


def _snapshot(record: RunRecord) -> RunSnapshot:
    return RunSnapshot(
        snapshot_id=uuid4(),
        run_id=record.run_id,
        scope=record.scope,
        version=record.version,
        schema_version="1.0",
        state={"status": record.status.value},
        progress=record.progress,
        result_summary=record.result_summary,
        audit_summary={"event": "run-updated"},
        created_at=record.updated_at,
    )


def _row(record: RunRecord) -> dict[str, object]:
    return {
        "run_id": str(record.run_id),
        "tenant_id": record.scope.tenant_id,
        "owner_principal_id": record.scope.owner_principal_id,
        "status": record.status.value,
        "profile": record.profile,
        "preset_version": record.preset_version,
        "graph_version": record.graph_version,
        "policy_version": record.policy_version,
        "progress": dict(record.progress),
        "result_summary": dict(record.result_summary),
        "version": record.version,
        "started_at": record.started_at,
        "updated_at": record.updated_at,
        "completed_at": record.completed_at,
    }


def test_run_snapshot_dtos_fail_fast_and_preserve_nested_immutability():
    record = _record()

    with pytest.raises(TypeError):
        record.progress["completed_steps"] = 2  # type: ignore[index]
    with pytest.raises(ValueError):
        RunScope(tenant_id="", owner_principal_id="user-1")
    with pytest.raises(ValueError):
        _record(version=0)
    with pytest.raises(ValueError):
        RunSnapshot(
            snapshot_id=uuid4(),
            run_id=record.run_id,
            scope=record.scope,
            version=1,
            schema_version="",
        )


def test_additive_schema_defines_scoped_double_table_without_replacing_legacy_snapshot_table():
    schema = "\n".join(ADDITIVE_RUN_SNAPSHOT_DDLS)

    assert "CREATE TABLE IF NOT EXISTS agent_runs" in schema
    assert "CREATE TABLE IF NOT EXISTS agent_run_snapshots" in schema
    assert "UNIQUE (run_id, version)" in schema
    assert "idx_agent_runs_tenant_owner_updated" in schema
    assert "task_snapshots" not in schema


def test_create_uses_parameterized_sql_and_returns_safe_business_record():
    record = _record()
    session = _Session(one_rows=(_row(record),))
    repository = PostgresRunSnapshotRepository(_Executor(session))

    result = repository.create(CreateRunCommand(record=record))

    assert result.ok is True
    assert result.value == record
    operation, statement, parameters = session.calls[0]
    assert operation == "fetch_one"
    assert "%s" in statement
    assert record.scope.tenant_id in parameters
    assert record.scope.owner_principal_id in parameters
    assert record.scope.tenant_id not in statement


def test_get_and_list_apply_scope_and_do_not_reveal_other_principal_run():
    record = _record()
    session = _Session(one_rows=(None,), all_rows=((),))
    repository = PostgresRunSnapshotRepository(_Executor(session))

    get_result = repository.get(_scope(owner_principal_id="user-2"), record.run_id)
    list_result = repository.list_recent(_scope(owner_principal_id="user-2"))

    assert get_result.code is RepositoryErrorCode.NOT_FOUND
    assert list_result.ok is True
    assert list_result.value == ()
    for _, statement, parameters in session.calls:
        assert "tenant_id = %s" in statement
        assert "owner_principal_id = %s" in statement
        assert "user-2" in parameters


def test_list_decodes_persisted_json_and_rejects_invalid_page_size():
    record = _record()
    persisted = _row(record)
    persisted["progress"] = '{"completed_steps":1}'
    persisted["result_summary"] = '{"answer":"safe summary"}'
    persisted["updated_at"] = "2026-07-19T00:00:00+00:00"
    repository = PostgresRunSnapshotRepository(_Executor(_Session(all_rows=((persisted,),))))

    result = repository.list_recent(record.scope, limit=1)

    assert result.ok is True
    assert result.value == (record,)
    with pytest.raises(ValueError):
        repository.list_recent(record.scope, limit=0)


def test_update_requires_expected_version_then_appends_same_version_snapshot_in_one_transaction():
    initial = _record(version=1)
    updated = _record(run_id=initial.run_id, scope=initial.scope, version=2)
    snapshot = _snapshot(updated)
    session = _Session(one_rows=(_row(updated),), execute_results=(1,))
    executor = _Executor(session)
    repository = PostgresRunSnapshotRepository(executor)

    result = repository.update_and_append(
        UpdateRunCommand(record=updated, snapshot=snapshot, expected_version=1)
    )

    assert result.ok is True
    assert result.value == updated
    assert executor.transactions == 1
    update_call, snapshot_call = session.calls
    assert "WHERE run_id = %s AND tenant_id = %s AND owner_principal_id = %s AND version = %s" in update_call[1]
    assert update_call[2][-1] == 1
    assert "INSERT INTO agent_run_snapshots" in snapshot_call[1]
    assert snapshot.version in snapshot_call[2]


def test_update_conflict_is_explicit_but_unscoped_or_missing_run_is_not_enumerated():
    record = _record(version=2)
    snapshot = _snapshot(record)
    conflict_session = _Session(one_rows=(None, _row(_record(run_id=record.run_id, scope=record.scope, version=1))))
    missing_session = _Session(one_rows=(None, None))

    conflict = PostgresRunSnapshotRepository(_Executor(conflict_session)).update_and_append(
        UpdateRunCommand(record=record, snapshot=snapshot, expected_version=1)
    )
    missing = PostgresRunSnapshotRepository(_Executor(missing_session)).update_and_append(
        UpdateRunCommand(record=record, snapshot=snapshot, expected_version=1)
    )

    assert conflict.code is RepositoryErrorCode.CONFLICT
    assert missing.code is RepositoryErrorCode.NOT_FOUND
    assert conflict.value is None
    assert missing.value is None


def test_write_paths_fail_closed_for_empty_return_or_failed_snapshot_append():
    record = _record()
    updated = _record(run_id=record.run_id, scope=record.scope, version=2)
    snapshot = _snapshot(updated)
    create = PostgresRunSnapshotRepository(_Executor(_Session(one_rows=(None,)))).create(CreateRunCommand(record=record))
    update = PostgresRunSnapshotRepository(
        _Executor(_Session(one_rows=(_row(updated),), execute_results=(0,)))
    ).update_and_append(UpdateRunCommand(record=updated, snapshot=snapshot, expected_version=1))

    assert create.code is RepositoryErrorCode.OPERATION_FAILED
    assert update.code is RepositoryErrorCode.OPERATION_FAILED


@pytest.mark.parametrize(
    ("executor", "expected_code"),
    [
        (_Executor(available=False), RepositoryErrorCode.UNAVAILABLE),
        (_Executor(failure=RuntimeError("postgres://user:sentinel-secret@db.internal")), RepositoryErrorCode.OPERATION_FAILED),
    ],
)
def test_durable_failures_are_explicit_and_do_not_leak_executor_details(executor, expected_code):
    result = PostgresRunSnapshotRepository(executor).get(_scope(), uuid4())

    assert result.code is expected_code
    assert result.value is None
    assert "sentinel-secret" not in result.message
    assert "db.internal" not in result.message


def test_unavailable_list_and_malformed_persisted_data_fail_closed():
    scope = _scope()
    unavailable = PostgresRunSnapshotRepository(_Executor(available=False)).list_recent(scope)
    malformed = PostgresRunSnapshotRepository(
        _Executor(_Session(one_rows=({"run_id": "not-a-uuid"},)))
    ).get(scope, uuid4())

    assert unavailable.code is RepositoryErrorCode.UNAVAILABLE
    assert malformed.code is RepositoryErrorCode.OPERATION_FAILED


def test_new_source_has_no_final_reverse_import_and_legacy_platform_consumes_additive_schema():
    from internal.platform import postgres

    forbidden_import = re.compile(r"^\s*(?:from|import)\s+final(?:\.|\s|$)", re.MULTILINE)
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "venagent").rglob("*.py"))
    legacy_platform = (ROOT / "final" / "internal" / "platform" / "postgres.py").read_text(encoding="utf-8")

    assert forbidden_import.search(source) is None
    assert "ADDITIVE_RUN_SNAPSHOT_DDLS" in legacy_platform
    assert set(ADDITIVE_RUN_SNAPSHOT_DDLS).issubset(postgres._DDLS)
