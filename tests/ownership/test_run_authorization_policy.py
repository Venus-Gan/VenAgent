"""RunAuthorizationPolicy 三条失败路径与放行路径（单点）。

- 授权查询异常 → ERROR 日志 + 拒绝：本文件单点。
- owner 不匹配 / 缺 tool.invoke → WARNING 日志 + 拒绝：本文件单点。
- gateway 对 authorizer False 的反应（RunGrantInvalid）由
  tests/tools/test_tools_gateway_contract.py 覆盖。
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.ownership.authorization import RunAuthorizationPolicy
from src.ownership.models import ExecutionAuthorization


def _authorization(
    owner_id: str = "owner-1",
    action_classes: tuple[str, ...] = ("tool.invoke",),
) -> ExecutionAuthorization:
    return ExecutionAuthorization(
        run_id="run-1",
        owner_id=owner_id,
        tenant_id="tenant-1",
        conversation_id="conv-1",
        allowed_data_scopes=(),
        allowed_action_classes=action_classes,
        authorization_epoch=1,
    )


class _FakeRunStore:
    def __init__(
        self,
        result: ExecutionAuthorization | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error

    def authorize_run(self, run_id: str, now: datetime) -> ExecutionAuthorization:
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def test_policy_allows_owner_with_tool_invoke(caplog) -> None:
    policy = RunAuthorizationPolicy(_FakeRunStore(result=_authorization()))
    with caplog.at_level(logging.WARNING):
        assert policy.authorize("run-1", "owner-1") is True
    assert caplog.records == []


def test_policy_rejects_owner_mismatch_with_warning(caplog) -> None:
    policy = RunAuthorizationPolicy(
        _FakeRunStore(result=_authorization(owner_id="owner-2"))
    )
    with caplog.at_level(logging.WARNING):
        assert policy.authorize("run-1", "owner-1") is False
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "owner mismatch" in warnings[0].getMessage()


def test_policy_rejects_missing_tool_invoke_with_warning(caplog) -> None:
    policy = RunAuthorizationPolicy(
        _FakeRunStore(result=_authorization(action_classes=()))
    )
    with caplog.at_level(logging.WARNING):
        assert policy.authorize("run-1", "owner-1") is False
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "lacks tool.invoke" in warnings[0].getMessage()


def test_policy_maps_lookup_failure_to_rejection_with_error(caplog) -> None:
    policy = RunAuthorizationPolicy(_FakeRunStore(error=RuntimeError("database down")))
    with caplog.at_level(logging.ERROR):
        assert policy.authorize("run-1", "owner-1") is False
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "lookup failed" in errors[0].getMessage()
    assert "RuntimeError" in errors[0].getMessage()
