"""工具运行授权策略：run 授权查询与 tool.invoke 动作校验。"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Protocol

from .models import ExecutionAuthorization

logger = logging.getLogger(__name__)


class RunAuthorizationStore(Protocol):
    def authorize_run(self, run_id: str, now: datetime) -> ExecutionAuthorization: ...


class RunAuthorizationPolicy:
    """判定一次工具调用是否被 run 授权覆盖；组合根只负责绑定本策略。"""

    def __init__(self, runs: RunAuthorizationStore) -> None:
        self._runs = runs

    def authorize(self, run_id: str, owner_id: str) -> bool:
        try:
            authorization = self._runs.authorize_run(
                run_id, datetime.now(timezone.utc)
            )
        except Exception as exc:
            # 授权查询异常与授权拒绝是两类事实；静默合并会让网关把
            # 基础设施故障伪装成越权。只记类型与 run_id，不带载荷。
            logger.error(
                "Tool run authorization lookup failed: run_id=%s error_type=%s\n%s",
                run_id,
                type(exc).__module__ + "." + type(exc).__name__,
                "".join(traceback.format_exception(exc)),
            )
            return False
        if authorization.owner_id != owner_id:
            logger.warning(
                "Tool run authorization owner mismatch: run_id=%s",
                run_id,
            )
            return False
        if "tool.invoke" not in authorization.allowed_action_classes:
            logger.warning(
                "Tool run authorization lacks tool.invoke: run_id=%s",
                run_id,
            )
            return False
        return True
