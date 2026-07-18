"""FastAPI lifespan 适配器。"""

import inspect
from contextlib import asynccontextmanager
from typing import Awaitable, Callable

from venagent.infrastructure.lifecycle import LifecycleManager


StartupFactory = Callable[[LifecycleManager], object | Awaitable[object]]


def create_lifespan(startup: StartupFactory):
    """创建只拥有一个生命周期管理器的 FastAPI context factory。"""

    if not callable(startup):
        raise TypeError("startup must be callable")

    @asynccontextmanager
    async def lifespan(app):
        manager = LifecycleManager()
        _set_state_value(app, "lifecycle_status", "starting")
        try:
            result = startup(manager)
            if inspect.isawaitable(result):
                result = await result
            _store_runtime_state(app, result)
            if not manager.started:
                await manager.startup()
            _set_state_value(app, "lifecycle_status", "started")
            yield
        except BaseException:
            _set_state_value(app, "lifecycle_status", "failed")
            await manager.shutdown()
            raise
        finally:
            await manager.shutdown()
            _set_state_value(app, "lifecycle_status", "stopped")

    return lifespan


def install_lifespan(app, startup: StartupFactory):
    """将 context factory 安装到 FastAPI 风格 app，不在导入时创建资源。"""

    router = getattr(app, "router", None)
    if router is None:
        raise TypeError("app must expose a router")
    router.lifespan_context = create_lifespan(startup)
    return app


def _store_runtime_state(app, result: object) -> None:
    if result is None:
        return
    state = getattr(app, "state", None)
    if state is None:
        return
    if isinstance(result, dict):
        for key, value in result.items():
            if (
                isinstance(key, str)
                and key.isidentifier()
                and _is_safe_state_value(value)
            ):
                setattr(state, key, value)


def _set_state_value(app, key: str, value: object) -> None:
    state = getattr(app, "state", None)
    if state is not None:
        setattr(state, key, value)


def _is_safe_state_value(value: object) -> bool:
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, (tuple, list)):
        return all(_is_safe_state_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_safe_state_value(item)
            for key, item in value.items()
        )
    return False
