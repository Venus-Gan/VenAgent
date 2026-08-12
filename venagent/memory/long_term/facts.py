"""长期事实、来源与分页值对象。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MemoryStatus = Literal["active", "superseded", "deleted", "expired", "quarantine"]
MemoryIndexStatus = Literal["ready", "pending", "failed"]


@dataclass(frozen=True)
class MemorySource:
    source_ref: str
    owner_id: str
    tenant_id: str
    source_kind: str
    conversation_id: str | None
    source_order: int
    created_at: datetime
    active: bool = True


@dataclass(frozen=True)
class MemoryFact:
    memory_id: str
    owner_id: str
    tenant_id: str
    subject: str
    slot: str
    fact: str
    status: MemoryStatus
    source_refs: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    valid_until: datetime | None = None
    supersedes_id: str | None = None
    sensitivity: str = "normal"
    index_status: MemoryIndexStatus = "ready"

    @property
    def active(self) -> bool:
        return self.status == "active"


@dataclass(frozen=True)
class MemoryPage:
    items: tuple[MemoryFact, ...]
    next_cursor: str | None

