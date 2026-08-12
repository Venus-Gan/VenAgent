"""G1 记忆条目图的版本化确定性构建。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Literal

from .long_term import MemoryFact, MemorySource
from .long_term.policy import lexical_similarity

RELATION_REGISTRY_VERSION = "m05-g1-v1"
SIMILARITY_THRESHOLD = 0.45
RelationKind = Literal["FOLLOWS", "SIMILAR_TO"]


@dataclass(frozen=True)
class MemoryEdge:
    edge_id: str
    owner_id: str
    tenant_id: str
    relation: RelationKind
    from_memory_id: str
    to_memory_id: str
    registry_version: str
    active: bool
    source: str
    created_at: datetime
    projection_revision: int = 0
    deletion_generation: int = 0


@dataclass(frozen=True)
class GraphReplayReport:
    from_versions: tuple[str, ...]
    to_version: str
    previous_active_edges: int
    replayed_active_edges: int
    retained_edges: int
    added_edges: int
    removed_edges: int


def build_g1_edges(
    facts: tuple[MemoryFact, ...], sources: dict[str, MemorySource]
) -> tuple[MemoryEdge, ...]:
    active = tuple(item for item in facts if item.active)
    edges: list[MemoryEdge] = []
    timelines: dict[tuple[str, str, str], list[tuple[MemoryFact, MemorySource]]] = (
        defaultdict(list)
    )
    for fact in active:
        for source_ref in fact.source_refs:
            source = sources.get(source_ref)
            if source is None or not source.active:
                continue
            timeline = source.conversation_id or source.source_ref.rsplit(":", 1)[0]
            timelines[(fact.owner_id, fact.tenant_id, timeline)].append((fact, source))
    for timeline_items in timelines.values():
        ordered = sorted(
            timeline_items,
            key=lambda item: (
                item[1].source_order,
                item[0].created_at,
                item[0].memory_id,
            ),
        )
        unique: list[MemoryFact] = []
        for fact, _source in ordered:
            if not unique or unique[-1].memory_id != fact.memory_id:
                unique.append(fact)
        for left, right in zip(unique, unique[1:]):
            edges.append(_edge("FOLLOWS", left, right, "source-timeline"))
    for index, left in enumerate(active):
        for right in active[index + 1 :]:
            if lexical_similarity(left.fact, right.fact) < SIMILARITY_THRESHOLD:
                continue
            first, second = sorted((left, right), key=lambda item: item.memory_id)
            edges.append(_edge("SIMILAR_TO", first, second, "lexical-bigram-v1"))
    return tuple(sorted(edges, key=lambda item: item.edge_id))


def replay_g1_edges(
    facts: tuple[MemoryFact, ...],
    sources: dict[str, MemorySource],
    previous: tuple[MemoryEdge, ...],
) -> tuple[tuple[MemoryEdge, ...], GraphReplayReport]:
    """从权威事实与来源重放当前注册表，并报告版本兼容变化。"""
    replayed = build_g1_edges(facts, sources)
    before = {item.edge_id for item in previous if item.active}
    after = {item.edge_id for item in replayed if item.active}
    return replayed, GraphReplayReport(
        from_versions=tuple(sorted({item.registry_version for item in previous})),
        to_version=RELATION_REGISTRY_VERSION,
        previous_active_edges=len(before),
        replayed_active_edges=len(after),
        retained_edges=len(before & after),
        added_edges=len(after - before),
        removed_edges=len(before - after),
    )


def _edge(
    relation: str, left: MemoryFact, right: MemoryFact, source: str
) -> MemoryEdge:
    identity = "|".join(
        (
            RELATION_REGISTRY_VERSION,
            relation,
            left.owner_id,
            left.tenant_id,
            left.memory_id,
            right.memory_id,
        )
    )
    return MemoryEdge(
        edge_id=sha256(identity.encode("utf-8")).hexdigest()[:32],
        owner_id=left.owner_id,
        tenant_id=left.tenant_id,
        relation=relation,  # type: ignore[arg-type]
        from_memory_id=left.memory_id,
        to_memory_id=right.memory_id,
        registry_version=RELATION_REGISTRY_VERSION,
        active=True,
        source=source,
        created_at=max(left.updated_at, right.updated_at),
    )
