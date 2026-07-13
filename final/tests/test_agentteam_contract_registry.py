from types import SimpleNamespace

import pytest

from internal.agentteam import PresetContract, PresetRegistry, PresetRegistration, PresetTask


def test_contract_exports_are_importable():
    assert PresetTask.__name__ == "PresetTask"
    assert PresetContract.__name__ == "PresetContract"
    assert PresetRegistry.__name__ == "PresetRegistry"
    assert PresetRegistration.__name__ == "PresetRegistration"


def test_preset_task_uses_immutable_upstream_mapping():
    task = PresetTask(
        id="task-1",
        goal="Prepare a summary",
        query="Summarize the upstream notes",
        upstream={"writer_agent": "draft"},
    )

    assert dict(task.upstream) == {"writer_agent": "draft"}
    with pytest.raises(TypeError):
        task.upstream["writer_agent"] = "edited"  # type: ignore[index]


def test_preset_contract_is_frozen_and_keeps_metadata():
    contract = PresetContract(
        name="writer_agent",
        role="writer",
        purpose="Draft the first pass of the output.",
        input_fields=("goal", "query", "upstream"),
        output_fields=("content",),
        tool_permissions=("read", "write"),
        memory_policy="read-only",
        retrieval_policy="none",
        prompt_template="Write the report.",
    )

    assert contract.name == "writer_agent"
    with pytest.raises(AttributeError):
        contract.name = "other"  # type: ignore[misc]


def test_registry_preserves_insertion_order_and_contract_lookup():
    registry = PresetRegistry()
    first = object()
    second = object()
    first_contract = PresetContract(
        name="alpha",
        role="alpha",
        purpose="First preset",
        input_fields=("id",),
        output_fields=("result",),
        tool_permissions=(),
        memory_policy="none",
        retrieval_policy="none",
        prompt_template="alpha",
    )
    second_contract = PresetContract(
        name="beta",
        role="beta",
        purpose="Second preset",
        input_fields=("id",),
        output_fields=("result",),
        tool_permissions=("tool",),
        memory_policy="memory",
        retrieval_policy="retrieval",
        prompt_template="beta",
    )

    registry.register("alpha", first, first_contract)
    registry.register("beta", second, second_contract)

    assert registry.names() == ("alpha", "beta")
    assert registry.get_contract("alpha") is first_contract
    assert registry.contracts() == {"alpha": first_contract, "beta": second_contract}


def test_registry_get_and_snapshot_return_runtime_compatibility_map():
    registry = PresetRegistry()
    runner = SimpleNamespace(name=lambda: "runner")
    contract = PresetContract(
        name="runner",
        role="runner",
        purpose="Compatibility check",
        input_fields=("id",),
        output_fields=("result",),
        tool_permissions=(),
        memory_policy="none",
        retrieval_policy="none",
        prompt_template="runner",
    )

    registry.register("runner", runner, contract)

    assert registry.get("runner") is runner
    assert registry.get("missing") is None

    snap = registry.snapshot()
    assert snap == {"runner": runner}
    assert list(snap) == ["runner"]
