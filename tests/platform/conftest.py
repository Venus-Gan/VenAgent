"""tests/platform/ 共用装配：create_app + 进程内存 persistence runtime（D5）。"""

from __future__ import annotations

import pytest

from src.interfaces.http.app import create_app
from src.platform.runtime import build_persistence_runtime


@pytest.fixture
def app_factory():
    """返回 (model=None, **kwargs) -> FastAPI 的装配工厂；缺省使用临时 persistence。"""

    def factory(model=None, **kwargs):
        kwargs.setdefault("persistence_runtime", build_persistence_runtime({}))
        return create_app(model, **kwargs)

    return factory