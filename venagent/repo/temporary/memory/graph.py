"""Non-durable G1 graph adapters used for tests and disabled mode."""

from __future__ import annotations

from dataclasses import replace
from threading import RLock

from ....memory.graph import MemoryEdge
from ....memory.ports import (
    G1GraphSnapshot,
    G1RecallSnapshot,
    GraphProjectionStatus,
    MemoryGraphSnapshotError,
)
from ....memory.ports import MemoryStoreError as StoreError


class _TemporaryGraphMixin:
    configured = True

    def recall_snapshot(self, owner_id: str, tenant_id: str) -> G1RecallSnapshot:
        with self._lock:
            return G1RecallSnapshot(
                owner_id=owner_id,
                tenant_id=tenant_id,
                settings=self.settings(owner_id),
                facts=self.active_facts(owner_id, tenant_id),
                sources=tuple(
                    sorted(
                        (
                            source
                            for source in self._sources.values()
                            if source.owner_id == owner_id
                            and source.tenant_id == tenant_id
                            and source.active
                        ),
                        key=lambda source: source.source_ref,
                    )
                ),
                authority_revision=self.authority_revision(owner_id, tenant_id),
            )

    def authority_revision(self, owner_id: str, tenant_id: str) -> int:
        with self._lock:
            return self._revisions.get((owner_id, tenant_id), 0)

    def read_edges(
        self,
        owner_id: str,
        tenant_id: str,
        seed_ids: tuple[str, ...],
        expected_revision: int,
        deletion_generation: int,
        registry_version: str,
    ) -> G1GraphSnapshot:
        with self._lock:
            state = self._projection_states.get((owner_id, tenant_id))
            if state != (expected_revision, deletion_generation, registry_version):
                raise MemoryGraphSnapshotError("memory graph projection is not current")
            seeds = set(seed_ids)
            edges = tuple(
                sorted(
                    (
                        edge
                        for edge in self._edges.values()
                        if edge.owner_id == owner_id
                        and edge.tenant_id == tenant_id
                        and edge.active
                        and edge.projection_revision == expected_revision
                        and edge.deletion_generation == deletion_generation
                        and edge.registry_version == registry_version
                        and (
                            edge.from_memory_id in seeds
                            or edge.to_memory_id in seeds
                        )
                    ),
                    key=lambda edge: edge.edge_id,
                )
            )
            return G1GraphSnapshot(
                owner_id,
                tenant_id,
                expected_revision,
                deletion_generation,
                registry_version,
                edges,
            )

    def replace_graph(
        self,
        owner_id: str,
        tenant_id: str,
        edges: tuple[MemoryEdge, ...],
        target_revision: int,
        deletion_generation: int,
        registry_version: str,
    ) -> GraphProjectionStatus:
        with self._lock:
            if any(
                edge.relation not in {"FOLLOWS", "SIMILAR_TO"}
                or edge.registry_version != registry_version
                or edge.owner_id != owner_id
                or edge.tenant_id != tenant_id
                for edge in edges
            ):
                raise StoreError("memory graph relation registry mismatch")
            state = self._projection_states.get((owner_id, tenant_id))
            applied_revision = state[0] if state is not None else 0
            if target_revision < applied_revision:
                return GraphProjectionStatus.STALE
            if target_revision == applied_revision and state is not None:
                return GraphProjectionStatus.CURRENT
            for edge_id, edge in tuple(self._edges.items()):
                if edge.owner_id == owner_id and edge.tenant_id == tenant_id:
                    self._edges[edge_id] = replace(
                        edge, active=False, projection_revision=target_revision
                    )
            self._edges.update(
                {
                    edge.edge_id: replace(
                        edge,
                        active=True,
                        projection_revision=target_revision,
                        deletion_generation=deletion_generation,
                    )
                    for edge in edges
                }
            )
            self._projection_states[(owner_id, tenant_id)] = (
                target_revision,
                deletion_generation,
                registry_version,
            )
            return GraphProjectionStatus.APPLIED

    def purge_graph(
        self,
        owner_id: str,
        tenant_id: str,
        target_revision: int,
        deletion_generation: int,
    ) -> None:
        with self._lock:
            self._edges = {
                edge_id: edge
                for edge_id, edge in self._edges.items()
                if not (edge.owner_id == owner_id and edge.tenant_id == tenant_id)
            }
            self._projection_states[(owner_id, tenant_id)] = (
                target_revision,
                deletion_generation,
                "m05-g1-v1",
            )

    # Compatibility helpers are confined to the non-durable test double.
    def replace_edges(
        self, owner_id: str, tenant_id: str, edges: tuple[MemoryEdge, ...]
    ) -> None:
        revision = self.authority_revision(owner_id, tenant_id)
        self.replace_graph(
            owner_id, tenant_id, edges, revision, 0, "m05-g1-v1"
        )

    def edges(self, owner_id: str, tenant_id: str) -> tuple[MemoryEdge, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        edge
                        for edge in self._edges.values()
                        if edge.owner_id == owner_id and edge.tenant_id == tenant_id
                    ),
                    key=lambda edge: edge.edge_id,
                )
            )


class TemporaryMemoryGraphStore(_TemporaryGraphMixin):
    def __init__(self) -> None:
        self._edges: dict[str, MemoryEdge] = {}
        self._projection_states: dict[tuple[str, str], tuple[int, int, str]] = {}
        self._revisions: dict[tuple[str, str], int] = {}
        self._lock = RLock()

