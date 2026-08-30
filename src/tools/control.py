"""M06 控制面组合：快照、Sandbox、Skill、调用载荷与 Gateway。"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..promptctx.context import ContextBlock
from ..promptctx.source_constraints import sandbox_constraints_block
from ..promptctx.source_skills import skill_context_block
from ..promptctx.source_tools import (
    tool_capability_block,
    tool_operation_summary_block,
)
from ..sandbox.docker import DockerSandboxRuntime
from ..skills.catalog import SkillCatalog
from .approval import ApprovalService
from .catalog import ToolCatalog
from .errors import ToolNotFound
from .exec_command import exec_command_descriptor
from .gateway import ToolGateway
from .invocation_store import InMemoryInvocationStore, InvocationStore
from .langchain import snapshot_to_langchain_tools
from .models import (
    ModelToolCall,
    Operation,
    StagedToolCall,
    ToolCatalogSnapshot,
    ToolResult,
)
from .operation_store import OperationStore
from .redaction import redacted_json
from .schema import validate_arguments


def operation_key_for(tool_id: str, tool_call_id: str) -> str:
    """稳定 operation_key：同一 Run 内同一 tool call 只对应一个 Operation。"""
    return f"{tool_id}:{tool_call_id}"


@dataclass
class ToolControlContext:
    """AgentRuntime 只通过该组合读取快照、模型工具和 Gateway。"""

    catalog: ToolCatalog
    sandbox: DockerSandboxRuntime
    skills: SkillCatalog
    gateway: ToolGateway
    approvals: ApprovalService
    operations: OperationStore
    snapshot_path: Path | None = None
    invocations: InvocationStore = field(default_factory=InMemoryInvocationStore)
    available_servers: frozenset[str] = frozenset()
    catalog_revision: int = 1
    _run_snapshots: dict[str, ToolCatalogSnapshot] = field(default_factory=dict)
    _run_skills_lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.snapshot_path is None or not self.snapshot_path.is_file():
            return
        raw = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        snapshots = raw.get("snapshots", {})
        if not isinstance(snapshots, dict):
            raise ValueError("run tool snapshots are invalid")
        self._run_snapshots = {
            str(run_id): _snapshot_from_json(item)
            for run_id, item in snapshots.items()
        }

    def refresh_servers(
        self, servers, *, ready_servers: frozenset[str] | None = None
    ) -> None:
        """只有 enabled 且实际连接成功的 Server 才可进入新快照。"""
        enabled = frozenset(server.server_id for server in servers if server.enabled)
        ready = self.available_servers if ready_servers is None else ready_servers
        self.available_servers = enabled & ready

    def snapshot(
        self,
        available_servers: frozenset[str] | None = None,
        *,
        run_id: str | None = None,
    ) -> ToolCatalogSnapshot:
        if run_id is not None:
            with self._run_skills_lock:
                fixed = self._run_snapshots.get(run_id)
            if fixed is not None:
                return fixed
        servers = (
            self.available_servers
            if available_servers is None
            else available_servers
        )
        capability = self.sandbox.capability(run_id)
        return self.catalog.build_snapshot(
            sandbox_ready=capability.ready,
            catalog_revision=self.catalog_revision,
            sandbox_reason=capability.reason_code,
            available_servers=servers,
            run_id=run_id,
        )

    def mark_catalog_refreshed(self) -> int:
        """推进全局目录版本；已绑定 Run 的不可变快照不受影响。"""
        with self._run_skills_lock:
            self.catalog_revision += 1
            return self.catalog_revision

    async def start_run(self, run_id: str) -> ToolCatalogSnapshot:
        # Run 启动只做探测与快照绑定，不创建 Docker 容器。
        if self.catalog.tool("exec_command") is None:
            self.catalog.register(exec_command_descriptor())
        snapshot = self.snapshot(run_id=run_id)
        with self._run_skills_lock:
            self._run_snapshots[run_id] = snapshot
            self._persist_run_snapshots_locked()
        return snapshot

    async def ensure_sandbox(
        self,
        run_id: str,
        tool_call_id: str,
        operation_key: str,
    ) -> bool:
        """首次真实执行 exec_command 时按需创建容器；旧 Operation 容器丢失不重建。"""
        operation = self.operations.find_operation(
            run_id, tool_call_id, operation_key
        )
        if operation is None:
            return False
        state = operation.sandbox_state or "not_requested"
        if state == "invalid":
            return False
        if state == "ready":
            capability = await self.sandbox.start_run(
                run_id,
                allow_create=False,
                generation_id=operation.sandbox_generation_id,
            )
            if capability.ready and await self._materialize_run_skills(run_id):
                return True
            await self.sandbox.stop_run(run_id)
            operation.sandbox_state = "invalid"
            self.operations.update(operation)
            return False
        if state == "provisioning":
            capability = await self.sandbox.start_run(
                run_id,
                allow_create=False,
                generation_id=operation.sandbox_generation_id,
            )
            if capability.ready and await self._materialize_run_skills(run_id):
                operation.sandbox_state = "ready"
                self.operations.update(operation)
                return True
            await self.sandbox.stop_run(run_id)
            operation.sandbox_state = "invalid"
            self.operations.update(operation)
            return False
        # not_requested
        if operation.status == "running" and operation.sandbox_generation_id is not None:
            operation.sandbox_state = "invalid"
            self.operations.update(operation)
            return False
        generation_id = str(uuid4())
        if not self.operations.compare_and_set_sandbox_state(
            operation.operation_id,
            expected="not_requested",
            next_state="provisioning",
            generation_id=generation_id,
        ):
            # 并发失败：读取权威状态后重试一次。
            return await self.ensure_sandbox(run_id, tool_call_id, operation_key)
        capability = await self.sandbox.start_run(
            run_id,
            allow_create=True,
            generation_id=generation_id,
        )
        operation = self.operations.get(operation.operation_id)
        if capability.ready and await self._materialize_run_skills(run_id):
            operation.sandbox_state = "ready"
            self.operations.update(operation)
            return True
        await self.sandbox.stop_run(run_id)
        operation.sandbox_state = "invalid"
        self.operations.update(operation)
        return False

    async def _materialize_run_skills(self, run_id: str) -> bool:
        try:
            packages = await asyncio.to_thread(
                self.skills.materializations_for_run, run_id
            )
        except (OSError, ValueError):
            return False
        if not packages:
            return True
        materialize = getattr(self.sandbox, "materialize_skills", None)
        if not callable(materialize):
            return False
        return bool(await materialize(run_id, packages))

    async def stop_run(self, run_id: str) -> None:
        await self.sandbox.stop_run(run_id)
        with self._run_skills_lock:
            self._run_snapshots.pop(run_id, None)
            self._persist_run_snapshots_locked()
        self.invocations.delete_run(run_id)
        # Skill catalog persistence uses fsync/replace; keep it off the agent loop.
        await asyncio.to_thread(self.skills.release_run, run_id)

    async def finalize_cancelled_run(self, run_id: str, owner_id: str) -> None:
        """取消 waiting_approval 后的幂等终态清理。"""
        self.approvals.cancel_by_run(run_id, owner_id)
        for operation in self.operations.list_by_run(run_id):
            if operation.status in {"queued", "running", "awaiting_approval"}:
                operation.status = "cancelled"
                operation.error_code = operation.error_code or "user_cancelled"
                operation.updated_at = datetime.now(timezone.utc)
                self.operations.update(operation)
        self.invocations.delete_run(run_id)
        await self.sandbox.stop_run(run_id)
        await self.stop_run(run_id)

    def model_tools(self, run_id: str) -> tuple[dict[str, Any], ...]:
        """返回固定 Snapshot 的 LangChain tool schemas。"""
        return snapshot_to_langchain_tools(self.snapshot(run_id=run_id))

    def stage_tool_call(
        self, run_id: str, owner_id: str, model_tool_call: ModelToolCall
    ) -> StagedToolCall:
        """校验参数并保存到私有调用载荷存储，返回定位引用。"""
        snapshot = self.snapshot(run_id=run_id)
        descriptor = snapshot.by_id(model_tool_call.name)
        if descriptor is None:
            raise ToolNotFound
        validate_arguments(descriptor.input_schema, model_tool_call.arguments)
        operation_key = operation_key_for(model_tool_call.name, model_tool_call.id)
        existing = self.operations.find_operation(
            run_id, model_tool_call.id, operation_key
        )
        now = datetime.now(timezone.utc)
        if existing is None:
            operation = Operation(
                operation_id=str(uuid4()),
                run_id=run_id,
                owner_id=owner_id,
                tool_call_id=model_tool_call.id,
                operation_key=operation_key,
                tool_id=model_tool_call.name,
                status="running" if descriptor.risk == "safe" else "awaiting_approval",
                risk=descriptor.risk,
                created_at=now,
                updated_at=now,
                source=descriptor.source,
                server_id=descriptor.server_id,
                arguments_summary=redacted_json(model_tool_call.arguments),
                risk_reason=(
                    f"{descriptor.public_name} 属于需审批工具。"
                    if descriptor.risk == "warn"
                    else None
                ),
                sandbox_state="not_requested",
            )
            try:
                self.operations.save(operation)
            except Exception:
                existing = self.operations.find_operation(
                    run_id, model_tool_call.id, operation_key
                )
                if existing is None:
                    raise
                operation = existing
        else:
            operation = existing
        self.invocations.save(
            run_id=run_id,
            owner_id=owner_id,
            operation_id=operation.operation_id,
            tool_call_id=model_tool_call.id,
            operation_key=operation_key,
            arguments=model_tool_call.arguments,
        )
        return StagedToolCall(
            tool_call_id=model_tool_call.id,
            operation_key=operation_key,
            tool_id=model_tool_call.name,
        )

    async def invoke_tool(
        self,
        run_id: str,
        owner_id: str,
        model_tool_call: ModelToolCall,
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> ToolResult:
        staged = self.stage_tool_call(run_id, owner_id, model_tool_call)
        snapshot = self.snapshot(run_id=run_id)
        descriptor = snapshot.by_id(model_tool_call.name)
        if (
            descriptor is not None
            and descriptor.source == "native"
            and descriptor.tool_id == "exec_command"
            and descriptor.risk == "safe"
        ):
            await self.ensure_sandbox(
                run_id, model_tool_call.id, staged.operation_key
            )
        result = await self.gateway.invoke(
            snapshot=snapshot,
            run_id=run_id,
            owner_id=owner_id,
            tool_call_id=model_tool_call.id,
            operation_key=staged.operation_key,
            tool_id=model_tool_call.name,
            arguments=model_tool_call.arguments,
            sandbox_ready=snapshot.sandbox_state == "ready",
            cancel_event=cancel_event,
        )
        self._bind_operation(
            run_id,
            owner_id,
            model_tool_call.id,
            staged.operation_key,
            result.operation_id,
            model_tool_call.arguments,
        )
        return result

    async def resume_tool(
        self,
        run_id: str,
        owner_id: str,
        pending_ref: Any,
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> ToolResult:
        arguments = self.invocations.get(
            run_id=run_id,
            owner_id=owner_id,
            tool_call_id=pending_ref.tool_call_id,
            operation_key=pending_ref.operation_key,
        )
        snapshot = self.snapshot(run_id=run_id)
        descriptor = snapshot.by_id(pending_ref.tool_id)
        if (
            descriptor is not None
            and descriptor.source == "native"
            and descriptor.tool_id == "exec_command"
        ):
            approval = self.approvals.resolve(run_id, pending_ref.tool_call_id)
            if descriptor.risk == "safe" or (
                approval is not None and approval.status == "approved"
            ):
                await self.ensure_sandbox(
                    run_id, pending_ref.tool_call_id, pending_ref.operation_key
                )
        result = await self.gateway.invoke(
            snapshot=snapshot,
            run_id=run_id,
            owner_id=owner_id,
            tool_call_id=pending_ref.tool_call_id,
            operation_key=pending_ref.operation_key,
            tool_id=pending_ref.tool_id,
            arguments=arguments,
            sandbox_ready=snapshot.sandbox_state == "ready",
            approval_id=pending_ref.approval_id,
            cancel_event=cancel_event,
        )
        self._bind_operation(
            run_id,
            owner_id,
            pending_ref.tool_call_id,
            pending_ref.operation_key,
            result.operation_id,
            arguments,
        )
        return result

    def load_tool_arguments(self, run_id: str, owner_id: str, pending_ref: Any) -> dict[str, Any]:
        """从私有 InvocationStore 读取原始参数，用于重建 assistant tool-call 消息。"""
        return self.invocations.get(
            run_id=run_id,
            owner_id=owner_id,
            tool_call_id=pending_ref.tool_call_id,
            operation_key=pending_ref.operation_key,
        )

    def project_tool_result(
        self,
        run_id: str,
        owner_id: str,
        pending_ref: Any,
        observation_ref: Any,
    ) -> str:
        """从权威存储读取并校验终态结果，生成给最终模型的有界内容。"""
        operation_id = getattr(observation_ref, "operation_id", "")
        if not operation_id:
            return _tool_result_projection_error("tool_result_unavailable")
        try:
            operation = self.operations.get(operation_id)
            result = self.operations.get_result(operation_id)
        except Exception:
            return _tool_result_projection_error("tool_result_unavailable")
        if result is None:
            return _tool_result_projection_error("tool_result_unavailable")
        expected = (
            operation.run_id == run_id,
            operation.owner_id == owner_id,
            operation.tool_call_id == pending_ref.tool_call_id,
            operation.operation_key == pending_ref.operation_key,
            operation.tool_id == pending_ref.tool_id,
            result.operation_id == operation_id,
            result.tool_call_id == pending_ref.tool_call_id,
            observation_ref.tool_call_id == pending_ref.tool_call_id,
            observation_ref.status == result.status,
        )
        if not all(expected):
            return _tool_result_projection_error("tool_result_reference_invalid")
        payload = {
            "status": result.status,
            "summary": result.summary,
            "content": result.content,
            "error_code": result.error,
            "artifacts": [
                {
                    "artifact_id": item.artifact_id,
                    "content_type": item.content_type,
                    "size_bytes": item.size_bytes,
                    "checksum_sha256": item.checksum_sha256,
                }
                for item in result.artifacts
            ],
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def _bind_operation(
        self,
        run_id: str,
        owner_id: str,
        tool_call_id: str,
        operation_key: str,
        operation_id: str,
        arguments: dict[str, Any],
    ) -> None:
        if not operation_id:
            return
        self.invocations.save(
            run_id=run_id,
            owner_id=owner_id,
            operation_id=operation_id,
            tool_call_id=tool_call_id,
            operation_key=operation_key,
            arguments=arguments,
        )

    def collect_blocks(
        self,
        *,
        run_id: str | None = None,
        selected_skill_ids: tuple[str, ...] = (),
        pending_approvals: int = 0,
        recent_operations: tuple[str, ...] = (),
    ) -> tuple[ContextBlock, ...]:
        snapshot = self.snapshot(run_id=run_id)
        if run_id is not None and not recent_operations:
            operations = self.operations.list_by_run(run_id)
            recent_operations = tuple(
                f"{item.tool_id}:{item.status}:{item.result_summary or item.error_code or ''}"
                for item in operations[-5:]
            )
        if run_id is not None and pending_approvals == 0:
            pending_approvals = sum(
                item.status == "pending" for item in self.approvals.list_by_run(run_id)
            )
        blocks = [
            tool_capability_block(snapshot),
            sandbox_constraints_block(self.sandbox.capability(run_id)),
            tool_operation_summary_block(
                pending_approvals=pending_approvals,
                recent_operations=recent_operations,
            ),
        ]
        try:
            skill_snapshot = (
                self.skills.snapshot_for_run(run_id)
                if run_id is not None
                else self.skills.snapshot(selected_skill_ids)
            )
        except ValueError:
            skill_snapshot = None
        blocks.append(skill_context_block(skill_snapshot))
        return tuple(blocks)

    def bind_run_skills(self, run_id: str, skill_ids: tuple[str, ...]) -> None:
        """创建 Run 时原子绑定本次选择的 Skill；快照校验失败不写入。"""
        self.skills.bind_run(run_id, skill_ids)

    def _persist_run_snapshots_locked(self) -> None:
        if self.snapshot_path is None:
            return
        _atomic_json(
            self.snapshot_path,
            {
                "snapshots": {
                    run_id: _snapshot_to_json(snapshot)
                    for run_id, snapshot in self._run_snapshots.items()
                }
            },
        )


def _tool_result_projection_error(error_code: str) -> str:
    return json.dumps(
        {
            "status": "error",
            "summary": "工具结果不可用。",
            "content": "",
            "error_code": error_code,
            "artifacts": [],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _snapshot_to_json(snapshot: ToolCatalogSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "created_at": snapshot.created_at,
        "policy_version": snapshot.policy_version,
        "catalog_revision": snapshot.catalog_revision,
        "sandbox_state": snapshot.sandbox_state,
        "run_id": snapshot.run_id,
        "tools": [
            {
                "tool_id": item.tool_id,
                "public_name": item.public_name,
                "source": item.source,
                "description": item.description,
                "input_schema": item.input_schema,
                "server_id": item.server_id,
                "risk": item.risk,
                "version": item.version,
                "exposed": item.exposed,
                "unavailable_reason": item.unavailable_reason,
                "metadata": list(item.metadata),
            }
            for item in snapshot.tools
        ],
    }


def _snapshot_from_json(raw: Any) -> ToolCatalogSnapshot:
    if not isinstance(raw, dict) or not isinstance(raw.get("tools"), list):
        raise ValueError("run tool snapshot is invalid")
    from .models import ToolDescriptor

    tools = tuple(
        ToolDescriptor(
            tool_id=str(item["tool_id"]),
            public_name=str(item["public_name"]),
            source=item["source"],
            description=str(item["description"]),
            input_schema=dict(item["input_schema"]),
            server_id=item.get("server_id"),
            risk=item.get("risk", "safe"),
            version=str(item.get("version", "1")),
            exposed=bool(item.get("exposed", True)),
            unavailable_reason=item.get("unavailable_reason"),
            metadata=tuple(
                (str(key), str(value))
                for key, value in item.get("metadata", ())
            ),
        )
        for item in raw["tools"]
        if isinstance(item, dict)
    )
    return ToolCatalogSnapshot(
        snapshot_id=str(raw["snapshot_id"]),
        created_at=str(raw["created_at"]),
        policy_version=str(raw["policy_version"]),
        catalog_revision=int(raw["catalog_revision"]),
        sandbox_state=str(raw["sandbox_state"]),
        tools=tools,
        run_id=str(raw["run_id"]) if raw.get("run_id") is not None else None,
    )


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name, suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
