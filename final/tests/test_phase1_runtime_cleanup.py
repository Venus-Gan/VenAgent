from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def test_initialize_runtime_stops_memory_writer_when_bootstrap_fails(monkeypatch):
    from config.config import APIConfig
    import internal.agent.agent as agent_module

    class FakeInfrastructure:
        repo = None

    agent = object.__new__(agent_module.UnifiedAgent)
    agent.cfg = APIConfig()
    agent.inf = FakeInfrastructure()
    agent._runtime_initialized = False
    agent.memory_writer = None

    stopped = []

    class Writer:
        def start(self):
            return None

        def stop(self):
            stopped.append(True)

    monkeypatch.setattr(agent_module, "AsyncMemoryWriter", Writer)
    monkeypatch.setattr(
        agent_module,
        "bootstrap_agent_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret=sentinel")),
    )

    with pytest.raises(RuntimeError):
        agent.initialize_runtime()

    assert stopped == [True]
    assert agent.memory_writer is None


def test_build_deps_closes_partial_resources_when_assembly_fails(monkeypatch):
    import main

    events = []

    class Resource:
        def close(self):
            events.append("close")

    resource = Resource()
    monkeypatch.setattr(main, "Infrastructure", lambda _cfg: resource)
    monkeypatch.setattr(
        main,
        "UnifiedAgent",
        lambda _cfg, _inf: (_ for _ in ()).throw(RuntimeError("secret=sentinel")),
    )

    with pytest.raises(RuntimeError):
        main.build_deps()

    assert events == ["close"]


def test_build_deps_closes_agent_and_infrastructure_when_routes_fail(monkeypatch):
    import main

    events = []

    class Resource:
        def __init__(self, name):
            self.name = name

        def close(self):
            events.append(f"close:{self.name}")

    class Agent(Resource):
        def initialize_runtime(self):
            events.append("initialize")

    infrastructure = Resource("infrastructure")
    agent = Agent("agent")
    monkeypatch.setattr(main, "Infrastructure", lambda _cfg: infrastructure)
    monkeypatch.setattr(main, "UnifiedAgent", lambda _cfg, _inf: agent)
    monkeypatch.setattr(
        main,
        "setup_routes",
        lambda *_: (_ for _ in ()).throw(RuntimeError("secret=sentinel")),
    )

    with pytest.raises(RuntimeError):
        main.build_deps()

    assert events == ["initialize", "close:agent", "close:infrastructure"]
