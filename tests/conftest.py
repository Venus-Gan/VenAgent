"""pytest 本地配置：只加载隔离测试数据库连接，不进入应用运行时配置。"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import pytest
from dotenv import dotenv_values

_TEST_DATABASE_URL = "TEST_DATABASE_URL"
_POSTGRES_PASSWORD = "POSTGRES_PASSWORD"
_TEST_NEO4J_URI = "TEST_NEO4J_URI"
_TEST_NEO4J_PASSWORD = "TEST_NEO4J_PASSWORD"
_NEO4J_PASSWORD = "NEO4J_PASSWORD"
_PASSWORD_PLACEHOLDER = "${POSTGRES_PASSWORD}"


def _load_local_test_database_url() -> None:
    """仅在没有显式环境值时，从 `.env` 安全装配测试数据库 DSN。"""
    if os.environ.get(_TEST_DATABASE_URL):
        return

    values = dotenv_values(
        Path(__file__).resolve().parents[1] / ".env", interpolate=False
    )
    database_url = values.get(_TEST_DATABASE_URL)
    password = values.get(_POSTGRES_PASSWORD)
    if isinstance(database_url, str) and _PASSWORD_PLACEHOLDER in database_url:
        if not isinstance(password, str) or not password:
            return
        database_url = database_url.replace(
            _PASSWORD_PLACEHOLDER, quote(password, safe="")
        )
    if isinstance(database_url, str) and database_url.strip():
        os.environ[_TEST_DATABASE_URL] = database_url


def _load_local_test_environment() -> None:
    """从本机 `.env` 装配隔离数据库与 Neo4j 的当前 pytest 进程环境。"""
    _load_local_test_database_url()
    values = dotenv_values(
        Path(__file__).resolve().parents[1] / ".env", interpolate=False
    )

    if not os.environ.get(_TEST_NEO4J_URI):
        neo4j_uri = values.get(_TEST_NEO4J_URI)
        if isinstance(neo4j_uri, str) and neo4j_uri.strip():
            os.environ[_TEST_NEO4J_URI] = neo4j_uri
    if not os.environ.get(_TEST_NEO4J_PASSWORD):
        neo4j_password = values.get(_NEO4J_PASSWORD)
        if isinstance(neo4j_password, str) and neo4j_password:
            os.environ[_TEST_NEO4J_PASSWORD] = neo4j_password


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
    from venagent.platform.neo4j import migrate_neo4j_schema
    from venagent.repo.neo4j import Neo4jMemoryGraphStore

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
