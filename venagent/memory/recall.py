"""授权后的短期、长期与 G1 候选召回和排序。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ..conversation.models import ConversationMessage
from ..ownership.ports import OwnershipStore
from .authorization import MemoryAuthorization, MemoryAuthorizer, MemoryRequestSnapshot
from .embedding.index import MemoryIndex
from .errors import MemoryUnauthorized
from .graph import RELATION_REGISTRY_VERSION, SIMILARITY_THRESHOLD, MemoryEdge
from .graph_memory import GraphMemory
from .long_term.facts import MemoryFact, MemorySource
from .long_term.policy import lexical_similarity
from .ports import G1RecallSnapshot, MemoryGraphSnapshotError, MemoryRecallStore
from .ports import MemoryStoreError as StoreError
from .short_term import (
    MemorySummary,
    SummaryBuilder,
    build_summary,
    select_recent_turns,
    split_recent_turns,
    summary_matches,
)

RECALL_POLICY_VERSION = "m05-g1-recall-v2"
LEXICAL_FALLBACK_VERSION = "m05-lexical-eval-v1"
LEXICAL_FALLBACK_ENABLED = True
_CANDIDATE_THRESHOLD = 0.05
_INJECTION_THRESHOLD = 0.10
_SEED_LIMIT = 10
_GRAPH_ONLY_LIMIT = 1


@dataclass(frozen=True)
class _RecallCandidate:
    fact: MemoryFact
    direct_score: float
    effective_score: float
    graph_only: bool


class MemoryRecall:
    def __init__(
        self,
        store: MemoryRecallStore,
        ownership: OwnershipStore,
        graph_memory: GraphMemory,
        authorizer: MemoryAuthorizer,
        local_disabled: set[str],
        now: Callable[[], datetime],
        transition: Callable[[str, str, str], None],
        summary_builder: SummaryBuilder | None = None,
        memory_index: MemoryIndex | None = None,
    ) -> None:
        self._store = store
        self._ownership = ownership
        self._graph_memory = graph_memory
        self._authorizer = authorizer
        self._local_disabled = local_disabled
        self._now = now
        self._transition = transition
        self._summary_builder = summary_builder
        self._memory_index = memory_index

    def long_term_candidates(
        self,
        auth: MemoryAuthorization,
        query: str,
        *,
        limit: int = 5,
        snapshot: MemoryRequestSnapshot | None = None,
    ) -> tuple[MemoryFact, ...]:
        self._authorizer.authorize(auth, write=False, allow_disabled=True)
        current = snapshot or self._authorizer.capture_snapshot(
            auth, allow_disabled=True
        )
        self._authorizer.validate_snapshot(auth, current)
        if not current.enabled:
            return ()
        states = dict(current.capability_states)
        if states.get("memory-long-term") in {"disabled", "unavailable"}:
            return ()
        owner = self._ownership.get_owner(auth.owner_id)
        if owner is None or owner.kind != "user":
            return ()
        now = self._now()
        try:
            self._store.expire_due(now)
        except StoreError:
            self._transition(
                "memory-long-term", "unavailable", "authoritative_store_unavailable"
            )
            return ()
        graph_enabled = self._graph_memory.configured and states.get(
            "memory-graph-g1"
        ) not in {
            "disabled",
            "unavailable",
        }
        try:
            recall = self._store.recall_snapshot(auth.owner_id, auth.tenant_id)
        except StoreError:
            self._transition(
                "memory-long-term",
                "unavailable",
                "authoritative_store_unavailable",
            )
            return ()
        if not self._recall_snapshot_matches(current, recall):
            return ()
        self._transition("memory-long-term", "healthy", "memory_ready")
        sources = {source.source_ref: source for source in recall.sources}
        facts = {
            fact.memory_id: fact
            for fact in recall.facts
            if fact.owner_id == auth.owner_id
            and fact.tenant_id == auth.tenant_id
            and fact.active
            and (fact.valid_until is None or fact.valid_until > now)
            and _has_valid_snapshot_source(auth, fact, sources)
        }
        direct_scores = self._direct_scores(query, facts, states)
        scored = _sort_direct_facts(facts, direct_scores)
        seed_scores = {
            fact.memory_id: score
            for score, fact in scored[:_SEED_LIMIT]
            if score >= _CANDIDATE_THRESHOLD
        }
        edges: tuple[MemoryEdge, ...] = ()
        if graph_enabled and seed_scores:
            try:
                edges = self._graph_memory.recall_edges(
                    auth.owner_id,
                    auth.tenant_id,
                    tuple(seed_scores),
                    recall.authority_revision,
                    recall.settings.deletion_generation,
                )
            except (MemoryGraphSnapshotError, StoreError):
                graph_enabled = False
                self._transition(
                    "memory-graph-g1", "degraded", "graph_store_unavailable"
                )
            else:
                self._transition("memory-graph-g1", "healthy", "memory_ready")
        graph_scores = _similarity_path_scores(
            edges if graph_enabled else (),
            facts,
            seed_scores,
            owner_id=auth.owner_id,
            tenant_id=auth.tenant_id,
        )
        # 图路径只参与相关性重排；安全、生命周期和严格注入门槛均已保留。
        ranked = _rank_recall_candidates(facts, direct_scores, graph_scores)
        selected = _select_recall_candidates(ranked, limit)
        if not self._recall_snapshot_still_current(auth, recall):
            return ()
        return selected

    def _direct_scores(
        self,
        query: str,
        facts: dict[str, MemoryFact],
        states: dict[str, str],
    ) -> dict[str, float]:
        slot = _query_slot(query)
        scores = {
            fact.memory_id: (
                1.0
                if slot is not None and fact.slot == slot
                else lexical_similarity(query, fact.fact)
                if LEXICAL_FALLBACK_ENABLED
                else 0.0
            )
            for fact in facts.values()
        }
        if not facts or self._memory_index is None or states.get("memory-index") in {
            "disabled",
            "unavailable",
        }:
            return scores
        first = next(iter(facts.values()))
        try:
            dense = self._memory_index.search(
                first.owner_id,
                first.tenant_id,
                query,
                limit=max(_SEED_LIMIT, len(facts)),
            )
        except Exception:
            self._transition("memory-embedding", "degraded", "embedding_unavailable")
            self._transition("memory-index", "degraded", "dense_recall_unavailable")
            return scores
        for match in dense:
            if match.memory_id in scores:
                scores[match.memory_id] = max(scores[match.memory_id], match.score)
        self._transition("memory-embedding", "healthy", "embedding_ready")
        self._transition("memory-index", "healthy", "index_ready")
        return scores

    def conversation_context(
        self,
        auth: MemoryAuthorization,
        messages: tuple[ConversationMessage, ...],
        input_message_id: str,
        *,
        token_budget: int = 20_000,
        snapshot: MemoryRequestSnapshot | None = None,
    ) -> tuple[ConversationMessage, ...]:
        """关闭记忆时只允许当前输入；启用时按完整 turn 选取。"""
        self._authorizer.authorize(auth, write=False, allow_disabled=True)
        eligible = tuple(
            item
            for item in messages
            if item.sequence
            <= next(
                source.sequence
                for source in messages
                if source.message_id == input_message_id
            )
        )
        current = snapshot or self._authorizer.capture_snapshot(
            auth, allow_disabled=True
        )
        self._authorizer.validate_snapshot(auth, current)
        if not current.enabled:
            return tuple(
                item for item in eligible if item.message_id == input_message_id
            )
        return select_recent_turns(eligible, token_budget=token_budget)

    def summary_candidates(
        self,
        auth: MemoryAuthorization,
        messages: tuple[ConversationMessage, ...],
        input_message_id: str,
        *,
        token_budget: int = 20_000,
        snapshot: MemoryRequestSnapshot | None = None,
    ) -> tuple[MemorySummary, ...]:
        self._authorizer.authorize(auth, write=False, allow_disabled=True)
        current = snapshot or self._authorizer.capture_snapshot(
            auth, allow_disabled=True
        )
        self._authorizer.validate_snapshot(auth, current)
        if not current.enabled or auth.conversation_id is None:
            return ()
        if dict(current.capability_states).get("memory-short-term") in {
            "disabled",
            "unavailable",
        }:
            return ()
        input_sequence = next(
            item.sequence for item in messages if item.message_id == input_message_id
        )
        eligible = tuple(item for item in messages if item.sequence <= input_sequence)
        recent, older = split_recent_turns(eligible, token_budget=token_budget)
        if not older:
            return ()
        try:
            summary = self._store.get_summary(auth.owner_id, auth.conversation_id)
            if summary is None or not summary_matches(
                summary, eligible, current.deletion_generation
            ):
                summary = build_summary(
                    auth.owner_id,
                    auth.tenant_id,
                    auth.conversation_id,
                    older,
                    recent,
                    deletion_generation=current.deletion_generation,
                    now=self._now(),
                    builder=self._summary_builder,
                )
                if summary is None:
                    self._transition(
                        "memory-short-term", "degraded", "summary_validation_failed"
                    )
                    return ()
                self._store.save_summary(summary)
        except (StoreError, ValueError):
            self._transition("memory-short-term", "degraded", "summary_unavailable")
            return ()
        return (summary,)

    def note_provider_timeout(self, component: str) -> None:
        self._transition(component, "degraded", "provider_timeout")

    def note_provider_ready(self, component: str, reason_code: str) -> None:
        self._transition(component, "healthy", reason_code)

    @staticmethod
    def _recall_snapshot_matches(
        request: MemoryRequestSnapshot, recall: G1RecallSnapshot
    ) -> bool:
        return (
            recall.owner_id == request.owner_id
            and recall.tenant_id == request.tenant_id
            and recall.settings.enabled
            and not recall.settings.purge_pending
            and recall.settings.deletion_generation == request.deletion_generation
            and recall.authority_revision == request.authority_revision
        )

    def _recall_snapshot_still_current(
        self, auth: MemoryAuthorization, recall: G1RecallSnapshot
    ) -> bool:
        try:
            self._authorizer.authorize(auth, write=False, allow_disabled=True)
            settings = self._store.settings(auth.owner_id)
        except (MemoryUnauthorized, StoreError):
            return False
        return (
            auth.owner_id not in self._local_disabled
            and settings.enabled
            and not settings.purge_pending
            and settings.deletion_generation == recall.settings.deletion_generation
            and self._store.authority_revision(auth.owner_id, auth.tenant_id)
            == recall.authority_revision
        )


def _has_valid_snapshot_source(
    auth: MemoryAuthorization,
    fact: MemoryFact,
    sources: dict[str, MemorySource],
) -> bool:
    return any(
        source.active
        and source.owner_id == auth.owner_id
        and source.tenant_id == auth.tenant_id
        for source_ref in fact.source_refs
        for source in (sources.get(source_ref),)
        if source is not None
    )


def _sort_direct_facts(
    facts: dict[str, MemoryFact], direct_scores: dict[str, float]
) -> list[tuple[float, MemoryFact]]:
    return sorted(
        ((direct_scores[memory_id], fact) for memory_id, fact in facts.items()),
        key=lambda item: (
            -item[0],
            -item[1].updated_at.timestamp(),
            item[1].memory_id,
        ),
    )


def _similarity_path_scores(
    edges: tuple[MemoryEdge, ...],
    facts: dict[str, MemoryFact],
    seed_scores: dict[str, float],
    *,
    owner_id: str,
    tenant_id: str,
) -> dict[str, float]:
    path_scores: dict[str, float] = {}
    for edge in edges:
        if not _eligible_similarity_edge(edge, owner_id, tenant_id):
            continue
        for seed_id, neighbor_id in (
            (edge.from_memory_id, edge.to_memory_id),
            (edge.to_memory_id, edge.from_memory_id),
        ):
            if seed_id not in seed_scores or neighbor_id not in facts:
                continue
            score = seed_scores[seed_id] * SIMILARITY_THRESHOLD
            path_scores[neighbor_id] = max(path_scores.get(neighbor_id, 0.0), score)
    return path_scores


def _eligible_similarity_edge(edge: MemoryEdge, owner_id: str, tenant_id: str) -> bool:
    # FOLLOWS 仅表示来源时间线，不作为语义相关性证据。
    return (
        edge.active
        and edge.owner_id == owner_id
        and edge.tenant_id == tenant_id
        and edge.relation == "SIMILAR_TO"
        and edge.registry_version == RELATION_REGISTRY_VERSION
    )


def _rank_recall_candidates(
    facts: dict[str, MemoryFact],
    direct_scores: dict[str, float],
    graph_scores: dict[str, float],
) -> tuple[_RecallCandidate, ...]:
    candidates: list[_RecallCandidate] = []
    for memory_id, fact in facts.items():
        direct_score = direct_scores[memory_id]
        graph_score = graph_scores.get(memory_id, 0.0)
        graph_only = direct_score < _INJECTION_THRESHOLD <= graph_score
        if direct_score < _INJECTION_THRESHOLD and not graph_only:
            continue
        candidates.append(
            _RecallCandidate(
                fact=fact,
                direct_score=direct_score,
                effective_score=graph_score if graph_only else direct_score,
                graph_only=graph_only,
            )
        )
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                -item.effective_score,
                -item.direct_score,
                -item.fact.updated_at.timestamp(),
                item.fact.memory_id,
            ),
        )
    )


def _select_recall_candidates(
    ranked: tuple[_RecallCandidate, ...], limit: int
) -> tuple[MemoryFact, ...]:
    selected: list[MemoryFact] = []
    graph_only_count = 0
    for candidate in ranked:
        if len(selected) >= max(0, limit):
            break
        if candidate.graph_only:
            if graph_only_count >= _GRAPH_ONLY_LIMIT:
                continue
            graph_only_count += 1
        selected.append(candidate.fact)
    return tuple(selected)


def _query_slot(query: str) -> str | None:
    normalized = "".join(query.casefold().split())
    for slot, terms in (
        ("name", ("叫什么", "我的名字", "姓名")),
        ("location", ("住哪里", "住在哪", "所在地")),
        ("occupation", ("职业", "做什么工作")),
        ("project", ("负责什么", "负责哪个", "项目")),
    ):
        if any(term in normalized for term in terms):
            return slot
    return None
