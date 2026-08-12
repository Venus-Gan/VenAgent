"""temporary memory adapter 的纯值转换。"""

from __future__ import annotations

# ruff: noqa: F401
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from threading import RLock
from uuid import uuid4

from ....memory.long_term.facts import MemoryFact


def _ids_hash(values: tuple[str, ...]) -> str:
    return sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()


def _redacted(fact: MemoryFact, status: str, now: datetime) -> MemoryFact:
    return replace(
        fact,
        subject="",
        slot="",
        fact="",
        status=status,  # type: ignore[arg-type]
        source_refs=(),
        sensitivity="redacted",
        updated_at=now,
    )
