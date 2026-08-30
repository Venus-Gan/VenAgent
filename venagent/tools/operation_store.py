"""Operation 的权威存储：可选 JSON 原子持久化，失败保留最后有效状态。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import OperationDuplicate, OperationNotFound
from .models import ArtifactRef, Operation, ToolResult


@dataclass
class OperationStore:
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _operations: dict[str, Operation] = field(default_factory=dict)
    _duplicate_keys: dict[tuple[str, str, str], str] = field(default_factory=dict)
    _results: dict[str, ToolResult] = field(default_factory=dict)
    _events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    path: Path | None = None

    def __post_init__(self) -> None:
        if self.path is not None and self.path.is_file():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for item in raw.get("operations", ()):
                operation = _operation_from_json(item)
                self._operations[operation.operation_id] = operation
                self._duplicate_keys[
                    (operation.run_id, operation.tool_call_id, operation.operation_key)
                ] = operation.operation_id
            for item in raw.get("results", ()):
                result = _result_from_json(item)
                self._results[result.operation_id] = result
            self._events = {
                str(operation_id): list(events)
                for operation_id, events in raw.get("events", {}).items()
            }

    def save(self, operation: Operation) -> Operation:
        with self._lock:
            duplicate_key = (
                operation.run_id,
                operation.tool_call_id,
                operation.operation_key,
            )
            if operation.operation_id in self._operations:
                raise OperationDuplicate
            existing = self._duplicate_keys.get(duplicate_key)
            if existing is not None and existing != operation.operation_id:
                raise OperationDuplicate
            self._operations[operation.operation_id] = operation
            self._duplicate_keys[duplicate_key] = operation.operation_id
            self._persist()
            return operation

    def get(self, operation_id: str) -> Operation:
        with self._lock:
            item = self._operations.get(operation_id)
        if item is None:
            raise OperationNotFound
        return item

    def update(self, operation: Operation) -> Operation:
        with self._lock:
            if operation.operation_id not in self._operations:
                raise OperationNotFound
            self._operations[operation.operation_id] = operation
            self._persist()
            return operation

    def save_result(self, operation_id: str, result: ToolResult) -> None:
        with self._lock:
            self._results[operation_id] = result
            self._persist()

    def get_result(self, operation_id: str) -> ToolResult | None:
        with self._lock:
            return self._results.get(operation_id)

    def append_event(
        self, operation_id: str, kind: str, payload: dict[str, Any]
    ) -> None:
        with self._lock:
            self._events.setdefault(operation_id, []).append(
                {"kind": kind, "payload": payload}
            )
            self._persist()

    def events_for(self, operation_id: str) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(self._events.get(operation_id, ()))

    def find_duplicate(
        self, run_id: str, tool_call_id: str, operation_key: str
    ) -> ToolResult | None:
        with self._lock:
            operation_id = self._duplicate_keys.get(
                (run_id, tool_call_id, operation_key)
            )
        if operation_id is None:
            return None
        return self._results.get(operation_id)

    def find_operation(
        self, run_id: str, tool_call_id: str, operation_key: str
    ) -> Operation | None:
        with self._lock:
            operation_id = self._duplicate_keys.get(
                (run_id, tool_call_id, operation_key)
            )
            if operation_id is None:
                return None
            return self._operations.get(operation_id)

    def list_by_owner(
        self, owner_id: str, run_id: str | None = None
    ) -> tuple[Operation, ...]:
        with self._lock:
            return tuple(
                item
                for item in self._operations.values()
                if item.owner_id == owner_id
                and (run_id is None or item.run_id == run_id)
            )

    def compare_and_set_sandbox_state(
        self,
        operation_id: str,
        *,
        expected: str,
        next_state: str,
        generation_id: str | None = None,
    ) -> bool:
        """按 Operation identity 和期望 Sandbox state 原子转换。"""
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None or operation.sandbox_state != expected:
                return False
            updated = _copy_operation(
                operation,
                sandbox_state=next_state,
                sandbox_generation_id=generation_id,
                updated_at=datetime.now(timezone.utc),
            )
            self._operations[operation_id] = updated
            self._persist()
            return True

    def list_by_run(self, run_id: str) -> tuple[Operation, ...]:
        with self._lock:
            return tuple(
                item for item in self._operations.values() if item.run_id == run_id
            )

    def _persist(self) -> None:
        if self.path is None:
            return
        payload = {
            "operations": [_operation_to_json(item) for item in self._operations.values()],
            "results": [_result_to_json(item) for item in self._results.values()],
            "events": self._events,
        }
        _atomic_json(self.path, payload)


def _operation_to_json(item: Operation) -> dict[str, Any]:
    return {
        "operation_id": item.operation_id,
        "run_id": item.run_id,
        "owner_id": item.owner_id,
        "tool_call_id": item.tool_call_id,
        "operation_key": item.operation_key,
        "tool_id": item.tool_id,
        "status": item.status,
        "risk": item.risk,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "approval_id": item.approval_id,
        "error_code": item.error_code,
        "result_summary": item.result_summary,
        "source": item.source,
        "server_id": item.server_id,
        "arguments_summary": item.arguments_summary,
        "risk_reason": item.risk_reason,
        "timing_ms": item.timing_ms,
        "sandbox_generation_id": item.sandbox_generation_id,
        "sandbox_state": item.sandbox_state,
        "artifacts": [
            {
                "artifact_id": artifact.artifact_id,
                "source": artifact.source,
                "size_bytes": artifact.size_bytes,
                "content_type": artifact.content_type,
                "checksum_sha256": artifact.checksum_sha256,
            }
            for artifact in item.artifacts
        ],
    }


def _operation_from_json(raw: dict[str, Any]) -> Operation:
    return Operation(
        operation_id=raw["operation_id"],
        run_id=raw["run_id"],
        owner_id=raw["owner_id"],
        tool_call_id=raw["tool_call_id"],
        operation_key=raw["operation_key"],
        tool_id=raw["tool_id"],
        status=raw["status"],
        risk=raw["risk"],
        created_at=datetime.fromisoformat(raw["created_at"]),
        updated_at=datetime.fromisoformat(raw["updated_at"]),
        approval_id=raw.get("approval_id"),
        error_code=raw.get("error_code"),
        result_summary=raw.get("result_summary"),
        source=raw.get("source", "native"),
        server_id=raw.get("server_id"),
        arguments_summary=raw.get("arguments_summary", "{}"),
        risk_reason=raw.get("risk_reason"),
        timing_ms=int(raw.get("timing_ms", 0)),
        sandbox_generation_id=raw.get("sandbox_generation_id"),
        sandbox_state=raw.get("sandbox_state", "not_requested"),
        artifacts=tuple(
            ArtifactRef(
                artifact_id=item["artifact_id"],
                source=item["source"],
                size_bytes=item["size_bytes"],
                content_type=item.get("content_type", "application/octet-stream"),
                checksum_sha256=item.get("checksum_sha256"),
            )
            for item in raw.get("artifacts", ())
        ),
    )


def _result_to_json(item: ToolResult) -> dict[str, Any]:
    return {
        "tool_call_id": item.tool_call_id,
        "operation_id": item.operation_id,
        "status": item.status,
        "summary": item.summary,
        "content": item.content,
        "artifacts": [
            {
                "artifact_id": artifact.artifact_id,
                "source": artifact.source,
                "size_bytes": artifact.size_bytes,
                "content_type": artifact.content_type,
                "checksum_sha256": artifact.checksum_sha256,
            }
            for artifact in item.artifacts
        ],
        "error": item.error,
        "timing_ms": item.timing_ms,
        "approval_id": item.approval_id,
    }


def _result_from_json(raw: dict[str, Any]) -> ToolResult:
    return ToolResult(
        tool_call_id=raw["tool_call_id"],
        operation_id=raw["operation_id"],
        status=raw["status"],
        summary=raw["summary"],
        content=raw["content"],
        artifacts=tuple(
            ArtifactRef(
                artifact_id=item["artifact_id"],
                source=item["source"],
                size_bytes=item["size_bytes"],
                content_type=item.get("content_type", "application/octet-stream"),
                checksum_sha256=item.get("checksum_sha256"),
            )
            for item in raw.get("artifacts", ())
        ),
        error=raw.get("error"),
        timing_ms=raw.get("timing_ms", 0),
        approval_id=raw.get("approval_id"),
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


def _copy_operation(operation: Operation, **updates: Any) -> Operation:
    values = {**operation.__dict__, **updates}
    return Operation(**values)
