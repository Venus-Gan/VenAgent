"""pytest 本地配置：只加载隔离测试数据库连接，不进入应用运行时配置。

D11：TEST_* 连接串从仓库根 config.yaml 的 persistence/neo4j 区块拼装；
显式进程环境优先，区块未启用时跳过（不设 TEST_* 环境变量）。
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from urllib.parse import quote

import pytest

_TEST_DATABASE_URL = "TEST_DATABASE_URL"
_TEST_NEO4J_URI = "TEST_NEO4J_URI"
_TEST_NEO4J_PASSWORD = "TEST_NEO4J_PASSWORD"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 测试进程默认禁用真实 Docker Sandbox，避免单元/集成测试创建宿主机容器。
os.environ.setdefault("VENAGENT_SANDBOX_DISABLED", "1")
# 测试进程提供固定加密密钥，允许 durable 模式安全初始化。
os.environ.setdefault("VENAGENT_INVOCATION_ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode())


def _load_local_test_environment() -> None:
    """从 config.yaml 拼装测试连接串；显式进程环境优先，缺配置则跳过。"""
    if os.environ.get(_TEST_DATABASE_URL) and os.environ.get(_TEST_NEO4J_URI):
        return

    try:
        from src.config import load_config

        config = load_config(project_root=PROJECT_ROOT)
    except Exception:
        return

    if not os.environ.get(_TEST_DATABASE_URL) and config.persistence.enabled:
        password = config.persistence.password.get_secret_value()
        if password:
            database_url = (
                f"postgresql://{quote(config.persistence.user, safe='')}"
                f":{quote(password, safe='')}"
                f"@{config.persistence.host}:{config.persistence.port}"
                # 集成测试只允许操作隔离测试库（tests/repo/conftest 白名单）。
                "/venagent_test"
            )
            os.environ[_TEST_DATABASE_URL] = database_url

    if not os.environ.get(_TEST_NEO4J_URI) and config.neo4j.enabled:
        password = config.neo4j.password.get_secret_value()
        if password:
            os.environ[_TEST_NEO4J_URI] = config.neo4j.uri
            os.environ[_TEST_NEO4J_PASSWORD] = password


_load_local_test_environment()


@pytest.fixture
def neo4j_graph_store():
    """提供真实 M05 图存储；连接和密码仅存在于当前 pytest 进程。"""
    uri = os.environ.get(_TEST_NEO4J_URI, "").strip()
    if not uri:
        pytest.skip("TEST_NEO4J_URI is not configured")
    password = os.environ.get(_TEST_NEO4J_PASSWORD, "")
    if not password:
        pytest.fail("TEST_NEO4J_PASSWORD is required with TEST_NEO4J_URI")

    neo4j = pytest.importorskip("neo4j")
    from src.platform.neo4j import migrate_neo4j_schema
    from src.repo.neo4j import Neo4jMemoryGraphStore

    database = os.environ.get("TEST_NEO4J_DATABASE", "neo4j")
    user = os.environ.get("TEST_NEO4J_USER", "neo4j")
    driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        migrate_neo4j_schema(driver, database)
        store = Neo4jMemoryGraphStore(
            driver,
            database=database,
            read_timeout=2.0,
            write_timeout=10.0,
        )
        store.set_available(True)
        yield store, driver, database
    finally:
        driver.close()
