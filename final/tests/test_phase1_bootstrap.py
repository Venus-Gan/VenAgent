from dataclasses import FrozenInstanceError
import ast
import asyncio
import os
from pathlib import Path
import sys
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from venagent.bootstrap import (
    BootstrapError,
    BootstrapStage,
    DependencyContainer,
    StageStatus,
    StagedBootstrapper,
)
from venagent.infrastructure.config import AppConfig


def _container(events: list[str], *, fail_at: str | None = None) -> DependencyContainer:
    config = AppConfig()
    app_shell = {"name": "app-shell"}

    def create_infrastructure(received_config):
        assert received_config is config
        events.append("infrastructure")
        if fail_at == "infrastructure":
            raise RuntimeError("password=sentinel-secret")
        return {"name": "fake-infrastructure"}

    def create_application(received_config, infrastructure):
        assert received_config is config
        assert infrastructure["name"] == "fake-infrastructure"
        events.append("application")
        if fail_at == "application":
            raise RuntimeError("api_key=sentinel-secret")
        return {"name": "fake-application"}

    def create_app(received_config, infrastructure, application):
        assert received_config is config
        assert infrastructure["name"] == "fake-infrastructure"
        assert application["name"] == "fake-application"
        events.append("app")
        if fail_at == "app":
            raise RuntimeError("token=sentinel-secret")
        return {"name": "fake-app"}

    return DependencyContainer(
        config=config,
        infrastructure_factory=create_infrastructure,
        application_factory=create_application,
        app_factory=create_app,
        app_shell_factory=lambda: app_shell,
    )


def test_staged_bootstrapper_executes_fixed_order_and_returns_app():
    events: list[str] = []
    result = StagedBootstrapper(_container(events)).run()

    assert events == ["infrastructure", "application", "app"]
    assert result.app == {"name": "fake-app"}
    assert [item.stage for item in result.diagnostics] == [
        BootstrapStage.CONFIG,
        BootstrapStage.INFRASTRUCTURE,
        BootstrapStage.APPLICATION,
        BootstrapStage.APP,
    ]
    assert all(item.status is StageStatus.SUCCEEDED for item in result.diagnostics)


@pytest.mark.parametrize("failed_stage", ["infrastructure", "application", "app"])
def test_bootstrap_failure_stops_following_stages_and_redacts_exception(
    failed_stage: str,
):
    events: list[str] = []

    with pytest.raises(BootstrapError) as error_info:
        StagedBootstrapper(_container(events, fail_at=failed_stage)).run()

    error = error_info.value
    assert error.stage.value == failed_stage
    assert "sentinel-secret" not in str(error)
    assert error.__context__ is None
    assert error.code == "BOOTSTRAP_STAGE_FAILED"
    expected_events = ["infrastructure"]
    if failed_stage in {"application", "app"}:
        expected_events.append("application")
    if failed_stage == "app":
        expected_events.append("app")
    assert events == expected_events
    assert error.diagnostics[-1].status is StageStatus.FAILED


def test_sync_bootstrapper_rejects_async_factory_without_marking_stage_ready():
    async def create_infrastructure(_config):
        return object()

    container = DependencyContainer(
        config=AppConfig(),
        infrastructure_factory=create_infrastructure,
        application_factory=lambda *_: object(),
        app_factory=lambda *_: object(),
    )

    with pytest.raises(BootstrapError) as error_info:
        StagedBootstrapper(container).run()

    error = error_info.value
    assert error.stage is BootstrapStage.INFRASTRUCTURE
    assert error.diagnostics[-1].status is StageStatus.FAILED
    assert error.diagnostics[-1].message == "infrastructure stage initialization failed"


def test_bootstrap_failure_closes_created_resources_in_reverse_order():
    events: list[str] = []

    class Closeable:
        def __init__(self, name: str):
            self.name = name

        def close(self):
            events.append(f"close:{self.name}")

    infrastructure = Closeable("infrastructure")
    application = Closeable("application")

    def create_application(_config, _infrastructure):
        events.append("application")
        return application

    def create_app(_config, _infrastructure, _application):
        events.append("app")
        raise RuntimeError("password=sentinel-secret")

    container = DependencyContainer(
        config=AppConfig(),
        infrastructure_factory=lambda _config: infrastructure,
        application_factory=create_application,
        app_factory=create_app,
    )

    with pytest.raises(BootstrapError):
        StagedBootstrapper(container).run()

    assert events == ["application", "app", "close:application", "close:infrastructure"]


def test_cancellation_still_closes_created_resources_before_propagating():
    closed: list[str] = []

    class Closeable:
        def close(self):
            closed.append("infrastructure")

    def create_application(_config, _infrastructure):
        raise asyncio.CancelledError()

    container = DependencyContainer(
        config=AppConfig(),
        infrastructure_factory=lambda _config: Closeable(),
        application_factory=create_application,
        app_factory=lambda *_: object(),
    )

    with pytest.raises(asyncio.CancelledError):
        StagedBootstrapper(container).run()

    assert closed == ["infrastructure"]


def test_async_close_is_rejected_and_recorded_by_sync_bootstrapper():
    class AsyncCloseable:
        async def close(self):
            raise AssertionError("async close must not be awaited by sync bootstrapper")

    container = DependencyContainer(
        config=AppConfig(),
        infrastructure_factory=lambda _config: AsyncCloseable(),
        application_factory=lambda *_: object(),
        app_factory=lambda *_: (_ for _ in ()).throw(RuntimeError("secret=sentinel-secret")),
    )

    with pytest.raises(BootstrapError) as error_info:
        StagedBootstrapper(container).run()

    assert error_info.value.cleanup_failures == ("AsyncCloseable",)


def test_cleanup_continues_after_base_exception_and_reports_safe_resource_name():
    events: list[str] = []

    class ApplicationResource:
        def close(self):
            events.append("close:application")
            raise asyncio.CancelledError()

    class InfrastructureResource:
        def close(self):
            events.append("close:infrastructure")

    container = DependencyContainer(
        config=AppConfig(),
        infrastructure_factory=lambda _config: InfrastructureResource(),
        application_factory=lambda *_: ApplicationResource(),
        app_factory=lambda *_: (_ for _ in ()).throw(RuntimeError("secret=sentinel-secret")),
    )

    with pytest.raises(BootstrapError) as error_info:
        StagedBootstrapper(container).run()

    assert events == ["close:application", "close:infrastructure"]
    assert error_info.value.cleanup_failures == ("ApplicationResource",)


def test_cancellation_adds_safe_cleanup_note_without_replacing_original_signal():
    class FailingResource:
        def close(self):
            raise RuntimeError("password=sentinel-secret")

    container = DependencyContainer(
        config=AppConfig(),
        infrastructure_factory=lambda _config: FailingResource(),
        application_factory=lambda *_: (_ for _ in ()).throw(asyncio.CancelledError()),
        app_factory=lambda *_: object(),
    )

    with pytest.raises(asyncio.CancelledError) as error_info:
        StagedBootstrapper(container).run()

    assert any("FailingResource" in note for note in error_info.value.__notes__)
    assert all("sentinel-secret" not in note for note in error_info.value.__notes__)


def test_dependency_container_is_frozen_and_rejects_non_callable_factories():
    container = _container([])

    with pytest.raises(FrozenInstanceError):
        container.config = AppConfig()  # type: ignore[misc]

    with pytest.raises(TypeError, match="infrastructure_factory"):
        DependencyContainer(
            config=AppConfig(),
            infrastructure_factory=None,
            application_factory=lambda *_: object(),
            app_factory=lambda *_: object(),
        )

    with pytest.raises(TypeError, match="AppConfig"):
        DependencyContainer(
            config=None,
            infrastructure_factory=lambda *_: object(),
            application_factory=lambda *_: object(),
            app_factory=lambda *_: object(),
        )


def test_new_bootstrap_modules_do_not_import_legacy_final_package():
    root = ROOT
    source_files = [
        *root.joinpath("src", "venagent").rglob("*.py"),
        *root.joinpath("apps").rglob("*.py"),
    ]

    assert source_files
    for source_file in source_files:
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported_modules = [node.module or ""]
            else:
                continue
            assert not any(
                module == "final" or module.startswith("final.")
                for module in imported_modules
            ), source_file


def test_app_factory_is_lazy_and_uses_bootstrapper():
    events: list[str] = []
    container = _container(events)

    from apps.api.main import create_app

    assert events == []
    app = create_app(container)

    assert app == {"name": "app-shell"}
    assert events == []


def test_api_entry_imports_from_repository_root_without_pythonpath():
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-B", "-c", "import apps.api.main"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_fastapi_app_factory_installs_lifespan_for_created_resources():
    from fastapi import FastAPI

    from apps.api.main import create_app

    events: list[str] = []

    class Resource:
        def __init__(self, name: str):
            self.name = name

        async def start(self):
            events.append(f"start:{self.name}")

        async def close(self):
            events.append(f"close:{self.name}")

    infrastructure = Resource("infrastructure")
    application = Resource("application")
    app = FastAPI()
    container = DependencyContainer(
        config=AppConfig(),
        infrastructure_factory=lambda _config: infrastructure,
        application_factory=lambda _config, _infra: application,
        app_factory=lambda *_: app,
        app_shell_factory=lambda: app,
    )

    app = create_app(container)
    assert app.router.lifespan_context is not None
    assert events == []

    async def scenario():
        async with app.router.lifespan_context(app):
            assert app.state.lifecycle_status == "started"
            assert not hasattr(app.state, "bootstrap_dependencies")
            assert not hasattr(app.state, "lifecycle")

    asyncio.run(scenario())
    assert events == [
        "start:infrastructure",
        "start:application",
        "close:application",
        "close:infrastructure",
    ]


def test_lifespan_creates_resources_only_after_context_entry():
    from fastapi import FastAPI

    from apps.api.main import create_app

    events: list[str] = []
    app = FastAPI()

    class Resource:
        def __init__(self, name: str):
            self.name = name

        async def start(self):
            events.append(f"start:{self.name}")

        async def close(self):
            events.append(f"close:{self.name}")

    def create_infrastructure(_config):
        events.append("create:infrastructure")
        return Resource("infrastructure")

    def create_application(_config, _infrastructure):
        events.append("create:application")
        return Resource("application")

    container = DependencyContainer(
        config=AppConfig(),
        infrastructure_factory=create_infrastructure,
        application_factory=create_application,
        app_factory=lambda *_: app,
        app_shell_factory=lambda: app,
    )

    created = create_app(container)
    assert created is app
    assert events == []

    async def scenario():
        async with app.router.lifespan_context(app):
            assert events[:4] == [
                "create:infrastructure",
                "create:application",
                "start:infrastructure",
                "start:application",
            ]

    asyncio.run(scenario())
