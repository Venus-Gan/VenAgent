from dataclasses import FrozenInstanceError
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pytest

from venagent.infrastructure.health import (
    CapabilityHealthEvaluator,
    CapabilityState,
    HealthSnapshot,
)


def _all_available():
    return {
        "llm": "available",
        "postgresql": "connected",
        "milvus": "connected",
        "elasticsearch": "connected",
        "kafka": "connected",
        "neo4j": "connected",
        "sandbox": "available",
    }


def test_health_evaluator_returns_available_capabilities_for_healthy_dependencies():
    snapshot = CapabilityHealthEvaluator(_all_available()).evaluate()

    assert snapshot.get("chat").state is CapabilityState.AVAILABLE
    assert snapshot.get("durable_workflow").state is CapabilityState.AVAILABLE
    assert snapshot.get("rag").state is CapabilityState.AVAILABLE


def test_postgres_failure_allows_chat_but_blocks_durable_workflow():
    statuses = _all_available()
    statuses["postgresql"] = "disconnected"

    snapshot = CapabilityHealthEvaluator(statuses).evaluate()

    assert snapshot.get("chat").state is CapabilityState.AVAILABLE
    assert snapshot.get("short_term_memory").state is CapabilityState.AVAILABLE
    assert snapshot.get("durable_workflow").state is CapabilityState.UNAVAILABLE
    assert snapshot.get("durable_workflow").reason_code == "DEPENDENCY_UNAVAILABLE"


def test_optional_capability_failure_is_localized_and_not_reported_as_success():
    statuses = _all_available()
    statuses["neo4j"] = "disconnected"
    statuses["sandbox"] = "disabled"

    snapshot = CapabilityHealthEvaluator(statuses).evaluate()

    assert snapshot.get("graph_memory").state is CapabilityState.DEGRADED
    assert snapshot.get("sandbox").state is CapabilityState.DISABLED
    assert snapshot.get("chat").state is CapabilityState.AVAILABLE


@pytest.mark.parametrize("dependency", ["milvus", "elasticsearch"])
def test_rag_is_unavailable_when_any_required_search_dependency_is_missing(dependency):
    statuses = _all_available()
    statuses[dependency] = "disconnected"

    snapshot = CapabilityHealthEvaluator(statuses).evaluate()

    assert snapshot.get("rag").state is CapabilityState.UNAVAILABLE
    assert snapshot.get("rag").non_durable_available is False


def test_unknown_capability_is_not_available_and_snapshot_is_immutable():
    snapshot = CapabilityHealthEvaluator(_all_available()).evaluate()

    with pytest.raises(KeyError):
        snapshot.get("not-registered")

    with pytest.raises(FrozenInstanceError):
        snapshot.capabilities = ()  # type: ignore[misc]

    public = snapshot.as_dict()
    public["chat"]["state"] = "tampered"
    assert snapshot.get("chat").state is CapabilityState.AVAILABLE


def test_health_diagnostics_do_not_expose_secret_or_connection_string():
    statuses = _all_available()
    statuses["postgresql"] = "password=sentinel-secret host=db.internal"

    snapshot = CapabilityHealthEvaluator(statuses).evaluate()

    assert "sentinel-secret" not in repr(snapshot)
    assert "db.internal" not in repr(snapshot)
