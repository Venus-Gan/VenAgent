"""进程内会话路径 adapter 的稳定导出。

memory 无内存镜像（见 docs/wayfinder/tickets/repo-双镜像去留.md 决策）：
非 durable 时 memory 端口由 bootstrap 的 _DisabledMemoryStore 占位。
"""

from __future__ import annotations

from .conversation import _InMemoryConversationMixin
from .ownership import InMemoryOwnershipStore
from .runs import _InMemoryRunMixin
from .state import InMemoryPlatformState


class InMemoryConversationRuntimeStore(
    _InMemoryConversationMixin,
    _InMemoryRunMixin,
):
    durable = False

    def __init__(
        self, state: InMemoryPlatformState | None = None, *, durable: bool = False
    ) -> None:
        self.state = state or InMemoryPlatformState()
        self.durable = durable


__all__ = [
    "InMemoryConversationRuntimeStore",
    "InMemoryOwnershipStore",
    "InMemoryPlatformState",
]