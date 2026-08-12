"""Phase 2 Sprint 10 的 orchestration 静态依赖门禁。"""

from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATION_ROOT = ROOT / "src" / "venagent" / "orchestration"

_BLOCKED_IMPORT_PREFIXES = (
    "final",
    "os",
    "asyncio",
    "aiohttp",
    "fastapi",
    "langchain",
    "langgraph",
    "mcp",
    "docker",
    "requests",
    "httpx",
    "socket",
    "subprocess",
    "urllib",
    "websockets",
    "importlib",
)
_PARTICIPANT_ALLOWED_VENAGENT_PREFIXES = (
    "venagent.application.governance",
    "venagent.capability",
    "venagent.orchestration.manifest",
    "venagent.orchestration.participants",
)
_MANIFEST_ALLOWED_VENAGENT_PREFIXES = (
    "venagent.capability.catalog",
    "venagent.orchestration.manifest",
)
_POLICY_ALLOWED_VENAGENT_PREFIXES = (
    "venagent.orchestration.policy",
)
_PARTICIPANT_BLOCKED_VENAGENT_PREFIXES = (
    "venagent.adapters",
    "venagent.core",
    "venagent.application.ports",
    "venagent.application.repository",
    "venagent.application.run_snapshot",
    "venagent.infrastructure",
)
_MANIFEST_BLOCKED_VENAGENT_PREFIXES = (
    "venagent.adapters",
    "venagent.core",
    "venagent.application",
    "venagent.infrastructure",
    "venagent.orchestration.participants",
)
_PARTICIPANT_BLOCKED_CALLS = {
    "open",
    "__import__",
    "eval",
    "exec",
    "compile",
    "os.system",
    "os.popen",
    "subprocess.run",
    "subprocess.Popen",
    "importlib.import_module",
}
_MANIFEST_BLOCKED_CALLS = _PARTICIPANT_BLOCKED_CALLS | {
    "Path.open",
    "Path.read_text",
    "Path.write_text",
    "Path.write_bytes",
}
_PARTICIPANT_BLOCKED_ATTRIBUTES = {
    "environ",
}
_PARTICIPANT_BLOCKED_PATH_METHODS = {
    "open",
    "chmod",
    "exists",
    "glob",
    "hardlink_to",
    "is_dir",
    "is_file",
    "iterdir",
    "lstat",
    "mkdir",
    "read_bytes",
    "readlink",
    "read_text",
    "rename",
    "replace",
    "resolve",
    "rglob",
    "rmdir",
    "samefile",
    "stat",
    "symlink_to",
    "touch",
    "unlink",
    "write_bytes",
    "write_text",
}


def _source_files() -> tuple[Path, ...]:
    return tuple(sorted(ORCHESTRATION_ROOT.rglob("*.py")))


def _relative_path(source_path: Path) -> PurePosixPath:
    return PurePosixPath(source_path.relative_to(ORCHESTRATION_ROOT).as_posix())


def _module_name(relative_path: PurePosixPath) -> str:
    parts = ["venagent", "orchestration", *relative_path.with_suffix("").parts]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _package_name(relative_path: PurePosixPath) -> str:
    module_name = _module_name(relative_path)
    if relative_path.name == "__init__.py":
        return module_name
    return module_name.rsplit(".", 1)[0]


def _scope_for(relative_path: PurePosixPath) -> str:
    if relative_path == PurePosixPath("__init__.py"):
        return "package"
    if relative_path.parts[0] == "manifest":
        return "manifest"
    if relative_path.parts[0] == "participants":
        return "participant"
    if relative_path.parts[0] == "policy":
        return "policy"
    return "unknown"


def _resolved_import(relative_path: PurePosixPath, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""

    package_parts = _package_name(relative_path).split(".")
    retained_count = len(package_parts) - (node.level - 1)
    if retained_count <= 0:
        return "<relative-import-escape>"
    target_parts = package_parts[:retained_count]
    if node.module:
        target_parts.extend(node.module.split("."))
    return ".".join(target_parts)


def _matches_prefix(module_name: str, prefixes: tuple[str, ...]) -> bool:
    return any(module_name == prefix or module_name.startswith(f"{prefix}.") for prefix in prefixes)


def _attribute_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attribute_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _attribute_name(node.func)
    return None


def _import_violations(tree: ast.AST, relative_path: PurePosixPath) -> list[str]:
    scope = _scope_for(relative_path)
    if scope == "unknown":
        return [f"{relative_path}: unclassified orchestration module"]

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_modules.append(_resolved_import(relative_path, node))

    violations: list[str] = []
    for imported_module in imported_modules:
        if imported_module == "<relative-import-escape>":
            violations.append(f"{relative_path}: ImportFrom relative import escapes package")
        elif _matches_prefix(imported_module, _BLOCKED_IMPORT_PREFIXES):
            violations.append(f"{relative_path}: forbidden import {imported_module}")
        elif scope == "participant" and imported_module.startswith("venagent"):
            if not _matches_prefix(imported_module, _PARTICIPANT_ALLOWED_VENAGENT_PREFIXES):
                violations.append(f"{relative_path}: participant import outside allowlist {imported_module}")
            elif _matches_prefix(imported_module, _PARTICIPANT_BLOCKED_VENAGENT_PREFIXES):
                violations.append(f"{relative_path}: forbidden participant import {imported_module}")
        elif scope == "manifest" and imported_module.startswith("venagent"):
            if not _matches_prefix(imported_module, _MANIFEST_ALLOWED_VENAGENT_PREFIXES):
                violations.append(f"{relative_path}: manifest import outside allowlist {imported_module}")
            elif _matches_prefix(imported_module, _MANIFEST_BLOCKED_VENAGENT_PREFIXES):
                violations.append(f"{relative_path}: forbidden manifest import {imported_module}")
        elif scope == "policy" and imported_module.startswith("venagent"):
            if not _matches_prefix(imported_module, _POLICY_ALLOWED_VENAGENT_PREFIXES):
                violations.append(f"{relative_path}: policy import outside allowlist {imported_module}")
    return violations


def _runtime_violations(tree: ast.AST, relative_path: PurePosixPath) -> list[str]:
    scope = _scope_for(relative_path)
    if scope == "package":
        return []

    violations: list[str] = []
    for node in ast.walk(tree):
        if scope in {"participant", "policy"} and isinstance(node, ast.Attribute) and node.attr in _PARTICIPANT_BLOCKED_ATTRIBUTES:
            violations.append(f"{relative_path}: forbidden {scope} attribute {node.attr}")
        if isinstance(node, ast.Call):
            call_name = _attribute_name(node.func)
            if call_name is None:
                continue
            blocked_calls = _MANIFEST_BLOCKED_CALLS if scope == "manifest" else _PARTICIPANT_BLOCKED_CALLS
            if call_name in blocked_calls:
                violations.append(f"{relative_path}: forbidden {scope} call {call_name}")
            if scope in {"participant", "policy"} and (
                call_name == "open"
                or call_name.endswith(".open")
                or (
                    call_name.startswith("Path.")
                    and call_name.rsplit(".", 1)[-1] in _PARTICIPANT_BLOCKED_PATH_METHODS
                )
            ):
                violations.append(f"{relative_path}: forbidden {scope} I/O call {call_name}")
    return violations


def _violations(source: str, relative_path: PurePosixPath) -> tuple[str, ...]:
    tree = ast.parse(source)
    return tuple(_import_violations(tree, relative_path) + _runtime_violations(tree, relative_path))


def test_every_current_orchestration_module_obeys_its_declared_dependency_boundary():
    source_files = _source_files()

    assert source_files, "orchestration source tree must not be empty"
    violations = [
        violation
        for source_path in source_files
        for violation in _violations(source_path.read_text(encoding="utf-8"), _relative_path(source_path))
    ]

    assert violations == []


@pytest.mark.parametrize(
    ("relative_path", "source", "expected"),
    [
        (PurePosixPath("participants/context.py"), "from final.internal.agent import UnifiedAgent", "forbidden import final.internal.agent"),
        (PurePosixPath("participants/context.py"), "from venagent.adapters.local import LocalRagAdapter", "outside allowlist venagent.adapters.local"),
        (PurePosixPath("participants/context.py"), "from venagent.core import RAG", "outside allowlist venagent.core"),
        (PurePosixPath("participants/context.py"), "from venagent.infrastructure import Infrastructure", "outside allowlist venagent.infrastructure"),
        (PurePosixPath("participants/context.py"), "from venagent.application.ports import RAGPort", "outside allowlist venagent.application.ports"),
        (PurePosixPath("manifest/loader.py"), "from venagent.adapters.local import LocalRagAdapter", "outside allowlist venagent.adapters.local"),
        (PurePosixPath("manifest/loader.py"), "from venagent.orchestration.participants import ParticipantRuntimeContext", "outside allowlist venagent.orchestration.participants"),
    ],
)
def test_import_policy_rejects_legacy_and_concrete_runtime_dependencies(
    relative_path: PurePosixPath,
    source: str,
    expected: str,
):
    violations = _violations(source, relative_path)

    assert any(expected in violation for violation in violations)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("open('unsafe')", "forbidden participant call open"),
        ("import os\nos.environ['TOKEN']", "forbidden participant attribute environ"),
        ("import subprocess\nsubprocess.run([])", "forbidden import subprocess"),
        ("import httpx\nhttpx.get('https://example.test')", "forbidden import httpx"),
        ("from pathlib import Path\nPath('x').read_text()", "forbidden participant I/O call Path.read_text"),
        ("from pathlib import Path\nPath('x').unlink()", "forbidden participant I/O call Path.unlink"),
        ("import builtins\nbuiltins.open('unsafe')", "forbidden participant I/O call builtins.open"),
        ("import urllib.request\nurllib.request.urlopen('https://example.test')", "forbidden import urllib.request"),
        ("import asyncio\nasyncio.create_subprocess_exec('cmd')", "forbidden import asyncio"),
        ("import importlib\nimportlib.import_module('venagent.adapters.local')", "forbidden import importlib"),
    ],
)
def test_participant_policy_rejects_file_environment_network_execution_and_dynamic_imports(
    source: str,
    expected: str,
):
    violations = _violations(source, PurePosixPath("participants/context.py"))

    assert any(expected in violation for violation in violations)


def test_comments_docstrings_and_plain_strings_do_not_trigger_dependency_violations():
    source = '''
"""The final UnifiedAgent may use subprocess in a different layer."""
# venagent.adapters.local must remain outside the participant boundary.
message = "httpx.get and os.environ are text, not behavior"
'''

    assert _violations(source, PurePosixPath("participants/models.py")) == ()


def test_manifest_policy_keeps_controlled_file_read_but_rejects_environment_and_execution():
    allowed_source = "from pathlib import Path\nPath('config.json').read_bytes()"
    environment_source = "import os\nos.environ.get('TOKEN')"
    execution_source = "import subprocess\nsubprocess.run([])"

    assert _violations(allowed_source, PurePosixPath("manifest/loader.py")) == ()
    assert any(
        "forbidden import os" in violation
        for violation in _violations(environment_source, PurePosixPath("manifest/loader.py"))
    )
    assert any(
        "forbidden import subprocess" in violation
        for violation in _violations(execution_source, PurePosixPath("manifest/loader.py"))
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from final.internal.agent import UnifiedAgent", "forbidden import final.internal.agent"),
        ("from venagent.adapters.local import LocalRagAdapter", "outside allowlist venagent.adapters.local"),
        ("open('unsafe')", "forbidden policy call open"),
    ],
)
def test_policy_contract_rejects_legacy_concrete_and_io_dependencies(source: str, expected: str):
    violations = _violations(source, PurePosixPath("policy/execution_plan.py"))

    assert any(expected in violation for violation in violations)


def test_new_orchestration_subpackage_requires_an_explicit_policy_classification():
    violations = _violations("pass", PurePosixPath("future_supervisor/runtime.py"))

    assert violations == ("future_supervisor/runtime.py: unclassified orchestration module",)
