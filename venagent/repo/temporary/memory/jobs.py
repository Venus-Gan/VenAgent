"""temporary memory 后台任务队列 adapter。"""

from __future__ import annotations

# ruff: noqa: F401
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from threading import RLock
from uuid import uuid4

from ....memory.capabilities import MemorySettings
from ....memory.jobs import MemoryJob
from ....memory.ports import MemoryStoreError as StoreError
from .fact_state import _redacted


class _TemporaryJobsMixin:
    def enqueue_job(self, job: MemoryJob) -> bool:
        with self._lock:
            if job.idempotency_key in self._job_keys:
                return False
            self._jobs[job.job_id] = job
            self._job_keys[job.idempotency_key] = job.job_id
            return True

    def claim_jobs(self, now: datetime, *, limit: int) -> tuple[MemoryJob, ...]:
        with self._lock:
            eligible = sorted(
                (
                    item
                    for item in self._jobs.values()
                    if item.available_at <= now
                    and item.status in {"pending", "running"}
                ),
                key=lambda item: (item.available_at, item.created_at, item.job_id),
            )[:limit]
            claimed = tuple(
                # available_at 同时充当 30 秒领取租约，worker 丢失后任务可再次 claim。
                replace(
                    item,
                    status="running",
                    attempts=item.attempts + 1,
                    available_at=now + timedelta(seconds=30),
                    claim_token=str(uuid4()),
                )
                for item in eligible
            )
            for item in claimed:
                self._jobs[item.job_id] = item
            return claimed

    def complete_job(self, job_id: str, claim_token: str, now: datetime) -> bool:
        del now
        with self._lock:
            job = self._jobs.get(job_id)
            if (
                job is None
                or job.status != "running"
                or job.claim_token != claim_token
            ):
                return False
            self._jobs[job_id] = replace(
                job, status="succeeded", content="", claim_token=None
            )
            return True

    def retry_job(
        self,
        job_id: str,
        claim_token: str,
        error_code: str,
        available_at: datetime,
        now: datetime,
    ) -> bool:
        del now
        with self._lock:
            job = self._jobs.get(job_id)
            if (
                job is None
                or job.status != "running"
                or job.claim_token != claim_token
            ):
                return False
            graph_job = job.operation in {"project", "purge"}
            exhausted = not graph_job and job.attempts >= job.max_attempts
            self._jobs[job_id] = replace(
                job,
                status="failed" if exhausted else "pending",
                available_at=available_at,
                claim_token=None,
            )
            current = self._settings.get(job.owner_id, MemorySettings(True, 0, False))
            self._settings[job.owner_id] = replace(current, last_error_code=error_code)
            return True

    def cancel_job(self, job_id: str, claim_token: str, now: datetime) -> bool:
        del now
        with self._lock:
            job = self._jobs.get(job_id)
            if (
                job is None
                or job.status != "running"
                or job.claim_token != claim_token
            ):
                return False
            self._jobs[job_id] = replace(
                job, status="cancelled", content="", claim_token=None
            )
            return True

    def requeue_failed(self, owner_id: str, now: datetime) -> int:
        with self._lock:
            settings = self.settings(owner_id)
            if not settings.enabled or settings.purge_pending:
                return 0
            targets = [
                job
                for job in self._jobs.values()
                if job.owner_id == owner_id
                and job.status == "failed"
                and job.deletion_generation == settings.deletion_generation
            ]
            for job in targets:
                self._jobs[job.job_id] = replace(
                    job, status="pending", attempts=0, available_at=now
                )
            if targets:
                self._settings[owner_id] = replace(
                    self._settings.get(owner_id, settings), last_error_code=None
                )
            return len(targets)

    def finish_purge(self, owner_id: str, generation: int, now: datetime) -> bool:
        del now
        with self._lock:
            current = self._settings.get(owner_id, MemorySettings(False, 0, False))
            if current.deletion_generation != generation or not current.purge_pending:
                return False
            for job_id, job in tuple(self._jobs.items()):
                if (
                    job.owner_id == owner_id
                    and job.deletion_generation < generation
                    and job.status in {"pending", "running"}
                ):
                    self._jobs[job_id] = replace(job, status="cancelled", content="")
            self._settings[owner_id] = replace(current, purge_pending=False)
            return True

    def expire_due(self, now: datetime) -> int:
        with self._lock:
            targets = [
                item.memory_id
                for item in self._facts.values()
                if item.status in {"active", "quarantine"}
                and item.valid_until is not None
                and item.valid_until <= now
            ]
            affected: set[tuple[str, str]] = set()
            for memory_id in targets:
                fact = self._facts[memory_id]
                self._facts[memory_id] = _redacted(fact, "expired", now)
                affected.add((fact.owner_id, fact.tenant_id))
            for owner_id, tenant_id in affected:
                self._enqueue_projection(owner_id, tenant_id, now)
            return len(targets)

    def _enqueue_projection(
        self, owner_id: str, tenant_id: str, now: datetime
    ) -> int:
        key = (owner_id, tenant_id)
        revision = self._revisions.get(key, 0) + 1
        self._revisions[key] = revision
        for job_id, job in tuple(self._jobs.items()):
            if (
                job.owner_id == owner_id
                and job.tenant_id == tenant_id
                and job.operation == "project"
                and job.status == "pending"
            ):
                self._jobs[job_id] = replace(job, status="cancelled")
        job = MemoryJob(
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
            deletion_generation=self.settings(owner_id).deletion_generation,
            status="pending",
            attempts=0,
            max_attempts=3,
            available_at=now,
            created_at=now,
            target_revision=revision,
        )
        self.enqueue_job(job)
        return revision

    def _enqueue_purge(
        self,
        owner_id: str,
        tenant_id: str,
        generation: int,
        now: datetime,
    ) -> None:
        key = (owner_id, tenant_id)
        revision = self._revisions.get(key, 0) + 1
        self._revisions[key] = revision
        for job_id, job in tuple(self._jobs.items()):
            if (
                job.owner_id == owner_id
                and job.tenant_id == tenant_id
                and job.operation == "project"
                and job.status == "pending"
            ):
                self._jobs[job_id] = replace(
                    job, status="cancelled", content=""
                )
        job = MemoryJob(
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
        )
        self.enqueue_job(job)
