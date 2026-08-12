"""组合 conversation 与 run ports 的 PostgreSQL adapter。"""

from typing import Any

from psycopg_pool import ConnectionPool

from .conversation import _PostgresConversationMixin
from .runs import _PostgresRunMixin


class PostgresConversationRuntimeStore(_PostgresConversationMixin, _PostgresRunMixin):
    """共享同一连接池，事务仍由具体操作方法控制。"""

    def __init__(self, pool: ConnectionPool[Any]) -> None:
        # conversation 和 run adapter 共享业务连接池；LangGraph checkpointer 使用独立异步池。
        self._pool = pool
