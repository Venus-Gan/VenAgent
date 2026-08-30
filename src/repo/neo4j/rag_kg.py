"""M08 KG 路 Neo4j adapter：实体-块图写入与子图召回。

对齐 AGI-saber：实体节点 (:RagEntity) + chunk 节点 (:RagChunk {pg_id})，
MENTIONS 边（实体 mention chunk）；查询种子=命中实体，apoc.path.subgraphNodes
max_hops=2（clamp≤3），APOC 缺失降级 searchDirect（一跳），老节点 pg_id=0 跳过。
"""

from __future__ import annotations

from typing import Any

from ...rag.kg_extract import KgExtraction
from ...rag.routes import RouteUnavailable

_MENTION_QUERY = """
    MATCH (entity:RagEntity {owner_id:$owner_id, name:$name})
    MATCH (chunk:RagChunk {owner_id:$owner_id, pg_id:$pg_id})
    MERGE (entity)-[m:MENTIONS]->(chunk)
    SET m.document_id=$document_id
"""

_APOC_QUERY = """
    MATCH (seed:RagEntity {owner_id:$owner_id})
    WHERE seed.name IN $seeds
    CALL apoc.path.subgraphNodes(seed, {maxHops:$max_hops}) YIELD node
    WITH seed, node
    WHERE node:RagChunk AND node.pg_id > 0
    RETURN node.pg_id AS pg_id, count(*) AS hops
"""

_DIRECT_QUERY = """
    MATCH (entity:RagEntity {owner_id:$owner_id})
    WHERE entity.name IN $seeds
    MATCH (entity)-[:MENTIONS]->(chunk:RagChunk {owner_id:$owner_id})
    WHERE chunk.pg_id > 0
    RETURN chunk.pg_id AS pg_id, 1 AS hops
"""


class RagKgStore:
    """KG 路图存储：写实体/mention 边，按种子实体召回 chunk pg_id。"""

    def __init__(self, driver: Any, *, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    def configured(self) -> bool:
        return self._driver is not None

    def write_extraction(
        self,
        owner_id: str,
        document_id: str,
        extraction: KgExtraction,
        chunk_ids: list[int],
    ) -> None:
        """为一份文档的抽取结果建实体节点与 mention 边（幂等 MERGE）。"""
        if self._driver is None:
            return
        with self._driver.session(database=self._database) as session:
            for entity in extraction.entities:
                session.run(
                    """
                    MERGE (e:RagEntity {owner_id:$owner_id, name:$name})
                    SET e.type=$type
                    """,
                    owner_id=owner_id,
                    name=entity.name,
                    type=entity.type,
                )
            for pg_id in chunk_ids:
                for entity in extraction.entities:
                    session.run(
                        _MENTION_QUERY,
                        owner_id=owner_id,
                        name=entity.name,
                        pg_id=pg_id,
                        document_id=document_id,
                    )

    def search(
        self,
        owner_id: str,
        seeds: list[str],
        *,
        max_hops: int = 2,
    ) -> dict[int, float]:
        """种子实体子图召回：返回 {pg_id: score}；APOC 缺失自动降级一跳。"""
        if self._driver is None:
            raise RouteUnavailable("graph route is unavailable")
        hops = max(1, min(max_hops, 3))
        try:
            with self._driver.session(database=self._database) as session:
                try:
                    result = session.run(
                        _APOC_QUERY,
                        owner_id=owner_id,
                        seeds=seeds,
                        max_hops=hops,
                    )
                    rows = result.data()
                except Exception:
                    # APOC 未安装：降级为 MENTIONS 一跳召回。
                    rows = session.run(
                        _DIRECT_QUERY, owner_id=owner_id, seeds=seeds
                    ).data()
        except Exception as exc:
            raise RouteUnavailable("graph route is unavailable") from exc
        return {int(row["pg_id"]): float(row["hops"]) for row in rows}

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
