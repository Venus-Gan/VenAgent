from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.memory.graph_memory import MemoryEdge
from src.memory.ports import GraphProjectionStatus
from src.platform import PersistenceError
from src.platform.neo4j import (
    migrate_neo4j_schema,
    validate_neo4j_schema,
)
from src.repo.neo4j import Neo4jMemoryGraphStore

NOW = datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)


class _Result:
    def __init__(self, *, single=None, records=()):
        self._single = single
        self._records = records

    def single(self):
        return self._single

    def consume(self):
        return None

    def __iter__(self):
        return iter(self._records)


class _Transaction:
    def __init__(self, state):
        self.state = state
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.committed = False
        self.rolled_back = False

    def run(self, query, **params):
        normalized = " ".join(query.split())
        self.calls.append((normalized, params))
        if "RETURN projection.applied_revision AS applied_revision" in normalized:
            return _Result(single=self.state)
        return _Result()

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class _Session:
    def __init__(self, transaction):
        self.transaction = transaction
        self.timeout = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def begin_transaction(self, *, timeout):
        self.timeout = timeout
        return self.transaction


class _Driver:
    def __init__(self, transaction):
        self.transaction = transaction
        self.database = None

    def session(self, *, database):
        self.database = database
        return _Session(self.transaction)


class _SchemaSession:
    def __init__(self, constraints):
        self.constraints = constraints

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def run(self, query, **params):
        del params
        normalized = " ".join(query.split())
        if normalized.startswith("MATCH (schema:M05GraphSchema"):
            return _Result(single={"version": 1})
        if normalized.startswith("SHOW CONSTRAINTS"):
            return _Result(
                records=tuple({"name": name} for name in self.constraints)
            )
        return _Result()


class _SchemaDriver:
    def __init__(self, constraints):
        self.constraints = constraints

    def session(self, *, database):
        assert database == "neo4j"
        return _SchemaSession(self.constraints)


def _store(state):
    transaction = _Transaction(state)
    store = Neo4jMemoryGraphStore(
        _Driver(transaction),
        database="neo4j",
        read_timeout=2.0,
        write_timeout=3.0,
    )
    store.set_available(True)
    return store, transaction


def _edge(revision: int = 2, generation: int = 1) -> MemoryEdge:
    return MemoryEdge(
        edge_id="edge-1",
        owner_id="owner-1",
        tenant_id="default",
        relation="FOLLOWS",
        from_memory_id="memory-1",
        to_memory_id="memory-2",
        registry_version="m05-g1-v1",
        active=True,
        source="source-timeline",
        created_at=NOW,
        projection_revision=revision,
        deletion_generation=generation,
    )


def test_replace_graph_rebuilds_exact_owner_tenant_projection_in_one_transaction() -> None:
    store, transaction = _store(
        {
            "applied_revision": 1,
            "deletion_generation": 1,
            "registry_version": "m05-g1-v1",
        }
    )

    status = store.replace_graph(
        "owner-1", "default", (_edge(),), 2, 1, "m05-g1-v1"
    )

    assert status is GraphProjectionStatus.APPLIED
    assert transaction.committed is True and transaction.rolled_back is False
    write_calls = tuple(params for _query, params in transaction.calls if params)
    assert any(
        params.get("owner_id") == "owner-1"
        and params.get("tenant_id") == "default"
        and params.get("target_revision") == 2
        and params.get("deletion_generation") == 1
        for params in write_calls
    )
    assert any(
        params.get("edges")
        == [
            {
                "edge_id": "edge-1",
                "from_memory_id": "memory-1",
                "to_memory_id": "memory-2",
                "source": "source-timeline",
                "created_at": NOW.isoformat(),
            }
        ]
        for params in write_calls
    )


def test_replace_graph_rejects_stale_revision_before_deleting_projection() -> None:
    store, transaction = _store(
        {
            "applied_revision": 3,
            "deletion_generation": 1,
            "registry_version": "m05-g1-v1",
        }
    )

    status = store.replace_graph(
        "owner-1", "default", (_edge(),), 2, 1, "m05-g1-v1"
    )

    # 行为契约：旧 revision 被拒绝后整个事务回滚，删除/写入都不会持久化。
    assert status is GraphProjectionStatus.STALE
    assert transaction.rolled_back is True and transaction.committed is False


def test_purge_graph_rejects_stale_generation_before_deleting_projection() -> None:
    store, transaction = _store(
        {
            "applied_revision": 4,
            "deletion_generation": 3,
        }
    )

    store.purge_graph("owner-1", "default", 5, 2)

    # 行为契约：旧 generation 被拒绝后整个事务回滚，不会持久化删除。
    assert transaction.rolled_back is True and transaction.committed is False


def test_schema_validation_requires_all_m05_constraints() -> None:
    validate_neo4j_schema(
        _SchemaDriver(
            {
                "m05_memory_identity",
                "m05_projection_identity",
                "m05_schema_component",
            }
        ),
        "neo4j",
    )

    with pytest.raises(PersistenceError, match="unsupported Neo4j graph schema"):
        validate_neo4j_schema(
            _SchemaDriver(
                {"m05_memory_identity", "m05_projection_identity"}
            ),
            "neo4j",
        )


@pytest.mark.integration
def test_real_neo4j_projection_round_trip_when_explicitly_configured() -> None:
    uri = os.environ.get("TEST_NEO4J_URI", "").strip()
    if not uri:
        pytest.skip("TEST_NEO4J_URI is not configured")
    neo4j = pytest.importorskip("neo4j")
    user = os.environ.get("TEST_NEO4J_USER", "neo4j")
    password = os.environ.get("TEST_NEO4J_PASSWORD") or os.environ.get(
        "NEO4J_PASSWORD", ""
    )
    database = os.environ.get("TEST_NEO4J_DATABASE", "neo4j")
    if not password:
        pytest.fail("TEST_NEO4J_PASSWORD is required with TEST_NEO4J_URI")
    owner_id = f"test-{uuid4()}"
    driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))
    store = Neo4jMemoryGraphStore(
        driver,
        database=database,
        read_timeout=2.0,
        write_timeout=10.0,
    )
    try:
        driver.verify_connectivity()
        migrate_neo4j_schema(driver, database)
        store.set_available(True)
        edge = MemoryEdge(
            edge_id=str(uuid4()),
            owner_id=owner_id,
            tenant_id="integration",
            relation="FOLLOWS",
            from_memory_id=str(uuid4()),
            to_memory_id=str(uuid4()),
            registry_version="m05-g1-v1",
            active=True,
            source="integration-test",
            created_at=NOW,
            projection_revision=1,
            deletion_generation=0,
        )

        assert store.replace_graph(
            owner_id, "integration", (edge,), 1, 0, "m05-g1-v1"
        ) is GraphProjectionStatus.APPLIED
        snapshot = store.read_edges(
            owner_id,
            "integration",
            (edge.from_memory_id,),
            1,
            0,
            "m05-g1-v1",
        )

        assert tuple(item.edge_id for item in snapshot.edges) == (edge.edge_id,)
    finally:
        with driver.session(database=database) as session:
            session.run(
                """MATCH (memory:M05Memory {owner_id:$owner_id})
                DETACH DELETE memory""",
                owner_id=owner_id,
            ).consume()
            session.run(
                """MATCH (projection:M05GraphProjection {owner_id:$owner_id})
                DETACH DELETE projection""",
                owner_id=owner_id,
            ).consume()
        driver.close()
