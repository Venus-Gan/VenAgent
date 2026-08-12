"""temporary memory adapter 的共享状态容器。"""

from __future__ import annotations

# ruff: noqa: F401
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from threading import RLock
from uuid import uuid4

from ....memory.capabilities import MemorySettings
from ....memory.graph import MemoryEdge
from ....memory.jobs import MemoryJob
from ....memory.long_term.facts import MemoryFact, MemorySource
from ....memory.short_term import MemorySummary
from .graph import _TemporaryGraphMixin
from .index import _TemporaryIndexMixin
from .jobs import _TemporaryJobsMixin
from .long_term import _TemporaryLongTermMixin
from .short_term import _TemporaryShortTermMixin


class TemporaryMemoryStore(
    _TemporaryLongTermMixin,
    _TemporaryIndexMixin,
    _TemporaryGraphMixin,
    _TemporaryShortTermMixin,
    _TemporaryJobsMixin,
):
    """所有能力共享一把锁，保持原有跨职责原子性。"""

    def __init__(self, *, durable: bool = False) -> None:
        self.durable = durable
        self._settings: dict[str, MemorySettings] = {}
        self._facts: dict[str, MemoryFact] = {}
        self._sources: dict[str, MemorySource] = {}
        self._edges: dict[str, MemoryEdge] = {}
        self._projection_states: dict[tuple[str, str], tuple[int, int, str]] = {}
        self._revisions: dict[tuple[str, str], int] = {}
        self._summaries: dict[tuple[str, str], MemorySummary] = {}
        self._jobs: dict[str, MemoryJob] = {}
        self._index_records = {}
        self._job_keys: dict[str, str] = {}
        self._confirmations: dict[str, tuple[str, str, str, str, datetime]] = {}
        self._lock = RLock()
