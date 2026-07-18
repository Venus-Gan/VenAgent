import asyncio
import inspect
import threading
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pytest

from apps.api.lifespan import create_lifespan, install_lifespan
from internal.agent.agent import UnifiedAgent
from internal.agent.memory_writer import AsyncMemoryWriter
from venagent.infrastructure.lifecycle import LifecycleError, LifecycleManager


class Resource:
    def __init__(self, name, events, *, fail_start=False, fail_close=False):
        self.name = name
        self.events = events
        self.fail_start = fail_start
        self.fail_close = fail_close

    async def start(self):
        self.events.append(f"start:{self.name}")
        if self.fail_start:
            raise RuntimeError("password=sentinel-secret")

    async def close(self):
        self.events.append(f"close:{self.name}")
        if self.fail_close:
            raise RuntimeError("token=sentinel-secret")


def test_lifecycle_manager_starts_in_order_and_closes_in_reverse_order():
    async def scenario():
        events = []
        manager = LifecycleManager()
        manager.register("infrastructure", Resource("infrastructure", events))
        manager.register("application", Resource("application", events))

        await manager.startup()
        cleanup_failures = await manager.shutdown()

        assert cleanup_failures == ()
        assert events == [
            "start:infrastructure",
            "start:application",
            "close:application",
            "close:infrastructure",
        ]

    asyncio.run(scenario())


def test_lifecycle_start_failure_cleans_started_resources_and_redacts_error():
    async def scenario():
        events = []
        manager = LifecycleManager()
        manager.register("infrastructure", Resource("infrastructure", events))
        manager.register(
            "application",
            Resource("application", events, fail_start=True),
        )

        with pytest.raises(LifecycleError) as error_info:
            await manager.startup()

        error = error_info.value
        assert error.resource == "application"
        assert error.__context__ is None
        assert "sentinel-secret" not in str(error)
        assert events == [
            "start:infrastructure",
            "start:application",
            "close:application",
            "close:infrastructure",
        ]

    asyncio.run(scenario())


def test_lifecycle_start_failure_reports_cleanup_failures_without_raw_error():
    async def scenario():
        events = []
        manager = LifecycleManager()
        manager.register(
            "infrastructure",
            Resource("infrastructure", events, fail_close=True),
        )
        manager.register(
            "application",
            Resource("application", events, fail_start=True),
        )

        with pytest.raises(LifecycleError) as error_info:
            await manager.startup()

        error = error_info.value
        assert error.cleanup_failures == ("infrastructure",)
        assert "sentinel-secret" not in repr(error)

    asyncio.run(scenario())


def test_lifecycle_close_continues_after_failure_and_is_idempotent():
    async def scenario():
        events = []
        manager = LifecycleManager()
        manager.register("infrastructure", Resource("infrastructure", events))
        manager.register(
            "application",
            Resource("application", events, fail_close=True),
        )
        await manager.startup()

        assert await manager.shutdown() == ("application",)
        assert await manager.shutdown() == ()
        assert events == [
            "start:infrastructure",
            "start:application",
            "close:application",
            "close:infrastructure",
        ]

    asyncio.run(scenario())


def test_lifespan_sets_app_state_and_cleans_on_exit():
    async def scenario():
        events = []
        app = SimpleNamespace(state=SimpleNamespace())

        async def startup(manager):
            manager.register("resource", Resource("resource", events))
            await manager.startup()
            return {"health_snapshot": "fake-health"}

        async with create_lifespan(startup)(app):
            assert app.state.health_snapshot == "fake-health"
            assert app.state.lifecycle_status == "started"

        assert events == ["start:resource", "close:resource"]

    asyncio.run(scenario())


def test_lifespan_cleans_up_before_propagating_cancellation():
    async def scenario():
        events = []
        app = SimpleNamespace(state=SimpleNamespace())

        async def startup(manager):
            manager.register("resource", Resource("resource", events))
            await manager.startup()

        with pytest.raises(asyncio.CancelledError):
            async with create_lifespan(startup)(app):
                raise asyncio.CancelledError()

        assert events == ["start:resource", "close:resource"]

    asyncio.run(scenario())


def test_install_lifespan_attaches_context_without_import_side_effects():
    app = SimpleNamespace(router=SimpleNamespace(lifespan_context=None))

    async def startup(_manager):
        return None

    installed = install_lifespan(app, startup)

    assert installed is app
    assert app.router.lifespan_context is not None


def test_unified_agent_constructor_does_not_start_runtime_or_memory_writer():
    source = inspect.getsource(UnifiedAgent.__init__)

    assert "_bootstrap_concurrent" not in source
    assert "init_knowledge_graph" not in source
    assert "AsyncMemoryWriter()" not in source


def test_memory_writer_is_lazy_and_stop_waits_for_worker():
    writer = AsyncMemoryWriter()

    assert writer.is_running is False
    writer.start()
    assert writer.is_running is True
    writer.stop()
    assert writer.is_running is False


def test_lifecycle_manager_supports_synchronous_resource_hooks():
    async def scenario():
        events = []

        class SyncResource:
            def start(self):
                events.append("start")

            def close(self):
                events.append("close")

        manager = LifecycleManager()
        manager.register("sync", SyncResource())
        await manager.startup()
        await manager.shutdown()

        assert events == ["start", "close"]

    asyncio.run(scenario())


def test_cancelled_sync_start_is_drained_before_partial_resource_cleanup():
    async def scenario():
        started = threading.Event()
        release = threading.Event()
        events = []

        class BlockingResource:
            def start(self):
                started.set()
                release.wait(timeout=2)
                events.append("start-finished")

            def close(self):
                events.append("close")

        manager = LifecycleManager()
        manager.register("blocking", BlockingResource())
        startup_task = asyncio.create_task(manager.startup())
        await asyncio.to_thread(started.wait, 1)
        startup_task.cancel()
        release.set()

        with pytest.raises(asyncio.CancelledError):
            await startup_task

        assert events == ["start-finished", "close"]

    asyncio.run(scenario())


def test_memory_writer_stop_drains_queued_tasks_before_returning():
    writer = AsyncMemoryWriter()
    processed: list[int] = []

    writer.start()
    for value in range(3):
        writer.submit(lambda value=value: processed.append(value))

    writer.stop()

    assert processed == [0, 1, 2]
    assert writer.is_running is False
