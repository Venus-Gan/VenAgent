"""Operation 与 Approval 的 JSON 原子持久化测试。"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from venagent.sandbox.docker import DockerSandboxRuntime
from venagent.skills.catalog import SkillCatalog
from venagent.tools.approval import ApprovalService
from venagent.tools.artifact_store import FileArtifactStore
from venagent.tools.catalog import ToolCatalog
from venagent.tools.control import ToolControlContext
from venagent.tools.gateway import ToolGateway
from venagent.tools.models import Operation, ToolDescriptor, ToolResult
from venagent.tools.operation_store import OperationStore
from venagent.tools.policy import ToolExposurePolicy
from venagent.tools.state_directory import StateDirectoryLease


def test_operation_store_round_trips_through_json(tmp_path: Path) -> None:
    path = tmp_path / "operations.json"
    now = datetime.now(timezone.utc)
    first = OperationStore(path=path)
    operation = Operation(
        operation_id="op-1",
        run_id="run-1",
        owner_id="owner-1",
        tool_call_id="call-1",
        operation_key="key-1",
        tool_id="exec_command",
        status="succeeded",
        risk="safe",
        created_at=now,
        updated_at=now,
        result_summary="done",
    )
    first.save(operation)
    first.save_result(
        "op-1",
        ToolResult(
            tool_call_id="call-1",
            operation_id="op-1",
            status="success",
            summary="done",
            content="ok",
            timing_ms=12,
        ),
    )

    second = OperationStore(path=path)
    loaded = second.get("op-1")
    assert loaded.run_id == "run-1"
    assert loaded.status == "succeeded"
    assert second.get_result("op-1").content == "ok"


def test_approval_service_round_trips_decisions(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    now = datetime.now(timezone.utc)
    first = ApprovalService(path=path)
    item = first.create(
        run_id="run-1",
        owner_id="owner-1",
        operation_id="op-1",
        tool_id="exec_command",
        tool_call_id="call-1",
        reason="test",
        now=now,
    )
    first.decide(item.approval_id, "owner-1", True, now=now)

    second = ApprovalService(path=path)
    loaded = second.get(item.approval_id)
    assert loaded.status == "approved"
    assert loaded.decided_at is not None


def test_artifact_store_round_trips_full_output(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "artifacts")
    content = "x" * 5000
    ref = store.save_text("tool:exec_command", content)
    assert ref.size_bytes == len(content)
    assert store.load(ref.artifact_id) == content.encode("utf-8")


def test_gateway_stores_full_output_and_returns_bounded_summary(
    tmp_path: Path,
) -> None:
    artifact_store = FileArtifactStore(tmp_path / "artifacts")

    async def executor(
        _descriptor: ToolDescriptor, _arguments: dict[str, object]
    ) -> ToolResult:
        return ToolResult(
            tool_call_id="",
            operation_id="",
            status="success",
            summary="done",
            content="y" * 5000,
        )

    async def scenario() -> None:
        policy = ToolExposurePolicy(
            policy_version="test",
            allowed_tool_ids=("exec_command",),
            risk_overrides=(("exec_command", "safe"),),
        )
        catalog = ToolCatalog(policy)
        catalog.register(
            ToolDescriptor(
                tool_id="exec_command",
                public_name="exec_command",
                source="native",
                description="exec",
                input_schema={"type": "object", "properties": {}},
                risk="safe",
            )
        )
        snapshot = catalog.build_snapshot(sandbox_ready=True)
        operations = OperationStore()
        approvals = ApprovalService()
        gateway = ToolGateway(
            operations=operations,
            approvals=approvals,
            executor=executor,
            artifact_store=artifact_store,
        )
        result = await gateway.invoke(
            snapshot=snapshot,
            run_id="run-artifact",
            owner_id="owner-1",
            tool_call_id="call-artifact",
            operation_key="key-artifact",
            tool_id="exec_command",
            arguments={},
            sandbox_ready=True,
        )
        assert len(result.content) < 5000
        assert len(result.artifacts) == 1
        loaded = artifact_store.load(result.artifacts[0].artifact_id)
        assert loaded == b"y" * 5000

    asyncio.run(scenario())


def test_durable_state_directory_rejects_second_process(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    lease = StateDirectoryLease(state_dir)
    lease.acquire()
    code = """
import sys
from pathlib import Path
from venagent.tools.state_directory import StateDirectoryInUse, StateDirectoryLease
lease = StateDirectoryLease(Path(sys.argv[1]))
try:
    lease.acquire()
except StateDirectoryInUse:
    raise SystemExit(23)
lease.release()
"""
    try:
        blocked = subprocess.run(
            [sys.executable, "-c", code, str(state_dir)],
            cwd=Path(__file__).parents[1],
            check=False,
            capture_output=True,
            timeout=10,
        )
        assert blocked.returncode == 23
    finally:
        lease.release()
    available = subprocess.run(
        [sys.executable, "-c", code, str(state_dir)],
        cwd=Path(__file__).parents[1],
        check=False,
        capture_output=True,
        timeout=10,
    )
    assert available.returncode == 0


def test_run_tool_snapshot_round_trips_across_control_restart(
    tmp_path: Path,
) -> None:
    policy = ToolExposurePolicy(
        policy_version="snapshot-v1",
        allowed_tool_ids=("exec_command",),
        risk_overrides=(("exec_command", "safe"),),
    )

    def control(catalog: ToolCatalog) -> ToolControlContext:
        operations = OperationStore()
        approvals = ApprovalService()
        return ToolControlContext(
            catalog=catalog,
            sandbox=DockerSandboxRuntime(
                probe=lambda: True, image_probe=lambda: True
            ),
            skills=SkillCatalog(),
            gateway=ToolGateway(
                operations=operations,
                approvals=approvals,
            ),
            approvals=approvals,
            operations=operations,
            snapshot_path=tmp_path / "run-tool-snapshots.json",
        )

    first_catalog = ToolCatalog(policy)
    first_catalog.register(
        ToolDescriptor(
            tool_id="exec_command",
            public_name="exec_command",
            source="native",
            description="original descriptor",
            input_schema={"type": "object", "properties": {}},
            risk="safe",
        )
    )

    async def scenario() -> None:
        first = control(first_catalog)
        original = await first.start_run("run-restart")

        changed_catalog = ToolCatalog(policy)
        changed_catalog.register(
            ToolDescriptor(
                tool_id="exec_command",
                public_name="exec_command",
                source="native",
                description="changed descriptor",
                input_schema={"type": "object", "properties": {}},
                risk="safe",
            )
        )
        restarted = control(changed_catalog)
        restored = await restarted.start_run("run-restart")
        assert restored.snapshot_id == original.snapshot_id
        assert restored.tools == original.tools
        assert restored.by_id("exec_command").description == "original descriptor"
        await restarted.stop_run("run-restart")
        final = control(changed_catalog)
        replacement = await final.start_run("run-restart")
        assert replacement.snapshot_id != original.snapshot_id
        assert replacement.by_id("exec_command").description == "changed descriptor"

    asyncio.run(scenario())
