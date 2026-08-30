"""Optional Neo4j driver lifecycle without changing PostgreSQL runtime mode."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from ...config import Neo4jConfig
from ...memory.graph_memory import DisabledGraphMemoryStore
from ...memory.management import MemoryCapabilityRegistry
from ...memory.ports import MemoryGraphStore
from ...repo.neo4j import Neo4jMemoryGraphStore
from ..observability import InfrastructureState, InfrastructureStatus
from .migrations import validate_neo4j_schema

_ALLOWED_SCHEMES = {
    "bolt",
    "bolt+s",
    "bolt+ssc",
    "neo4j",
    "neo4j+s",
    "neo4j+ssc",
}

_NEO4J_STATUS = {
    "neo4j_ready": (
        InfrastructureState.READY,
        "connected",
        "Neo4j 连接正常，图存储 schema 与当前版本兼容。",
    ),
    "neo4j_not_configured": (
        InfrastructureState.DISABLED,
        "not_configured",
        "未配置 Neo4j，图存储未启用。",
    ),
    "neo4j_durable_identity_required": (
        InfrastructureState.DISABLED,
        "disabled",
        "PostgreSQL 持久化身份不可用，Neo4j 图存储未启用。",
    ),
    "neo4j_config_invalid": (
        InfrastructureState.DEGRADED,
        "invalid_configuration",
        "Neo4j 配置无效，图存储当前不可用。",
    ),
    "neo4j_driver_unavailable": (
        InfrastructureState.DEGRADED,
        "unavailable",
        "Neo4j 驱动初始化失败，图存储当前不可用。",
    ),
    "neo4j_connecting": (
        InfrastructureState.DEGRADED,
        "connecting",
        "Neo4j 正在连接并校验图存储 schema。",
    ),
    "neo4j_unavailable": (
        InfrastructureState.DEGRADED,
        "unavailable",
        "Neo4j 连接或图存储 schema 校验失败，GraphMemory 图能力已降级。",
    ),
}


def _neo4j_infrastructure(reason_code: str) -> InfrastructureStatus:
    state, health_status, operator_message = _NEO4J_STATUS[reason_code]
    return InfrastructureStatus(
        component="neo4j",
        state=state,
        reason_code=reason_code,
        operator_message=operator_message,
        health_status=health_status,
    )


@dataclass
class Neo4jRuntime:
    graph_store: MemoryGraphStore
    registry: MemoryCapabilityRegistry
    driver: Any | None = None
    database: str = "neo4j"
    infrastructure: InfrastructureStatus = field(
        default_factory=lambda: _neo4j_infrastructure("neo4j_not_configured")
    )

    async def open(self) -> None:
        if self.driver is None:
            return
        store = self.graph_store
        try:
            await asyncio.to_thread(self.driver.verify_connectivity)
            await asyncio.to_thread(
                validate_neo4j_schema, self.driver, self.database
            )
        except Exception:
            if isinstance(store, Neo4jMemoryGraphStore):
                store.set_available(False)
            self.infrastructure = _neo4j_infrastructure("neo4j_unavailable")
            self.registry.transition(
                "memory-graph-g1", "degraded", "graph_store_unavailable"
            )
            return
        if isinstance(store, Neo4jMemoryGraphStore):
            store.set_available(True)
        self.infrastructure = _neo4j_infrastructure("neo4j_ready")
        self.registry.transition("memory-graph-g1", "healthy", "memory_ready")

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)

    def close(self) -> None:
        if isinstance(self.graph_store, Neo4jMemoryGraphStore):
            self.graph_store.set_available(False)
        if self.driver is not None:
            self.driver.close()


def build_neo4j_runtime(
    config: Neo4jConfig,
    registry: MemoryCapabilityRegistry,
    *,
    authority_durable: bool,
) -> Neo4jRuntime:
    if not authority_durable:
        registry.transition(
            "memory-graph-g1", "disabled", "durable_identity_required"
        )
        return Neo4jRuntime(
            DisabledGraphMemoryStore(),
            registry,
            infrastructure=_neo4j_infrastructure(
                "neo4j_durable_identity_required"
            ),
        )
    if not config.enabled:
        registry.transition("memory-graph-g1", "disabled", "neo4j_not_configured")
        return Neo4jRuntime(
            DisabledGraphMemoryStore(),
            registry,
            infrastructure=_neo4j_infrastructure("neo4j_not_configured"),
        )
    if not _valid_config(config):
        registry.transition("memory-graph-g1", "degraded", "neo4j_config_invalid")
        return Neo4jRuntime(
            DisabledGraphMemoryStore(),
            registry,
            infrastructure=_neo4j_infrastructure("neo4j_config_invalid"),
        )
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            config.uri,
            auth=(config.user, config.password.get_secret_value()),
            max_connection_pool_size=config.max_pool_size,
            connection_timeout=config.connection_timeout,
            connection_acquisition_timeout=config.acquisition_timeout,
        )
    except Exception:
        registry.transition("memory-graph-g1", "degraded", "neo4j_driver_unavailable")
        return Neo4jRuntime(
            DisabledGraphMemoryStore(),
            registry,
            infrastructure=_neo4j_infrastructure("neo4j_driver_unavailable"),
        )
    store = Neo4jMemoryGraphStore(
        driver,
        database=config.database,
        read_timeout=config.read_timeout,
        write_timeout=config.write_timeout,
    )
    registry.transition("memory-graph-g1", "recovering", "neo4j_connecting")
    return Neo4jRuntime(
        store,
        registry,
        driver,
        config.database,
        _neo4j_infrastructure("neo4j_connecting"),
    )


def _valid_config(config: Neo4jConfig) -> bool:
    parsed = urlsplit(config.uri)
    return bool(
        parsed.scheme in _ALLOWED_SCHEMES
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and config.database.strip()
        and config.user.strip()
        and config.password.get_secret_value()
    )
