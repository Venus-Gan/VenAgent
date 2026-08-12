"""Feature-first package layout 的架构约束。"""

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "venagent"


def test_approved_m01_m05_package_layout_exists_without_infra() -> None:
    expected = {
        "agent/observation.py",
        "agent/runtime.py",
        "conversation/rules.py",
        "memory/authorization.py",
        "memory/capabilities.py",
        "memory/command_adapter.py",
        "memory/jobs.py",
        "memory/job_worker.py",
        "memory/management.py",
        "memory/recall.py",
        "memory/service.py",
        "memory/short_term.py",
        "memory/long_term/facts.py",
        "memory/long_term/policy.py",
        "memory/long_term/writer.py",
        "promptctx/assembler.py",
        "promptctx/context.py",
        "promptctx/errors.py",
        "promptctx/recall_provider.py",
        "promptctx/schema.py",
        "promptctx/source.py",
        "repo/postgresql/conversation.py",
        "repo/postgresql/conversation_mapping.py",
        "repo/postgresql/conversation_runtime.py",
        "repo/postgresql/ownership.py",
        "repo/postgresql/runs.py",
        "repo/temporary/conversation.py",
        "repo/temporary/conversation_runtime.py",
        "repo/temporary/ownership.py",
        "repo/temporary/runs.py",
        "repo/temporary/state.py",
        "repo/neo4j/memory_graph.py",
        "platform/errors.py",
        "platform/observability.py",
        "platform/runtime.py",
        "platform/postgresql/migrations.py",
        "platform/postgresql/runtime.py",
        "platform/neo4j/migrations.py",
        "platform/neo4j/runtime.py",
        "llm/config.py",
        "llm/factory.py",
        "llm/providers.py",
        "config/loader.py",
        "interfaces/http/app.py",
        "interfaces/http/routes/auth.py",
        "interfaces/http/routes/conversations.py",
        "interfaces/http/routes/runs.py",
        "bootstrap.py",
    }
    assert all((PACKAGE / path).is_file() for path in expected)
    assert not (PACKAGE / "infra").exists()
    assert not (PACKAGE / "agent/context.py").exists()
    assert not (PACKAGE / "memory/long_term.py").exists()
    assert not (PACKAGE / "interfaces/http/routes.py").exists()
    assert not any(
        (PACKAGE / name).exists()
        for name in ("tools", "planner", "rag", "queue", "application")
    )


def test_core_capabilities_do_not_import_edge_adapters() -> None:
    forbidden = {
        "fastapi",
        "psycopg",
        "psycopg_pool",
        "venagent.repo",
        "venagent.interfaces",
    }
    violations: list[str] = []
    for package in (PACKAGE / "conversation", PACKAGE / "agent", PACKAGE / "memory"):
        for path in package.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    if any(
                        name == item or name.startswith(f"{item}.")
                        for item in forbidden
                    ):
                        violations.append(f"{path.relative_to(ROOT)} imports {name}")
    assert violations == []


def test_top_level_public_agent_exports_match_the_run_runtime() -> None:
    from venagent import AgentRun, AgentRuntime, RunState, build_local_model

    assert AgentRuntime.__module__ == "venagent.agent.runtime"
    assert AgentRun.__module__ == "venagent.agent.runs"
    assert RunState.__module__ == "venagent.agent.state"
    assert callable(build_local_model)


def test_platform_owns_resources_and_bootstrap_owns_adapter_composition() -> None:
    pool_constructors: list[str] = []
    forbidden_http_database_access: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        relative = path.relative_to(PACKAGE).as_posix()
        if "ConnectionPool(" in content or "AsyncConnectionPool(" in content:
            pool_constructors.append(relative)
        if relative.startswith("interfaces/http/") and any(
            marker in content for marker in ("get_db", "sessionmaker", "psycopg")
        ):
            forbidden_http_database_access.append(relative)

    assert pool_constructors == ["platform/postgresql/runtime.py"]
    assert forbidden_http_database_access == []
    platform_runtime = (PACKAGE / "platform/runtime.py").read_text(encoding="utf-8")
    assert "repo" not in platform_runtime
    bootstrap = (PACKAGE / "bootstrap.py").read_text(encoding="utf-8")
    assert "PostgresConversationRuntimeStore" in bootstrap
    assert "TemporaryConversationRuntimeStore" in bootstrap


def test_memory_service_is_an_explicit_composition_facade() -> None:
    path = PACKAGE / "memory/service.py"
    content = path.read_text(encoding="utf-8")
    tree = ast.parse(content)
    service = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MemoryService"
    )
    assert service.bases == []
    assert len(content.splitlines()) <= 800
    for collaborator in (
        "MemoryAuthorizer",
        "MemoryManager",
        "LongTermWriter",
        "MemoryJobs",
        "MemoryRecall",
    ):
        assert collaborator in content
