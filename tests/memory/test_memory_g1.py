"""memory G1 图语义契约（服务层权威）：图投影生命周期、图上下文召回、次要过滤（原 test_memory_context.py 拆分五）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from tests.memory._store import InMemoryMemoryStore
from venagent.memory.graph_memory import MemoryEdge, build_g1_edges, replay_g1_edges
from venagent.memory.long_term.facts import MemoryFact
from venagent.memory.management import (
    MemoryCapabilityRegistry,
    MemoryCapabilityStatus,
)
from venagent.memory.ports import G1GraphSnapshot
from venagent.memory.ports import MemoryStoreError as StoreError
from venagent.memory.service import MemoryService
from venagent.repo.inmemory import (
    InMemoryOwnershipStore as MemoryOwnershipStore,
)

NOW = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)

def test_fact_update_delete_source_and_g1_edges_are_lifecycle_safe(memory_service) -> None:
    service, store, actor, _state = memory_service()
    auth = service.command_authorization(actor)
    first = service.remember(
        auth,
        "记住，我叫小维",
        source_ref="message:1",
        source_order=1,
        explicit=True,
    )
    second = service.remember(
        auth,
        "我负责小维项目",
        source_ref="message:2",
        source_order=2,
        explicit=False,
    )

    assert first is not None and second is not None
    assert first.index_status == "ready" and second.index_status == "ready"
    assert service.status(auth).graph_pending == 1
    service.process_pending_jobs()
    edges = store.edges(actor.owner_id, "default")
    assert any(
        edge.relation == "FOLLOWS"
        and edge.from_memory_id == first.memory_id
        and edge.to_memory_id == second.memory_id
        and edge.registry_version == "m05-g1-v1"
        for edge in edges
    )

    replacement = service.update(auth, first.memory_id, "我叫维安")
    service.process_pending_jobs()
    assert store.get_fact(actor.owner_id, first.memory_id).status == "superseded"
    assert replacement.supersedes_id == first.memory_id
    assert any(
        edge.from_memory_id == first.memory_id and edge.active is False
        for edge in store.edges(actor.owner_id, "default")
    )

    service.forget(auth, replacement.memory_id)
    service.process_pending_jobs()
    assert service.list(auth).items == (second,)
    tombstone = store.get_fact(actor.owner_id, replacement.memory_id)
    assert tombstone is not None
    assert (tombstone.subject, tombstone.slot, tombstone.fact) == ("", "", "")
    assert all(
        replacement.memory_id not in {edge.from_memory_id, edge.to_memory_id}
        for edge in store.edges(actor.owner_id, "default")
        if edge.active
    )
    service.delete_all(auth)
    superseded = store.get_fact(actor.owner_id, first.memory_id)
    assert superseded is not None and superseded.fact == ""

def test_graph_pending_is_visible_while_facts_remain_recallable(memory_service) -> None:
    class RecoverableGraphStore(InMemoryMemoryStore):
        fail_graph = True

        def replace_graph(
            self,
            owner_id,
            tenant_id,
            edges,
            target_revision,
            deletion_generation,
            registry_version,
        ):
            if self.fail_graph:
                raise StoreError("injected graph failure")
            return super().replace_graph(
                owner_id,
                tenant_id,
                edges,
                target_revision,
                deletion_generation,
                registry_version,
            )

    current = [NOW]
    _unused, _store, actor, state = memory_service()
    store = RecoverableGraphStore(durable=True)
    registry = MemoryCapabilityRegistry(
        (
            MemoryCapabilityStatus("memory-extraction", "healthy", "memory_ready"),
            MemoryCapabilityStatus("memory-graph-g1", "healthy", "memory_ready"),
        )
    )
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: current[0],
        capability_registry=registry,
    )
    auth = service.command_authorization(actor)
    fact = service.remember(
        auth,
        "我住在杭州",
        source_ref="message:index",
        source_order=1,
        explicit=False,
    )

    assert fact is not None and fact.index_status == "ready"
    assert service.status(auth).index_pending == 0
    assert service.status(auth).graph_pending == 1
    assert service.context_blocks(auth, "杭州")

    service.process_pending_jobs()
    assert service.status(auth).graph_pending == 1
    assert registry.get("memory-graph-g1").state == "degraded"
    assert registry.get("memory-extraction").state == "healthy"
    store.fail_graph = False
    current[0] += timedelta(seconds=2)
    service.process_pending_jobs()
    recovered = service.show(auth, fact.memory_id)
    assert recovered.index_status == "ready"
    assert service.status(auth).graph_pending == 0
    assert registry.get("memory-graph-g1").state == "healthy"
    assert service.context_blocks(auth, "杭州")

def test_graph_registry_replay_reports_compatibility_changes(memory_service) -> None:
    service, store, actor, _state = memory_service()
    auth = service.command_authorization(actor)
    service.remember(
        auth, "我住在杭州", source_ref="message:1", source_order=1, explicit=False
    )
    service.remember(
        auth, "我负责火星项目", source_ref="message:2", source_order=2, explicit=False
    )
    facts = store.active_facts(actor.owner_id, "default")
    sources = {
        ref: store.source(actor.owner_id, ref)
        for fact in facts
        for ref in fact.source_refs
    }
    valid_sources = {key: value for key, value in sources.items() if value is not None}
    previous = build_g1_edges(facts, valid_sources)

    replayed, report = replay_g1_edges(facts, valid_sources, previous)

    assert replayed == previous
    assert report.retained_edges == report.previous_active_edges
    assert report.added_edges == 0 and report.removed_edges == 0

def test_g1_similarity_path_adds_at_most_one_deterministic_neighbor(memory_service, save_recall_fact, recall_edge, injected_graph_snapshot) -> None:
    class InjectedGraphStore(InMemoryMemoryStore):
        injected: tuple[MemoryEdge, ...] = ()

        def read_edges(
            self,
            owner_id,
            tenant_id,
            seed_ids,
            expected_revision,
            deletion_generation,
            registry_version,
        ):
            del seed_ids
            return injected_graph_snapshot(
                owner_id,
                tenant_id,
                expected_revision,
                deletion_generation,
                registry_version,
                self.injected,
            )

    _unused, _store, actor, state = memory_service()
    store = InjectedGraphStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)
    seed = save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0002-000000000001",
        "alpha beta coordinator",
        1,
    )
    first_neighbor = save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0002-000000000002",
        "technical architecture",
        2,
    )
    newest_neighbor = save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0002-000000000003",
        "release governance",
        3,
    )
    store.injected = (
        recall_edge(seed, first_neighbor, "SIMILAR_TO", "edge:similar:first"),
        recall_edge(seed, newest_neighbor, "SIMILAR_TO", "edge:similar:newest"),
    )

    first = service.context_blocks(auth, "coordinator", limit=5)
    replay = service.context_blocks(auth, "coordinator", limit=5)

    assert replay == first
    assert tuple(block.block_id for block in first) == (
        f"memory:{seed.memory_id}",
        f"memory:{newest_neighbor.memory_id}",
    )

def test_g1_follows_and_weak_similarity_path_do_not_inject_neighbors(memory_service, save_recall_fact, recall_edge, injected_graph_snapshot) -> None:
    class InjectedGraphStore(InMemoryMemoryStore):
        injected: tuple[MemoryEdge, ...] = ()

        def read_edges(
            self,
            owner_id,
            tenant_id,
            seed_ids,
            expected_revision,
            deletion_generation,
            registry_version,
        ):
            del seed_ids
            return injected_graph_snapshot(
                owner_id,
                tenant_id,
                expected_revision,
                deletion_generation,
                registry_version,
                self.injected,
            )

    _unused, _store, actor, state = memory_service()
    store = InjectedGraphStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)
    follows_seed = save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0003-000000000001",
        "alpha beta coordinator",
        1,
    )
    follows_neighbor = save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0003-000000000002",
        "technical architecture",
        2,
    )
    weak_seed = save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0003-000000000003",
        "coordinator abcdefghijklmnopqrstuvwxyz 0123456789",
        3,
    )
    weak_neighbor = save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0003-000000000004",
        "release governance",
        4,
    )
    store.injected = (
        recall_edge(follows_seed, follows_neighbor, "FOLLOWS", "edge:follows:ignored"),
        recall_edge(weak_seed, weak_neighbor, "SIMILAR_TO", "edge:similar:weak"),
    )

    blocks = service.context_blocks(auth, "coordinator", limit=5)

    block_ids = {block.block_id for block in blocks}
    assert f"memory:{follows_seed.memory_id}" in block_ids
    assert f"memory:{weak_seed.memory_id}" in block_ids
    assert f"memory:{follows_neighbor.memory_id}" not in block_ids
    assert f"memory:{weak_neighbor.memory_id}" not in block_ids

def test_g1_does_not_expand_a_second_hop(memory_service, save_recall_fact, recall_edge, injected_graph_snapshot) -> None:
    class InjectedGraphStore(InMemoryMemoryStore):
        injected: tuple[MemoryEdge, ...] = ()

        def read_edges(
            self,
            owner_id,
            tenant_id,
            seed_ids,
            expected_revision,
            deletion_generation,
            registry_version,
        ):
            del seed_ids
            return injected_graph_snapshot(
                owner_id,
                tenant_id,
                expected_revision,
                deletion_generation,
                registry_version,
                self.injected,
            )

    _unused, _store, actor, state = memory_service()
    store = InjectedGraphStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)
    seed = save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0004-000000000001",
        "alpha beta coordinator",
        1,
    )
    first_hop = save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0004-000000000002",
        "technical architecture",
        2,
    )
    second_hop = save_recall_fact(
        store,
        actor.owner_id,
        "00000000-0000-0000-0004-000000000003",
        "release governance",
        3,
    )
    store.injected = (
        recall_edge(seed, first_hop, "SIMILAR_TO", "edge:first-hop"),
        recall_edge(first_hop, second_hop, "SIMILAR_TO", "edge:second-hop"),
    )

    block_ids = {
        block.block_id for block in service.context_blocks(auth, "coordinator")
    }

    assert f"memory:{first_hop.memory_id}" in block_ids
    assert f"memory:{second_hop.memory_id}" not in block_ids

def test_graph_snapshot_failure_falls_back_to_direct_facts(memory_service) -> None:
    class FailingGraphStore(InMemoryMemoryStore):
        fail_graph = False

        def read_edges(
            self,
            owner_id,
            tenant_id,
            seed_ids,
            expected_revision,
            deletion_generation,
            registry_version,
        ):
            if self.fail_graph:
                raise StoreError("injected graph read failure")
            return super().read_edges(
                owner_id,
                tenant_id,
                seed_ids,
                expected_revision,
                deletion_generation,
                registry_version,
            )

    _unused, _store, actor, state = memory_service()
    store = FailingGraphStore(durable=True)
    registry = MemoryCapabilityRegistry(
        (
            MemoryCapabilityStatus("memory-long-term", "healthy", "ready"),
            MemoryCapabilityStatus("memory-graph-g1", "healthy", "ready"),
        )
    )
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
        capability_registry=registry,
    )
    auth = service.command_authorization(actor)
    fact = service.remember(
        auth,
        "我住在杭州",
        source_ref="message:graph-fallback",
        source_order=1,
        explicit=False,
    )
    assert fact is not None
    store.fail_graph = True

    blocks = service.context_blocks(auth, "杭州")

    assert tuple(block.block_id for block in blocks) == (f"memory:{fact.memory_id}",)
    assert registry.get("memory-graph-g1").state == "degraded"

def test_secondary_filter_rejects_cross_owner_adapter_results(memory_service) -> None:
    class CrossOwnerStore(InMemoryMemoryStore):
        foreign: MemoryFact | None = None

        def active_facts(self, owner_id, tenant_id):
            values = super().active_facts(owner_id, tenant_id)
            return values + ((self.foreign,) if self.foreign is not None else ())

    _unused, _store, actor, state = memory_service()
    store = CrossOwnerStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)
    own = service.remember(
        auth,
        "我住在杭州",
        source_ref="message:own",
        source_order=1,
        explicit=False,
    )
    assert own is not None
    store.foreign = replace(
        own,
        memory_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        owner_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        fact="其他 owner 负责秘密项目",
    )

    blocks = service.context_blocks(auth, "项目 杭州")

    assert all("秘密项目" not in block.content for block in blocks)
    assert any("杭州" in block.content for block in blocks)

def test_secondary_filter_rejects_unknown_graph_relation_and_registry(memory_service) -> None:
    class UnknownEdgeStore(InMemoryMemoryStore):
        injected: MemoryEdge | None = None

        def read_edges(
            self,
            owner_id,
            tenant_id,
            seed_ids,
            expected_revision,
            deletion_generation,
            registry_version,
        ):
            del seed_ids
            edges = (self.injected,) if self.injected is not None else ()
            return G1GraphSnapshot(
                owner_id,
                tenant_id,
                expected_revision,
                deletion_generation,
                registry_version,
                tuple(
                    replace(
                        edge,
                        projection_revision=expected_revision,
                        deletion_generation=deletion_generation,
                    )
                    for edge in edges
                ),
            )

    _unused, _store, actor, state = memory_service()
    store = UnknownEdgeStore(durable=True)
    service = MemoryService(
        store,
        MemoryOwnershipStore(state, account_available=True, mode="durable"),
        cursor_secret="x" * 32,
        clock=lambda: NOW,
    )
    auth = service.command_authorization(actor)
    first = service.remember(
        auth, "我住在杭州", source_ref="message:g1", source_order=1, explicit=False
    )
    second = service.remember(
        auth,
        "我负责火星项目",
        source_ref="message:g2",
        source_order=2,
        explicit=False,
    )
    assert first is not None and second is not None
    store.injected = MemoryEdge(
        "unknown-edge",
        actor.owner_id,
        "default",
        "SIMILAR_TO",
        first.memory_id,
        second.memory_id,
        "unknown-registry",
        True,
        "injected",
        NOW,
    )

    blocks = service.context_blocks(auth, "杭州")

    assert any(first.memory_id in block.block_id for block in blocks)
    assert all(second.memory_id not in block.block_id for block in blocks)