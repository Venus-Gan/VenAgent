"""PostgreSQL memory adapter 的稳定导出。"""

from typing import Any

from psycopg_pool import ConnectionPool

from .index import _PostgresIndexMixin
from .jobs import _PostgresJobsMixin
from .long_term import _PostgresLongTermMixin
from .short_term import _PostgresShortTermMixin


class PostgresMemoryStore(
    _PostgresLongTermMixin,
    _PostgresIndexMixin,
    _PostgresShortTermMixin,
    _PostgresJobsMixin,
):
    """只接收平台 runtime 注入的池，不拥有连接生命周期。"""

    durable = True

    def __init__(self, pool: ConnectionPool[Any]) -> None:
        self._pool = pool


__all__ = ["PostgresMemoryStore"]
