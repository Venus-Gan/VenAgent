"""Phase 2 Sprint 07 的 `.team` manifest 受控加载测试。"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from venagent.bootstrap import (  # noqa: E402
    BootstrapError,
    BootstrapStage,
    DependencyContainer,
    StagedBootstrapper,
)
from venagent.capability.catalog import CapabilityCatalog  # noqa: E402
from venagent.capability.contracts import (  # noqa: E402
    CapabilityDescriptor,
    CapabilityHealthState,
    CapabilityRisk,
    CapabilitySideEffect,
)
from venagent.capability.runtime_models import CapabilityRegistration  # noqa: E402
from venagent.infrastructure.config import AppConfig  # noqa: E402
from venagent.orchestration.manifest import (  # noqa: E402
    TeamManifestLoadError,
    TeamManifestLoader,
)


class _Adapter:
    def __init__(self, descriptor: CapabilityDescriptor) -> None:
        self.descriptor = descriptor

    def execute(self, _parameters: object) -> dict[str, object]:
        raise AssertionError("manifest loading must not execute an adapter")


def _descriptor(capability_id: str, version: str = "1.0.0") -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        contract_version=version,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        risk=CapabilityRisk.LOW,
        side_effect=CapabilitySideEffect.NONE,
        durable=False,
        adapter_id=f"local.{capability_id}",
        health=CapabilityHealthState.AVAILABLE,
    )


def _catalog(*identities: tuple[str, str]) -> CapabilityCatalog:
    registrations = []
    for capability_id, version in identities:
        descriptor = _descriptor(capability_id, version)
        registrations.append(
            CapabilityRegistration(
                descriptor=descriptor,
                adapter=_Adapter(descriptor),
                health=CapabilityHealthState.AVAILABLE,
            )
        )
    return CapabilityCatalog(tuple(registrations))


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "participants": [
            {
                "id": "research_agent",
                "name": "Research Agent",
                "role": "research",
                "variant": "default",
                "enabled": True,
                "version": "1.0.0",
                "prompt_text": "Collect evidence with read-only retrieval.",
                "capability_scope": ["rag.retrieve", "search.query"],
                "memory_scope": ["read"],
                "retrieval_scope": ["rag", "search"],
            },
            {
                "id": "doc_qa_agent",
                "name": "Document QA Agent",
                "role": "doc_qa",
                "variant": "default",
                "enabled": True,
                "version": "1.0.0",
                "prompt_text": "Answer document questions with evidence.",
                "capability_scope": ["rag.retrieve", "document.get"],
                "memory_scope": ["read"],
                "retrieval_scope": ["rag", "document"],
            },
            {
                "id": "synthesis_agent",
                "name": "Synthesis Agent",
                "role": "synthesis",
                "variant": "default",
                "enabled": False,
                "version": "1.0.0",
                "prompt_text": "Remain declarative.",
                "capability_scope": [],
                "memory_scope": ["none"],
                "retrieval_scope": ["upstream"],
            },
            {
                "id": "ops_agent",
                "name": "Operations Agent",
                "role": "ops",
                "variant": "default",
                "enabled": False,
                "version": "1.0.0",
                "prompt_text": "Remain disabled.",
                "capability_scope": [],
                "memory_scope": ["none"],
                "retrieval_scope": ["none"],
            },
        ],
    }


def _write_manifest(root: Path, content: bytes | None = None) -> Path:
    manifest_path = root / ".team" / "config.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(content or json.dumps(_manifest()).encode("utf-8"))
    return manifest_path


def _complete_catalog() -> CapabilityCatalog:
    return _catalog(
        ("rag.retrieve", "1.0.0"),
        ("search.query", "1.0.0"),
        ("document.get", "1.0.0"),
    )


def test_loader_returns_immutable_metadata_without_prompt_path_or_runtime_objects(tmp_path: Path):
    _write_manifest(tmp_path)

    loaded = TeamManifestLoader(tmp_path, _complete_catalog()).load()

    research = loaded.require_participant("research_agent")
    assert research.capabilities[0].capability_id == "rag.retrieve"
    assert research.capabilities[0].contract_version == "1.0.0"
    assert research.role == "research"
    assert "prompt" not in repr(loaded).lower()
    assert "path" not in repr(loaded).lower()
    assert not hasattr(research, "adapter")
    with pytest.raises((AttributeError, TypeError)):
        research.capabilities += ()  # type: ignore[misc]


@pytest.mark.parametrize(
    ("content", "setup", "expected_code"),
    [
        (None, None, "manifest_missing"),
        (None, lambda root: (root / ".team" / "config.json").mkdir(parents=True), "manifest_not_file"),
        (b"\xff\xfe", None, "manifest_invalid_encoding"),
        (b"{", None, "manifest_invalid_json"),
        (b"x" * (64 * 1024 + 1), None, "manifest_too_large"),
        (json.dumps({"schema_version": "2.0.0", "participants": []}).encode("utf-8"), None, "manifest_invalid_schema"),
    ],
    ids=["missing", "directory", "invalid-utf8", "invalid-json", "too-large", "invalid-schema"],
)
def test_loader_fails_closed_for_missing_invalid_or_oversized_files(
    tmp_path: Path,
    content: bytes | None,
    setup,
    expected_code: str,
):
    if setup is not None:
        setup(tmp_path)
    elif content is not None:
        _write_manifest(tmp_path, content)

    with pytest.raises(TeamManifestLoadError) as error_info:
        TeamManifestLoader(tmp_path, _complete_catalog()).load()

    assert error_info.value.code == expected_code
    assert str(tmp_path) not in str(error_info.value)
    assert "participants" not in str(error_info.value)


def test_loader_rejects_non_directory_root_without_disclosing_input_path(tmp_path: Path):
    root_file = tmp_path / "not-a-directory"
    root_file.write_text("x", encoding="utf-8")

    with pytest.raises(TeamManifestLoadError) as error_info:
        TeamManifestLoader(root_file, _complete_catalog()).load()

    assert error_info.value.code == "invalid_repository_root"
    assert str(root_file) not in str(error_info.value)


def test_loader_rejects_a_resolved_manifest_path_outside_the_repository_root(tmp_path: Path):
    root = tmp_path / "repository"
    root.mkdir()
    outside_manifest = tmp_path / "outside.json"
    outside_manifest.write_text("{}", encoding="utf-8")

    with pytest.raises(TeamManifestLoadError) as error_info:
        TeamManifestLoader._read_manifest_bytes(root.resolve(), outside_manifest)

    assert error_info.value.code == "manifest_path_escape"
    assert str(outside_manifest) not in str(error_info.value)


@pytest.mark.parametrize(
    ("catalog", "expected_code"),
    [
        (_catalog(("rag.retrieve", "1.0.0")), "manifest_capability_missing"),
        (
            _catalog(
                ("rag.retrieve", "1.0.0"),
                ("rag.retrieve", "2.0.0"),
                ("search.query", "1.0.0"),
                ("document.get", "1.0.0"),
            ),
            "manifest_capability_ambiguous",
        ),
    ],
)
def test_loader_requires_each_declared_capability_to_have_one_catalog_version(
    tmp_path: Path,
    catalog: CapabilityCatalog,
    expected_code: str,
):
    _write_manifest(tmp_path)

    with pytest.raises(TeamManifestLoadError) as error_info:
        TeamManifestLoader(tmp_path, catalog).load()

    assert error_info.value.code == expected_code


def test_loader_does_not_read_prompt_reference_files(tmp_path: Path):
    manifest = _manifest()
    participant = manifest["participants"][0]  # type: ignore[index]
    participant.pop("prompt_text")
    participant["prompt_ref"] = "prompts/missing.md"
    _write_manifest(tmp_path, json.dumps(manifest).encode("utf-8"))

    loaded = TeamManifestLoader(tmp_path, _complete_catalog()).load()

    assert loaded.require_participant("research_agent").participant_id == "research_agent"
    with pytest.raises(KeyError, match="unknown participant"):
        loaded.require_participant("missing_agent")


def test_manifest_bootstrap_stage_runs_before_resource_factories_and_returns_metadata(tmp_path: Path):
    _write_manifest(tmp_path)
    events: list[str] = []
    config = AppConfig()

    def manifest_factory(received_config: AppConfig):
        assert received_config is config
        events.append("manifest")
        return TeamManifestLoader(tmp_path, _complete_catalog()).load()

    container = DependencyContainer(
        config=config,
        team_manifest_factory=manifest_factory,
        infrastructure_factory=lambda _config: events.append("infrastructure") or object(),
        application_factory=lambda _config, _infrastructure: events.append("application") or object(),
        app_factory=lambda _config, _infrastructure, _application: events.append("app") or object(),
    )

    result = StagedBootstrapper(container).run()

    assert events == ["manifest", "infrastructure", "application", "app"]
    assert result.dependencies.team_manifest is not None
    assert [diagnostic.stage for diagnostic in result.diagnostics] == [
        BootstrapStage.CONFIG,
        BootstrapStage.MANIFEST,
        BootstrapStage.INFRASTRUCTURE,
        BootstrapStage.APPLICATION,
        BootstrapStage.APP,
    ]


def test_manifest_bootstrap_failure_stops_before_resource_creation_and_redacts_error():
    events: list[str] = []

    def failing_manifest_factory(_config: AppConfig):
        events.append("manifest")
        raise RuntimeError("api_key=sentinel-secret")

    container = DependencyContainer(
        config=AppConfig(),
        team_manifest_factory=failing_manifest_factory,
        infrastructure_factory=lambda _config: events.append("infrastructure") or object(),
        application_factory=lambda *_: events.append("application") or object(),
        app_factory=lambda *_: events.append("app") or object(),
    )

    with pytest.raises(BootstrapError) as error_info:
        StagedBootstrapper(container).run()

    assert error_info.value.stage is BootstrapStage.MANIFEST
    assert events == ["manifest"]
    assert "sentinel-secret" not in str(error_info.value)


@pytest.mark.parametrize("factory_result", [object(), None])
def test_manifest_bootstrap_rejects_invalid_factory_results(factory_result: object):
    container = DependencyContainer(
        config=AppConfig(),
        team_manifest_factory=lambda _config: factory_result,  # type: ignore[arg-type]
        infrastructure_factory=lambda _config: (_ for _ in ()).throw(AssertionError("must not run")),
        application_factory=lambda *_: object(),
        app_factory=lambda *_: object(),
    )

    with pytest.raises(BootstrapError) as error_info:
        StagedBootstrapper(container).run()

    assert error_info.value.stage is BootstrapStage.MANIFEST


def test_manifest_bootstrap_rejects_an_async_factory_without_running_resources():
    events: list[str] = []

    async def async_factory(_config: AppConfig):
        return object()

    container = DependencyContainer(
        config=AppConfig(),
        team_manifest_factory=async_factory,  # type: ignore[arg-type]
        infrastructure_factory=lambda _config: events.append("infrastructure") or object(),
        application_factory=lambda *_: object(),
        app_factory=lambda *_: object(),
    )

    with pytest.raises(BootstrapError) as error_info:
        StagedBootstrapper(container).run()

    assert error_info.value.stage is BootstrapStage.MANIFEST
    assert events == []


def test_loader_and_bootstrap_extension_have_no_runtime_or_network_dependencies():
    source_paths = (
        ROOT / "src" / "venagent" / "orchestration" / "manifest" / "loader.py",
        ROOT / "src" / "venagent" / "orchestration" / "manifest" / "metadata.py",
        ROOT / "src" / "venagent" / "bootstrap" / "bootstrapper.py",
    )
    forbidden = re.compile(
        r"^\s*(?:from|import)\s+(?:final|fastapi|langgraph|langchain|mcp|docker|requests|httpx|subprocess)(?:\.|\s|$)",
        re.MULTILINE,
    )

    for source_path in source_paths:
        source = source_path.read_text(encoding="utf-8")
        assert forbidden.search(source) is None
        assert "os.environ" not in source
        assert "Path.cwd" not in source
        assert "AuthorizedToolInvoker" not in source
        assert "CapabilityBroker" not in source
