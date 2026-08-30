"""启动 Web UI，或显式迁移 conversation persistence schema。"""

import argparse
import asyncio
import sys
from copy import deepcopy
from typing import Any

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from .config import get_runtime_config
from .platform import (
    PersistenceError,
    migrate_database,
    migrate_neo4j_database,
)


def _configure_event_loop_policy() -> None:
    """psycopg 异步连接在 Windows 上要求 Selector event loop。"""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _build_log_config() -> dict[str, Any]:
    """保留 Uvicorn 默认日志，并单独开启 VenAgent 的 INFO 输出。"""
    # 复制默认配置，避免修改 Uvicorn 的进程级共享常量。
    config = deepcopy(LOGGING_CONFIG)
    config["loggers"]["venagent"] = {
        "handlers": ["default"],
        "level": "INFO",
        "propagate": False,
    }
    return config


def main() -> None:
    _configure_event_loop_policy()
    parser = argparse.ArgumentParser(prog="python -m src")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("serve", "migrate"),
        default="serve",
    )
    args = parser.parse_args()
    config = get_runtime_config()
    if args.command == "migrate":
        try:
            migrate_database(config.persistence.database_url.get_secret_value())
            if config.neo4j.enabled:
                migrate_neo4j_database(
                    config.neo4j.uri,
                    config.neo4j.user,
                    config.neo4j.password.get_secret_value(),
                    config.neo4j.database,
                    connection_timeout=config.neo4j.connection_timeout,
                )
        except PersistenceError as exc:
            parser.error(str(exc))
        print("VenAgent PostgreSQL/Neo4j schema 已迁移到当前版本。")
        return
    uvicorn.run(
        "src.interfaces.http.app:app",
        host="127.0.0.1",
        port=config.server.port,
        reload=False,
        loop="none",
        log_config=_build_log_config(),
    )


if __name__ == "__main__":
    main()
