"""temporary 对话摘要 adapter。"""

from __future__ import annotations

# ruff: noqa: F401
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from threading import RLock
from uuid import uuid4

from ....memory.ports import MemoryStoreError as StoreError
from ....memory.short_term import MemorySummary


class _TemporaryShortTermMixin:
    def get_summary(self, owner_id: str, conversation_id: str) -> MemorySummary | None:
        with self._lock:
            summary = self._summaries.get((owner_id, conversation_id))
            settings = self.settings(owner_id)
            if (
                summary is None
                or not settings.enabled
                or settings.purge_pending
                or summary.deletion_generation != settings.deletion_generation
            ):
                return None
            return summary

    def save_summary(self, summary: MemorySummary) -> None:
        with self._lock:
            settings = self.settings(summary.owner_id)
            if (
                not settings.enabled
                or settings.purge_pending
                or summary.deletion_generation != settings.deletion_generation
            ):
                return
            self._summaries[(summary.owner_id, summary.conversation_id)] = summary
