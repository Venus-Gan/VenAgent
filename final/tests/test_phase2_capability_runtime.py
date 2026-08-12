"""Phase 2 Sprint 02 的 capability runtime 契约测试。"""

from dataclasses import replace
from pathlib import Path
import re
import sys
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from venagent.adapters.local import (
    LocalDocumentGetAdapter,
    LocalDocumentWriteAdapter,
    LocalLLMCompleteAdapter,
    LocalLLMEmbedAdapter,
    LocalMemoryRecallAdapter,
    LocalMemoryRememberAdapter,
    LocalRAGRetrieveAdapter,
    LocalSearchAdapter,
    UnavailableSandboxAdapter,
)
from venagent.application.ports import (
    ChatCompletionResult,
    DocumentRecord,
    EmbeddingResult,
    MemoryRecord,
    RetrievalHit,
    RetrievalRequest,
    SearchHit,
)
from venagent.capability.broker import CapabilityBroker
from venagent.capability.catalog import CapabilityCatalog
from venagent.capability.contracts import (
    CapabilityCall,
    CapabilityDescriptor,
    CapabilityErrorCode,
    CapabilityHealthState,
    CapabilityOutcome,
    CapabilityRisk,
    CapabilitySideEffect,
    ServerExecutionContext,
)
from venagent.capability.invoker import AuthorizedToolInvoker
from venagent.capability.runtime_models import CapabilityAuthorization, CapabilityRegistration
from venagent.capability.validation import ParameterValidationError, validate_parameters


class _RagFake:
    def retrieve(self, request: RetrievalRequest) -> tuple[RetrievalHit, ...]:
        return (
            RetrievalHit(
                document_id="document-1",
                content=f"evidence for {request.query}",
                score=0.9,
                source="fake",
            ),
        )


class _FailingAdapter:
    def __init__(self, descriptor: CapabilityDescriptor) -> None:
        self.descriptor = descriptor

    def execute(self, parameters: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("password=sentinel-secret host=internal.example")


class _MemoryFake:
    def recall(self, query: str, *, limit: int) -> tuple[MemoryRecord, ...]:
        return (MemoryRecord(memory_id="memory-1", content=f"memory for {query}"),)[:limit]

    def remember(self, request):
        return MemoryRecord(memory_id="memory-2", content=request.content, metadata=request.metadata)


class _DocumentFake:
    def get_document(self, document_id: str) -> DocumentRecord:
        return DocumentRecord(document_id=document_id, title="title", content="content")

    def write_document(self, request):
        return DocumentRecord(
            document_id=request.document_id or "document-2",
            title=request.title,
            content=request.content,
            metadata=request.metadata,
        )


class _SearchFake:
    def search(self, request) -> tuple[SearchHit, ...]:
        return (SearchHit(title=request.query, url="https://example.invalid", snippet="snippet"),)[: request.limit]


class _LLMFake:
    def complete(self, request) -> ChatCompletionResult:
        return ChatCompletionResult(content=request.messages[-1].content)

    def embed(self, request) -> EmbeddingResult:
        return EmbeddingResult(vector=(float(len(request.text)),))


def _descriptor(
    *,
    capability_id: str = "rag.retrieve",
    adapter_id: str = "local.rag",
    health: CapabilityHealthState = CapabilityHealthState.AVAILABLE,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        contract_version="1.0.0",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        risk=CapabilityRisk.LOW,
        side_effect=CapabilitySideEffect.NONE,
        durable=False,
        adapter_id=adapter_id,
        health=health,
    )


def _authorization(*, allowed: bool = True) -> CapabilityAuthorization:
    capability_scope = frozenset({"rag.retrieve"}) if allowed else frozenset()
    return CapabilityAuthorization(
        intent_scope=capability_scope,
        participant_scope=capability_scope,
        deployment_scope=capability_scope,
        user_scope=capability_scope,
        approval_scope=capability_scope,
    )


def _call(*, parameters: dict[str, object] | None = None) -> CapabilityCall:
    return CapabilityCall(
        call_id=uuid4(),
        capability_id="rag.retrieve",
        contract_version="1.0.0",
        parameters=parameters or {"query": "what is RAG?", "top_k": 2},
        context=ServerExecutionContext(
            tenant_id="tenant-1",
            principal_id="user-1",
            run_id=uuid4(),
        ),
        idempotency_key="phase2-runtime-test",
    )


def _catalog(*, health: CapabilityHealthState = CapabilityHealthState.AVAILABLE) -> CapabilityCatalog:
    descriptor = _descriptor()
    adapter = LocalRAGRetrieveAdapter(descriptor=descriptor, port=_RagFake())
    registration = CapabilityRegistration(descriptor=descriptor, adapter=adapter, health=health)
    return CapabilityCatalog((registration,))


def test_injected_local_rag_adapter_maps_port_dto_without_legacy_dependency():
    descriptor = _descriptor()
    adapter = LocalRAGRetrieveAdapter(descriptor=descriptor, port=_RagFake())

    result = adapter.execute({"query": "architecture", "top_k": 1})

    assert result["hits"] == [
        {
            "document_id": "document-1",
            "content": "evidence for architecture",
            "score": 0.9,
            "source": "fake",
            "metadata": {},
        }
    ]

    forbidden_import = re.compile(r"^\s*(?:from|import)\s+final(?:\.|\s|$)", re.MULTILINE)
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "venagent").rglob("*.py"))
    assert forbidden_import.search(source) is None


def test_unavailable_sandbox_adapter_does_not_execute_or_claim_success():
    descriptor = _descriptor(capability_id="sandbox.execute", adapter_id="local.sandbox")
    adapter = UnavailableSandboxAdapter(descriptor=descriptor)

    with pytest.raises(RuntimeError, match="unavailable"):
        adapter.execute({"command": "id", "timeout_ms": 10})


def test_other_injected_local_adapters_map_their_ports_to_serializable_data():
    memory_descriptor = _descriptor(capability_id="memory.recall", adapter_id="local.memory")
    document_descriptor = _descriptor(capability_id="document.get", adapter_id="local.document")
    search_descriptor = _descriptor(capability_id="search.query", adapter_id="local.search")
    llm_descriptor = _descriptor(capability_id="llm.complete", adapter_id="local.llm")
    memory = _MemoryFake()
    document = _DocumentFake()
    llm = _LLMFake()

    assert LocalMemoryRecallAdapter(memory_descriptor, memory).execute({"query": "policy", "limit": 1}) == {
        "records": [{"memory_id": "memory-1", "content": "memory for policy", "metadata": {}}]
    }
    assert LocalMemoryRememberAdapter(memory_descriptor, memory).execute(
        {"content": "remember", "category": "fact", "metadata": {"source": "test"}}
    ) == {"memory_id": "memory-2", "content": "remember", "metadata": {"source": "test"}}
    assert LocalDocumentGetAdapter(document_descriptor, document).execute({"document_id": "document-1"})["title"] == "title"
    assert LocalDocumentWriteAdapter(document_descriptor, document).execute(
        {"title": "new", "content": "body", "metadata": {"kind": "note"}}
    )["document_id"] == "document-2"
    assert LocalSearchAdapter(search_descriptor, _SearchFake()).execute({"query": "search", "limit": 1})["hits"][0]["title"] == "search"
    assert LocalLLMCompleteAdapter(llm_descriptor, llm).execute(
        {"messages": [{"role": "user", "content": "hello"}]}
    ) == {"content": "hello"}
    assert LocalLLMEmbedAdapter(llm_descriptor, llm).execute({"text": "abc"}) == {"vector": [3.0]}


def test_local_adapter_and_schema_validation_reject_invalid_parameter_shapes():
    descriptor = _descriptor(capability_id="memory.write", adapter_id="local.memory")

    with pytest.raises(ValueError, match="metadata"):
        LocalMemoryRememberAdapter(descriptor, _MemoryFake()).execute({"content": "memory", "metadata": ["bad"]})
    with pytest.raises(ParameterValidationError):
        validate_parameters({}, {"type": "object", "required": ["query"]})
    with pytest.raises(ParameterValidationError):
        validate_parameters({"query": "ok"}, {"type": "array"})
    with pytest.raises(ParameterValidationError):
        validate_parameters({"query": "ok"}, {"type": "object", "properties": []})
    with pytest.raises(ParameterValidationError):
        validate_parameters({"query": "ok"}, {"type": "object", "properties": {"query": {"type": "date"}}})


def test_catalog_rejects_duplicate_and_mismatched_adapter_registration():
    descriptor = _descriptor()
    registration = CapabilityRegistration(
        descriptor=descriptor,
        adapter=LocalRAGRetrieveAdapter(descriptor=descriptor, port=_RagFake()),
        health=CapabilityHealthState.AVAILABLE,
    )

    with pytest.raises(ValueError, match="duplicate"):
        CapabilityCatalog((registration, registration))

    mismatched_adapter = _FailingAdapter(_descriptor(adapter_id="local.other"))
    with pytest.raises(ValueError, match="adapter"):
        CapabilityRegistration(
            descriptor=descriptor,
            adapter=mismatched_adapter,
            health=CapabilityHealthState.AVAILABLE,
        )


def test_broker_hides_unavailable_or_unapproved_capabilities():
    catalog = _catalog()
    broker = CapabilityBroker(catalog)

    assert [item.capability_id for item in broker.list_available(_authorization())] == ["rag.retrieve"]
    assert broker.list_available(replace(_authorization(), approval_scope=frozenset())) == ()

    unavailable_catalog = _catalog(health=CapabilityHealthState.UNAVAILABLE)
    assert CapabilityBroker(unavailable_catalog).list_available(_authorization()) == ()


def test_invoker_reauthorizes_when_execution_scope_or_health_changes():
    planner_catalog = _catalog()
    assert CapabilityBroker(planner_catalog).list_available(_authorization())

    invoker = AuthorizedToolInvoker(_catalog(health=CapabilityHealthState.UNAVAILABLE))
    result = invoker.invoke(_call(), _authorization())

    assert result.outcome is CapabilityOutcome.FAILED
    assert result.error_code is CapabilityErrorCode.UNAVAILABLE

    denied_result = AuthorizedToolInvoker(planner_catalog).invoke(_call(), _authorization(allowed=False))
    assert denied_result.error_code is CapabilityErrorCode.UNAUTHORIZED


def test_invoker_rejects_unknown_and_schema_invalid_calls_without_echoing_sensitive_input():
    invoker = AuthorizedToolInvoker(_catalog())
    invalid_result = invoker.invoke(_call(parameters={"query": 7, "api_key": "sentinel-secret"}), _authorization())
    unknown_call = _call()
    unknown_call = unknown_call.model_copy(update={"capability_id": "rag.unknown"})
    unknown_result = invoker.invoke(unknown_call, _authorization())

    assert invalid_result.error_code is CapabilityErrorCode.INVALID_INPUT
    assert "sentinel-secret" not in str(invalid_result)
    assert unknown_result.error_code is CapabilityErrorCode.UNAUTHORIZED


def test_invoker_maps_adapter_exceptions_to_safe_result_with_audit_summary():
    descriptor = _descriptor()
    catalog = CapabilityCatalog(
        (
            CapabilityRegistration(
                descriptor=descriptor,
                adapter=_FailingAdapter(descriptor),
                health=CapabilityHealthState.AVAILABLE,
            ),
        )
    )

    result = AuthorizedToolInvoker(catalog).invoke(_call(), _authorization())

    assert result.error_code is CapabilityErrorCode.ADAPTER_ERROR
    assert result.audit.decision_id is not None
    assert len(result.audit.parameter_digest) == 64
    assert "sentinel-secret" not in str(result)


def test_successful_invocation_preserves_call_identity_and_safe_audit_data():
    call = _call()

    result = AuthorizedToolInvoker(_catalog()).invoke(call, _authorization())

    assert result.outcome is CapabilityOutcome.SUCCEEDED
    assert result.call_id == call.call_id
    assert result.adapter_id == "local.rag"
    assert result.audit.decision_id is not None
