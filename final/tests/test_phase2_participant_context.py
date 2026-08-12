"""Phase 2 Sprint 08 的受限 participant context 测试。"""

from __future__ import annotations

from pathlib import Path
import re
import sys
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from venagent.application.governance import LocalFixedPrincipalProvider
from venagent.capability import AuthorizedToolInvoker, CapabilityBroker, CapabilityCatalog
from venagent.capability.contracts import (
    CapabilityDescriptor,
    CapabilityHealthState,
    CapabilityOutcome,
    CapabilityRisk,
    CapabilitySideEffect,
)
from venagent.capability.runtime_models import CapabilityAuthorization, CapabilityRegistration
from venagent.orchestration.manifest import CapabilityReference, LoadedTeamManifest, ParticipantMetadata
from venagent.orchestration.participants import (
    ParticipantCapabilityRequest,
    ParticipantContextError,
    ParticipantContextFactory,
)


class _Adapter:
    def __init__(self, descriptor: CapabilityDescriptor) -> None:
        self.descriptor = descriptor
        self.calls: list[dict[str, object]] = []

    def execute(self, parameters: dict[str, object]) -> dict[str, object]:
        self.calls.append(dict(parameters))
        return {"capability": self.descriptor.capability_id}


class _CapturingInvoker(AuthorizedToolInvoker):
    def __init__(self, catalog: CapabilityCatalog) -> None:
        super().__init__(catalog)
        self.calls = []

    def invoke(self, call, authorization):
        self.calls.append((call, authorization))
        return super().invoke(call, authorization)


def _descriptor(capability_id: str, version: str = "1.0.0") -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        contract_version=version,
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        output_schema={"type": "object"},
        risk=CapabilityRisk.LOW,
        side_effect=CapabilitySideEffect.NONE,
        durable=False,
        adapter_id=f"local.{capability_id}",
        health=CapabilityHealthState.AVAILABLE,
    )


def _runtime() -> tuple[ParticipantContextFactory, _CapturingInvoker, dict[str, _Adapter]]:
    descriptors = (
        _descriptor("rag.retrieve"),
        _descriptor("search.query"),
        _descriptor("document.write"),
        _descriptor("rag.retrieve", "2.0.0"),
    )
    adapters = {f"{item.capability_id}:{item.contract_version}": _Adapter(item) for item in descriptors}
    catalog = CapabilityCatalog(
        tuple(
            CapabilityRegistration(
                descriptor=item,
                adapter=adapters[f"{item.capability_id}:{item.contract_version}"],
                health=CapabilityHealthState.AVAILABLE,
            )
            for item in descriptors
        )
    )
    manifest = LoadedTeamManifest(
        participants=(
            ParticipantMetadata(
                participant_id="research_agent",
                role="research",
                variant="default",
                enabled=True,
                version="1.0.0",
                capabilities=(
                    CapabilityReference("rag.retrieve", "1.0.0"),
                    CapabilityReference("search.query", "1.0.0"),
                ),
                memory_scope=("read",),
                retrieval_scope=("rag", "search"),
            ),
            ParticipantMetadata(
                participant_id="ops_agent",
                role="ops",
                variant="default",
                enabled=False,
                version="1.0.0",
                capabilities=(),
                memory_scope=("none",),
                retrieval_scope=("none",),
            ),
        )
    )
    invoker = _CapturingInvoker(catalog)
    return (
        ParticipantContextFactory(
            manifest=manifest,
            broker=CapabilityBroker(catalog),
            invoker=invoker,
            principal_provider=LocalFixedPrincipalProvider("tenant-trusted", "principal-trusted"),
        ),
        invoker,
        adapters,
    )


def _authorization(*, include_all: bool = True) -> CapabilityAuthorization:
    scopes = frozenset({"rag.retrieve", "search.query", "document.write"}) if include_all else frozenset()
    return CapabilityAuthorization(
        intent_scope=scopes,
        participant_scope=scopes,
        deployment_scope=scopes,
        user_scope=scopes,
        approval_scope=scopes,
    )


def test_enabled_context_exposes_only_safe_metadata_and_exact_planner_descriptors():
    factory, _invoker, _adapters = _runtime()

    context = factory.create("research_agent")
    descriptors = context.list_available(_authorization())

    assert context.metadata.participant_id == "research_agent"
    assert [(item.capability_id, item.contract_version) for item in descriptors] == [
        ("rag.retrieve", "1.0.0"),
        ("search.query", "1.0.0"),
    ]
    assert not any(name in dir(context) for name in ("agent", "repo", "catalog", "broker", "invoker", "adapter", "prompt"))
    assert not any(name in dir(factory) for name in ("broker", "invoker", "principal_provider"))


def test_context_overwrites_spoofed_participant_scope_for_planner_and_executor():
    factory, invoker, adapters = _runtime()
    context = factory.create("research_agent")
    request = ParticipantCapabilityRequest(
        capability_id="rag.retrieve",
        parameters={"query": "evidence"},
        run_id=uuid4(),
        idempotency_key="context-call-1",
    )

    result = context.invoke(request, _authorization())

    call, authorization = invoker.calls[-1]
    assert result.outcome is CapabilityOutcome.SUCCEEDED
    assert authorization.participant_scope == frozenset({"rag.retrieve", "search.query"})
    assert call.contract_version == "1.0.0"
    assert call.context.tenant_id == "tenant-trusted"
    assert call.context.principal_id == "principal-trusted"
    assert call.context.run_id == request.run_id
    assert adapters["rag.retrieve:1.0.0"].calls == [{"query": "evidence"}]
    assert not adapters["rag.retrieve:2.0.0"].calls


def test_undeclared_capability_is_rejected_before_invoker_or_adapter_receives_parameters():
    factory, invoker, adapters = _runtime()
    context = factory.create("research_agent")
    request = ParticipantCapabilityRequest(
        capability_id="document.write",
        parameters={"query": "api_key=sentinel-secret"},
        run_id=uuid4(),
        idempotency_key="context-call-2",
    )

    with pytest.raises(ParticipantContextError) as error_info:
        context.invoke(request, _authorization())

    assert error_info.value.code == "capability_not_declared"
    assert "sentinel-secret" not in str(error_info.value)
    assert invoker.calls == []
    assert not any(adapter.calls for adapter in adapters.values())


def test_request_repr_hides_parameters_from_accidental_diagnostics():
    request = ParticipantCapabilityRequest(
        capability_id="rag.retrieve",
        parameters={"api_key": "sentinel-secret"},
        run_id=uuid4(),
        idempotency_key="context-call-redacted",
    )

    assert "sentinel-secret" not in repr(request)


@pytest.mark.parametrize("participant_id", ["ops_agent", "missing_agent"])
def test_disabled_or_unknown_participant_never_creates_a_context(participant_id: str):
    factory, invoker, adapters = _runtime()

    with pytest.raises(ParticipantContextError) as error_info:
        factory.create(participant_id)

    assert error_info.value.code in {"participant_disabled", "participant_unknown"}
    assert invoker.calls == []
    assert not any(adapter.calls for adapter in adapters.values())


def test_existing_authorization_and_schema_denials_remain_in_effect():
    factory, invoker, adapters = _runtime()
    context = factory.create("research_agent")
    request = ParticipantCapabilityRequest(
        capability_id="rag.retrieve",
        parameters={"query": 7},
        run_id=uuid4(),
        idempotency_key="context-call-3",
    )

    denied = context.invoke(request, _authorization(include_all=False))
    invalid = context.invoke(request, _authorization())

    assert denied.outcome is CapabilityOutcome.FAILED
    assert invalid.outcome is CapabilityOutcome.FAILED
    assert len(invoker.calls) == 2
    assert not any(adapter.calls for adapter in adapters.values())


@pytest.mark.parametrize(
    "request_data",
    [
        {"capability_id": "rag.retrieve", "parameters": [], "run_id": uuid4(), "idempotency_key": "valid"},
        {"capability_id": "rag.retrieve", "parameters": {}, "run_id": "not-a-uuid", "idempotency_key": "valid"},
        {"capability_id": "rag.retrieve", "parameters": {}, "run_id": uuid4(), "idempotency_key": ""},
    ],
)
def test_request_contract_rejects_invalid_parameters_identity_or_idempotency_key(request_data: dict[str, object]):
    with pytest.raises(ValidationError):
        ParticipantCapabilityRequest.model_validate(request_data)


def test_context_source_has_no_legacy_framework_io_or_runtime_dependencies():
    source = (ROOT / "src" / "venagent" / "orchestration" / "participants" / "context.py").read_text(encoding="utf-8")

    assert re.search(
        r"^\s*(?:from|import)\s+(?:final|fastapi|langgraph|langchain|mcp|docker|requests|httpx|subprocess)(?:\.|\s|$)",
        source,
        re.MULTILINE,
    ) is None
    assert "os.environ" not in source
    assert "Path(" not in source
    assert "open(" not in source
