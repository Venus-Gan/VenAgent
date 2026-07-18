import threading
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pytest

from venagent.bootstrap.concurrent import (
    BootstrapTask,
    ConcurrentBootstrapper,
    TaskStatus,
)


def test_concurrent_bootstrap_runs_tasks_in_parallel_and_barrier_after_all():
    started = {name: threading.Event() for name in ("rag", "restore", "sandbox")}
    release = threading.Event()
    barrier_seen = []

    def task(name):
        def run():
            started[name].set()
            release.wait(timeout=1)
            return name.upper()

        return run

    def barrier(result):
        barrier_seen.append(tuple(item.name for item in result.results))
        assert all(event.is_set() for event in started.values())

    coordinator = ConcurrentBootstrapper(
        (
            BootstrapTask("rag", task("rag")),
            BootstrapTask("restore", task("restore")),
            BootstrapTask("sandbox", task("sandbox")),
        ),
        barrier=barrier,
    )

    worker = threading.Thread(target=lambda: coordinator.run(), daemon=True)
    worker.start()
    assert all(event.wait(timeout=1) for event in started.values())
    release.set()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert barrier_seen == [("rag", "restore", "sandbox")]


def test_concurrent_bootstrap_isolates_task_failure_and_redacts_error():
    result = ConcurrentBootstrapper(
        (
            BootstrapTask("restore", lambda: (_ for _ in ()).throw(
                RuntimeError("password=sentinel-secret")
            )),
            BootstrapTask("rag", lambda: "ready"),
        )
    ).run()

    assert [item.status for item in result.results] == [
        TaskStatus.FAILED,
        TaskStatus.SUCCEEDED,
    ]
    assert result.results[0].message == "task initialization failed"
    assert "sentinel-secret" not in repr(result)
    assert result.results[1].value == "ready"


def test_concurrent_bootstrap_propagates_control_flow_exception_after_workers_finish():
    completed = threading.Event()

    def cancel():
        completed.set()
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        ConcurrentBootstrapper(
            (
                BootstrapTask("cancel", cancel),
                BootstrapTask("other", lambda: completed.wait(timeout=1)),
            )
        ).run()

    assert completed.is_set()


def test_concurrent_bootstrap_rejects_duplicate_or_invalid_tasks():
    with pytest.raises(ValueError, match="duplicate"):
        ConcurrentBootstrapper(
            (
                BootstrapTask("same", lambda: None),
                BootstrapTask("same", lambda: None),
            )
        )

    with pytest.raises(TypeError, match="callable"):
        BootstrapTask("invalid", None)  # type: ignore[arg-type]
