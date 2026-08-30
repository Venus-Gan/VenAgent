"""Explicit M05 Neo4j schema migration and compatibility checks."""

from __future__ import annotations

from typing import Any

from ..errors import PersistenceError

NEO4J_SCHEMA_VERSION = 1
_CONSTRAINT_NAMES = (
    "m05_memory_identity",
    "m05_projection_identity",
    "m05_schema_component",
)

_SCHEMA_QUERIES = (
    """CREATE CONSTRAINT m05_memory_identity IF NOT EXISTS
    FOR (memory:M05Memory)
    REQUIRE (memory.owner_id,memory.tenant_id,memory.memory_id) IS UNIQUE""",
    """CREATE CONSTRAINT m05_projection_identity IF NOT EXISTS
    FOR (projection:M05GraphProjection)
    REQUIRE (projection.owner_id,projection.tenant_id) IS UNIQUE""",
    """CREATE CONSTRAINT m05_schema_component IF NOT EXISTS
    FOR (schema:M05GraphSchema) REQUIRE schema.component IS UNIQUE""",
)


def migrate_neo4j_schema(driver: Any, database: str) -> None:
    try:
        with driver.session(database=database) as session:
            for query in _SCHEMA_QUERIES:
                session.run(query).consume()
            session.run(
                """MERGE (schema:M05GraphSchema {component:'m05-graph-memory'})
                SET schema.version=$version,schema.updated_at=datetime()""",
                version=NEO4J_SCHEMA_VERSION,
            ).consume()
    except Exception as exc:
        raise PersistenceError("Neo4j schema migration failed") from exc


def validate_neo4j_schema(driver: Any, database: str) -> None:
    try:
        with driver.session(database=database) as session:
            row = session.run(
                """MATCH (schema:M05GraphSchema {component:'m05-graph-memory'})
                RETURN schema.version AS version"""
            ).single()
            constraints = {
                str(item["name"])
                for item in session.run(
                    """SHOW CONSTRAINTS YIELD name
                    WHERE name IN $names RETURN name""",
                    names=list(_CONSTRAINT_NAMES),
                )
            }
        if (
            row is None
            or int(row["version"]) != NEO4J_SCHEMA_VERSION
            or constraints != set(_CONSTRAINT_NAMES)
        ):
            raise PersistenceError("unsupported Neo4j graph schema")
    except PersistenceError:
        raise
    except Exception as exc:
        raise PersistenceError("unable to validate Neo4j graph schema") from exc


def migrate_neo4j_database(
    uri: str,
    user: str,
    password: str,
    database: str,
    *,
    connection_timeout: float,
) -> None:
    if not uri.strip() or not user.strip() or not password or not database.strip():
        raise PersistenceError("Neo4j migration configuration is incomplete")
    driver = None
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            connection_timeout=connection_timeout,
        )
        driver.verify_connectivity()
        migrate_neo4j_schema(driver, database)
    except PersistenceError:
        raise
    except Exception as exc:
        raise PersistenceError("Neo4j migration failed") from exc
    finally:
        if driver is not None:
            driver.close()
