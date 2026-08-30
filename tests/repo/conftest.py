"""tests/repo 共用装配（D5）：把原 test_persistence.py 的模块级 helper 收编为
conftest fixture，供拆分后的持久化主题测试就近复用。

- postgres_database_url：隔离测试库 DSN（带 venagent_test 白名单，拆库清理前置检查）；
- persistence_runtime：按环境装配持久化运行时并在 durable 模式注入 Postgres 仓储；
- create_run / ownership_service / clear_neo4j_owner：run 装配、所有权服务与验收 owner 清理；
- fixed_streaming_model / blocking_streaming_model：FastAPI 集成用固定/阻塞流式模型。
"""

from __future__ import annotations

import asyncio
import os
from threading import Event
from typing import Any, Callable
from uuid import uuid4

import psycopg
import pytest
from langchain_core.messages import AIMessageChunk

from src.ownership.service import OwnershipService
from src.platform.postgresql.migrations import migrate_database
from src.platform.runtime import build_persistence_runtime as _build_resources
from src.platform.security import Argon2PasswordHasher, JwtAccessTokenCodec
from src.repo.postgresql import (
    PostgresConversationRuntimeStore,
    PostgresOwnershipStore,
)
from src.repo.postgresql.memory import PostgresMemoryStore


@pytest.fixture
def postgres_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    with psycopg.connect(database_url) as connection:
        database_name = connection.execute("SELECT current_database()").fetchone()[0]
    if database_name != "venagent_test":
        pytest.fail("真实集成测试只允许清理隔离数据库 venagent_test")

    migrate_database(database_url)
    with psycopg.connect(database_url) as connection:
        # 只有通过上方数据库名白名单后才允许执行破坏性清理。
        connection.execute("TRUNCATE TABLE owners CASCADE")
    return database_url


@pytest.fixture
def persistence_runtime() -> Callable[[dict[str, str]], Any]:
    """按环境装配持久化运行时；durable 模式注入 Postgres 仓储。"""

    def _build(environment: dict[str, str]) -> Any:
        runtime = _build_resources(environment)
        if runtime.status.mode == "durable":
            pool = runtime.postgresql_pool
            runtime.store = PostgresConversationRuntimeStore(pool)
            runtime.ownership_store = PostgresOwnershipStore(pool)
            runtime.memory_store = PostgresMemoryStore(pool)
        return runtime

    return _build


@pytest.fixture
def create_run() -> Callable[[Any, Any, str], Any]:
    """创建一条 run（durable 运行时装配）并返回 (actor, conversation, run)。"""

    def _build(runtime: Any, now: Any, content: str) -> Any:
        assert runtime.status.mode == "durable"
        ownership = OwnershipService(
            runtime.ownership_store,
            Argon2PasswordHasher(),
            JwtAccessTokenCodec(
                "postgres-test-secret-that-is-at-least-32-bytes-long",
                issuer="venagent",
                audience="venagent-web",
            ),
        )
        actor = ownership.bootstrap_guest().actor
        conversation = runtime.store.create_conversation(actor, now)
        created = runtime.store.create_run(
            actor, conversation.conversation_id, content, str(uuid4()), now
        )
        return actor, conversation, created.run

    return _build


@pytest.fixture
def ownership_service() -> Callable[[Any], OwnershipService]:
    """按 runtime 装配所有权服务（测试用密钥，固定 issuer/audience）。"""

    def _build(runtime: Any) -> OwnershipService:
        return OwnershipService(
            runtime.ownership_store,
            Argon2PasswordHasher(),
            JwtAccessTokenCodec(
                "postgres-test-secret-that-is-at-least-32-bytes-long",
                issuer="venagent",
                audience="venagent-web",
            ),
        )

    return _build


@pytest.fixture
def clear_neo4j_owner() -> Callable[[Any, str, str], None]:
    """清除单个真实验收 owner 的图投影，保持其他测试数据不受影响。"""

    def _build(driver: Any, database: str, owner_id: str) -> None:
        with driver.session(database=database) as session:
            session.run(
                """MATCH (memory:M05Memory {owner_id:$owner_id})
                DETACH DELETE memory""",
                owner_id=owner_id,
            ).consume()
            session.run(
                """MATCH (projection:M05GraphProjection {owner_id:$owner_id})
                DETACH DELETE projection""",
                owner_id=owner_id,
            ).consume()

    return _build


class _FixedStreamingModel:
    async def astream(self, _messages):
        yield AIMessageChunk(content="持久回答")


class _BlockingStreamingModel:
    def __init__(self) -> None:
        self.started = Event()
        self.cancelled = Event()

    async def astream(self, _messages):
        self.started.set()
        try:
            await asyncio.sleep(60)
            yield AIMessageChunk(content="不应到达")
        finally:
            self.cancelled.set()


@pytest.fixture
def fixed_streaming_model() -> Callable[..., Any]:
    """返回固定流式模型类；测试每次实例化获得全新对象。"""

    return _FixedStreamingModel


@pytest.fixture
def blocking_streaming_model() -> Callable[..., Any]:
    """返回阻塞流式模型类；测试每次实例化获得全新对象。"""

    return _BlockingStreamingModel