# Final Stage — 全阶段整合 AI 助手（Python 版）
#
# 启动入口：
# - 加载配置（路径与 cwd 解耦）
# - 初始化基础设施
# - 构建统一智能体
# - 注册 HTTP 路由
# - 启动 FastAPI 服务
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# 把项目根（final/）加入 sys.path，让 `config.config` / `internal.*` 可被绝对导入
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
SOURCE_ROOT = os.path.join(os.path.dirname(PROJECT_ROOT), "src")
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)

# 默认前端目录指向 final/frontend，避免 cwd 不在项目根时挂载失败
os.environ.setdefault("FRONTEND_DIR", os.path.join(PROJECT_ROOT, "frontend"))

from config.config import APIConfig  # noqa: E402
from apps.api.compat import (  # noqa: E402
    LegacyFactories,
    build_legacy_dependencies,
    load_legacy_config,
)
from internal.agent.agent import UnifiedAgent  # noqa: E402
from internal.handler.handler import setup_routes  # noqa: E402
from internal.infra.infra import Infrastructure  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class Deps:
    cfg: object
    inf: Infrastructure
    agent: UnifiedAgent
    app: object


def _runtime_env_file() -> Path | None:
    project_root = Path(PROJECT_ROOT)
    configured_root = Path(os.environ.get("AGI_PROJECT_ROOT", project_root))
    candidates = (configured_root / ".env", project_root.parent / ".env", project_root / ".env")
    return next((path for path in candidates if path.is_file()), None)


def _runtime_config_paths() -> tuple[Path, Path]:
    configured_path = os.environ.get("AGI_CONFIG")
    if configured_path:
        path = Path(configured_path)
        return path, path
    configured_root = Path(os.environ.get("AGI_PROJECT_ROOT", PROJECT_ROOT))
    shared = configured_root / "config" / "config.yaml"
    local = configured_root / "config" / "config.local.yaml"
    return shared, local


def default_config():
    """通过 canonical loader 读取 YAML、`.env` 和进程环境变量。"""

    shared_path, local_path = _runtime_config_paths()
    return load_legacy_config(
        APIConfig,
        shared_path=shared_path,
        local_path=local_path,
        env_file=_runtime_env_file(),
    )


def build_deps():
    cfg = default_config()
    result = build_legacy_dependencies(
        cfg,
        LegacyFactories(
            infrastructure_factory=lambda legacy_cfg: Infrastructure(legacy_cfg),
            agent_factory=lambda legacy_cfg, infrastructure: UnifiedAgent(
                legacy_cfg, infrastructure
            ),
            runtime_initializer=lambda agent: agent.initialize_runtime(),
            app_factory=lambda legacy_cfg, infrastructure, agent: setup_routes(
                agent, infrastructure, legacy_cfg
            ),
        ),
    )
    dependencies = result.dependencies
    return Deps(
        cfg=cfg,
        inf=dependencies.infrastructure,
        agent=dependencies.application,
        app=dependencies.app,
    )


def _close_safely(resource) -> None:
    close = getattr(resource, "close", None)
    if not callable(close):
        return
    try:
        close()
    except BaseException:
        logger.warning("资源关闭失败: %s", type(resource).__name__)


def main():
    deps = None
    try:
        deps = build_deps()
        print_banner(deps.cfg, deps.inf)

        import uvicorn

        uvicorn.run(deps.app, host="0.0.0.0", port=int(deps.cfg.server_port))
    finally:
        if deps is not None:
            try:
                deps.agent.close()
            except Exception:
                pass
            try:
                deps.inf.close()
            except Exception:
                pass


def print_banner(cfg, inf):
    addr = f":{cfg.server_port}"
    print("========================================")
    print("Final Stage · AGI 智能助手启动成功")
    print("========================================")
    print(f"[INFO] Service       http://localhost{addr}")
    print(f"[INFO] 通用模型           {cfg.llm_model}")
    print(f"[INFO] Embedding     {cfg.embedding_model}")
    print("----------------------------------------")
    print(f"[INFO] Milvus        {inf.ready.milvus}")
    print(f"[INFO] PostgreSQL    {cfg.pg_host}:{cfg.pg_port}")
    print(f"[INFO] ElasticSearch {inf.ready.elasticsearch}")
    print(f"[INFO] Kafka         {inf.ready.kafka}")
    print("----------------------------------------")
    print("[READY] 道阻且长，行则将至。")
    print("========================================")


if __name__ == "__main__":
    main()
