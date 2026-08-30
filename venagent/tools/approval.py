"""warn 工具调用的 Approval 项与决定记录，可选 JSON 原子持久化。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .errors import ApprovalExpired
from .models import ApprovalItem


@dataclass
class ApprovalService:
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _items: dict[str, ApprovalItem] = field(default_factory=dict)
    ttl: timedelta = timedelta(minutes=5)
    path: Path | None = None

    def __post_init__(self) -> None:
        if self.path is not None and self.path.is_file():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for item in raw.get("items", ()):
                approval = _approval_from_json(item)
                self._items[approval.approval_id] = approval

    def create(
        self,
        *,
        run_id: str,
        owner_id: str,
        operation_id: str,
        tool_id: str,
        tool_call_id: str,
        reason: str,
        now: datetime | None = None,
    ) -> ApprovalItem:
        now = now or datetime.now(timezone.utc)
        item = ApprovalItem(
            approval_id=f"ap-{run_id}-{operation_id}",
            run_id=run_id,
            owner_id=owner_id,
            operation_id=operation_id,
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            risk="warn",
            reason=reason,
            created_at=now,
            expires_at=now + self.ttl,
        )
        with self._lock:
            self._items[item.approval_id] = item
            self._persist()
        return item

    def find_or_create(
        self,
        *,
        run_id: str,
        owner_id: str,
        operation_id: str,
        tool_id: str,
        tool_call_id: str,
        reason: str,
        now: datetime | None = None,
    ) -> ApprovalItem:
        """按调用 identity 幂等返回同一审批项，避免 graph 重放重复创建。"""
        existing = self.resolve(run_id, tool_call_id)
        if existing is not None:
            return existing
        return self.create(
            run_id=run_id,
            owner_id=owner_id,
            operation_id=operation_id,
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            reason=reason,
            now=now,
        )

    def get(self, approval_id: str) -> ApprovalItem:
        with self._lock:
            item = self._items.get(approval_id)
        if item is None:
            raise ApprovalExpired
        return item

    def decide_detailed(
        self,
        approval_id: str,
        owner_id: str,
        approved: bool,
        *,
        rejected_reason: str | None = None,
        now: datetime | None = None,
    ) -> tuple[ApprovalItem, bool, bool]:
        """返回 (item, changed, conflict)；相同决定重试 changed=False。"""
        now = now or datetime.now(timezone.utc)
        current = self.get(approval_id)
        if current.owner_id != owner_id:
            raise ApprovalExpired
        if current.status == "pending" and current.expires_at < now:
            item = _copy_approval(current, status="expired", decided_at=now)
            with self._lock:
                self._items[approval_id] = item
                self._persist()
            raise ApprovalExpired
        desired = "approved" if approved else "rejected"
        if current.status != "pending":
            conflict = current.status != desired
            return current, False, conflict
        item = _copy_approval(
            current,
            status=desired,
            decided_at=now,
            rejected_reason=rejected_reason if not approved else None,
        )
        with self._lock:
            self._items[approval_id] = item
            self._persist()
        return item, True, False

    def decide(
        self,
        approval_id: str,
        owner_id: str,
        approved: bool,
        *,
        rejected_reason: str | None = None,
        now: datetime | None = None,
    ) -> ApprovalItem:
        item, _changed, _conflict = self.decide_detailed(
            approval_id,
            owner_id,
            approved,
            rejected_reason=rejected_reason,
            now=now,
        )
        return item

    def resolve_pending(
        self, run_id: str, tool_call_id: str
    ) -> ApprovalItem | None:
        """返回当前 pending 项；无 pending 时返回 None。"""
        with self._lock:
            items = list(self._items.values())
        pending = [
            item
            for item in items
            if item.run_id == run_id
            and item.tool_call_id == tool_call_id
            and item.status == "pending"
        ]
        return pending[-1] if pending else None

    def resolve(
        self, run_id: str, tool_call_id: str
    ) -> ApprovalItem | None:
        """返回最近的任意状态项，供 Gateway 幂等恢复决定。"""
        with self._lock:
            items = list(self._items.values())
        matched = [
            item
            for item in items
            if item.run_id == run_id
            and item.tool_call_id == tool_call_id
        ]
        return matched[-1] if matched else None

    def resolve_identity(
        self,
        *,
        approval_id: str,
        run_id: str,
        owner_id: str,
        operation_id: str,
        tool_id: str,
        tool_call_id: str,
    ) -> ApprovalItem | None:
        try:
            item = self.get(approval_id)
        except ApprovalExpired:
            return None
        if (
            item.run_id != run_id
            or item.owner_id != owner_id
            or item.operation_id != operation_id
            or item.tool_id != tool_id
            or item.tool_call_id != tool_call_id
        ):
            return None
        return item

    def cancel_by_run(self, run_id: str, owner_id: str) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            changed = False
            for item in self._items.values():
                if (
                    item.run_id == run_id
                    and item.owner_id == owner_id
                    and item.status == "pending"
                ):
                    self._items[item.approval_id] = _copy_approval(
                        item,
                        status="cancelled",
                        decided_at=now,
                        rejected_reason="用户取消",
                    )
                    changed = True
            if changed:
                self._persist()

    def list_by_run(self, run_id: str) -> tuple[ApprovalItem, ...]:
        with self._lock:
            return tuple(item for item in self._items.values() if item.run_id == run_id)

    def _persist(self) -> None:
        if self.path is None:
            return
        payload = {
            "items": [_approval_to_json(item) for item in self._items.values()]
        }
        _atomic_json(self.path, payload)


def _copy_approval(
    item: ApprovalItem,
    **updates: object,
) -> ApprovalItem:
    values = {**item.__dict__, **updates}
    return ApprovalItem(**values)


def _approval_to_json(item: ApprovalItem) -> dict[str, Any]:
    return {
        "approval_id": item.approval_id,
        "run_id": item.run_id,
        "owner_id": item.owner_id,
        "operation_id": item.operation_id,
        "tool_id": item.tool_id,
        "tool_call_id": item.tool_call_id,
        "risk": item.risk,
        "reason": item.reason,
        "created_at": item.created_at.isoformat(),
        "expires_at": item.expires_at.isoformat(),
        "status": item.status,
        "decided_at": item.decided_at.isoformat() if item.decided_at else None,
        "rejected_reason": item.rejected_reason,
    }


def _approval_from_json(raw: dict[str, Any]) -> ApprovalItem:
    decided_at = raw.get("decided_at")
    return ApprovalItem(
        approval_id=raw["approval_id"],
        run_id=raw["run_id"],
        owner_id=raw["owner_id"],
        operation_id=raw["operation_id"],
        tool_id=raw["tool_id"],
        tool_call_id=raw["tool_call_id"],
        risk=raw["risk"],
        reason=raw["reason"],
        created_at=datetime.fromisoformat(raw["created_at"]),
        expires_at=datetime.fromisoformat(raw["expires_at"]),
        status=raw.get("status", "pending"),
        decided_at=datetime.fromisoformat(decided_at) if decided_at else None,
        rejected_reason=raw.get("rejected_reason"),
    )


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f"{path.name}-", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
