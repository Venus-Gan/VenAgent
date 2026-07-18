"""新的 API 组合入口。

本模块只在显式调用 ``create_app`` 时执行装配，不在导入期间创建副作用。
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from venagent.bootstrap import DependencyContainer, StagedBootstrapper
from apps.api.lifespan import install_lifespan


def create_app(container: DependencyContainer) -> object:
    """创建无副作用的应用壳，把资源装配延迟到 lifespan startup。"""

    shell_factory = container.app_shell_factory
    if not callable(shell_factory):
        raise TypeError("app_shell_factory is required for lazy app creation")
    app = shell_factory()
    if not (hasattr(app, "router") and hasattr(app, "state")):
        return app

    async def startup(manager):
        result = StagedBootstrapper(container).run()
        dependencies = result.dependencies
        manager.register("infrastructure", dependencies.infrastructure)
        manager.register("application", dependencies.application)
        _adopt_built_app(app, dependencies.app)
        return {
            "bootstrap_diagnostics": tuple(
                f"{item.stage.value}:{item.status.value}:{item.code}"
                for item in result.diagnostics
            )
        }

    install_lifespan(app, startup)
    return app


def _adopt_built_app(shell: object, built: object) -> None:
    """将 startup 阶段构建的 FastAPI 状态接入预先返回的应用壳。"""

    if built is shell:
        return
    for attribute in ("router", "user_middleware", "exception_handlers"):
        if hasattr(built, attribute):
            setattr(shell, attribute, getattr(built, attribute))
    if hasattr(shell, "middleware_stack"):
        shell.middleware_stack = None
