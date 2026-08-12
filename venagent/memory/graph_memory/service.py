"""M05 GraphMemory application service."""

from __future__ import annotations

from dataclasses import replace

from ..graph import RELATION_REGISTRY_VERSION, MemoryEdge, build_g1_edges
from ..ports import (
    G1GraphSnapshot,
    GraphProjectionStatus,
    MemoryGraphAuthorityStore,
    MemoryGraphSnapshotError,
    MemoryGraphStore,
)


class DisabledGraphMemoryStore:
    configured = False

    def read_edges(self, *args, **kwargs):
        del args, kwargs
        raise MemoryGraphSnapshotError("memory graph is disabled")

    def replace_graph(self, *args, **kwargs):
        del args, kwargs
        raise MemoryGraphSnapshotError("memory graph is disabled")

    def purge_graph(self, *args, **kwargs) -> None:
        del args, kwargs
        raise MemoryGraphSnapshotError("memory graph is disabled")


class GraphMemory:
    """Coordinates authoritative facts with the rebuildable G1 graph."""

    def __init__(
        self, authority: MemoryGraphAuthorityStore, graph_store: MemoryGraphStore
    ) -> None:
        self._authority = authority
        self._graph_store = graph_store

    @property
    def graph_store(self) -> MemoryGraphStore:
        return self._graph_store

    @property
    def configured(self) -> bool:
        return self._graph_store.configured

    def project(
        self,
        owner_id: str,
        tenant_id: str,
        target_revision: int,
        deletion_generation: int,
    ) -> GraphProjectionStatus:
        snapshot = self._authority.recall_snapshot(owner_id, tenant_id)
        if (
            snapshot.authority_revision > target_revision
            or snapshot.settings.deletion_generation > deletion_generation
        ):
            return GraphProjectionStatus.STALE
        if (
            snapshot.authority_revision != target_revision
            or snapshot.settings.deletion_generation != deletion_generation
        ):
            raise ValueError("projection revision is ahead of authoritative memory")
        sources = {source.source_ref: source for source in snapshot.sources}
        edges = tuple(
            replace(
                edge,
                projection_revision=target_revision,
                deletion_generation=deletion_generation,
            )
            for edge in build_g1_edges(snapshot.facts, sources)
        )
        return self._graph_store.replace_graph(
            owner_id,
            tenant_id,
            edges,
            target_revision,
            deletion_generation,
            RELATION_REGISTRY_VERSION,
        )

    def recall_edges(
        self,
        owner_id: str,
        tenant_id: str,
        seed_ids: tuple[str, ...],
        authority_revision: int,
        deletion_generation: int,
    ) -> tuple[MemoryEdge, ...]:
        snapshot: G1GraphSnapshot = self._graph_store.read_edges(
            owner_id,
            tenant_id,
            seed_ids,
            authority_revision,
            deletion_generation,
            RELATION_REGISTRY_VERSION,
        )
        if (
            snapshot.owner_id != owner_id
            or snapshot.tenant_id != tenant_id
            or snapshot.applied_revision != authority_revision
            or snapshot.deletion_generation != deletion_generation
            or snapshot.registry_version != RELATION_REGISTRY_VERSION
            or any(
                edge.owner_id != owner_id
                or edge.tenant_id != tenant_id
                or edge.projection_revision != authority_revision
                or edge.deletion_generation != deletion_generation
                or edge.registry_version != RELATION_REGISTRY_VERSION
                or not edge.active
                for edge in snapshot.edges
            )
        ):
            raise MemoryGraphSnapshotError("memory graph snapshot contract mismatch")
        return snapshot.edges

    def purge(
        self,
        owner_id: str,
        tenant_id: str,
        target_revision: int,
        generation: int,
    ) -> None:
        self._graph_store.purge_graph(
            owner_id, tenant_id, target_revision, generation
        )
