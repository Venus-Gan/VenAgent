from __future__ import annotations

from datetime import datetime, timezone

import pytest

from venagent.memory.graph import MemoryEdge
from venagent.memory.graph_memory import GraphMemory
from venagent.memory.long_term.facts import MemoryFact, MemorySource
from venagent.memory.ports import (
    G1GraphSnapshot,
    GraphProjectionStatus,
    MemoryGraphSnapshotError,
)
from venagent.repo.temporary.memory import (
    TemporaryMemoryGraphStore,
    TemporaryMemoryStore,
)

NOW = datetime(2026, 8, 7, tzinfo=timezone.utc)


def _edge(edge_id: str, revision: int) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        owner_id="owner-1",
        tenant_id="default",
        relation="SIMILAR_TO",
        from_memory_id="memory-1",
        to_memory_id="memory-2",
        registry_version="m05-g1-v1",
        active=True,
        source="test",
        created_at=NOW,
        projection_revision=revision,
        deletion_generation=0,
    )


def test_graph_store_rejects_stale_projection_and_reads_only_current_revision() -> None:
    graph = TemporaryMemoryGraphStore()

    assert graph.replace_graph(
        "owner-1", "default", (_edge("edge-2", 2),), 2, 0, "m05-g1-v1"
    ) == GraphProjectionStatus.APPLIED
    assert graph.replace_graph(
        "owner-1", "default", (_edge("edge-1", 1),), 1, 0, "m05-g1-v1"
    ) == GraphProjectionStatus.STALE

    snapshot = graph.read_edges(
        "owner-1",
        "default",
        ("memory-1",),
        2,
        0,
        "m05-g1-v1",
    )
    assert snapshot.applied_revision == 2
    assert [edge.edge_id for edge in snapshot.edges] == ["edge-2"]


def test_graph_memory_projects_authoritative_snapshot_without_copying_fact_text() -> None:
    authority = TemporaryMemoryStore(durable=True)
    graph = TemporaryMemoryGraphStore()
    memory = GraphMemory(authority, graph)

    assert memory.graph_store is graph
    assert graph.configured is True
    for index, fact_text in enumerate(("我住在杭州", "我负责火星项目"), start=1):
        source = MemorySource(
            source_ref=f"message:{index}",
            owner_id="owner-1",
            tenant_id="default",
            source_kind="user_message",
            conversation_id="conversation-1",
            source_order=index,
            created_at=NOW,
        )
        fact = MemoryFact(
            memory_id=f"memory-{index}",
            owner_id="owner-1",
            tenant_id="default",
            subject="我",
            slot=f"slot-{index}",
            fact=fact_text,
            status="active",
            source_refs=(source.source_ref,),
            created_at=NOW,
            updated_at=NOW,
            index_status="ready",
        )
        authority.save_fact(fact, source, NOW)

    assert memory.project("owner-1", "default", 2, 0) is GraphProjectionStatus.APPLIED
    edges = memory.recall_edges(
        "owner-1", "default", ("memory-1",), 2, 0
    )

    assert tuple(edge.relation for edge in edges) == ("FOLLOWS",)
    assert all("fact" not in vars(edge) for edge in edges)
    assert all("杭州" not in str(vars(edge)) for edge in edges)


def test_graph_memory_rejects_cross_scope_graph_snapshot() -> None:
    class CrossScopeGraphStore(TemporaryMemoryGraphStore):
        def read_edges(self, *args, **kwargs):
            del args, kwargs
            return G1GraphSnapshot(
                "other-owner", "default", 0, 0, "m05-g1-v1", ()
            )

    memory = GraphMemory(
        TemporaryMemoryStore(durable=True), CrossScopeGraphStore()
    )

    with pytest.raises(MemoryGraphSnapshotError):
        memory.recall_edges("owner-1", "default", (), 0, 0)
