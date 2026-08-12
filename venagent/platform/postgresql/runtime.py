"""PostgreSQL 连接池、schema 校验与 LangGraph checkpointer 生命周期。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool

from ...agent.graph import checkpoint_serializer
from ..errors import PersistenceError
from .migrations import SCHEMA_VERSION


class PostgreSQLUnavailable(PersistenceError):
    """连接池无法在启动预算内建立。"""


class PostgreSQLSchemaIncompatible(PersistenceError):
    """数据库可连接，但活动 schema 不满足当前 runtime。"""


class DeferredAsyncPostgresSaver(BaseCheckpointSaver[str]):
    """把官方异步 saver 的构造延迟到 FastAPI 事件循环。"""

    def __init__(self) -> None:
        super().__init__(serde=checkpoint_serializer())
        self._delegate: AsyncPostgresSaver | None = None

    def bind(self, delegate: AsyncPostgresSaver) -> None:
        self._delegate = delegate

    def unbind(self) -> None:
        self._delegate = None

    @property
    def config_specs(self) -> list[Any]:
        return self._require_delegate().config_specs

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return await self._require_delegate().aget_tuple(config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        async for item in self._require_delegate().alist(
            config,
            filter=filter,
            before=before,
            limit=limit,
        ):
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await self._require_delegate().aput(
            config, checkpoint, metadata, new_versions
        )

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await self._require_delegate().aput_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        await self._require_delegate().adelete_thread(thread_id)

    def get_next_version(self, current: str | None, channel: None) -> str:
        return self._require_delegate().get_next_version(current, channel)

    def _require_delegate(self) -> AsyncPostgresSaver:
        if self._delegate is None:
            raise PersistenceError("PostgreSQL checkpointer is not open")
        return self._delegate


@dataclass
class PostgreSQLRuntime:
    """只拥有 PostgreSQL 技术资源，不构造任何 feature adapter。"""

    pool: ConnectionPool[Any]
    checkpointer_pool: AsyncConnectionPool[Any]
    checkpointer: DeferredAsyncPostgresSaver

    async def open(self) -> None:
        if not self.checkpointer_pool.closed:
            return
        try:
            await self.checkpointer_pool.open(wait=True, timeout=3)
            self.checkpointer.bind(
                AsyncPostgresSaver(
                    self.checkpointer_pool,
                    serde=self.checkpointer.serde,
                )
            )
        except Exception:
            await self.checkpointer_pool.close()
            self.close()
            raise PersistenceError("unable to open PostgreSQL checkpointer") from None

    async def aclose(self) -> None:
        if not self.checkpointer_pool.closed:
            await self.checkpointer_pool.close()
        self.checkpointer.unbind()
        self.close()

    def close(self) -> None:
        self.pool.close()


def build_postgresql_runtime(database_url: str) -> PostgreSQLRuntime:
    """建立并校验 PostgreSQL 技术资源，失败原因由平台 façade 映射。"""

    pool: ConnectionPool[Any] | None = None
    try:
        pool = ConnectionPool(
            database_url,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
            min_size=1,
            max_size=10,
            open=False,
            timeout=3,
        )
        pool.open(wait=True, timeout=3)
    except Exception:
        if pool is not None:
            pool.close()
        raise PostgreSQLUnavailable("unable to open PostgreSQL pool") from None

    migration_saver = PostgresSaver(pool, serde=checkpoint_serializer())
    try:
        _validate_schema(pool, migration_saver)
    except Exception:
        pool.close()
        raise PostgreSQLSchemaIncompatible("unsupported PostgreSQL schema") from None

    checkpointer_pool = AsyncConnectionPool(
        database_url,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
        min_size=1,
        max_size=10,
        open=False,
        timeout=3,
    )
    checkpointer = DeferredAsyncPostgresSaver()
    return PostgreSQLRuntime(pool, checkpointer_pool, checkpointer)


def _validate_schema(pool: ConnectionPool[Any], saver: PostgresSaver) -> None:
    with pool.connection() as conn:
        applied = [
            int(row["version"])
            for row in conn.execute(
                "SELECT version FROM venagent_schema_migrations ORDER BY version"
            ).fetchall()
        ]
        if applied != [SCHEMA_VERSION]:
            raise PersistenceError("unsupported VenAgent schema")
        required = (
            "owners",
            "conversations",
            "conversation_messages",
            "agent_runs",
            "run_grants",
            "run_requests",
            "memory_settings",
            "memory_sources",
            "memory_facts",
            "memory_fact_sources",
            "memory_graph_authority",
            "memory_confirmations",
            "memory_summaries",
            "memory_jobs",
        )
        rows = [
            conn.execute(
                "SELECT to_regclass(%s) AS relation", (f"public.{table}",)
            ).fetchone()
            for table in required
        ]
        if any(row is None or row["relation"] is None for row in rows):
            raise PersistenceError("incomplete VenAgent schema")

    # 真实读取 checkpoint 可同时验证 LangGraph 表及 serializer 兼容性。
    saver.get_tuple(
        {"configurable": {"thread_id": "00000000-0000-0000-0000-000000000000"}}
    )
