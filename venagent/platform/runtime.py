"""Backend-neutral 持久化资源 façade 与启动降级状态。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from psycopg_pool import ConnectionPool

from .errors import PersistenceError
from .observability import InfrastructureState, InfrastructureStatus
from .postgresql.runtime import (
    PostgreSQLRuntime,
    PostgreSQLSchemaIncompatible,
    PostgreSQLUnavailable,
    build_postgresql_runtime,
)

# 仅供装配层传递已解析的连接串，不是环境变量名称。
DATABASE_URL = "database_url"

_STATUS_DESCRIPTIONS = {
    "postgresql_ready": "PostgreSQL 连接正常，对话可在服务重启后恢复。",
    "postgresql_not_configured": "未配置 PostgreSQL，当前使用进程内存，服务重启后对话上下文将失效。",
    "postgresql_unavailable": "PostgreSQL 当前不可用，已使用进程内存启动，服务重启后对话上下文将失效。",
    "persistence_schema_incompatible": (
        "PostgreSQL 已连接，但持久化 schema 与当前版本不兼容，已使用进程内存启动，"
        "服务重启后对话上下文将失效。"
    ),
    "authentication_configuration_unavailable": (
        "持久认证配置当前不可用，PostgreSQL 持久化已停用，账号功能不可用。"
    ),
}


@dataclass(frozen=True)
class PersistenceStatus:
    mode: str
    postgresql: str
    conversation_persistence: str
    reason_code: str

    @property
    def infrastructure(self) -> InfrastructureStatus:
        state = (
            InfrastructureState.READY
            if self.mode == "durable"
            else InfrastructureState.DEGRADED
        )
        return _infrastructure_status(
            state=state,
            health_status=self.postgresql,
            reason_code=self.reason_code,
        )

    def as_health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": self.mode,
            "infrastructure": {"postgresql": {"status": self.postgresql}},
            "capabilities": {
                "anonymous_chat": "available",
                "account_identity": (
                    "available" if self.mode == "durable" else "unavailable"
                ),
                "conversation_persistence": self.conversation_persistence,
                "run_execution": "available",
                "restart_recovery": (
                    "available" if self.mode == "durable" else "unavailable"
                ),
            },
            "reason_code": self.reason_code,
        }


@dataclass
class PersistenceRuntime:
    """暴露共享技术资源；feature adapters 只能由 bootstrap 构造。"""

    checkpointer: BaseCheckpointSaver
    status: PersistenceStatus
    postgresql_runtime: PostgreSQLRuntime | None = None

    @property
    def postgresql_pool(self) -> ConnectionPool[Any]:
        if self.postgresql_runtime is None:
            raise PersistenceError("PostgreSQL resources are not available")
        return self.postgresql_runtime.pool

    async def open(self) -> None:
        if self.postgresql_runtime is not None:
            await self.postgresql_runtime.open()

    async def aclose(self) -> None:
        if self.postgresql_runtime is not None:
            await self.postgresql_runtime.aclose()

    def close(self) -> None:
        if self.postgresql_runtime is not None:
            self.postgresql_runtime.close()


def build_persistence_runtime(
    environment: Mapping[str, str] | None = None,
) -> PersistenceRuntime:
    """选择技术 backend；adapter 选择留给 composition root。"""

    source = environment if environment is not None else os.environ
    database_url = source.get(DATABASE_URL, "").strip()
    if not database_url:
        return _build_temporary_runtime("postgresql_not_configured", "not_configured")

    try:
        postgresql = build_postgresql_runtime(database_url)
    except PostgreSQLUnavailable:
        return _build_temporary_runtime("postgresql_unavailable", "unavailable")
    except PostgreSQLSchemaIncompatible:
        return _build_temporary_runtime("persistence_schema_incompatible", "connected")

    status = PersistenceStatus(
        mode="durable",
        postgresql="connected",
        conversation_persistence="available",
        reason_code="postgresql_ready",
    )
    return PersistenceRuntime(postgresql.checkpointer, status, postgresql)


def build_temporary_runtime(
    reason_code: str = "authentication_configuration_unavailable",
    postgresql: str = "connected",
) -> PersistenceRuntime:
    return _build_temporary_runtime(reason_code, postgresql)


def _build_temporary_runtime(reason_code: str, postgresql: str) -> PersistenceRuntime:
    status = PersistenceStatus(
        mode="temporary",
        postgresql=postgresql,
        conversation_persistence="unavailable",
        reason_code=reason_code,
    )
    return PersistenceRuntime(InMemorySaver(), status)


def _infrastructure_status(
    *,
    state: InfrastructureState,
    health_status: str,
    reason_code: str,
) -> InfrastructureStatus:
    # 固定文案可避免原始异常或连接信息进入日志与健康响应。
    return InfrastructureStatus(
        component="postgresql",
        state=state,
        reason_code=reason_code,
        operator_message=_STATUS_DESCRIPTIONS[reason_code],
        health_status=health_status,
    )
