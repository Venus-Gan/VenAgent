"""Optional Elasticsearch client lifecycle for the RAG keyword route (M08).

照 neo4j/runtime.py 模式：驱动可选、按配置降级、能力状态走
MemoryCapabilityRegistry，启动快照与 health 共用同一份事实。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from ..config import ESConfig
from ..memory.management import MemoryCapabilityRegistry
from .observability import InfrastructureState, InfrastructureStatus

_ES_STATUS = {
    "es_ready": (
        InfrastructureState.READY,
        "connected",
        "Elasticsearch 连接正常，RAG keyword 检索可用。",
    ),
    "es_not_configured": (
        InfrastructureState.DISABLED,
        "not_configured",
        "未配置 Elasticsearch，RAG keyword 检索未启用。",
    ),
    "es_durable_identity_required": (
        InfrastructureState.DISABLED,
        "disabled",
        "PostgreSQL 持久化身份不可用，Elasticsearch 未启用。",
    ),
    "es_config_invalid": (
        InfrastructureState.DEGRADED,
        "invalid_configuration",
        "Elasticsearch 配置无效，RAG keyword 检索当前不可用。",
    ),
    "es_driver_unavailable": (
        InfrastructureState.DEGRADED,
        "unavailable",
        "elasticsearch-py 驱动初始化失败，RAG keyword 检索当前不可用。",
    ),
    "es_connecting": (
        InfrastructureState.DEGRADED,
        "connecting",
        "Elasticsearch 正在连接并校验集群。",
    ),
    "es_unavailable": (
        InfrastructureState.DEGRADED,
        "unavailable",
        "Elasticsearch 连接或集群校验失败，RAG keyword 检索已降级。",
    ),
}


def _es_infrastructure(reason_code: str) -> InfrastructureStatus:
    state, health_status, operator_message = _ES_STATUS[reason_code]
    return InfrastructureStatus(
        component="elasticsearch",
        state=state,
        reason_code=reason_code,
        operator_message=operator_message,
        health_status=health_status,
    )


@dataclass
class ESRuntime:
    client: Any | None = None
    registry: MemoryCapabilityRegistry | None = None
    index: str = "rag_chunks"
    infrastructure: InfrastructureStatus = field(
        default_factory=lambda: _es_infrastructure("es_not_configured")
    )

    async def open(self) -> None:
        if self.client is None or self.registry is None:
            return
        try:
            ok = await asyncio.to_thread(self.client.ping)
            if not ok:
                raise RuntimeError("elasticsearch ping failed")
            # 确保索引存在（照 AGI-saber ragchunk.go:194-222）
            await asyncio.to_thread(self._ensure_index)
        except Exception:
            self.infrastructure = _es_infrastructure("es_unavailable")
            self.registry.transition("rag-keyword", "degraded", "es_unavailable")
            return
        self.infrastructure = _es_infrastructure("es_ready")
        self.registry.transition("rag-keyword", "healthy", "es_ready")

    def _ensure_index(self) -> None:
        """创建索引（如不存在）；mapping 参照 AGI-saber ragchunk.go:206-222。"""
        if self.client is None:
            return
        if self.client.indices.exists(index=self.index):
            return
        mapping = {
            "mappings": {
                "properties": {
                    "owner_id": {"type": "keyword"},
                    "content": {"type": "text", "analyzer": "standard"},
                }
            }
        }
        self.client.indices.create(index=self.index, body=mapping)

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)

    def close(self) -> None:
        if self.client is not None:
            self.client.close()


def build_es_runtime(
    config: ESConfig,
    registry: MemoryCapabilityRegistry,
    *,
    authority_durable: bool,
) -> ESRuntime:
    if not authority_durable:
        registry.transition(
            "rag-keyword", "disabled", "durable_identity_required"
        )
        return ESRuntime(
            infrastructure=_es_infrastructure("es_durable_identity_required")
        )
    if not config.enabled:
        registry.transition("rag-keyword", "disabled", "es_not_configured")
        return ESRuntime(
            infrastructure=_es_infrastructure("es_not_configured")
        )
    if not _valid_config(config):
        registry.transition("rag-keyword", "degraded", "es_config_invalid")
        return ESRuntime(
            infrastructure=_es_infrastructure("es_config_invalid")
        )
    try:
        from elasticsearch import Elasticsearch
    except Exception:
        registry.transition(
            "rag-keyword", "degraded", "es_driver_unavailable"
        )
        return ESRuntime(
            infrastructure=_es_infrastructure("es_driver_unavailable")
        )
    try:
        client = Elasticsearch(
            hosts=[config.uri],
            basic_auth=(
                (config.user, config.password.get_secret_value())
                if config.user
                else None
            ),
            request_timeout=config.timeout,
        )
    except Exception:
        registry.transition(
            "rag-keyword", "degraded", "es_driver_unavailable"
        )
        return ESRuntime(
            infrastructure=_es_infrastructure("es_driver_unavailable")
        )
    registry.transition("rag-keyword", "recovering", "es_connecting")
    return ESRuntime(
        client,
        registry,
        config.index,
        _es_infrastructure("es_connecting"),
    )


def _valid_config(config: ESConfig) -> bool:
    parsed = urlsplit(config.uri)
    return bool(
        parsed.scheme in ("http", "https")
        and parsed.hostname
        and parsed.port
        and config.index.strip()
    )
