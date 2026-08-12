"""Memory 状态、查询、更新、删除与确认管理用例。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from ..ownership.ports import OwnershipStore
from .authorization import MemoryAuthorization, MemoryAuthorizer
from .capabilities import MemoryHealth
from .errors import (
    MemoryConfirmationInvalid,
    MemoryDisableNotPersisted,
    MemoryInvalidCursor,
    MemoryNotFound,
    MemoryPurgePending,
    MemoryUnsafeContent,
    MemoryUnsupported,
)
from .long_term.facts import MemoryFact, MemoryPage, MemorySource
from .long_term.policy import extract_candidates, lexical_similarity, reject_reason
from .long_term.writer import LongTermWriter, valid_until
from .ports import MemoryManagementStore
from .ports import MemoryStoreError as StoreError

POLICY_VERSION = "m05-policy-v1"


class MemoryManager:
    def __init__(
        self,
        store: MemoryManagementStore,
        ownership: OwnershipStore,
        authorizer: MemoryAuthorizer,
        writer: LongTermWriter,
        local_disabled: set[str],
        cursor_secret: bytes,
        now: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._ownership = ownership
        self._authorizer = authorizer
        self._writer = writer
        self._local_disabled = local_disabled
        self._secret = cursor_secret
        self._now = now

    def status(self, auth: MemoryAuthorization) -> MemoryHealth:
        self._authorizer.authorize(auth, write=False, allow_disabled=True)
        owner = self._ownership.get_owner(auth.owner_id)
        if not self._store.durable or owner is None or owner.kind != "user":
            return MemoryHealth("DISABLED", "durable_identity_required")
        settings = self._store.settings(auth.owner_id)
        if settings.purge_pending:
            state, reason = "DEGRADED", "purge_pending"
        elif not settings.enabled or auth.owner_id in self._local_disabled:
            state, reason = "DISABLED", "owner_disabled"
        elif settings.failed_jobs or settings.index_pending or settings.graph_failed:
            state, reason = "DEGRADED", "memory_sync_degraded"
        elif settings.graph_pending:
            state, reason = "DEGRADED", "graph_sync_pending"
        else:
            state, reason = "READY", "memory_ready"
        return MemoryHealth(
            state=state,
            reason_code=reason,
            pending=settings.pending_jobs,
            failed=settings.failed_jobs,
            index_pending=settings.index_pending,
            purge_pending=settings.purge_pending,
            error_summary=_safe_error(settings.last_error_code),
            graph_pending=settings.graph_pending,
            graph_failed=settings.graph_failed,
            graph_reason=(
                "graph_projection_failed"
                if settings.graph_failed
                else "graph_projection_pending" if settings.graph_pending else None
            ),
        )

    def set_enabled(self, auth: MemoryAuthorization, enabled: bool) -> None:
        self._authorizer.authorize(auth, write=False, allow_disabled=True)
        owner = self._ownership.get_owner(auth.owner_id)
        if not self._store.durable or owner is None or owner.kind != "user":
            raise MemoryUnsupported
        if not enabled:
            self._local_disabled.add(auth.owner_id)
        try:
            self._store.set_enabled(auth.owner_id, enabled, self._now())
        except StoreError as exc:
            if not enabled:
                raise MemoryDisableNotPersisted from exc
            if "purge" in str(exc).casefold():
                raise MemoryPurgePending from exc
            raise
        if enabled:
            self._local_disabled.discard(auth.owner_id)

    def list(self, auth: MemoryAuthorization, cursor: str | None = None) -> MemoryPage:
        self._authorizer.authorize(auth, write=False, allow_disabled=True)
        self._store.expire_due(self._now())
        before = self._decode_cursor(auth.owner_id, cursor) if cursor else None
        rows = self._store.list_facts(
            auth.owner_id, auth.tenant_id, before=before, limit=21
        )
        visible = rows[:20]
        next_cursor = None
        if len(rows) > 20 and visible:
            last = visible[-1]
            next_cursor = self._encode_cursor(
                auth.owner_id, last.updated_at, last.memory_id
            )
        return MemoryPage(visible, next_cursor)

    def show(self, auth: MemoryAuthorization, memory_id: str) -> MemoryFact:
        self._authorizer.authorize(auth, write=False, allow_disabled=True)
        self._store.expire_due(self._now())
        canonical = _uuid(memory_id)
        fact = self._store.get_fact(auth.owner_id, canonical)
        if fact is None or not fact.active:
            raise MemoryNotFound
        return fact

    def forget(self, auth: MemoryAuthorization, memory_id: str) -> None:
        self._authorizer.authorize(auth, write=False, allow_disabled=True)
        canonical = _uuid(memory_id)
        if not self._store.deactivate_fact(
            auth.owner_id, canonical, "deleted", self._now()
        ):
            raise MemoryNotFound

    def forget_matching(
        self, auth: MemoryAuthorization, query: str
    ) -> tuple[MemoryFact, ...]:
        """自然语言删除只在唯一强匹配时执行。"""
        self._authorizer.authorize(auth, write=False, allow_disabled=True)
        candidates = sorted(
            (
                (lexical_similarity(query.strip(), fact.fact), fact)
                for fact in self._store.active_facts(auth.owner_id, auth.tenant_id)
            ),
            key=lambda item: (-item[0], item[1].memory_id),
        )
        strong = [item for item in candidates if item[0] >= 0.35]
        if len(strong) == 1 or (len(strong) > 1 and strong[0][0] >= strong[1][0] + 0.2):
            self.forget(auth, strong[0][1].memory_id)
            return (strong[0][1],)
        return tuple(item[1] for item in strong[:5])

    def delete_all(self, auth: MemoryAuthorization) -> int:
        self._authorizer.authorize(auth, write=False, allow_disabled=True)
        count = self._store.delete_all(auth.owner_id, self._now())
        return count

    def request_delete_all(self, auth: MemoryAuthorization) -> tuple[str, int]:
        self._authorizer.authorize(auth, write=False, allow_disabled=True)
        ids = tuple(
            item.memory_id
            for item in self._store.active_facts(auth.owner_id, auth.tenant_id)
        )
        token = str(uuid4())
        self._store.issue_confirmation(
            auth.owner_id,
            "delete-all",
            "*",
            _token_hash(token),
            _ids_hash(ids),
            self._now() + timedelta(minutes=5),
            self._now(),
        )
        return token, len(ids)

    def confirm_delete_all(self, auth: MemoryAuthorization, token: str) -> int:
        self._authorizer.authorize(auth, write=False, allow_disabled=True)
        ids = tuple(
            item.memory_id
            for item in self._store.active_facts(auth.owner_id, auth.tenant_id)
        )
        count = self._store.confirm_delete_all(
            auth.owner_id, _token_hash(token), _ids_hash(ids), self._now()
        )
        if count is None:
            raise MemoryConfirmationInvalid
        return count

    def revoke_source(self, auth: MemoryAuthorization, source_ref: str) -> int:
        self._authorizer.authorize(auth, write=False, allow_disabled=True)
        count = self._store.revoke_source(auth.owner_id, source_ref, self._now())
        if count == 0:
            raise MemoryNotFound
        return count

    def request_revoke_source(
        self, auth: MemoryAuthorization, source_ref: str
    ) -> tuple[int, str | None]:
        self._authorizer.authorize(auth, write=False, allow_disabled=True)
        impact = self._store.source_impact(auth.owner_id, source_ref)
        if not impact:
            raise MemoryNotFound
        if len(impact) == 1:
            return self.revoke_source(auth, source_ref), None
        token = str(uuid4())
        self._store.issue_confirmation(
            auth.owner_id,
            "revoke-source",
            source_ref,
            _token_hash(token),
            _ids_hash(impact),
            self._now() + timedelta(minutes=5),
            self._now(),
        )
        return len(impact), token

    def confirm_revoke_source(
        self, auth: MemoryAuthorization, source_ref: str, token: str
    ) -> int:
        self._authorizer.authorize(auth, write=False, allow_disabled=True)
        impact = self._store.source_impact(auth.owner_id, source_ref)
        count = self._store.confirm_revoke_source(
            auth.owner_id,
            source_ref,
            _token_hash(token),
            _ids_hash(impact),
            self._now(),
        )
        if count is None:
            raise MemoryConfirmationInvalid
        return count

    def update(
        self, auth: MemoryAuthorization, memory_id: str, content: str
    ) -> MemoryFact:
        self._authorizer.authorize(auth, write=True)
        previous = self.show(auth, memory_id)
        candidates = extract_candidates(content)
        if not candidates:
            raise MemoryUnsafeContent
        candidate = candidates[0]
        if (
            len(
                {
                    item.fact
                    for item in candidates
                    if item.subject == candidate.subject and item.slot == candidate.slot
                }
            )
            > 1
        ):
            raise MemoryUnsafeContent("ambiguous_conflict")
        reason = reject_reason(
            content, explicit=True, third_party=candidate.subject != "我"
        )
        if reason is not None:
            raise MemoryUnsafeContent(reason)
        now = self._now()
        source = MemorySource(
            f"command:{auth.session_id}:{uuid4()}",
            auth.owner_id,
            auth.tenant_id,
            "command",
            None,
            0,
            now,
        )
        replacement = MemoryFact(
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
            supersedes_id=previous.memory_id,
            sensitivity=candidate.sensitivity,
            index_status="ready",
        )
        saved = self._store.replace_fact(previous, replacement, source, now)
        self._writer.resolve_quarantine(auth, candidate, now)
        return self._store.get_fact(auth.owner_id, saved.memory_id) or saved

    def _encode_cursor(self, owner_id: str, at: datetime, memory_id: str) -> str:
        body = json.dumps(
            {"o": owner_id, "t": at.isoformat(), "i": memory_id},
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.new(self._secret, body, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(body + signature).decode("ascii").rstrip("=")

    def _decode_cursor(self, owner_id: str, cursor: str) -> tuple[datetime, str]:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            body, signature = raw[:-32], raw[-32:]
            expected = hmac.new(self._secret, body, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            payload = json.loads(body)
            if payload["o"] != owner_id:
                raise ValueError
            return datetime.fromisoformat(payload["t"]), _uuid(payload["i"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise MemoryInvalidCursor from exc


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise MemoryNotFound from exc


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ids_hash(values: tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()


def _safe_error(error_code: str | None) -> str | None:
    if error_code is None:
        return None
    # 只允许固定 reason code 进入状态面，任意原始异常统一净化。
    allowed = {
        "store_unavailable",
        "background_retry_exhausted",
        "projection_unavailable",
    }
    return error_code if error_code in allowed else "background_processing_degraded"
