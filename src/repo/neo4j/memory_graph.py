"""Neo4j implementation of the M05 MemoryGraphStore port."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ...memory.graph_memory import MemoryEdge
from ...memory.ports import (
    G1GraphSnapshot,
    GraphProjectionStatus,
    MemoryGraphSnapshotError,
)
from ...memory.ports import MemoryStoreError as StoreError

_RELATION_QUERIES = {
    "FOLLOWS": """
        UNWIND $edges AS edge
        MATCH (source:M05Memory {owner_id:$owner_id,tenant_id:$tenant_id,
              memory_id:edge.from_memory_id})
        MATCH (target:M05Memory {owner_id:$owner_id,tenant_id:$tenant_id,
              memory_id:edge.to_memory_id})
        MERGE (source)-[relation:M05_FOLLOWS {edge_id:edge.edge_id}]->(target)
        SET relation.owner_id=$owner_id,relation.tenant_id=$tenant_id,
            relation.from_memory_id=edge.from_memory_id,
            relation.to_memory_id=edge.to_memory_id,
            relation.source=edge.source,relation.active=true,
            relation.registry_version=$registry_version,
            relation.projection_revision=$target_revision,
            relation.deletion_generation=$deletion_generation,
            relation.created_at=edge.created_at,
            relation.inactive_revision=null
    """,
    "SIMILAR_TO": """
        UNWIND $edges AS edge
        MATCH (source:M05Memory {owner_id:$owner_id,tenant_id:$tenant_id,
              memory_id:edge.from_memory_id})
        MATCH (target:M05Memory {owner_id:$owner_id,tenant_id:$tenant_id,
              memory_id:edge.to_memory_id})
        MERGE (source)-[relation:M05_SIMILAR_TO {edge_id:edge.edge_id}]->(target)
        SET relation.owner_id=$owner_id,relation.tenant_id=$tenant_id,
            relation.from_memory_id=edge.from_memory_id,
            relation.to_memory_id=edge.to_memory_id,
            relation.source=edge.source,relation.active=true,
            relation.registry_version=$registry_version,
            relation.projection_revision=$target_revision,
            relation.deletion_generation=$deletion_generation,
            relation.created_at=edge.created_at,
            relation.inactive_revision=null
    """,
}


class Neo4jMemoryGraphStore:
    configured = True

    def __init__(
        self,
        driver: Any,
        *,
        database: str,
        read_timeout: float,
        write_timeout: float,
    ) -> None:
        self._driver = driver
        self._database = database
        self._read_timeout = read_timeout
        self._write_timeout = write_timeout
        self._available = False

    def set_available(self, available: bool) -> None:
        self._available = available

    def read_edges(
        self,
        owner_id: str,
        tenant_id: str,
        seed_ids: tuple[str, ...],
        expected_revision: int,
        deletion_generation: int,
        registry_version: str,
    ) -> G1GraphSnapshot:
        self._require_available()
        try:
            with self._driver.session(database=self._database) as session:
                tx = session.begin_transaction(timeout=self._read_timeout)
                try:
                    state = tx.run(
                        """MATCH (projection:M05GraphProjection
                           {owner_id:$owner_id,tenant_id:$tenant_id})
                        RETURN projection.applied_revision AS applied_revision,
                               projection.deletion_generation AS deletion_generation,
                               projection.registry_version AS registry_version""",
                        owner_id=owner_id,
                        tenant_id=tenant_id,
                    ).single()
                    if (
                        state is None
                        or int(state["applied_revision"]) != expected_revision
                        or int(state["deletion_generation"]) != deletion_generation
                        or str(state["registry_version"]) != registry_version
                    ):
                        raise MemoryGraphSnapshotError(
                            "memory graph projection is not current"
                        )
                    records = tx.run(
                        """MATCH ()-[relation:M05_FOLLOWS|M05_SIMILAR_TO]->()
                        WHERE relation.owner_id=$owner_id
                          AND relation.tenant_id=$tenant_id
                          AND relation.active=true
                          AND relation.projection_revision=$expected_revision
                          AND relation.deletion_generation=$deletion_generation
                          AND relation.registry_version=$registry_version
                          AND (relation.from_memory_id IN $seed_ids
                               OR relation.to_memory_id IN $seed_ids)
                        RETURN relation.edge_id AS edge_id,
                               type(relation) AS relation_type,
                               relation.from_memory_id AS from_memory_id,
                               relation.to_memory_id AS to_memory_id,
                               relation.source AS source,
                               relation.created_at AS created_at
                        ORDER BY edge_id""",
                        owner_id=owner_id,
                        tenant_id=tenant_id,
                        expected_revision=expected_revision,
                        deletion_generation=deletion_generation,
                        registry_version=registry_version,
                        seed_ids=list(seed_ids),
                    )
                    edges = tuple(
                        _edge_from_record(
                            record,
                            owner_id,
                            tenant_id,
                            expected_revision,
                            deletion_generation,
                            registry_version,
                        )
                        for record in records
                    )
                    tx.commit()
                except Exception:
                    tx.rollback()
                    raise
            return G1GraphSnapshot(
                owner_id,
                tenant_id,
                expected_revision,
                deletion_generation,
                registry_version,
                edges,
            )
        except MemoryGraphSnapshotError:
            raise
        except Exception as exc:
            raise StoreError("unable to read memory graph") from exc

    def replace_graph(
        self,
        owner_id: str,
        tenant_id: str,
        edges: tuple[MemoryEdge, ...],
        target_revision: int,
        deletion_generation: int,
        registry_version: str,
    ) -> GraphProjectionStatus:
        self._require_available()
        _validate_edges(
            edges,
            owner_id,
            tenant_id,
            target_revision,
            deletion_generation,
            registry_version,
        )
        try:
            with self._driver.session(database=self._database) as session:
                tx = session.begin_transaction(timeout=self._write_timeout)
                try:
                    state = tx.run(
                        """MERGE (projection:M05GraphProjection
                           {owner_id:$owner_id,tenant_id:$tenant_id})
                        ON CREATE SET projection.applied_revision=0,
                                      projection.deletion_generation=0,
                                      projection.registry_version=$registry_version,
                                      projection.lock_version=0
                        SET projection.lock_version=projection.lock_version+1
                        RETURN projection.applied_revision AS applied_revision,
                               projection.deletion_generation AS deletion_generation,
                               projection.registry_version AS registry_version""",
                        owner_id=owner_id,
                        tenant_id=tenant_id,
                        registry_version=registry_version,
                    ).single()
                    applied_revision = int(state["applied_revision"])
                    if target_revision < applied_revision:
                        tx.rollback()
                        return GraphProjectionStatus.STALE
                    if (
                        target_revision == applied_revision
                        and int(state["deletion_generation"]) == deletion_generation
                        and str(state["registry_version"]) == registry_version
                    ):
                        tx.rollback()
                        return GraphProjectionStatus.CURRENT
                    params = {
                        "owner_id": owner_id,
                        "tenant_id": tenant_id,
                        "target_revision": target_revision,
                        "deletion_generation": deletion_generation,
                        "registry_version": registry_version,
                    }
                    tx.run(
                        """MATCH (memory:M05Memory
                           {owner_id:$owner_id,tenant_id:$tenant_id})
                        DETACH DELETE memory""",
                        **params,
                    ).consume()
                    nodes = sorted(
                        {
                            memory_id
                            for edge in edges
                            for memory_id in (
                                edge.from_memory_id,
                                edge.to_memory_id,
                            )
                        }
                    )
                    tx.run(
                        """UNWIND $memory_ids AS memory_id
                        MERGE (memory:M05Memory
                          {owner_id:$owner_id,tenant_id:$tenant_id,memory_id:memory_id})
                        SET memory.registry_version=$registry_version,
                            memory.projection_revision=$target_revision,
                            memory.deletion_generation=$deletion_generation""",
                        memory_ids=nodes,
                        **params,
                    ).consume()
                    for relation, query in _RELATION_QUERIES.items():
                        rows = [_edge_params(edge) for edge in edges if edge.relation == relation]
                        if rows:
                            tx.run(query, edges=rows, **params).consume()
                    tx.run(
                        """MATCH (projection:M05GraphProjection
                           {owner_id:$owner_id,tenant_id:$tenant_id})
                        SET projection.applied_revision=$target_revision,
                            projection.deletion_generation=$deletion_generation,
                            projection.registry_version=$registry_version,
                            projection.updated_at=datetime()""",
                        **params,
                    ).consume()
                    tx.commit()
                    return GraphProjectionStatus.APPLIED
                except Exception:
                    tx.rollback()
                    raise
        except Exception as exc:
            raise StoreError("unable to replace memory graph") from exc

    def purge_graph(
        self,
        owner_id: str,
        tenant_id: str,
        target_revision: int,
        deletion_generation: int,
    ) -> None:
        self._require_available()
        try:
            with self._driver.session(database=self._database) as session:
                tx = session.begin_transaction(timeout=self._write_timeout)
                try:
                    state = tx.run(
                        """MERGE (projection:M05GraphProjection
                           {owner_id:$owner_id,tenant_id:$tenant_id})
                        ON CREATE SET projection.applied_revision=0,
                                      projection.deletion_generation=0,
                                      projection.registry_version='m05-g1-v1',
                                      projection.lock_version=0
                        SET projection.lock_version=projection.lock_version+1
                        RETURN projection.applied_revision AS applied_revision,
                               projection.deletion_generation AS deletion_generation""",
                        owner_id=owner_id,
                        tenant_id=tenant_id,
                    ).single()
                    applied_revision = int(state["applied_revision"])
                    applied_generation = int(state["deletion_generation"])
                    if (
                        target_revision < applied_revision
                        or deletion_generation < applied_generation
                    ):
                        tx.rollback()
                        return
                    if (
                        target_revision == applied_revision
                        and deletion_generation == applied_generation
                    ):
                        tx.rollback()
                        return
                    tx.run(
                        """MATCH (memory:M05Memory
                           {owner_id:$owner_id,tenant_id:$tenant_id})
                        DETACH DELETE memory""",
                        owner_id=owner_id,
                        tenant_id=tenant_id,
                    ).consume()
                    tx.run(
                        """MERGE (projection:M05GraphProjection
                           {owner_id:$owner_id,tenant_id:$tenant_id})
                        SET projection.applied_revision=$target_revision,
                            projection.deletion_generation=$deletion_generation,
                            projection.registry_version='m05-g1-v1',
                            projection.updated_at=datetime()""",
                        owner_id=owner_id,
                        tenant_id=tenant_id,
                        target_revision=target_revision,
                        deletion_generation=deletion_generation,
                    ).consume()
                    tx.commit()
                except Exception:
                    tx.rollback()
                    raise
        except Exception as exc:
            raise StoreError("unable to purge memory graph") from exc

    def _require_available(self) -> None:
        if not self._available:
            raise MemoryGraphSnapshotError("memory graph is unavailable")


def _validate_edges(
    edges: tuple[MemoryEdge, ...],
    owner_id: str,
    tenant_id: str,
    target_revision: int,
    deletion_generation: int,
    registry_version: str,
) -> None:
    if any(
        edge.owner_id != owner_id
        or edge.tenant_id != tenant_id
        or edge.relation not in _RELATION_QUERIES
        or edge.registry_version != registry_version
        or edge.projection_revision != target_revision
        or edge.deletion_generation != deletion_generation
        or edge.from_memory_id == edge.to_memory_id
        for edge in edges
    ):
        raise StoreError("memory graph edge contract mismatch")


def _edge_params(edge: MemoryEdge) -> dict[str, Any]:
    return {
        "edge_id": edge.edge_id,
        "from_memory_id": edge.from_memory_id,
        "to_memory_id": edge.to_memory_id,
        "source": edge.source,
        "created_at": edge.created_at.isoformat(),
    }


def _edge_from_record(
    record: Any,
    owner_id: str,
    tenant_id: str,
    revision: int,
    generation: int,
    registry_version: str,
) -> MemoryEdge:
    relation = str(record["relation_type"]).removeprefix("M05_")
    if relation not in {"FOLLOWS", "SIMILAR_TO"}:
        raise MemoryGraphSnapshotError("memory graph relation is not registered")
    return MemoryEdge(
        edge_id=str(record["edge_id"]),
        owner_id=owner_id,
        tenant_id=tenant_id,
        relation=relation,  # type: ignore[arg-type]
        from_memory_id=str(record["from_memory_id"]),
        to_memory_id=str(record["to_memory_id"]),
        registry_version=registry_version,
        active=True,
        source=str(record["source"]),
        created_at=datetime.fromisoformat(str(record["created_at"])),
        projection_revision=revision,
        deletion_generation=generation,
    )
