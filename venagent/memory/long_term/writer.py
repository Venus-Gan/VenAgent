"""长期事实写入、版本化与隔离处理。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from ..authorization import MemoryAuthorization, MemoryAuthorizer
from ..errors import MemoryUnauthorized, MemoryUnsafeContent
from ..ports import MemoryFactWriteStore
from ..ports import MemoryStoreError as StoreError
from .conflict import ConflictJudge, MergeAction, decide_merge
from .facts import MemoryFact, MemorySource
from .policy import (
    CandidateRejection,
    FactCandidate,
    candidate_reject_reason,
    evaluate_candidates,
    extract_candidates,
)


@dataclass(frozen=True)
class MemoryWriteResult:
    saved: tuple[MemoryFact, ...]
    rejected: tuple[CandidateRejection, ...] = ()


class LongTermWriter:
    def __init__(
        self,
        store: MemoryFactWriteStore,
        authorizer: MemoryAuthorizer,
        now: Callable[[], datetime],
        transition: Callable[[str, str, str], None],
        *,
        quarantine_ttl: timedelta,
        conflict_judge: ConflictJudge | None = None,
    ) -> None:
        self._store = store
        self._authorizer = authorizer
        self._now = now
        self._transition = transition
        self._quarantine_ttl = quarantine_ttl
        self._conflict_judge = conflict_judge

    def remember(
        self,
        auth: MemoryAuthorization,
        content: str,
        *,
        source_ref: str,
        source_order: int,
        explicit: bool,
        source_kind: str = "user_message",
        extracted_candidates: tuple[FactCandidate, ...] | None = None,
    ) -> MemoryFact | None:
        saved = self.remember_all(
            auth,
            content,
            source_ref=source_ref,
            source_order=source_order,
            explicit=explicit,
            source_kind=source_kind,
            extracted_candidates=extracted_candidates,
        )
        return saved[0] if saved else None

    def remember_all(
        self,
        auth: MemoryAuthorization,
        content: str,
        *,
        source_ref: str,
        source_order: int,
        explicit: bool,
        source_kind: str = "user_message",
        extracted_candidates: tuple[FactCandidate, ...] | None = None,
    ) -> tuple[MemoryFact, ...]:
        result = self.remember_all_result(
            auth,
            content,
            source_ref=source_ref,
            source_order=source_order,
            explicit=explicit,
            source_kind=source_kind,
            extracted_candidates=extracted_candidates,
        )
        if explicit and not result.saved:
            reason = result.rejected[0].reason if result.rejected else "no_stable_fact"
            raise MemoryUnsafeContent(reason)
        return result.saved

    def remember_all_result(
        self,
        auth: MemoryAuthorization,
        content: str,
        *,
        source_ref: str,
        source_order: int,
        explicit: bool,
        source_kind: str = "user_message",
        extracted_candidates: tuple[FactCandidate, ...] | None = None,
    ) -> MemoryWriteResult:
        self._authorizer.authorize(auth, write=True)
        if source_kind not in {"user_message", "tool_result"}:
            raise MemoryUnauthorized
        candidates = (
            extracted_candidates
            if extracted_candidates is not None
            else extract_candidates(content)
        )
        if not candidates:
            return MemoryWriteResult((), (CandidateRejection("no_stable_fact"),))
        eligible, rejected = evaluate_candidates(
            content, candidates, explicit=explicit
        )
        if not eligible:
            return MemoryWriteResult((), rejected)
        now = self._now()
        source = MemorySource(
            source_ref,
            auth.owner_id,
            auth.tenant_id,
            "command" if auth.source_kind == "command" else source_kind,
            auth.conversation_id,
            source_order,
            now,
        )
        ambiguous_slots = {
            (candidate.subject, candidate.slot)
            for candidate in eligible
            if len(
                {
                    item.fact
                    for item in eligible
                    if item.subject == candidate.subject
                    and item.slot == candidate.slot
                }
            )
            > 1
        }
        saved: list[MemoryFact] = []
        seen_ambiguous: set[tuple[str, str]] = set()
        for candidate in eligible:
            slot_key = (candidate.subject, candidate.slot)
            if slot_key in ambiguous_slots and slot_key in seen_ambiguous:
                continue
            saved.append(
                self._remember_candidate(
                    auth,
                    content,
                    candidate,
                    source,
                    now,
                    force_quarantine=slot_key in ambiguous_slots,
                )
            )
            if slot_key in ambiguous_slots:
                seen_ambiguous.add(slot_key)
        return MemoryWriteResult(tuple(saved), rejected)

    def _remember_candidate(
        self,
        auth: MemoryAuthorization,
        content: str,
        candidate: FactCandidate,
        source: MemorySource,
        now: datetime,
        *,
        force_quarantine: bool,
    ) -> MemoryFact:
        previous = self._store.find_active_by_slot(
            auth.owner_id, auth.tenant_id, candidate.subject, candidate.slot
        )
        decision = decide_merge(candidate, previous, self._conflict_judge)
        if force_quarantine or decision.action is MergeAction.QUARANTINE:
            quarantined = MemoryFact(
                str(uuid4()),
                auth.owner_id,
                auth.tenant_id,
                candidate.subject,
                candidate.slot,
                candidate.fact,
                "quarantine",
                (source.source_ref,),
                now,
                now,
                valid_until=now + self._quarantine_ttl,
                sensitivity=candidate.sensitivity,
                index_status="ready",
            )
            return self._store.save_fact(quarantined, source, now)
        if decision.action is MergeAction.NOOP and previous is not None:
            saved = self._store.add_source(previous, source, now)
            self.resolve_quarantine(auth, candidate, now)
            return saved
        fact = MemoryFact(
            str(uuid4()),
            auth.owner_id,
            auth.tenant_id,
            candidate.subject,
            candidate.slot,
            candidate.fact,
            "active",
            (source.source_ref,),
            now,
            now,
            valid_until=valid_until(content, now),
            supersedes_id=(
                previous.memory_id
                if decision.action is MergeAction.UPDATE and previous is not None
                else None
            ),
            sensitivity=candidate.sensitivity,
            index_status="ready",
        )
        if decision.action is MergeAction.UPDATE and previous is not None:
            saved = self._store.replace_fact(previous, fact, source, now)
        else:
            saved = self._store.save_fact(fact, source, now)
        self.resolve_quarantine(auth, candidate, now)
        return self._store.get_fact(auth.owner_id, saved.memory_id) or saved

    def resolve_quarantine(
        self,
        auth: MemoryAuthorization,
        candidate: FactCandidate,
        now: datetime,
    ) -> None:
        try:
            self._store.resolve_quarantine(
                auth.owner_id,
                auth.tenant_id,
                candidate.subject,
                candidate.slot,
                candidate.fact,
                now,
            )
        except StoreError:
            self._transition(
                "memory-extraction", "degraded", "quarantine_review_pending"
            )


def valid_until(content: str, now: datetime) -> datetime | None:
    if any(term in content for term in ("目前", "当前", "临时", "截至")):
        return now + timedelta(days=180)
    return None


def _candidate_reject_reason(
    content: str, candidate: FactCandidate, *, explicit: bool
) -> str | None:
    """兼容旧调用方；新写入流程使用 evaluate_candidates。"""

    del content
    return candidate_reject_reason(candidate, explicit=explicit)
