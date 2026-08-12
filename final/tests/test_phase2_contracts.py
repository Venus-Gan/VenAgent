"""Phase 2 / Sprint 01：Ports 与 Capability Contract 的边界测试。"""

import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from venagent.application.ports import (  # noqa: E402
    ChatCompletionRequest,
    ChatCompletionResult,
    DocumentReadPort,
    DocumentRecord,
    DocumentWritePort,
    DocumentWriteRequest,
    EmbeddingRequest,
    EmbeddingResult,
    LLMPort,
    MemoryReadPort,
    MemoryRecord,
    MemoryWritePort,
    MemoryWriteRequest,
    RAGReadPort,
    RetrievalHit,
    RetrievalRequest,
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxPort,
    SearchHit,
    SearchPort,
    SearchRequest,
)
from venagent.capability.contracts import (  # noqa: E402
    CapabilityAuditSummary,
    CapabilityCall,
    CapabilityDescriptor,
    CapabilityErrorCode,
    CapabilityHealthState,
    CapabilityOutcome,
    CapabilityResult,
    CapabilityRisk,
    CapabilitySideEffect,
    ServerExecutionContext,
)


class _RagFake:
    def retrieve(self, request: RetrievalRequest) -> tuple[RetrievalHit, ...]:
        return ()


class _MemoryFake:
    def recall(self, query: str, *, limit: int) -> tuple[MemoryRecord, ...]:
        return ()

    def remember(self, request: MemoryWriteRequest) -> MemoryRecord:
        return MemoryRecord(memory_id="memory-1", content=request.content)


class _DocumentFake:
    def get_document(self, document_id: str) -> DocumentRecord:
        return DocumentRecord(document_id=document_id, title="test", content="content")

    def write_document(self, request: DocumentWriteRequest) -> DocumentRecord:
        return DocumentRecord(document_id="document-1", title=request.title, content=request.content)


class _SearchFake:
    def search(self, request: SearchRequest) -> tuple[SearchHit, ...]:
        return ()


class _SandboxFake:
    def execute(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
        return SandboxExecutionResult(
            exit_code=0,
            stdout="",
            stderr="",
            backend="docker",
        )


class _LLMFake:
    def complete(self, request: ChatCompletionRequest) -> ChatCompletionResult:
        return ChatCompletionResult(content="answer")

    def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        return EmbeddingResult(vector=(0.1, 0.2))


def test_ports_are_runtime_checkable_and_accept_isolated_fakes():
    memory = _MemoryFake()
    document = _DocumentFake()

    assert isinstance(_RagFake(), RAGReadPort)
    assert isinstance(memory, MemoryReadPort)
    assert isinstance(memory, MemoryWritePort)
    assert isinstance(document, DocumentReadPort)
    assert isinstance(document, DocumentWritePort)
    assert isinstance(_SearchFake(), SearchPort)
    assert isinstance(_SandboxFake(), SandboxPort)
    assert isinstance(_LLMFake(), LLMPort)


def test_port_dtos_validate_requests_and_defensively_freeze_metadata():
    metadata = {"source": "user-input"}
    hit = RetrievalHit(
        document_id="document-1",
        content="content",
        score=0.9,
        metadata=metadata,
    )
    metadata["source"] = "tampered"

    assert hit.metadata["source"] == "user-input"
    with pytest.raises(TypeError):
        hit.metadata["source"] = "mutated"  # type: ignore[index]

    with pytest.raises(ValueError, match="query"):
        RetrievalRequest(query=" ")
    with pytest.raises(ValueError, match="top_k"):
        RetrievalRequest(query="question", top_k=0)
    with pytest.raises(ValueError, match="title"):
        DocumentWriteRequest(title=" ", content="content")
    with pytest.raises(ValueError, match="content"):
        MemoryWriteRequest(content=" ")
    with pytest.raises(ValueError, match="limit"):
        SearchRequest(query="question", limit=0)
    with pytest.raises(ValueError, match="command"):
        SandboxExecutionRequest(command=" ", timeout_ms=10)
    with pytest.raises(ValueError, match="timeout_ms"):
        SandboxExecutionRequest(command="pwd", timeout_ms=0)
    with pytest.raises(ValueError, match="messages"):
        ChatCompletionRequest(messages=())
    with pytest.raises(ValueError, match="text"):
        EmbeddingRequest(text=" ")


def test_descriptor_call_and_result_are_versioned_frozen_and_schema_exportable():
    descriptor = CapabilityDescriptor(
        capability_id="rag.retrieve",
        contract_version="1.0.0",
        input_schema={"type": "object", "required": ["query"]},
        output_schema={"type": "object", "required": ["hits"]},
        risk=CapabilityRisk.LOW,
        side_effect=CapabilitySideEffect.NONE,
        durable=False,
        adapter_id="local.rag",
        health=CapabilityHealthState.AVAILABLE,
    )
    context = ServerExecutionContext(
        tenant_id="tenant-1",
        principal_id="user-1",
        run_id=uuid4(),
    )
    call = CapabilityCall(
        call_id=uuid4(),
        capability_id=descriptor.capability_id,
        contract_version=descriptor.contract_version,
        parameters={"query": "how does RAG work?"},
        context=context,
        idempotency_key="call-rag-retrieve-1",
    )
    result = CapabilityResult.success(
        call_id=call.call_id,
        data={"hits": []},
        audit=CapabilityAuditSummary(parameter_digest="a" * 64),
        adapter_id=descriptor.adapter_id,
    )

    assert result.outcome is CapabilityOutcome.SUCCEEDED
    assert result.error_code is None
    assert UUID(str(call.call_id)) == call.call_id
    assert CapabilityDescriptor.model_json_schema()["properties"]["contract_version"]["type"] == "string"
    assert call.model_dump(mode="json")["parameters"] == {"query": "how does RAG work?"}
    assert result.model_dump(mode="json")["data"] == {"hits": []}

    with pytest.raises(ValidationError):
        descriptor.health = CapabilityHealthState.UNAVAILABLE  # type: ignore[misc]


@pytest.mark.parametrize(
    ("payload", "expected_field"),
    [
        ({"capability_id": "RAG Retrieve"}, "capability_id"),
        ({"contract_version": "v1"}, "contract_version"),
        ({"api_key": "never-allowed"}, "api_key"),
    ],
)
def test_descriptor_rejects_invalid_identity_version_and_unknown_sensitive_fields(payload, expected_field):
    valid = {
        "capability_id": "rag.retrieve",
        "contract_version": "1.0.0",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "risk": "low",
        "side_effect": "none",
        "durable": False,
        "adapter_id": "local.rag",
        "health": "available",
    }

    with pytest.raises(ValidationError) as error:
        CapabilityDescriptor(**(valid | payload))

    assert expected_field in str(error.value)
    assert "never-allowed" not in str(error.value)


def test_failed_result_requires_stable_error_code_and_never_accepts_raw_exception_text():
    call_id = uuid4()

    with pytest.raises(ValidationError):
        CapabilityResult(
            call_id=call_id,
            outcome=CapabilityOutcome.FAILED,
            data={},
            retryable=False,
            audit=CapabilityAuditSummary(parameter_digest="b" * 64),
            adapter_id="local.sandbox",
        )

    with pytest.raises(ValidationError) as error:
        CapabilityResult(
            call_id=call_id,
            outcome=CapabilityOutcome.FAILED,
            error_code=CapabilityErrorCode.UNAVAILABLE,
            data={},
            retryable=False,
            audit=CapabilityAuditSummary(parameter_digest="b" * 64),
            adapter_id="local.sandbox",
            raw_exception="password=sentinel-secret host=db.internal",
        )

    assert "sentinel-secret" not in str(error.value)


def test_unavailable_sandbox_result_is_explicit_and_does_not_claim_execution_success():
    result = CapabilityResult.failure(
        call_id=uuid4(),
        error_code=CapabilityErrorCode.UNAVAILABLE,
        retryable=False,
        audit=CapabilityAuditSummary(parameter_digest="c" * 64),
        adapter_id="local.sandbox",
    )

    assert result.outcome is CapabilityOutcome.FAILED
    assert result.error_code is CapabilityErrorCode.UNAVAILABLE
    assert result.data == {}
