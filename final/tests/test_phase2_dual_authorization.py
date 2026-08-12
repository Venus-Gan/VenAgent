"""Phase 2 Sprint 09 planner/executor 双重授权矩阵。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from venagent.application.governance import LocalFixedPrincipalProvider
from venagent.capability import AuthorizedToolInvoker, CapabilityBroker, CapabilityCatalog
from venagent.capability.contracts import (
    CapabilityDescriptor,
    CapabilityErrorCode,
    CapabilityHealthState,
    CapabilityOutcome,
    CapabilityRisk,
    CapabilitySideEffect,
)
from venagent.capability.runtime_models import CapabilityAuthorization, CapabilityRegistration
from venagent.orchestration.manifest import CapabilityReference, LoadedTeamManifest, ParticipantMetadata
from venagent.orchestration.participants import ParticipantCapabilityRequest, ParticipantContextFactory


class _Adapter:
    def __init__(self, descriptor: CapabilityDescriptor) -> None:
        self.descriptor = descriptor
        self.calls = 0

    def execute(self, _parameters: dict[str, object]) -> dict[str, object]:
        self.calls += 1
        return {"ok": True}


def _descriptor(health: CapabilityHealthState) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id="rag.retrieve",
        contract_version="1.0.0",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        output_schema={"type": "object"},
        risk=CapabilityRisk.LOW,
        side_effect=CapabilitySideEffect.NONE,
        durable=False,
        adapter_id="local.rag",
        health=health,
    )


def _catalog(health: CapabilityHealthState) -> tuple[CapabilityCatalog, _Adapter]:
    descriptor = _descriptor(health)
    adapter = _Adapter(descriptor)
    return CapabilityCatalog((CapabilityRegistration(descriptor, adapter, health),)), adapter


def _context(*, executor_health: CapabilityHealthState = CapabilityHealthState.AVAILABLE):
    planner_catalog, _planner_adapter = _catalog(CapabilityHealthState.AVAILABLE)
    executor_catalog, executor_adapter = _catalog(executor_health)
    manifest = LoadedTeamManifest(
        participants=(
            ParticipantMetadata(
                participant_id="research_agent", role="research", variant="default", enabled=True, version="1.0.0",
                capabilities=(CapabilityReference("rag.retrieve", "1.0.0"),),
                memory_scope=("read",), retrieval_scope=("rag",),
            ),
        )
    )
    factory = ParticipantContextFactory(
        manifest=manifest,
        broker=CapabilityBroker(planner_catalog),
        invoker=AuthorizedToolInvoker(executor_catalog),
        principal_provider=LocalFixedPrincipalProvider("tenant-1", "principal-1"),
    )
    return factory.create("research_agent"), executor_adapter


def _authorization() -> CapabilityAuthorization:
    scope = frozenset({"rag.retrieve", "document.write", "sandbox.execute"})
    return CapabilityAuthorization(scope, scope, scope, scope, scope)


def _request(parameters: dict[str, object] | None = None) -> ParticipantCapabilityRequest:
    return ParticipantCapabilityRequest(
        capability_id="rag.retrieve",
        parameters=parameters or {"query": "evidence"},
        run_id=uuid4(),
        idempotency_key="dual-auth-test",
    )


def test_planner_visibility_and_executor_success_use_exact_manifest_reference():
    context, adapter = _context()

    visible = context.list_available(_authorization())
    result = context.invoke(_request(), _authorization())

    assert [(item.capability_id, item.contract_version) for item in visible] == [("rag.retrieve", "1.0.0")]
    assert result.outcome is CapabilityOutcome.SUCCEEDED
    assert adapter.calls == 1


@pytest.mark.parametrize("scope_name", ["intent_scope", "deployment_scope", "user_scope", "approval_scope"])
def test_each_non_participant_scope_hides_planner_and_rejects_executor(scope_name: str):
    context, adapter = _context()
    authorization = replace(_authorization(), **{scope_name: frozenset()})

    visible = context.list_available(authorization)
    result = context.invoke(_request(), authorization)

    assert visible == ()
    assert result.error_code is CapabilityErrorCode.UNAUTHORIZED
    assert adapter.calls == 0


@pytest.mark.parametrize("scope_name", ["intent_scope", "deployment_scope", "user_scope", "approval_scope"])
def test_executor_reauthorizes_when_scope_is_revoked_after_planning(scope_name: str):
    context, adapter = _context()
    planned = context.list_available(_authorization())
    revoked = replace(_authorization(), **{scope_name: frozenset()})

    result = context.invoke(_request(), revoked)

    assert planned
    assert result.error_code is CapabilityErrorCode.UNAUTHORIZED
    assert adapter.calls == 0


def test_executor_rechecks_health_after_planner_saw_available_capability():
    context, adapter = _context(executor_health=CapabilityHealthState.UNAVAILABLE)

    planned = context.list_available(_authorization())
    result = context.invoke(_request(), _authorization())

    assert planned
    assert result.error_code is CapabilityErrorCode.UNAVAILABLE
    assert adapter.calls == 0


def test_schema_rejection_does_not_execute_adapter_or_leak_parameters():
    context, adapter = _context()

    result = context.invoke(_request({"query": 7, "api_key": "sentinel-secret"}), _authorization())

    assert result.error_code is CapabilityErrorCode.INVALID_INPUT
    assert adapter.calls == 0
    assert "sentinel-secret" not in str(result)
