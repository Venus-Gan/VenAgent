"""把 legacy Agent 初始化动作绑定到目标 Bootstrap 编排器。"""

import logging

from .init_sandbox import init_sandbox
from .restore import restore_from_db, restore_rag_from_db

logger = logging.getLogger(__name__)


def bootstrap_agent_runtime(
    agent,
    *,
    restore_db=restore_from_db,
    restore_rag_db=restore_rag_from_db,
    sandbox_initializer=init_sandbox,
):
    """执行 Agent 的四路启动任务，并返回安全的结构化结果。"""
    # 延迟导入避免 legacy 单元测试在未配置 src 路径时产生反向导入副作用。
    from venagent.bootstrap.concurrent import BootstrapTask, ConcurrentBootstrapper

    def init_ragchunk():
        repo = getattr(getattr(agent.inf, "repo", None), "ragchunk", None)
        if repo is not None and hasattr(repo, "init"):
            repo.init(int(agent.cfg.rag_milvus_dim or 1024))

    def restore_runtime():
        preference = getattr(agent, "preference", None)
        if preference is not None and hasattr(preference, "load_from_storage"):
            try:
                preference.load_from_storage()
            except Exception:
                logger.warning("⚠️  preference runtime restore failed")
        restore_db(agent)

    def restore_rag():
        restore_rag_db(agent)

    def initialize_sandbox():
        sandbox_initializer(agent)

    tasks = (
        BootstrapTask("ragchunk", init_ragchunk),
        BootstrapTask("restore-db", restore_runtime),
        BootstrapTask("restore-rag", restore_rag),
        BootstrapTask("sandbox", initialize_sandbox),
    )
    result = ConcurrentBootstrapper(tasks).run()
    for failure in result.failures:
        logger.warning("⚠️  bootstrap task failed: %s", failure.name)
    return result
