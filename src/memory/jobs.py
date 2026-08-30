"""持久 memory job、claim dispatch、retry 与 fencing 行为。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from ..ownership.ports import OwnershipStore
from ..promptctx.context import conservative_token_count
from .embedding.index import INDEX_VERSION, MemoryIndex
from .errors import MemoryUnauthorized, MemoryUnsafeContent
from .graph_memory import GraphMemory
from .long_term.facts import FactCandidate, MemoryFact, contains_secret
from .long_term.writer import LongTermWriter
from .model_adapters import StructuredMemoryExtractor
from .ports import MemoryJobStore
from .ports import MemoryStoreError as StoreError
from .recall import MEMORY_SCOPE, MemoryAuthorization, MemoryAuthorizer

if TYPE_CHECKING:
    from ..conversation.models import ConversationMessage
    from ..conversation.ports import ConversationStore
    from .service import MemoryService

POLICY_VERSION = "m05-policy-v1"
CONSOLIDATION_POLICY_VERSION = "m05-consolidation-v1"
MemoryJobOperation = Literal[
    "extract", "index", "project", "purge", "quarantine-review", "expire", "consolidate"
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
        conversation: ConversationStore | None = None,
        *,
        window_messages: int = 5,
        idle_seconds: int = 600,
        max_input_tokens: int = 4000,
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
        self._conversation = conversation
        self._window_messages = window_messages
        self._idle_seconds = idle_seconds
        self._max_input_tokens = max_input_tokens

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

    def record_user_message_for_consolidation(
        self,
        auth: MemoryAuthorization,
        *,
        conversation_id: str,
        sequence: int,
        now: datetime | None = None,
    ) -> bool:
        """用户消息只推进对话游标；攒满窗口时入队一次 consolidate job。

        含密钥消息照样推进游标（抽取时剔除内容）。旧 extract 通道不再被调用。
        返回是否实际入队了 consolidate job。
        """
        self._authorizer.authorize(auth, write=True)
        snapshot = self._authorizer.capture_snapshot(auth)
        at = now or self._now()
        previous = self._store.get_consolidation_cursor(
            auth.owner_id, auth.tenant_id, conversation_id
        )
        cursor = self._store.upsert_consolidation_cursor(
            auth.owner_id,
            auth.tenant_id,
            conversation_id,
            sequence,
            at,
            snapshot.deletion_generation,
        )
        if cursor is None:
            return False
        window = (
            cursor.last_message_sequence - cursor.last_consolidated_sequence
        )
        if window < self._window_messages:
            return False
        if previous is not None and previous.last_message_sequence >= cursor.last_message_sequence:
            return False
        previous_window = (
            previous.last_message_sequence - previous.last_consolidated_sequence
            if previous is not None
            else 0
        )
        if previous_window >= self._window_messages:
            # 上一批已入队但游标未推进（任务未完成）；不重复入队重叠窗口，
            # 残余消息由空闲兜底扫描补齐。
            return False
        return self.enqueue_consolidation(
            auth,
            conversation_id=conversation_id,
            start_sequence=cursor.last_consolidated_sequence,
            end_sequence=cursor.last_message_sequence,
        )

    def enqueue_consolidation(
        self,
        auth: MemoryAuthorization,
        *,
        conversation_id: str,
        start_sequence: int,
        end_sequence: int,
    ) -> bool:
        """入队一个 consolidate job；幂等 key 保证同窗口只入队一次。"""
        self._authorizer.authorize(auth, write=True)
        if start_sequence < 0 or end_sequence < start_sequence:
            raise MemoryUnauthorized
        snapshot = self._authorizer.capture_snapshot(auth)
        identity = "|".join(
            (
                auth.owner_id,
                auth.tenant_id,
                conversation_id,
                str(start_sequence),
                str(end_sequence),
                CONSOLIDATION_POLICY_VERSION,
                "consolidate",
            )
        )
        now = self._now()
        job = MemoryJob(
            job_id=str(uuid4()),
            idempotency_key=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            owner_id=auth.owner_id,
            tenant_id=auth.tenant_id,
            operation="consolidate",
            source_ref=f"consolidation:{conversation_id}",
            source_kind="user_message",
            run_id=auth.run_id,
            conversation_id=conversation_id,
            source_order=start_sequence,
            content=json.dumps(
                {
                    "conversation_id": conversation_id,
                    "start_sequence": start_sequence,
                    "end_sequence": end_sequence,
                },
                ensure_ascii=False,
            ),
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
            self._enqueue_idle_consolidations(now)
        except StoreError:
            self._transition(
                "memory-extraction", "unavailable", "job_store_unavailable"
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

    def _enqueue_idle_consolidations(self, now: datetime) -> None:
        """空闲兜底：未攒满窗口的静默对话由扫描补齐（D1）。"""
        idle = self._store.find_idle_consolidations(
            now, idle_before=now - timedelta(seconds=self._idle_seconds), limit=8
        )
        for cursor in idle:
            owner = self._ownership.get_owner(cursor.owner_id)
            if owner is None or owner.lifecycle_state != "active":
                continue
            auth = MemoryAuthorization(
                owner_id=cursor.owner_id,
                tenant_id=cursor.tenant_id,
                allowed_data_scopes=(MEMORY_SCOPE,),
                allowed_action_classes=("memory.write",),
                authorization_epoch=owner.authorization_epoch,
                source_kind="run",
                action="write",
                conversation_id=cursor.conversation_id,
            )
            try:
                self.enqueue_consolidation(
                    auth,
                    conversation_id=cursor.conversation_id,
                    start_sequence=cursor.last_consolidated_sequence,
                    end_sequence=cursor.last_message_sequence,
                )
            except (MemoryUnauthorized, MemoryUnsafeContent):
                continue

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
            elif job.operation == "consolidate":
                self._dispatch_consolidation(job, now)
            self._store.complete_job(job.job_id, claim_token, now)
            self._transition("memory-extraction", "healthy", "memory_ready")
            return 1
        except Exception as exc:
            self._retry(job, claim_token, now, exc)
            return 0

    def _dispatch_consolidation(self, job: MemoryJob, now: datetime) -> None:
        """consolidate 分支：读窗口消息 → 分段抽取 → 写入 → 推进游标。

        游标推进先于 complete_job：崩溃重放时同窗口消息已被 decide_merge 收敛，
        不会产生重复事实（两种乱序都由游标单调性与幂等 key 覆盖）。
        """
        if self._conversation is None:
            raise StoreError("conversation store is unavailable for consolidation")
        payload = json.loads(job.content or "")
        conversation_id = str(payload["conversation_id"])
        start_sequence = int(payload["start_sequence"])
        end_sequence = int(payload["end_sequence"])
        auth = self._consolidation_auth(job)
        messages = tuple(
            message
            for message in self._conversation.messages(
                job.owner_id, conversation_id
            )
            if start_sequence < message.sequence <= end_sequence
            and not contains_secret(message.content)
        )
        if not messages:
            self._store.advance_consolidation_cursor(
                job.owner_id, conversation_id, end_sequence, now
            )
            return
        segments = _segment_transcript(messages, self._max_input_tokens)
        for text, seg_start, seg_end in segments:
            candidates = (
                self._extractor.extract_window(text)
                if self._extractor is not None
                else ()
            )
            result = self._writer.remember_all_result(
                auth,
                text,
                source_ref=f"consolidation:{conversation_id}:{seg_start}-{seg_end}",
                source_order=seg_start,
                explicit=False,
                source_kind="user_message",
                extracted_candidates=_latest_candidates(candidates),
            )
            for fact in result.saved:
                self.enqueue_index(fact)
        self._store.advance_consolidation_cursor(
            job.owner_id, conversation_id, end_sequence, now
        )

    @staticmethod
    def _consolidation_auth(job: MemoryJob) -> MemoryAuthorization:
        return MemoryAuthorization(
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


def _message_line(message: ConversationMessage) -> str:
    role = "用户" if message.role == "user" else "助手"
    return f"[seq:{message.sequence}|{role}]{message.content}"


def _segment_transcript(
    messages: Sequence[ConversationMessage], max_input_tokens: int
) -> tuple[tuple[str, int, int], ...]:
    """按时间顺序把窗口消息切成 token 受限的段；早期优先，每段独立抽取。

    返回 (段文本, 段首 sequence, 段尾 sequence) 的元组。
    """
    segments: list[tuple[str, int, int]] = []
    current: list[str] = []
    first_seq: int | None = None
    last_seq: int | None = None
    for message in sorted(messages, key=lambda item: item.sequence):
        line = _message_line(message)
        if current:
            candidate = "\n".join([*current, line])
            if conservative_token_count(candidate) > max_input_tokens:
                segments.append(("\n".join(current), first_seq or 0, last_seq or 0))
                current = [line]
                first_seq = last_seq = message.sequence
                continue
        current.append(line)
        last_seq = message.sequence
        if first_seq is None:
            first_seq = message.sequence
    if current:
        segments.append(("\n".join(current), first_seq or 0, last_seq or 0))
    return tuple(segments)


def _latest_candidates(
    candidates: tuple[FactCandidate, ...],
) -> tuple[FactCandidate, ...]:
    """同一 (subject, slot) 只保留最后一次陈述；改口直接产出最终值。"""
    latest: dict[tuple[str, str], FactCandidate] = {}
    for candidate in candidates:
        latest[(candidate.subject, candidate.slot)] = candidate
    return tuple(latest.values())


LOGGER = logging.getLogger("venagent.memory.job_worker")


class MemoryMaintenanceWorker:
    def __init__(
        self, service: MemoryService, *, poll_interval: float = 1.0, batch_size: int = 8
    ) -> None:
        self._service = service
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(
                    self._service.process_pending_jobs, limit=self._batch_size
                )
            except Exception:
                LOGGER.warning(
                    "记忆后台维护单轮失败。",
                    extra={"reason_code": "memory_maintenance_iteration_failed"},
                )
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._poll_interval
                )
            except asyncio.TimeoutError:
                continue
