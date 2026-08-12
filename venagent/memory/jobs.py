"""持久 memory job、claim dispatch、retry 与 fencing 行为。"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from ..ownership.ports import OwnershipStore
from .authorization import MEMORY_SCOPE, MemoryAuthorization, MemoryAuthorizer
from .embedding.index import INDEX_VERSION, MemoryIndex
from .errors import MemoryUnauthorized, MemoryUnsafeContent
from .graph_memory import GraphMemory
from .long_term.extractor import StructuredMemoryExtractor
from .long_term.facts import MemoryFact
from .long_term.policy import contains_secret
from .long_term.writer import LongTermWriter
from .ports import MemoryJobStore
from .ports import MemoryStoreError as StoreError

POLICY_VERSION = "m05-policy-v1"
MemoryJobOperation = Literal[
    "extract", "index", "project", "purge", "quarantine-review", "expire"
]
MemoryJobStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]


@dataclass(frozen=True)
class MemoryJob:
    job_id: str
    idempotency_key: str
    owner_id: str
    tenant_id: str
    operation: MemoryJobOperation
    source_ref: str | None
    source_kind: str | None
    run_id: str | None
    conversation_id: str | None
    source_order: int
    content: str
    authorization_epoch: int
    deletion_generation: int
    status: MemoryJobStatus
    attempts: int
    max_attempts: int
    available_at: datetime
    created_at: datetime
    target_revision: int = 0
    registry_version: str = "m05-g1-v1"
    claim_token: str | None = None
    memory_id: str | None = None


class MemoryJobs:
    def __init__(
        self,
        store: MemoryJobStore,
        ownership: OwnershipStore,
        graph_memory: GraphMemory,
        authorizer: MemoryAuthorizer,
        writer: LongTermWriter,
        now: Callable[[], datetime],
        transition: Callable[[str, str, str], None],
        extractor: StructuredMemoryExtractor | None = None,
        memory_index: MemoryIndex | None = None,
    ) -> None:
        self._store = store
        self._ownership = ownership
        self._graph_memory = graph_memory
        self._authorizer = authorizer
        self._writer = writer
        self._now = now
        self._transition = transition
        self._extractor = extractor
        self._memory_index = memory_index

    def enqueue_extraction(
        self,
        auth: MemoryAuthorization,
        content: str,
        *,
        source_ref: str,
        source_order: int,
        source_kind: str = "user_message",
    ) -> bool:
        self._authorizer.authorize(auth, write=True)
        if source_kind not in {"user_message", "tool_result"}:
            raise MemoryUnauthorized
        # 凭据和支付数据不得进入外部提取模型；候选资格仍只在拆分后判断一次。
        if contains_secret(content):
            return False
        snapshot = self._authorizer.capture_snapshot(auth)
        identity = "|".join(
            (auth.owner_id, auth.tenant_id, source_ref, POLICY_VERSION, "extract")
        )
        now = self._now()
        job = MemoryJob(
            job_id=str(uuid4()),
            idempotency_key=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            owner_id=auth.owner_id,
            tenant_id=auth.tenant_id,
            operation="extract",
            source_ref=source_ref,
            source_kind=source_kind,
            run_id=auth.run_id,
            conversation_id=auth.conversation_id,
            source_order=source_order,
            content=content,
            authorization_epoch=auth.authorization_epoch,
            deletion_generation=snapshot.deletion_generation,
            status="pending",
            attempts=0,
            max_attempts=3,
            available_at=now,
            created_at=now,
        )
        return self._store.enqueue_job(job)

    def process_pending_jobs(self, *, limit: int = 8) -> int:
        now = self._now()
        try:
            self._store.expire_due(now)
        except StoreError:
            self._transition(
                "memory-long-term", "unavailable", "lifecycle_store_unavailable"
            )
        try:
            jobs = self._store.claim_jobs(now, limit=limit)
        except StoreError:
            self._transition(
                "memory-extraction", "unavailable", "job_store_unavailable"
            )
            return 0
        completed = 0
        for job in jobs:
            completed += self._dispatch(job, now)
        return completed

    def replay_failed_jobs(self, auth: MemoryAuthorization) -> int:
        self._authorizer.authorize(auth, write=True)
        count = self._store.requeue_failed(auth.owner_id, self._now())
        if count:
            self._transition("memory-extraction", "recovering", "replay_pending")
        return count

    def enqueue_index(self, fact: MemoryFact) -> bool:
        if self._memory_index is None:
            return False
        owner = self._ownership.get_owner(fact.owner_id)
        if owner is None or owner.lifecycle_state != "active":
            return False
        now = self._now()
        identity = "|".join(
            (fact.memory_id, fact.fact, fact.status, INDEX_VERSION)
        )
        job = MemoryJob(
            job_id=str(uuid4()),
            idempotency_key=(
                "index:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
            ),
            owner_id=fact.owner_id,
            tenant_id=fact.tenant_id,
            operation="index",
            source_ref=None,
            source_kind=None,
            run_id=None,
            conversation_id=None,
            source_order=0,
            content="",
            authorization_epoch=owner.authorization_epoch,
            deletion_generation=self._store.settings(fact.owner_id).deletion_generation,
            status="pending",
            attempts=0,
            max_attempts=3,
            available_at=now,
            created_at=now,
            memory_id=fact.memory_id,
        )
        enqueued = self._store.enqueue_job(job)
        if enqueued and fact.active:
            self._store.set_index_status(
                fact.owner_id, (fact.memory_id,), "pending", now
            )
        return enqueued

    def _dispatch(self, job: MemoryJob, now: datetime) -> int:
        claim_token = job.claim_token or ""
        try:
            if job.operation == "purge":
                self._graph_memory.purge(
                    job.owner_id,
                    job.tenant_id,
                    job.target_revision,
                    job.deletion_generation,
                )
                if self._store.finish_purge(
                    job.owner_id, job.deletion_generation, now
                ):
                    self._store.complete_job(job.job_id, claim_token, now)
                else:
                    self._store.cancel_job(job.job_id, claim_token, now)
                self._transition("memory-graph-g1", "healthy", "memory_ready")
                return 1

            owner = self._ownership.get_owner(job.owner_id)
            settings = self._store.settings(job.owner_id)
            source = (
                self._store.source(job.owner_id, job.source_ref)
                if job.source_ref
                else None
            )
            if (
                owner is None
                or owner.lifecycle_state != "active"
                or (
                    job.operation != "project"
                    and owner.authorization_epoch != job.authorization_epoch
                )
                or not settings.enabled
                or settings.purge_pending
                or settings.deletion_generation != job.deletion_generation
                or (source is not None and not source.active)
            ):
                self._store.cancel_job(job.job_id, claim_token, now)
                return 1
            if job.operation == "project":
                self._graph_memory.project(
                    job.owner_id,
                    job.tenant_id,
                    job.target_revision,
                    job.deletion_generation,
                )
                self._transition("memory-graph-g1", "healthy", "memory_ready")
            elif job.operation == "index":
                fact = (
                    self._store.get_fact(job.owner_id, job.memory_id)
                    if job.memory_id
                    else None
                )
                if fact is None or self._memory_index is None:
                    self._store.cancel_job(job.job_id, claim_token, now)
                    return 1
                self._memory_index.project(fact, now=now)
                if fact.active:
                    self._store.set_index_status(
                        job.owner_id, (fact.memory_id,), "ready", now
                    )
                self._transition("memory-index", "healthy", "index_ready")
            elif job.operation == "extract":
                auth = MemoryAuthorization(
                    owner_id=job.owner_id,
                    tenant_id=job.tenant_id,
                    allowed_data_scopes=(MEMORY_SCOPE,),
                    allowed_action_classes=("memory.write",),
                    authorization_epoch=job.authorization_epoch,
                    source_kind="run",
                    action="write",
                    run_id=job.run_id,
                    conversation_id=job.conversation_id,
                )
                candidates = (
                    self._extractor.extract(job.content)
                    if self._extractor is not None
                    else None
                )
                result = self._writer.remember_all_result(
                    auth,
                    job.content,
                    source_ref=job.source_ref or "",
                    source_order=job.source_order,
                    explicit=False,
                    source_kind=job.source_kind or "user_message",
                    extracted_candidates=candidates,
                )
                for fact in result.saved:
                    self.enqueue_index(fact)
            self._store.complete_job(job.job_id, claim_token, now)
            self._transition("memory-extraction", "healthy", "memory_ready")
            return 1
        except Exception as exc:
            self._retry(job, claim_token, now, exc)
            return 0

    def _retry(
        self,
        job: MemoryJob,
        claim_token: str,
        now: datetime,
        exc: Exception,
    ) -> None:
        error_code = _job_error_code(exc)
        delay = timedelta(seconds=min(60, 2 ** max(0, job.attempts - 1)))
        component = (
            "memory-graph-g1"
            if job.operation in {"project", "purge"}
            else "memory-index" if job.operation == "index" else "memory-extraction"
        )
        try:
            self._store.retry_job(
                job.job_id, claim_token, error_code, now + delay, now
            )
        except StoreError:
            self._transition(component, "unavailable", "job_store_unavailable")
        else:
            if job.operation == "index" and job.memory_id and job.attempts >= job.max_attempts:
                self._store.set_index_status(
                    job.owner_id, (job.memory_id,), "failed", now
                )
            reason = (
                "graph_projection_retry_pending"
                if job.operation in {"project", "purge"}
                else "index_retry_pending"
                if job.operation == "index"
                else "background_retry_pending"
            )
            self._transition(component, "degraded", reason)


def _job_error_code(exc: Exception) -> str:
    if isinstance(exc, StoreError):
        return "store_unavailable"
    if isinstance(exc, (MemoryUnauthorized, MemoryUnsafeContent)):
        return exc.code
    return "background_retry_exhausted"
