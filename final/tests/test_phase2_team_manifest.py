"""Phase 2 `.team` participant manifest contract tests."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _ROOT / ".team" / "config.json"
_SRC_ROOT = _ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from venagent.orchestration.manifest import ParticipantRole, TeamManifest  # noqa: E402


def _participant(
    *,
    participant_id: str,
    role: str,
    enabled: bool,
    capability_scope: list[str],
    memory_scope: list[str],
    retrieval_scope: list[str],
    **overrides: object,
) -> dict[str, object]:
    value: dict[str, object] = {
        "id": participant_id,
        "name": participant_id.replace("_", " ").title(),
        "role": role,
        "variant": "default",
        "enabled": enabled,
        "version": "1.0.0",
        "prompt_text": f"Act as the {role} participant.",
        "capability_scope": capability_scope,
        "memory_scope": memory_scope,
        "retrieval_scope": retrieval_scope,
    }
    value.update(overrides)
    return value


def _manifest(*, participants: list[dict[str, object]] | None = None, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1.0.0",
        "participants": participants
        or [
            _participant(
                participant_id="research_agent",
                role="research",
                enabled=True,
                capability_scope=["rag.retrieve", "search.query"],
                memory_scope=["read"],
                retrieval_scope=["rag", "search"],
            ),
            _participant(
                participant_id="doc_qa_agent",
                role="doc_qa",
                enabled=True,
                capability_scope=["rag.retrieve", "document.get"],
                memory_scope=["read"],
                retrieval_scope=["rag", "document"],
            ),
            _participant(
                participant_id="synthesis_agent",
                role="synthesis",
                enabled=False,
                capability_scope=[],
                memory_scope=["none"],
                retrieval_scope=["upstream"],
            ),
            _participant(
                participant_id="ops_agent",
                role="ops",
                enabled=False,
                capability_scope=[],
                memory_scope=["none"],
                retrieval_scope=["none"],
            ),
        ],
    }
    value.update(overrides)
    return value


def test_manifest_parses_from_json_as_an_immutable_versioned_contract():
    manifest = TeamManifest.from_json_bytes(json.dumps(_manifest()).encode("utf-8"))

    assert manifest.schema_version == "1.0.0"
    assert manifest.participants[0].role is ParticipantRole.RESEARCH
    assert manifest.model_dump(mode="json", exclude_none=True) == _manifest()

    with pytest.raises((TypeError, ValidationError)):
        manifest.participants += ()  # type: ignore[misc]


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    [
        (lambda value: value.update(schema_version="2.0.0"), "schema_version"),
        (lambda value: value["participants"][0].update(version="v1"), "version"),  # type: ignore[index]
        (lambda value: value["participants"][0].update(id="bad id"), "id"),  # type: ignore[index]
        (lambda value: value["participants"][0].update(role="writer"), "role"),  # type: ignore[index]
        (lambda value: value["participants"][0].update(variant="Bad Variant"), "variant"),  # type: ignore[index]
        (lambda value: value["participants"][0].update(enabled="true"), "enabled"),  # type: ignore[index]
        (lambda value: value["participants"][0].update(capability_scope=["Bad Capability"]), "capability_scope"),  # type: ignore[index]
    ],
)
def test_manifest_rejects_invalid_version_identity_role_variant_and_scope(mutation, expected_path):
    value = _manifest()
    mutation(value)

    with pytest.raises(ValidationError) as error:
        TeamManifest.model_validate(value)

    assert expected_path in str(error.value)


def test_manifest_requires_default_variant_for_each_canonical_role_and_unique_identity():
    missing_ops = _manifest(participants=_manifest()["participants"][:-1])  # type: ignore[index]
    duplicate_id = _manifest()
    duplicate_id["participants"][1]["id"] = "research_agent"  # type: ignore[index]
    duplicate_role_variant = _manifest()
    duplicate_role_variant["participants"][1]["role"] = "research"  # type: ignore[index]

    for value in (missing_ops, duplicate_id, duplicate_role_variant):
        with pytest.raises(ValidationError):
            TeamManifest.model_validate(value)


def test_default_variant_uses_the_stable_canonical_participant_id():
    value = _manifest()
    value["participants"][0]["id"] = "different_research_agent"  # type: ignore[index]

    with pytest.raises(ValidationError):
        TeamManifest.model_validate(value)


def test_non_default_variant_keeps_a_canonical_role_but_does_not_create_runtime_behavior():
    value = _manifest()
    extra = _participant(
        participant_id="research_brief_agent",
        role="research",
        enabled=False,
        capability_scope=[],
        memory_scope=["none"],
        retrieval_scope=["none"],
        variant="brief",
    )
    value["participants"].append(extra)  # type: ignore[index]

    manifest = TeamManifest.model_validate(value)

    assert manifest.participants[-1].variant == "brief"
    assert not callable(getattr(manifest, "build_participant", None))


@pytest.mark.parametrize(
    "prompt_fields",
    [
        {"prompt_text": "", "prompt_ref": None},
        {"prompt_text": "inline", "prompt_ref": "prompts/research.md"},
        {"prompt_text": None, "prompt_ref": None},
        {"prompt_text": None, "prompt_ref": "../outside.md"},
        {"prompt_text": None, "prompt_ref": "https://example.invalid/prompt.md"},
        {"prompt_text": None, "prompt_ref": "${PROMPT_PATH}"},
    ],
)
def test_manifest_requires_exactly_one_safe_prompt_source(prompt_fields):
    value = _manifest()
    participant = value["participants"][0]  # type: ignore[index]
    participant.pop("prompt_text")
    participant.update(prompt_fields)

    with pytest.raises(ValidationError) as error:
        TeamManifest.model_validate(value)

    assert "Act as the research participant" not in str(error.value)


def test_manifest_rejects_obvious_secret_assignment_in_inline_prompt_without_echoing_value():
    value = _manifest()
    value["participants"][0]["prompt_text"] = "Use api_key=sentinel-secret only for this task."  # type: ignore[index]

    with pytest.raises(ValidationError) as error:
        TeamManifest.model_validate(value)

    assert "sentinel-secret" not in str(error.value)


@pytest.mark.parametrize(
    "prohibited_key",
    [
        "api_key",
        "token",
        "password",
        "secret",
        "credential",
        "env_vars",
        "host_path",
        "docker_socket",
        "runner_class",
        "checkpoint",
        "inbox",
        "task",
    ],
)
def test_manifest_rejects_secrets_execution_and_runtime_state_fields(prohibited_key):
    value = _manifest()
    value["participants"][0][prohibited_key] = "sentinel-value"  # type: ignore[index]

    with pytest.raises(ValidationError) as error:
        TeamManifest.model_validate(value)

    assert "sentinel-value" not in str(error.value)


def test_read_only_roles_reject_write_execute_or_unknown_capability_declarations():
    for capability_id in ("memory.write", "document.write", "sandbox.execute", "rag.unregistered"):
        value = _manifest()
        value["participants"][0]["capability_scope"] = [capability_id]  # type: ignore[index]

        with pytest.raises(ValidationError):
            TeamManifest.model_validate(value)


def test_default_manifest_declares_only_canonical_roles_and_read_only_capabilities():
    manifest = TeamManifest.from_json_bytes(_MANIFEST_PATH.read_bytes())
    by_id = {participant.id: participant for participant in manifest.participants}

    assert set(by_id) == {"research_agent", "doc_qa_agent", "synthesis_agent", "ops_agent"}
    assert by_id["research_agent"].enabled
    assert by_id["doc_qa_agent"].enabled
    assert by_id["research_agent"].capability_scope == ("rag.retrieve", "search.query")
    assert by_id["doc_qa_agent"].capability_scope == ("rag.retrieve", "document.get")
    assert not by_id["synthesis_agent"].enabled
    assert not by_id["ops_agent"].enabled
    assert by_id["synthesis_agent"].capability_scope == ()
    assert by_id["ops_agent"].capability_scope == ()


def test_manifest_contract_has_no_legacy_runtime_or_io_dependencies():
    source = (_ROOT / "src" / "venagent" / "orchestration" / "manifest" / "models.py").read_text(encoding="utf-8")

    assert re.search(r"^\\s*(?:from|import)\\s+(?:final|fastapi|langgraph|langchain|mcp|docker|subprocess)(?:\\.|\\s|$)", source, re.MULTILINE) is None
    assert "os.environ" not in source
    assert "Path(" not in source
    assert "open(" not in source
