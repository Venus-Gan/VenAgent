"""共享 state 的 temporary conversation/run 薄 façade。"""

from .conversation import _TemporaryConversationMixin
from .runs import _TemporaryRunMixin
from .state import TemporaryPlatformState


class TemporaryConversationRuntimeStore(
    _TemporaryConversationMixin,
    _TemporaryRunMixin,
):
    durable = False

    def __init__(
        self, state: TemporaryPlatformState | None = None, *, durable: bool = False
    ) -> None:
        self.state = state or TemporaryPlatformState()
        self.durable = durable
