"""Optional Milvus client lifecycle for the RAG dense route (M08).

照 neo4j/runtime.py 模式：驱动可选、按配置降级、能力状态走
MemoryCapabilityRegistry，启动快照与 health 共用同一份事实。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from ..config import MilvusConfig
from ..memory.management import MemoryCapabilityRegistry
from .observability import InfrastructureState, InfrastructureStatus

_MILVUS_STATUS = {
    "milvus_ready": (
        InfrastructureState.READY,
        "connected",
        "Milvus 连接正常，RAG dense 检索可用。",
    ),
    "milvus_not_configured": (
        InfrastructureState.DISABLED,
        "not_configured",
        "未配置 Milvus，RAG dense 检索未启用。",
    ),
    "milvus_durable_identity_required": (
        InfrastructureState.DISABLED,
        "disabled",
        "PostgreSQL 持久化身份不可用，Milvus 未启用。",
    ),
    "milvus_config_invalid": (
        InfrastructureState.DEGRADED,
        "invalid_configuration",
        "Milvus 配置无效，RAG dense 检索当前不可用。",
    ),
    "milvus_driver_unavailable": (
        InfrastructureState.DEGRADED,
        "unavailable",
        "pymilvus 驱动初始化失败，RAG dense 检索当前不可用。",
    ),
    "milvus_connecting": (
        InfrastructureState.DEGRADED,
        "connecting",
        "Milvus 正在连接并校验集合。",
    ),
    "milvus_unavailable": (
        InfrastructureState.DEGRADED,
        "unavailable",
        "Milvus 连接或集合校验失败，RAG dense 检索已降级。",
    ),
}


def _milvus_infrastructure(reason_code: str) -> InfrastructureStatus:
    state, health_status, operator_message = _MILVUS_STATUS[reason_code]
    return InfrastructureStatus(
        component="milvus",
        state=state,
        reason_code=reason_code,
        operator_message=operator_message,
        health_status=health_status,
    )


@dataclass
class MilvusRuntime:
    client: Any | None = None
    registry: MemoryCapabilityRegistry | None = None
    collection: str = "rag_chunks"
    infrastructure: InfrastructureStatus = field(
        default_factory=lambda: _milvus_infrastructure("milvus_not_configured")
    )

    async def open(self) -> None:
        if self.client is None or self.registry is None:
            return
        try:
            await asyncio.to_thread(self.client.list_collections)
        except Exception:
            self.infrastructure = _milvus_infrastructure("milvus_unavailable")
            self.registry.transition(
                "rag-dense", "degraded", "milvus_unavailable"
            )
            return
        self.infrastructure = _milvus_infrastructure("milvus_ready")
        self.registry.transition("rag-dense", "healthy", "milvus_ready")

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)

    def close(self) -> None:
        if self.client is not None:
            self.client.close()


def build_milvus_runtime(
    config: MilvusConfig,
    registry: MemoryCapabilityRegistry,
    *,
    authority_durable: bool,
) -> MilvusRuntime:
    if not authority_durable:
        registry.transition(
            "rag-dense", "disabled", "durable_identity_required"
        )
        return MilvusRuntime(
            infrastructure=_milvus_infrastructure(
                "milvus_durable_identity_required"
            )
        )
    if not config.enabled:
        registry.transition("rag-dense", "disabled", "milvus_not_configured")
        return MilvusRuntime(
            infrastructure=_milvus_infrastructure("milvus_not_configured")
        )
    if not _valid_config(config):
        registry.transition("rag-dense", "degraded", "milvus_config_invalid")
        return MilvusRuntime(
            infrastructure=_milvus_infrastructure("milvus_config_invalid")
        )
    try:
        from pymilvus import MilvusClient
    except Exception:
        registry.transition(
            "rag-dense", "degraded", "milvus_driver_unavailable"
        )
        return MilvusRuntime(
            infrastructure=_milvus_infrastructure("milvus_driver_unavailable")
        )
    try:
        client = MilvusClient(
            uri=config.uri,
            user=config.user or None,
            password=config.password.get_secret_value() or None,
            timeout=config.timeout,
        )
    except Exception:
        registry.transition(
            "rag-dense", "degraded", "milvus_driver_unavailable"
        )
        return MilvusRuntime(
            infrastructure=_milvus_infrastructure("milvus_driver_unavailable")
        )
    registry.transition("rag-dense", "recovering", "milvus_connecting")
    return MilvusRuntime(
        client,
        registry,
        config.collection,
        _milvus_infrastructure("milvus_connecting"),
    )


def _valid_config(config: MilvusConfig) -> bool:
    parsed = urlsplit(config.uri)
    return bool(
        parsed.scheme in ("http", "https")
        and parsed.hostname
        and parsed.port
        and config.collection.strip()
        and config.dim > 0
    )
