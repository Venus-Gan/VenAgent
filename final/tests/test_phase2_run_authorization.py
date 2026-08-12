"""Phase 2 Sprint 04：可信本地身份与 Run 对象级授权契约。"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path
import sys
from uuid import UUID, uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from venagent.application.governance.identity import LocalFixedPrincipalProvider  # noqa: E402
from venagent.application.governance.run_access import (  # noqa: E402
    RunAccessService,
    RunAction,
)
from venagent.application.ports import (  # noqa: E402
    RepositoryErrorCode,
    RepositoryResult,
    RunRecord,
    RunScope,
    RunStatus,
)


class _Repository:
    def __init__(self, records: tuple[RunRecord, ...] = ()) -> None:
        self.records = {(record.scope, record.run_id): record for record in records}
        self.get_calls: list[tuple[RunScope, UUID]] = []
        self.list_calls: list[tuple[RunScope, int]] = []
        self.next_get_result: RepositoryResult[RunRecord] | None = None
        self.next_list_result: RepositoryResult[tuple[RunRecord, ...]] | None = None

    def create(self, command):  # pragma: no cover - Protocol filler
        raise AssertionError("authorization service must not create runs")

    def get(self, scope: RunScope, run_id: UUID) -> RepositoryResult[RunRecord]:
        self.get_calls.append((scope, run_id))
        if self.next_get_result is not None:
            return self.next_get_result
        record = self.records.get((scope, run_id))
        return RepositoryResult.success(record) if record is not None else RepositoryResult.failure(RepositoryErrorCode.NOT_FOUND)

    def list_recent(self, scope: RunScope, *, limit: int = 50) -> RepositoryResult[tuple[RunRecord, ...]]:
        self.list_calls.append((scope, limit))
        if self.next_list_result is not None:
            return self.next_list_result
        return RepositoryResult.success(tuple(record for (record_scope, _), record in self.records.items() if record_scope == scope))

    def update_and_append(self, command):  # pragma: no cover - Protocol filler
        raise AssertionError("authorization service must not update runs")


def _scope(*, tenant_id: str = "tenant-local", owner_principal_id: str = "local-user") -> RunScope:
    return RunScope(tenant_id=tenant_id, owner_principal_id=owner_principal_id)


def _record(*, run_id: UUID | None = None, scope: RunScope | None = None) -> RunRecord:
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
        updated_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )


def _service(repository: _Repository | None = None) -> tuple[RunAccessService, _Repository, LocalFixedPrincipalProvider]:
    provider = LocalFixedPrincipalProvider(tenant_id="tenant-local", principal_id="local-user")
    repo = repository or _Repository()
    return RunAccessService(repository=repo, principal_provider=provider), repo, provider


def test_local_fixed_principal_is_validated_immutable_and_generates_server_context():
    provider = LocalFixedPrincipalProvider(tenant_id="tenant-local", principal_id="local-user")
    run_id = uuid4()

    assert provider.current_scope() == _scope()
    assert provider.current_scope() is provider.current_scope()
    assert provider.execution_context(run_id).model_dump() == {
        "tenant_id": "tenant-local",
        "principal_id": "local-user",
        "run_id": run_id,
        "source": "server",
    }
    with pytest.raises(ValueError):
        LocalFixedPrincipalProvider(tenant_id="", principal_id="local-user")
    with pytest.raises(ValueError):
        LocalFixedPrincipalProvider(tenant_id="tenant-local", principal_id="invalid identity")


def test_run_access_public_methods_do_not_accept_client_identity_or_scope():
    signatures = {
        "list_recent": inspect.signature(RunAccessService.list_recent),
        "get": inspect.signature(RunAccessService.get),
        "authorize": inspect.signature(RunAccessService.authorize),
    }

    assert tuple(signatures["list_recent"].parameters) == ("self", "limit")
    assert tuple(signatures["get"].parameters) == ("self", "run_id")
    assert tuple(signatures["authorize"].parameters) == ("self", "run_id", "action")


def test_list_and_get_only_use_current_trusted_scope():
    owned = _record()
    foreign = _record(run_id=owned.run_id, scope=_scope(tenant_id="tenant-other", owner_principal_id="other-user"))
    service, repository, provider = _service(_Repository((owned, foreign)))

    listed = service.list_recent(limit=10)
    fetched = service.get(owned.run_id)

    assert listed.ok and listed.value == (owned,)
    assert fetched.ok and fetched.value == owned
    assert repository.list_calls == [(provider.current_scope(), 10)]
    assert repository.get_calls == [(provider.current_scope(), owned.run_id)]


@pytest.mark.parametrize("action", tuple(RunAction))
def test_foreign_and_missing_runs_have_identical_non_enumerating_authorization_results(action: RunAction):
    foreign = _record(scope=_scope(tenant_id="tenant-other", owner_principal_id="other-user"))
    service, repository, provider = _service(_Repository((foreign,)))

    foreign_result = service.authorize(foreign.run_id, action)
    missing_result = service.authorize(uuid4(), action)

    assert (foreign_result.code, foreign_result.message) == (missing_result.code, missing_result.message) == (
        RepositoryErrorCode.NOT_FOUND,
        "run not found",
    )
    assert foreign_result.record is None and missing_result.record is None
    assert repository.get_calls == [(provider.current_scope(), foreign.run_id), (provider.current_scope(), missing_result.run_id)]


@pytest.mark.parametrize(
    "code",
    (
        RepositoryErrorCode.UNAVAILABLE,
        RepositoryErrorCode.CONFLICT,
        RepositoryErrorCode.OPERATION_FAILED,
    ),
)
def test_repository_failures_are_preserved_without_empty_or_authorized_fallback(code: RepositoryErrorCode):
    service, repository, _ = _service()
    repository.next_get_result = RepositoryResult.failure(code)
    repository.next_list_result = RepositoryResult.failure(code)

    authorized = service.authorize(uuid4(), RunAction.CANCEL)
    listed = service.list_recent()

    assert (authorized.ok, authorized.record, authorized.code, authorized.message) == (False, None, code, RepositoryResult.failure(code).message)
    assert (listed.ok, listed.value, listed.code, listed.message) == (False, None, code, RepositoryResult.failure(code).message)


def test_invalid_run_identity_and_malformed_repository_success_fail_closed():
    service, repository, provider = _service()
    repository.next_get_result = RepositoryResult()

    with pytest.raises(ValueError):
        provider.execution_context("not-a-uuid")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        service.get("not-a-uuid")  # type: ignore[arg-type]

    result = service.authorize(uuid4(), RunAction.READ)

    assert (result.ok, result.record, result.code, result.message) == (
        False,
        None,
        RepositoryErrorCode.OPERATION_FAILED,
        "durable repository operation failed",
    )


def test_authorize_confirms_access_without_executing_or_mutating_run():
    record = _record()
    service, repository, _ = _service(_Repository((record,)))

    result = service.authorize(record.run_id, RunAction.CANCEL)

    assert result.ok and result.action is RunAction.CANCEL and result.record == record
    assert repository.get_calls == [(record.scope, record.run_id)]
    assert repository.list_calls == []
    assert record.status is RunStatus.RUNNING


def test_authorization_modules_do_not_depend_on_legacy_or_http_identity_parsers():
    governance_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "venagent" / "application" / "governance").rglob("*.py")
    )
    all_new_source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "venagent").rglob("*.py"))

    assert "final." not in all_new_source
    assert "fastapi" not in governance_source.lower()
    assert "from starlette" not in governance_source.lower()
    assert ".headers" not in governance_source
    assert "Request" not in governance_source
