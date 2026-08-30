"""所有 Agent Tool 调用的唯一 Gateway。"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .approval import ApprovalService
from .artifact_store import FileArtifactStore
from .errors import (
    ApprovalRejected,
    OperationDuplicate,
    RunGrantInvalid,
    ToolBlocked,
    ToolCancelled,
    ToolNotExposed,
    ToolNotFound,
    ToolTimeout,
    ToolUnavailable,
)
from .models import (
    ApprovalItem,
    Operation,
    ToolCatalogSnapshot,
    ToolDescriptor,
    ToolResult,
)
from .operation_store import OperationStore
from .redaction import redact_text, redacted_json, truncate_content
from .schema import validate_arguments

Executor = Callable[..., Awaitable[ToolResult]]
EventSink = Callable[[str, str, dict[str, Any]], Awaitable[None]]
RunAuthorizer = Callable[[str, str], bool]

logger = logging.getLogger(__name__)


class ToolGateway:
    def __init__(
        self,
        *,
        operations: OperationStore,
        approvals: ApprovalService,
        executor: Executor | None = None,
        timeout_seconds: float = 30.0,
        artifact_store: FileArtifactStore | None = None,
        event_sink: EventSink | None = None,
        run_authorizer: RunAuthorizer | None = None,
        retry_attempts: int = 1,
    ) -> None:
        self._operations = operations
        self._approvals = approvals
        self._executor = executor
        self._timeout_seconds = timeout_seconds
        self._artifact_store = artifact_store
        self._event_sink = event_sink
        self._run_authorizer = run_authorizer
        self._retry_attempts = max(0, retry_attempts)

    def set_executor(self, executor: Executor) -> None:
        self._executor = executor

    def set_event_sink(self, sink: EventSink | None) -> None:
        """绑定运行时的 SSE 事件发布器；不改变 Gateway 权威边界。"""
        self._event_sink = sink

    def load_artifact(self, artifact_id: str) -> bytes | None:
        if self._artifact_store is None:
            return None
        return self._artifact_store.load(artifact_id)

    async def invoke(
        self,
        *,
        snapshot: ToolCatalogSnapshot,
        run_id: str,
        owner_id: str,
        tool_call_id: str,
        operation_key: str,
        tool_id: str,
        arguments: dict[str, Any],
        sandbox_ready: bool,
        approval_id: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> ToolResult:
        if snapshot.run_id is not None and snapshot.run_id != run_id:
            logger.warning(
                "Tool catalog snapshot bound to another run: snapshot_run_id=%s run_id=%s tool_id=%s",
                snapshot.run_id,
                run_id,
                tool_id,
            )
            raise RunGrantInvalid
        if self._run_authorizer is not None and not self._run_authorizer(
            run_id, owner_id
        ):
            logger.warning(
                "Tool run rejected by authorizer: run_id=%s tool_id=%s",
                run_id,
                tool_id,
            )
            raise RunGrantInvalid
        duplicate = self._operations.find_duplicate(run_id, tool_call_id, operation_key)
        if duplicate is not None:
            return duplicate
        descriptor = snapshot.by_id(tool_id)
        if descriptor is None:
            raise ToolNotFound
        if not descriptor.exposed:
            raise ToolNotExposed
        validate_arguments(descriptor.input_schema, arguments)
        now = datetime.now(timezone.utc)
        existing = self._operations.find_operation(
            run_id, tool_call_id, operation_key
        )
        if existing is None:
            operation = Operation(
                operation_id=str(uuid4()),
                run_id=run_id,
                owner_id=owner_id,
                tool_call_id=tool_call_id,
                operation_key=operation_key,
                tool_id=tool_id,
                status="running" if descriptor.risk == "safe" else "awaiting_approval",
                risk=descriptor.risk,
                created_at=now,
                updated_at=now,
                source=descriptor.source,
                server_id=descriptor.server_id,
                arguments_summary=redacted_json(arguments),
                risk_reason=(
                    f"{descriptor.public_name} 属于需审批工具。"
                    if descriptor.risk == "warn"
                    else None
                ),
            )
            try:
                self._operations.save(operation)
            except OperationDuplicate:
                existing = self._operations.find_operation(
                    run_id, tool_call_id, operation_key
                )
                if existing is None:
                    raise
                operation = existing

        else:
            operation = existing

        if descriptor.risk == "block":
            return _record_terminal_result(
                self._operations,
                operation,
                _rejected(
                    tool_call_id,
                    operation.operation_id,
                    "blocked",
                    "该工具被本地策略禁止执行。",
                    ToolBlocked.code,
                ),
            )

        if descriptor.risk == "warn":
            approval = self._resolve_approval(
                operation,
                approval_id,
                run_id=run_id,
                owner_id=owner_id,
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                reason=f"{descriptor.public_name} 属于需审批工具。",
                now=now,
            )
            if approval is None:
                latest = (
                    self._approvals.resolve_identity(
                        approval_id=operation.approval_id,
                        run_id=run_id,
                        owner_id=owner_id,
                        operation_id=operation.operation_id,
                        tool_id=tool_id,
                        tool_call_id=tool_call_id,
                    )
                    if operation.approval_id is not None
                    else None
                )
                if latest is not None and latest.status == "rejected":
                    return _record_terminal_result(
                        self._operations,
                        operation,
                        _rejected(
                            tool_call_id,
                            operation.operation_id,
                            "blocked",
                            latest.rejected_reason or "该工具调用已被拒绝。",
                            ApprovalRejected.code,
                        ),
                    )
                await self._emit(
                    run_id,
                    "awaiting_approval",
                    {
                        "operation_id": operation.operation_id,
                        "tool_id": tool_id,
                        "tool_call_id": tool_call_id,
                        "risk": descriptor.risk,
                    },
                )
                return _awaiting(operation, tool_call_id)
            if approval.status == "rejected":
                return _record_terminal_result(
                    self._operations,
                    operation,
                    _rejected(
                        tool_call_id,
                        operation.operation_id,
                        "blocked",
                        approval.rejected_reason or "该工具调用已被拒绝。",
                        ApprovalRejected.code,
                    ),
                )
            operation.approval_id = approval.approval_id
            operation.status = "running"
            self._operations.update(operation)

        await self._emit(
            run_id,
            "started",
            {
                "operation_id": operation.operation_id,
                "tool_id": tool_id,
                "tool_call_id": tool_call_id,
                "risk": descriptor.risk,
                "source": descriptor.source,
                "server_id": descriptor.server_id,
                "arguments": operation.arguments_summary,
                "risk_reason": operation.risk_reason,
            },
        )

        executor = self._executor
        if executor is None:
            raise ToolUnavailable
        # `sandbox_ready` describes the immutable snapshot; a sandbox-bound
        # executor may initialize its per-run container on first invocation.
        started = time.monotonic()
        try:
            result = await self._execute(
                executor,
                descriptor,
                arguments,
                run_id,
                owner_id=owner_id,
                cancel_event=cancel_event,
            )
        except asyncio.CancelledError:
            await self._emit(
                run_id,
                "cancelled",
                {
                    "operation_id": operation.operation_id,
                    "tool_id": tool_id,
                    "tool_call_id": tool_call_id,
                    "error_code": ToolCancelled.code,
                },
            )
            return _record_terminal_result(
                self._operations,
                operation,
                ToolResult(
                    tool_call_id=tool_call_id,
                    operation_id=operation.operation_id,
                    status="cancelled",
                    summary="工具调用已取消。",
                    content="",
                    error=ToolCancelled.code,
                ),
            )
        except asyncio.TimeoutError:
            await self._emit(
                run_id,
                "failed",
                {
                    "operation_id": operation.operation_id,
                    "tool_id": tool_id,
                    "tool_call_id": tool_call_id,
                    "error_code": ToolTimeout.code,
                },
            )
            return _record_terminal_result(
                self._operations,
                operation,
                ToolResult(
                    tool_call_id=tool_call_id,
                    operation_id=operation.operation_id,
                    status="error",
                    summary="工具调用超时。",
                    content="",
                    error=ToolTimeout.code,
                ),
            )
        except Exception as exc:
            operation.status = "failed"
            operation.error_code = getattr(exc, "code", "tool_execution_failed")
            operation.updated_at = datetime.now(timezone.utc)
            self._operations.update(operation)
            await self._emit(
                run_id,
                "failed",
                {
                    "operation_id": operation.operation_id,
                    "tool_id": tool_id,
                    "tool_call_id": tool_call_id,
                    "error_code": operation.error_code,
                },
            )
            raise
        elapsed = int((time.monotonic() - started) * 1000)
        safe = _sanitize_result(
            result,
            elapsed,
            tool_call_id=tool_call_id,
            operation_id=operation.operation_id,
            artifact_store=self._artifact_store,
            source=f"tool:{tool_id}",
        )
        operation.status = "succeeded" if safe.status == "success" else "failed"
        operation.result_summary = safe.summary
        operation.timing_ms = safe.timing_ms
        operation.artifacts = safe.artifacts
        operation.updated_at = datetime.now(timezone.utc)
        self._operations.update(operation)
        self._operations.save_result(operation.operation_id, safe)
        await self._emit(
            run_id,
            "completed",
            {
                "operation_id": operation.operation_id,
                "tool_id": tool_id,
                "tool_call_id": tool_call_id,
                "status": safe.status,
                "summary": safe.summary,
                "timing_ms": safe.timing_ms,
                "artifacts": [item.artifact_id for item in safe.artifacts],
            },
        )
        return safe

    async def _execute(
        self,
        executor: Executor,
        descriptor: ToolDescriptor,
        arguments: dict[str, Any],
        run_id: str,
        *,
        owner_id: str | None = None,
        cancel_event: asyncio.Event | None,
    ) -> ToolResult:
        attempt = 0
        while True:
            task = asyncio.create_task(
                _call_executor(executor, descriptor, arguments, run_id, owner_id)
            )
            cancel_task = (
                asyncio.create_task(cancel_event.wait())
                if cancel_event is not None
                else None
            )
            try:
                if cancel_task is None:
                    return await asyncio.wait_for(task, timeout=self._timeout_seconds)
                done, _ = await asyncio.wait(
                    {task, cancel_task},
                    timeout=self._timeout_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_task in done:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise asyncio.CancelledError
                if task not in done:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise asyncio.TimeoutError
                return await task
            except Exception as exc:
                code = getattr(exc, "code", "")
                retryable = (
                    descriptor.source == "mcp"
                    and descriptor.risk == "safe"
                    and code
                    in {
                        "mcp_http_429",
                        "mcp_http_502",
                        "mcp_http_503",
                        "mcp_http_504",
                        "mcp_http_unreachable",
                        "mcp_request_timeout",
                    }
                )
                if not retryable or attempt >= self._retry_attempts:
                    raise
                attempt += 1
                await asyncio.sleep(min(0.25 * (2**attempt), 1.0))
            finally:
                if cancel_task is not None:
                    cancel_task.cancel()
                    await asyncio.gather(cancel_task, return_exceptions=True)

    async def _emit(
        self,
        run_id: str,
        kind: str,
        payload: dict[str, Any],
    ) -> None:
        operation_id = payload.get("operation_id")
        if isinstance(operation_id, str):
            self._operations.append_event(operation_id, kind, payload)
        if self._event_sink is not None:
            await self._event_sink(run_id, kind, payload)

    def _resolve_approval(
        self,
        operation: Operation,
        approval_id: str | None,
        *,
        run_id: str,
        owner_id: str,
        tool_id: str,
        tool_call_id: str,
        reason: str,
        now: datetime,
    ) -> ApprovalItem | None:
        latest = None
        if operation.approval_id is not None:
            latest = self._approvals.resolve_identity(
                approval_id=operation.approval_id,
                run_id=run_id,
                owner_id=owner_id,
                operation_id=operation.operation_id,
                tool_id=tool_id,
                tool_call_id=tool_call_id,
            )
        if latest is not None:
            if latest.status in {"approved", "rejected"}:
                return latest
            return None
        if approval_id is not None:
            approval = self._approvals.resolve_identity(
                approval_id=approval_id,
                run_id=run_id,
                owner_id=owner_id,
                operation_id=operation.operation_id,
                tool_id=tool_id,
                tool_call_id=tool_call_id,
            )
            if approval is None:
                return None
            if approval.status in {"approved", "rejected"}:
                return approval
            return None
        created = self._approvals.create(
            run_id=run_id,
            owner_id=owner_id,
            operation_id=operation.operation_id,
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            reason=reason,
            now=now,
        )
        operation.approval_id = created.approval_id
        self._operations.update(operation)
        return None


def _call_executor(
    executor: Executor,
    descriptor: ToolDescriptor,
    arguments: dict[str, Any],
    run_id: str,
    owner_id: str | None = None,
) -> Awaitable[ToolResult]:
    """兼容早期二/三参数执行器；正式 Router 接收 run_id 与 owner_id。"""
    try:
        parameters = inspect.signature(executor).parameters.values()
    except (TypeError, ValueError):
        return executor(descriptor, arguments, run_id)
    positional = [
        item
        for item in parameters
        if item.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if any(item.kind == inspect.Parameter.VAR_POSITIONAL for item in parameters):
        return executor(descriptor, arguments, run_id, owner_id)
    if len(positional) >= 4:
        return executor(descriptor, arguments, run_id, owner_id)
    if len(positional) >= 3:
        return executor(descriptor, arguments, run_id)
    return executor(descriptor, arguments)


def _awaiting(operation: Operation, tool_call_id: str) -> ToolResult:
    return ToolResult(
        tool_call_id=tool_call_id,
        operation_id=operation.operation_id,
        status="awaiting_approval",
        summary="该工具调用等待用户审批。",
        content="",
        approval_id=operation.approval_id,
    )


def _rejected(
    tool_call_id: str,
    operation_id: str,
    status: str,
    summary: str,
    code: str,
) -> ToolResult:
    return ToolResult(
        tool_call_id=tool_call_id,
        operation_id=operation_id,
        status="blocked",
        summary=summary,
        content="",
        error=code,
    )


def _record_terminal_result(
    operations: OperationStore,
    operation: Operation,
    result: ToolResult,
) -> ToolResult:
    operation.status = (
        "cancelled"
        if result.status == "cancelled"
        else "succeeded"
        if result.status == "success"
        else "failed"
    )
    operation.error_code = result.error
    operation.result_summary = result.summary
    operation.timing_ms = result.timing_ms
    operation.artifacts = result.artifacts
    operation.updated_at = datetime.now(timezone.utc)
    operations.update(operation)
    operations.save_result(operation.operation_id, result)
    return result


def _sanitize_result(
    result: ToolResult,
    elapsed_ms: int,
    *,
    tool_call_id: str,
    operation_id: str,
    artifact_store: FileArtifactStore | None = None,
    source: str = "tool",
) -> ToolResult:
    artifacts = result.artifacts
    full_content = redact_text(result.content or "")
    content = truncate_content(full_content, 4096)
    if artifact_store is not None and full_content:
        # Artifact 也先脱敏，避免秘密响应被长期持久化。
        artifacts = (*artifacts, artifact_store.save_text(source, full_content))
    return ToolResult(
        tool_call_id=tool_call_id,
        operation_id=operation_id,
        status=result.status,
        summary=truncate_content(redact_text(result.summary or ""), 1024),
        content=content,
        artifacts=artifacts,
        error=redact_text(result.error) if result.error else None,
        timing_ms=elapsed_ms,
        approval_id=result.approval_id,
    )
