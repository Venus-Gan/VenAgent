"""tests 专用 in-memory MemoryStore 双（替代已删除的 repo/temporary/memory 镜像）。

语义对齐 repo/postgresql/memory 生产 adapter：
- 写操作（active save/replace/add_source/deactivate/revoke/expire/set_enabled changed）bump authority_revision 并入队 project job；
- delete_all/confirm_delete_all 置 purge_pending=True、deletion_generation+1、入队 purge job；
- claim_jobs 30 秒租约 + claim_token fencing；enqueue_job 按 idempotency_key 去重；
- settings() 派生 pending/failed/index/graph counts（与 PG 统计口径一致）；
- recall_snapshot 全程持同一把锁（含子类可覆盖的 active_facts/settings 调用点）。
同时实现 MemoryGraphStore（replace_graph/read_edges/purge_graph）与 MemoryIndexStore
（upsert_index/index_records/delete_index）面，供 service/graph/index 测试直接装配。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from threading import RLock
from uuid import uuid4

from src.memory.embedding.index import MemoryIndexRecord
from src.memory.graph_memory import MemoryEdge
from src.memory.jobs import MemoryJob
from src.memory.long_term.facts import MemoryFact, MemorySource
from src.memory.management import MemorySettings
from src.memory.ports import (
    ConsolidationCursor,
    G1GraphSnapshot,
    G1RecallSnapshot,
    GraphProjectionStatus,
    MemoryStoreError,
)
from src.memory.short_term import MemorySummary


def _token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _ids_hash(values: tuple[str, ...]) -> str:
    return sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()


class _Confirmation:
    __slots__ = ("owner_id", "operation", "target_ref", "state_hash", "expires_at", "consumed")

    def __init__(
        self,
        owner_id: str,
        operation: str,
        target_ref: str,
        state_hash: str,
        expires_at: datetime,
    ) -> None:
        self.owner_id = owner_id
        self.operation = operation
        self.target_ref = target_ref
        self.state_hash = state_hash
        self.expires_at = expires_at
        self.consumed = False


class InMemoryMemoryStore:
    """MemoryStore + MemoryGraphStore + MemoryIndexStore 的最小 in-memory 双。"""

    configured = True

    def __init__(self, *, durable: bool = False) -> None:
        self.durable = durable
        self._lock = RLock()
        self._settings: dict[str, MemorySettings] = {}
        self._facts: dict[tuple[str, str], MemoryFact] = {}
        self._sources: dict[tuple[str, str], MemorySource] = {}
        self._authority: dict[tuple[str, str], int] = {}
        self._jobs: dict[str, MemoryJob] = {}
        self._job_keys: dict[str, str] = {}
        self._confirmations: dict[str, _Confirmation] = {}
        self._summaries: dict[tuple[str, str], MemorySummary] = {}
        self._edges: dict[tuple[str, str], tuple[MemoryEdge, ...]] = {}
        self._applied_revision: dict[tuple[str, str], int] = {}
        self._graph_generation: dict[tuple[str, str], int] = {}
        self._index: dict[str, MemoryIndexRecord] = {}
        self._consolidation: dict[tuple[str, str, str], ConsolidationCursor] = {}

    # ---------------------------------------------------------------- 授权面

    def enabled(self, owner_id: str) -> bool:
        return self.settings(owner_id).enabled

    def settings(self, owner_id: str) -> MemorySettings:
        with self._lock:
            base = self._settings.get(owner_id)
            pending = failed = graph_pending = graph_failed = 0
            for job in self._jobs.values():
                if job.owner_id != owner_id:
                    continue
                if job.status in {"pending", "running"}:
                    pending += 1
                    if job.operation in {"project", "purge"}:
                        graph_pending += 1
                elif job.status == "failed":
                    failed += 1
                    if job.operation in {"project", "purge"}:
                        graph_failed += 1
            index_pending = sum(
                1
                for fact in self._facts.values()
                if fact.owner_id == owner_id
                and fact.status == "active"
                and fact.index_status != "ready"
            )
            return MemorySettings(
                enabled=base.enabled if base is not None else True,
                deletion_generation=(
                    base.deletion_generation if base is not None else 0
                ),
                purge_pending=base.purge_pending if base is not None else False,
                pending_jobs=pending,
                failed_jobs=failed,
                index_pending=index_pending,
                last_error_code=base.last_error_code if base is not None else None,
                graph_pending=graph_pending,
                graph_failed=graph_failed,
            )

    def authority_revision(self, owner_id: str, tenant_id: str) -> int:
        with self._lock:
            return self._authority.get((owner_id, tenant_id), 0)

    def set_enabled(self, owner_id: str, enabled: bool, now: datetime) -> None:
        with self._lock:
            current = self._settings.get(owner_id)
            if enabled and current is not None and current.purge_pending:
                raise MemoryStoreError("memory purge is pending")
            changed = current is None or current.enabled != enabled
            self._settings[owner_id] = MemorySettings(
                enabled=enabled,
                deletion_generation=(
                    current.deletion_generation if current is not None else 0
                ),
                purge_pending=current.purge_pending if current is not None else False,
                last_error_code=(
                    current.last_error_code if current is not None else None
                ),
            )
            if changed:
                tenants = {
                    fact.tenant_id
                    for fact in self._facts.values()
                    if fact.owner_id == owner_id
                } | {
                    source.tenant_id
                    for source in self._sources.values()
                    if source.owner_id == owner_id
                }
                for tenant in tenants or {"default"}:
                    self._bump(owner_id, tenant, now)

    def set_index_status(
        self, owner_id: str, memory_ids: tuple[str, ...], status: str, now: datetime
    ) -> None:
        if not memory_ids:
            return
        with self._lock:
            for memory_id in memory_ids:
                key = (owner_id, memory_id)
                fact = self._facts.get(key)
                if fact is not None and fact.status == "active":
                    self._facts[key] = replace(fact, index_status=status, updated_at=now)  # type: ignore[arg-type]

    def list_facts(
        self,
        owner_id: str,
        tenant_id: str,
        *,
        before: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[MemoryFact, ...]:
        with self._lock:
            rows = sorted(
                (
                    fact
                    for fact in self._facts.values()
                    if fact.owner_id == owner_id
                    and fact.tenant_id == tenant_id
                    and fact.status == "active"
                    and (
                        before is None
                        or (fact.updated_at, fact.memory_id) < before
                    )
                ),
                key=lambda item: (item.updated_at, item.memory_id),
                reverse=True,
            )
            return tuple(rows[:limit])

    def get_fact(self, owner_id: str, memory_id: str) -> MemoryFact | None:
        with self._lock:
            return self._facts.get((owner_id, memory_id))

    def find_active_by_slot(
        self, owner_id: str, tenant_id: str, subject: str, slot: str
    ) -> MemoryFact | None:
        with self._lock:
            rows = [
                fact
                for fact in self._facts.values()
                if fact.owner_id == owner_id
                and fact.tenant_id == tenant_id
                and fact.subject == subject
                and fact.slot == slot
                and fact.status == "active"
            ]
            if not rows:
                return None
            return sorted(
                rows, key=lambda item: (item.updated_at, item.memory_id), reverse=True
            )[0]

    def resolve_quarantine(
        self,
        owner_id: str,
        tenant_id: str,
        subject: str,
        slot: str,
        chosen_fact: str,
        now: datetime,
    ) -> int:
        del chosen_fact
        with self._lock:
            count = 0
            for key, fact in list(self._facts.items()):
                if (
                    fact.owner_id == owner_id
                    and fact.tenant_id == tenant_id
                    and fact.subject == subject
                    and fact.slot == slot
                    and fact.status == "quarantine"
                ):
                    self._facts[key] = replace(fact, status="superseded", updated_at=now)  # type: ignore[arg-type]
                    count += 1
            return count

    # ---------------------------------------------------------------- 写面

    def _insert_source(self, source: MemorySource) -> None:
        existing = self._sources.get((source.owner_id, source.source_ref))
        if existing is not None:
            return
        owner_of_ref = {
            (owner, source_ref)
            for (owner, source_ref) in self._sources
            if source_ref == source.source_ref
        }
        if owner_of_ref:
            raise MemoryStoreError("memory source belongs to another owner")
        self._sources[(source.owner_id, source.source_ref)] = source

    def save_fact(
        self, fact: MemoryFact, source: MemorySource, now: datetime
    ) -> MemoryFact:
        with self._lock:
            self._insert_source(source)
            self._facts[(fact.owner_id, fact.memory_id)] = fact
            if fact.active:
                self._bump(fact.owner_id, fact.tenant_id, now)
            return fact

    def add_source(
        self, fact: MemoryFact, source: MemorySource, now: datetime
    ) -> MemoryFact:
        with self._lock:
            self._insert_source(source)
            key = (fact.owner_id, fact.memory_id)
            current = self._facts[key]
            refs = (
                current.source_refs
                if source.source_ref in current.source_refs
                else current.source_refs + (source.source_ref,)
            )
            refreshed = replace(current, source_refs=refs, updated_at=now)
            self._facts[key] = refreshed
            self._bump(fact.owner_id, fact.tenant_id, now)
            return refreshed

    def replace_fact(
        self,
        previous: MemoryFact,
        replacement: MemoryFact,
        source: MemorySource,
        now: datetime,
    ) -> MemoryFact:
        with self._lock:
            key = (previous.owner_id, previous.memory_id)
            current = self._facts.get(key)
            if current is None or current.status != "active":
                raise MemoryStoreError("memory fact is no longer active")
            self._facts[key] = replace(current, status="superseded", updated_at=now)  # type: ignore[arg-type]
            self._insert_source(source)
            self._facts[(replacement.owner_id, replacement.memory_id)] = replacement
            self._bump(replacement.owner_id, replacement.tenant_id, now)
            return replacement

    def deactivate_fact(
        self, owner_id: str, memory_id: str, status: str, now: datetime
    ) -> bool:
        with self._lock:
            key = (owner_id, memory_id)
            fact = self._facts.get(key)
            if fact is None or fact.status != "active":
                return False
            self._facts[key] = replace(
                fact,
                status=status,  # type: ignore[arg-type]
                subject="",
                slot="",
                fact="",
                sensitivity="redacted",
                updated_at=now,
            )
            self._bump(owner_id, fact.tenant_id, now)
            return True

    def delete_all(self, owner_id: str, now: datetime) -> int:
        with self._lock:
            return self._delete_all_locked(owner_id, now)

    def revoke_source(self, owner_id: str, source_ref: str, now: datetime) -> int:
        with self._lock:
            return self._revoke_source_locked(owner_id, source_ref, now)

    def source(self, owner_id: str, source_ref: str) -> MemorySource | None:
        with self._lock:
            return self._sources.get((owner_id, source_ref))

    def source_impact(self, owner_id: str, source_ref: str) -> tuple[str, ...]:
        with self._lock:
            source = self._sources.get((owner_id, source_ref))
            if source is None or not source.active:
                return ()
            return tuple(
                sorted(
                    fact.memory_id
                    for fact in self._facts.values()
                    if fact.owner_id == owner_id
                    and fact.status == "active"
                    and source_ref in fact.source_refs
                )
            )

    def issue_confirmation(
        self,
        owner_id: str,
        operation: str,
        target_ref: str,
        token_hash: str,
        state_hash: str,
        expires_at: datetime,
        now: datetime,
    ) -> None:
        del now
        with self._lock:
            self._confirmations[token_hash] = _Confirmation(
                owner_id, operation, target_ref, state_hash, expires_at
            )

    def confirm_delete_all(
        self, owner_id: str, token_hash: str, state_hash: str, now: datetime
    ) -> int | None:
        with self._lock:
            if not self._consume(owner_id, "delete-all", "*", token_hash, state_hash, now):
                return None
            if _ids_hash(self._active_ids_locked(owner_id)) != state_hash:
                return None
            return self._delete_all_locked(owner_id, now)

    def confirm_revoke_source(
        self,
        owner_id: str,
        source_ref: str,
        token_hash: str,
        state_hash: str,
        now: datetime,
    ) -> int | None:
        with self._lock:
            if not self._consume(
                owner_id, "revoke-source", source_ref, token_hash, state_hash, now
            ):
                return None
            impact = self.source_impact(owner_id, source_ref)
            if _ids_hash(impact) != state_hash:
                return None
            return self._revoke_source_locked(owner_id, source_ref, now)

    def active_facts(self, owner_id: str, tenant_id: str) -> tuple[MemoryFact, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        fact
                        for fact in self._facts.values()
                        if fact.owner_id == owner_id
                        and fact.tenant_id == tenant_id
                        and fact.status == "active"
                    ),
                    key=lambda item: (item.created_at, item.memory_id),
                )
            )

    def expire_due(self, now: datetime) -> int:
        with self._lock:
            affected: set[tuple[str, str]] = set()
            count = 0
            for key, fact in list(self._facts.items()):
                if (
                    fact.status in {"active", "quarantine"}
                    and fact.valid_until is not None
                    and fact.valid_until <= now
                ):
                    self._facts[key] = replace(
                        fact,
                        status="expired",  # type: ignore[arg-type]
                        subject="",
                        slot="",
                        fact="",
                        sensitivity="redacted",
                        updated_at=now,
                    )
                    affected.add((fact.owner_id, fact.tenant_id))
                    count += 1
            for owner_id, tenant_id in affected:
                self._bump(owner_id, tenant_id, now)
            return count

    # ---------------------------------------------------------------- 召回面

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
                        key=lambda item: item.source_ref,
                    )
                ),
                authority_revision=self._authority.get((owner_id, tenant_id), 0),
            )

    def get_summary(
        self, owner_id: str, conversation_id: str
    ) -> MemorySummary | None:
        with self._lock:
            return self._summaries.get((owner_id, conversation_id))

    def save_summary(self, summary: MemorySummary) -> None:
        with self._lock:
            self._summaries[(summary.owner_id, summary.conversation_id)] = summary

    # ---------------------------------------------------------------- 任务面

    def enqueue_job(self, job: MemoryJob) -> bool:
        with self._lock:
            if job.idempotency_key in self._job_keys:
                return False
            self._job_keys[job.idempotency_key] = job.job_id
            self._jobs[job.job_id] = job
            return True

    def claim_jobs(self, now: datetime, *, limit: int) -> tuple[MemoryJob, ...]:
        with self._lock:
            candidates = sorted(
                (
                    job
                    for job in self._jobs.values()
                    if job.status in {"pending", "running"}
                    and job.available_at <= now
                ),
                key=lambda item: (item.available_at, item.created_at, item.job_id),
            )
            claimed: list[MemoryJob] = []
            for job in candidates[:limit]:
                claimed_job = replace(
                    job,
                    status="running",
                    attempts=job.attempts + 1,
                    available_at=now + timedelta(seconds=30),
                    claim_token=str(uuid4()),
                )
                self._jobs[job.job_id] = claimed_job
                claimed.append(claimed_job)
            return tuple(claimed)

    def complete_job(self, job_id: str, claim_token: str, now: datetime) -> bool:
        return self._update_job_terminal(job_id, claim_token, "succeeded", now)

    def cancel_job(self, job_id: str, claim_token: str, now: datetime) -> bool:
        return self._update_job_terminal(job_id, claim_token, "cancelled", now)

    def retry_job(
        self,
        job_id: str,
        claim_token: str,
        error_code: str,
        available_at: datetime,
        now: datetime,
    ) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "running" or job.claim_token != claim_token:
                return False
            graph_job = job.operation in {"project", "purge"}
            exhausted = not graph_job and job.attempts >= job.max_attempts
            self._jobs[job_id] = replace(
                job,
                status="failed" if exhausted else "pending",
                available_at=available_at,
                claim_token=None,
            )
            settings = self._settings.get(job.owner_id)
            self._settings[job.owner_id] = MemorySettings(
                enabled=settings.enabled if settings is not None else True,
                deletion_generation=(
                    settings.deletion_generation if settings is not None else 0
                ),
                purge_pending=settings.purge_pending if settings is not None else False,
                last_error_code=error_code,
            )
            return True

    def requeue_failed(self, owner_id: str, now: datetime) -> int:
        with self._lock:
            settings = self.settings(owner_id)
            if not settings.enabled or settings.purge_pending:
                return 0
            count = 0
            for job_id, job in list(self._jobs.items()):
                if (
                    job.owner_id == owner_id
                    and job.status == "failed"
                    and job.deletion_generation == settings.deletion_generation
                ):
                    self._jobs[job_id] = replace(
                        job,
                        status="pending",
                        attempts=0,
                        available_at=now,
                        claim_token=None,
                    )
                    count += 1
            if count:
                self._settings[owner_id] = replace(settings, last_error_code=None)
            return count

    # ------------------------------------------------------------- 沉淀游标面

    def upsert_consolidation_cursor(
        self,
        owner_id: str,
        tenant_id: str,
        conversation_id: str,
        sequence: int,
        now: datetime,
        deletion_generation: int,
    ) -> ConsolidationCursor | None:
        with self._lock:
            key = (owner_id, tenant_id, conversation_id)
            current = self._consolidation.get(key)
            if current is None:
                made = ConsolidationCursor(
                    owner_id, tenant_id, conversation_id, 0, sequence, now, deletion_generation
                )
            else:
                made = ConsolidationCursor(
                    owner_id,
                    tenant_id,
                    conversation_id,
                    current.last_consolidated_sequence,
                    max(current.last_message_sequence, sequence),
                    now,
                    deletion_generation,
                )
            self._consolidation[key] = made
            return made

    def get_consolidation_cursor(
        self, owner_id: str, tenant_id: str, conversation_id: str
    ) -> ConsolidationCursor | None:
        with self._lock:
            return self._consolidation.get((owner_id, tenant_id, conversation_id))

    def advance_consolidation_cursor(
        self, owner_id: str, conversation_id: str, sequence: int, now: datetime
    ) -> bool:
        with self._lock:
            changed = False
            for key, cursor in list(self._consolidation.items()):
                if (
                    key[0] == owner_id
                    and key[2] == conversation_id
                    and cursor.last_consolidated_sequence < sequence
                ):
                    self._consolidation[key] = replace(
                        cursor,
                        last_consolidated_sequence=sequence,
                        last_activity_at=now,
                    )
                    changed = True
            return changed

    def find_idle_consolidations(
        self, now: datetime, idle_before: datetime, limit: int
    ) -> tuple[ConsolidationCursor, ...]:
        del now
        with self._lock:
            rows = sorted(
                (
                    cursor
                    for cursor in self._consolidation.values()
                    if cursor.last_message_sequence > cursor.last_consolidated_sequence
                    and cursor.last_activity_at < idle_before
                ),
                key=lambda item: item.last_activity_at,
            )
            return tuple(rows[:limit])

    def finish_purge(self, owner_id: str, generation: int, now: datetime) -> bool:
        with self._lock:
            settings = self._settings.get(owner_id)
            if (
                settings is None
                or settings.deletion_generation != generation
                or not settings.purge_pending
            ):
                return False
            self._summaries = {
                key: summary
                for key, summary in self._summaries.items()
                if summary.owner_id != owner_id
            }
            linked_refs = {
                source_ref
                for fact in self._facts.values()
                if fact.owner_id == owner_id
                for source_ref in fact.source_refs
            }
            self._sources = {
                key: source
                for key, source in self._sources.items()
                if source.owner_id != owner_id or key[1] in linked_refs
            }
            for job_id, job in list(self._jobs.items()):
                if (
                    job.owner_id == owner_id
                    and job.deletion_generation < generation
                    and job.status in {"pending", "running"}
                ):
                    self._jobs[job_id] = replace(
                        job, status="cancelled", content=""
                    )
            self._settings[owner_id] = replace(settings, purge_pending=False)
            return True

    # ---------------------------------------------------------------- 图面

    def edges(self, owner_id: str, tenant_id: str) -> tuple[MemoryEdge, ...]:
        """mirror 特有查询：当前 owner/tenant 的全量边（含已失活的旧边）。"""
        with self._lock:
            return tuple(
                sorted(
                    self._edges.get((owner_id, tenant_id), ()),
                    key=lambda item: item.edge_id,
                )
            )

    def read_edges(
        self,
        owner_id: str,
        tenant_id: str,
        seed_ids: tuple[str, ...],
        expected_revision: int,
        deletion_generation: int,
        registry_version: str,
    ) -> G1GraphSnapshot:
        del seed_ids, expected_revision
        with self._lock:
            return G1GraphSnapshot(
                owner_id=owner_id,
                tenant_id=tenant_id,
                applied_revision=self._applied_revision.get((owner_id, tenant_id), 0),
                deletion_generation=self._graph_generation.get((owner_id, tenant_id), 0),
                registry_version=registry_version,
                edges=tuple(
                    edge
                    for edge in self._edges.get((owner_id, tenant_id), ())
                    if edge.active
                ),
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
        del registry_version
        with self._lock:
            key = (owner_id, tenant_id)
            applied = self._applied_revision.get(key, -1)
            if target_revision < applied:
                return GraphProjectionStatus.STALE
            if target_revision == applied and applied >= 0:
                return GraphProjectionStatus.CURRENT
            previous = self._edges.get(key, ())
            retained = tuple(
                replace(edge, active=False)
                for edge in previous
                if edge.active
            )
            self._applied_revision[key] = target_revision
            self._graph_generation[key] = deletion_generation
            self._edges[key] = retained + tuple(edges)
            return GraphProjectionStatus.APPLIED

    def purge_graph(
        self,
        owner_id: str,
        tenant_id: str,
        target_revision: int,
        deletion_generation: int,
    ) -> None:
        del target_revision, deletion_generation
        with self._lock:
            key = (owner_id, tenant_id)
            self._edges.pop(key, None)
            self._applied_revision.pop(key, None)
            self._graph_generation.pop(key, None)

    # ---------------------------------------------------------------- 索引面

    def upsert_index(self, record: MemoryIndexRecord) -> None:
        with self._lock:
            self._index[record.memory_id] = record

    def index_records(
        self, owner_id: str, tenant_id: str, model: str, index_version: str
    ) -> tuple[MemoryIndexRecord, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        record
                        for record in self._index.values()
                        if record.owner_id == owner_id
                        and record.tenant_id == tenant_id
                        and record.model == model
                        and record.index_version == index_version
                    ),
                    key=lambda item: item.memory_id,
                )
            )

    def delete_index(self, owner_id: str, memory_ids: tuple[str, ...]) -> int:
        with self._lock:
            count = 0
            for memory_id in memory_ids:
                record = self._index.get(memory_id)
                if record is not None and record.owner_id == owner_id:
                    del self._index[memory_id]
                    count += 1
            return count

    # ---------------------------------------------------------------- 内部

    def _consume(
        self,
        owner_id: str,
        operation: str,
        target_ref: str,
        token_hash: str,
        state_hash: str,
        now: datetime,
    ) -> bool:
        confirmation = self._confirmations.get(token_hash)
        if (
            confirmation is None
            or confirmation.owner_id != owner_id
            or confirmation.operation != operation
            or confirmation.target_ref != target_ref
            or confirmation.state_hash != state_hash
            or confirmation.consumed
            or confirmation.expires_at <= now
        ):
            return False
        confirmation.consumed = True
        return True

    def _active_ids_locked(self, owner_id: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                fact.memory_id
                for fact in self._facts.values()
                if fact.owner_id == owner_id and fact.status == "active"
            )
        )

    def _delete_all_locked(self, owner_id: str, now: datetime) -> int:
        count = 0
        for key, fact in list(self._facts.items()):
            if fact.owner_id == owner_id and fact.status != "deleted":
                self._facts[key] = replace(
                    fact,
                    status="deleted",  # type: ignore[arg-type]
                    subject="",
                    slot="",
                    fact="",
                    sensitivity="redacted",
                    updated_at=now,
                )
                count += 1
        settings = self._settings.get(owner_id)
        generation = (settings.deletion_generation if settings is not None else 0) + 1
        self._settings[owner_id] = MemorySettings(
            enabled=False,
            deletion_generation=generation,
            purge_pending=True,
            last_error_code=(
                settings.last_error_code if settings is not None else None
            ),
        )
        tenants = {
            fact.tenant_id
            for fact in self._facts.values()
            if fact.owner_id == owner_id
        } | {
            source.tenant_id
            for source in self._sources.values()
            if source.owner_id == owner_id
        }
        for tenant in tenants or {"default"}:
            self._enqueue_purge(owner_id, tenant, generation, now)
        return count

    def _revoke_source_locked(
        self, owner_id: str, source_ref: str, now: datetime
    ) -> int:
        source = self._sources.get((owner_id, source_ref))
        if source is None or not source.active:
            return 0
        self._sources[(owner_id, source_ref)] = replace(
            source, active=False
        )
        affected: list[tuple[str, str]] = []
        for key, fact in list(self._facts.items()):
            if (
                fact.owner_id == owner_id
                and fact.status == "active"
                and source_ref in fact.source_refs
            ):
                remaining = {
                    ref
                    for ref in fact.source_refs
                    if (owner_id, ref) in self._sources
                    and self._sources[(owner_id, ref)].active
                }
                if not remaining:
                    self._facts[key] = replace(
                        fact,
                        status="deleted",  # type: ignore[arg-type]
                        subject="",
                        slot="",
                        fact="",
                        sensitivity="redacted",
                        updated_at=now,
                    )
                affected.append((fact.owner_id, fact.tenant_id))
        for fact_owner, tenant in set(affected):
            self._bump(fact_owner, tenant, now)
        return len(affected)

    def _bump(self, owner_id: str, tenant_id: str, now: datetime) -> int:
        key = (owner_id, tenant_id)
        revision = self._authority.get(key, 0) + 1
        self._authority[key] = revision
        for job_id, job in list(self._jobs.items()):
            if (
                job.owner_id == owner_id
                and job.tenant_id == tenant_id
                and job.operation == "project"
                and job.status == "pending"
                and job.target_revision < revision
            ):
                self._jobs[job_id] = replace(job, status="cancelled", content="")
        settings = self.settings(owner_id)
        project = MemoryJob(
            job_id=str(uuid4()),
            idempotency_key=f"project:{owner_id}:{tenant_id}:{revision}",
            owner_id=owner_id,
            tenant_id=tenant_id,
            operation="project",
            source_ref=None,
            source_kind=None,
            run_id=None,
            conversation_id=None,
            source_order=0,
            content="",
            authorization_epoch=0,
            deletion_generation=settings.deletion_generation,
            status="pending",
            attempts=0,
            max_attempts=3,
            available_at=now,
            created_at=now,
            target_revision=revision,
            registry_version="m05-g1-v1",
        )
        if project.idempotency_key not in self._job_keys:
            self._job_keys[project.idempotency_key] = project.job_id
            self._jobs[project.job_id] = project
        return revision

    def _enqueue_purge(
        self, owner_id: str, tenant_id: str, generation: int, now: datetime
    ) -> int:
        revision = self._bump(owner_id, tenant_id, now)
        for job_id, job in list(self._jobs.items()):
            if (
                job.owner_id == owner_id
                and job.tenant_id == tenant_id
                and job.operation == "project"
                and job.status == "pending"
                and job.target_revision == revision
            ):
                self._jobs[job_id] = replace(job, status="cancelled", content="")
        purge = MemoryJob(
            job_id=str(uuid4()),
            idempotency_key=f"purge:{owner_id}:{tenant_id}:{generation}",
            owner_id=owner_id,
            tenant_id=tenant_id,
            operation="purge",
            source_ref=None,
            source_kind=None,
            run_id=None,
            conversation_id=None,
            source_order=0,
            content="",
            authorization_epoch=0,
            deletion_generation=generation,
            status="pending",
            attempts=0,
            max_attempts=3,
            available_at=now,
            created_at=now,
            target_revision=revision,
            registry_version="m05-g1-v1",
        )
        if purge.idempotency_key not in self._job_keys:
            self._job_keys[purge.idempotency_key] = purge.job_id
            self._jobs[purge.job_id] = purge
        return revision

    def _update_job_terminal(
        self, job_id: str, claim_token: str, status: str, now: datetime
    ) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "running" or job.claim_token != claim_token:
                return False
            self._jobs[job_id] = replace(
                job,
                status=status,  # type: ignore[arg-type]
                content="",
                claim_token=None,
                available_at=now,
            )
            return True
