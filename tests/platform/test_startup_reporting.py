from __future__ import annotations

import asyncio
import logging
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr
from uvicorn.config import LOGGING_CONFIG

from src import __main__ as main_module
from src import bootstrap as bootstrap_module
from src.bootstrap import build_application
from src.config import Neo4jConfig, load_config
from src.platform.neo4j import build_neo4j_runtime
from src.platform.observability import (
    InfrastructureState,
    InfrastructureStatus,
    StartupReport,
    log_startup_report,
)
from src.platform.runtime import (
    PersistenceRuntime,
    PersistenceStatus,
    build_persistence_runtime,
)


class FixedModel:
    def invoke(self, _messages):
        return AIMessage(content="ok")


class _ReadyPostgresqlRuntime:
    """构造期最小假 PG runtime：按 durable 装配语义持有 pool 资源。

    bootstrap._build_repository_adapters（src/bootstrap.py:453-473）在
    mode=durable 时访问 `runtime.postgresql_pool`（platform/runtime.py:88-92 的
    属性，postgresql_runtime 为 None 时会抛 PersistenceError）。真实 durable
    runtime 由 build_postgresql_runtime 提供 `pool`，此假对象只补这一个资源面。
    """

    pool: object = object()

    async def open(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    def close(self) -> None:
        return None


def test_reporter_logs_natural_language_for_arbitrary_infrastructure(caplog):
    logger = logging.getLogger("test.venagent.startup")
    report = StartupReport(
        mode="degraded",
        infrastructure=(
            InfrastructureStatus(
                component="postgresql",
                state=InfrastructureState.READY,
                reason_code="postgresql_ready",
                operator_message="PostgreSQL 连接正常，对话可在服务重启后恢复。",
                health_status="connected",
            ),
            InfrastructureStatus(
                component="vector-store",
                state=InfrastructureState.DEGRADED,
                reason_code="vector_store_unavailable",
                operator_message="向量存储当前不可用，语义检索能力已降级。",
                health_status="unavailable",
            ),
        ),
    )

    with caplog.at_level(logging.INFO, logger=logger.name):
        log_startup_report(report, logger=logger)

    messages = [record.getMessage() for record in caplog.records]
    assert messages == [
        "PostgreSQL 连接正常，对话可在服务重启后恢复。",
        "向量存储当前不可用，语义检索能力已降级。",
        "基础设施初始化完成：1 项可用、1 项降级、0 项未启用、0 项失败。"
        "VenAgent 将以降级模式启动。",
    ]
    assert [record.levelno for record in caplog.records] == [
        logging.INFO,
        logging.WARNING,
        logging.WARNING,
    ]
    assert caplog.records[1].component == "vector-store"
    assert caplog.records[1].state == "degraded"
    assert caplog.records[1].reason_code == "vector_store_unavailable"


@pytest.mark.parametrize(
    ("state", "level"),
    [
        (InfrastructureState.READY, logging.INFO),
        (InfrastructureState.DEGRADED, logging.WARNING),
        (InfrastructureState.DISABLED, logging.INFO),
        (InfrastructureState.FAILED, logging.ERROR),
    ],
)
def test_reporter_maps_each_state_to_its_operator_level(caplog, state, level):
    logger = logging.getLogger(f"test.venagent.level.{state.value}")
    report = StartupReport(
        mode="degraded",
        infrastructure=(
            InfrastructureStatus(
                component="test-component",
                state=state,
                reason_code=f"test_{state.value}",
                operator_message="测试基础设施状态。",
                health_status=state.value,
            ),
        ),
    )

    with caplog.at_level(logging.INFO, logger=logger.name):
        log_startup_report(report, logger=logger)

    assert caplog.records[0].levelno == level


def test_lifespan_logs_one_report_and_health_uses_the_same_status(caplog, app_factory):
    runtime = build_persistence_runtime({})
    app = app_factory(
        FixedModel(),
        persistence_runtime=runtime,
    )

    with caplog.at_level(logging.INFO, logger="venagent.startup"):
        with TestClient(app) as client:
            first = client.get("/health")
            second = client.get("/health")

    assert first.json() == second.json()
    assert first.json()["infrastructure"]["postgresql"]["status"] == (
        runtime.status.infrastructure.health_status
    )
    assert first.json()["infrastructure"]["neo4j"] == {
        "status": "disabled",
        "state": "disabled",
        "reason_code": "neo4j_durable_identity_required",
    }
    messages = [record.getMessage() for record in caplog.records]
    assert sum("未配置 PostgreSQL" in message for message in messages) == 1
    assert messages[1] == (
        "PostgreSQL 持久化身份不可用，Neo4j 图存储未启用。"
    )
    assert sum("基础设施初始化完成" in message for message in messages) == 1
    components = [
        record.component
        for record in caplog.records
        if hasattr(record, "component")
    ]
    assert components == [
        "postgresql",
        "neo4j",
        "milvus",
        "elasticsearch",
        "memory-embedding",
        "memory-extraction",
        "memory-graph-g1",
        "memory-index",
        "memory-long-term",
        "memory-short-term",
        "rag-dense",
        "rag-keyword",
    ]


def test_ready_neo4j_is_reported_between_postgresql_and_memory_capabilities(
    monkeypatch,
    tmp_path,
):
    import neo4j

    from src.platform.neo4j import runtime as neo4j_runtime_module

    class FakeDriver:
        def verify_connectivity(self) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        neo4j.GraphDatabase,
        "driver",
        lambda *_args, **_kwargs: FakeDriver(),
    )
    monkeypatch.setattr(
        neo4j_runtime_module,
        "validate_neo4j_schema",
        lambda *_args, **_kwargs: None,
    )

    config = load_config(
        project_root=tmp_path,
        environ={
            "NEO4J__ENABLED": "true",
            "NEO4J__URI": "neo4j://127.0.0.1:7687",
            "NEO4J__DATABASE": "venagent",
            "NEO4J__USER": "neo4j",
            "NEO4J_PASSWORD": "test-password",
            "JWT_SECRET": "0123456789abcdef0123456789abcdef",
            "VENAGENT_INVOCATION_ENCRYPTION_KEY": os.environ[
                "VENAGENT_INVOCATION_ENCRYPTION_KEY"
            ],
        },
    )
    # durable 装配会把 state directory 放在 DEFAULT_MCP_CONFIG_PATH.parent/"state"；
    # 指向 tmp_path 避免在仓库树内写锁文件（state_directory_lease.acquire）。
    monkeypatch.setattr(
        bootstrap_module,
        "DEFAULT_MCP_CONFIG_PATH",
        tmp_path / "mcp-configs" / "mcp-servers.json",
    )
    persistence = PersistenceRuntime(
        InMemorySaver(),
        PersistenceStatus(
            mode="durable",
            postgresql="connected",
            conversation_persistence="available",
            reason_code="postgresql_ready",
        ),
        _ReadyPostgresqlRuntime(),
    )
    application = build_application(config=config, persistence_runtime=persistence)
    try:
        asyncio.run(application.open())
        report = application.startup_report
        health = application.health
    finally:
        application.close()

    assert tuple(item.component for item in report.infrastructure) == (
        "postgresql",
        "neo4j",
        "milvus",
        "elasticsearch",
        "memory-embedding",
        "memory-extraction",
        "memory-graph-g1",
        "memory-index",
        "memory-long-term",
        "memory-short-term",
        "rag-dense",
        "rag-keyword",
    )
    assert health["infrastructure"]["neo4j"] == {
        "status": "connected",
        "state": "ready",
        "reason_code": "neo4j_ready",
    }


def test_neo4j_runtime_tracks_connection_and_schema_result(monkeypatch, caplog):
    import neo4j

    from src.memory.management import (
        MemoryCapabilityRegistry,
        MemoryCapabilityStatus,
    )
    from src.platform.neo4j import runtime as neo4j_runtime_module

    class FakeDriver:
        def verify_connectivity(self) -> None:
            return None

        def close(self) -> None:
            return None

    driver = FakeDriver()
    monkeypatch.setattr(
        neo4j.GraphDatabase,
        "driver",
        lambda *_args, **_kwargs: driver,
    )
    monkeypatch.setattr(
        neo4j_runtime_module,
        "validate_neo4j_schema",
        lambda *_args, **_kwargs: None,
    )
    registry = MemoryCapabilityRegistry(
        (MemoryCapabilityStatus("memory-graph-g1", "healthy", "memory_ready"),)
    )
    config = Neo4jConfig(enabled=True, password=SecretStr("test-password"))

    with caplog.at_level(logging.WARNING, logger="venagent.memory"):
        runtime = build_neo4j_runtime(config, registry, authority_durable=True)
        asyncio.run(runtime.open())

    assert runtime.infrastructure.state is InfrastructureState.READY
    assert runtime.infrastructure.reason_code == "neo4j_ready"
    assert registry.get("memory-graph-g1").state == "healthy"
    assert [record.getMessage() for record in caplog.records] == [
        "记忆能力状态已变化：healthy -> recovering。",
        "记忆能力状态已变化：recovering -> healthy。",
    ]
    runtime.close()


def test_neo4j_runtime_reports_not_configured_separately_from_graph_capability():
    from src.memory.management import (
        MemoryCapabilityRegistry,
        MemoryCapabilityStatus,
    )

    registry = MemoryCapabilityRegistry(
        (MemoryCapabilityStatus("memory-graph-g1", "healthy", "memory_ready"),)
    )

    runtime = build_neo4j_runtime(
        Neo4jConfig(), registry, authority_durable=True
    )

    assert runtime.infrastructure.state is InfrastructureState.DISABLED
    assert runtime.infrastructure.reason_code == "neo4j_not_configured"
    assert registry.get("memory-graph-g1").state == "disabled"
    assert registry.get("memory-graph-g1").reason_code == "neo4j_not_configured"


def test_neo4j_runtime_reports_connection_failure_without_changing_durable_mode(
    monkeypatch,
):
    import neo4j

    from src.memory.management import (
        MemoryCapabilityRegistry,
        MemoryCapabilityStatus,
    )

    class FailingDriver:
        def verify_connectivity(self) -> None:
            raise RuntimeError("private connection detail")

        def close(self) -> None:
            return None

    driver = FailingDriver()
    monkeypatch.setattr(
        neo4j.GraphDatabase,
        "driver",
        lambda *_args, **_kwargs: driver,
    )
    registry = MemoryCapabilityRegistry(
        (MemoryCapabilityStatus("memory-graph-g1", "healthy", "memory_ready"),)
    )
    config = Neo4jConfig(enabled=True, password=SecretStr("test-password"))

    runtime = build_neo4j_runtime(config, registry, authority_durable=True)
    asyncio.run(runtime.open())

    assert runtime.infrastructure.state is InfrastructureState.DEGRADED
    assert runtime.infrastructure.reason_code == "neo4j_unavailable"
    assert "private connection detail" not in runtime.infrastructure.operator_message
    assert registry.get("memory-graph-g1").state == "degraded"
    assert registry.get("memory-graph-g1").reason_code == "graph_store_unavailable"
    runtime.close()


def test_runtime_memory_state_transition_updates_health_without_relogging_startup(
    app_factory,
):
    runtime = build_persistence_runtime({})
    app = app_factory(FixedModel(), persistence_runtime=runtime)

    with TestClient(app) as client:
        app.state.memory_service.note_provider_timeout("memory-short-term")
        first = client.get("/health").json()
        second = client.get("/health").json()

    assert first == second
    assert first["infrastructure"]["memory-short-term"] == {
        "status": "degraded",
        "state": "degraded",
        "reason_code": "provider_timeout",
    }


def test_cli_log_config_enables_only_the_venagent_namespace(monkeypatch):
    assert "venagent" not in LOGGING_CONFIG["loggers"]

    captured: dict[str, object] = {}
    monkeypatch.setattr(sys, "argv", ["venagent"])
    monkeypatch.setattr(
        main_module,
        "get_runtime_config",
        lambda: SimpleNamespace(server=SimpleNamespace(port=8090)),
    )
    monkeypatch.setattr(
        main_module.uvicorn,
        "run",
        lambda app, **options: captured.update(app=app, **options),
    )

    main_module.main()

    log_config = captured["log_config"]
    assert log_config["loggers"]["venagent"] == {
        "handlers": ["default"],
        "level": "INFO",
        "propagate": False,
    }
    assert "root" not in log_config
    assert "venagent" not in LOGGING_CONFIG["loggers"]


def test_cli_keeps_the_configured_windows_event_loop_policy(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(sys, "argv", ["venagent"])
    monkeypatch.setattr(
        main_module,
        "get_runtime_config",
        lambda: SimpleNamespace(server=SimpleNamespace(port=8090)),
    )
    monkeypatch.setattr(
        main_module.uvicorn,
        "run",
        lambda app, **options: captured.update(app=app, **options),
    )

    main_module.main()

    assert captured["app"] == "src.interfaces.http.app:app"
    assert captured["loop"] == "none"
