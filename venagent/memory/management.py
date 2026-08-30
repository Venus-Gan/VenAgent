"""Memory 状态、查询、更新、删除与确认管理用例。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import RLock
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from ..ownership.models import Actor
from ..ownership.ports import OwnershipStore
from .errors import (
    MemoryConfirmationInvalid,
    MemoryDisableNotPersisted,
    MemoryError,
    MemoryInvalidCommand,
    MemoryInvalidCursor,
    MemoryNotFound,
    MemoryPurgePending,
    MemoryUnsafeContent,
    MemoryUnsupported,
)
from .long_term.facts import (
    MemoryFact,
    MemoryPage,
    MemorySource,
    extract_candidates,
    lexical_similarity,
    reject_reason,
)
from .long_term.writer import LongTermWriter, valid_until
from .ports import MemoryManagementStore
from .ports import MemoryStoreError as StoreError
from .recall import MemoryAuthorization, MemoryAuthorizer

if TYPE_CHECKING:
    from .service import MemoryService

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


ProviderState = Literal[
    "healthy",
    "degraded",
    "recovering",
    "disabled",
    "unavailable",
    "purge_pending",
]


@dataclass(frozen=True)
class MemoryHealth:
    state: Literal["READY", "DEGRADED", "DISABLED", "FAILED"]
    reason_code: str
    pending: int = 0
    failed: int = 0
    index_pending: int = 0
    purge_pending: bool = False
    error_summary: str | None = None
    graph_pending: int = 0
    graph_failed: int = 0
    graph_reason: str | None = None


@dataclass(frozen=True)
class MemorySettings:
    enabled: bool
    deletion_generation: int
    purge_pending: bool
    pending_jobs: int = 0
    failed_jobs: int = 0
    index_pending: int = 0
    last_error_code: str | None = None
    graph_pending: int = 0
    graph_failed: int = 0


@dataclass(frozen=True)
class MemoryCapabilityStatus:
    component: str
    state: ProviderState
    reason_code: str


class MemoryCapabilityRegistry:
    """同一份状态同时供启动快照、运行时 health 和安全降级使用。"""

    def __init__(
        self,
        statuses: tuple[MemoryCapabilityStatus, ...],
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._statuses = {item.component: item for item in statuses}
        self._logger = logger or logging.getLogger("venagent.memory")
        self._lock = RLock()

    def snapshot(self) -> tuple[MemoryCapabilityStatus, ...]:
        with self._lock:
            return tuple(self._statuses[key] for key in sorted(self._statuses))

    def get(self, component: str) -> MemoryCapabilityStatus:
        with self._lock:
            return self._statuses[component]

    def transition(
        self, component: str, state: ProviderState, reason_code: str
    ) -> None:
        value = MemoryCapabilityStatus(component, state, reason_code)
        with self._lock:
            previous = self._statuses.get(component)
            if previous == value:
                return
            self._statuses[component] = value
        self._logger.warning(
            "记忆能力状态已变化：%s -> %s。",
            previous.state if previous else "unknown",
            state,
            extra={
                "component": component,
                "state": state,
                "reason_code": reason_code,
            },
        )

    def mark_ready(self, component: str, reason_code: str) -> None:
        current = self.get(component)
        if current.state != "healthy" or current.reason_code != reason_code:
            self.transition(component, "healthy", reason_code)


@dataclass(frozen=True)
class MemoryCommandResult:
    code: str
    message: str


class MemoryCommandAdapter:
    def __init__(self, service: MemoryService) -> None:
        self._service = service

    @staticmethod
    def matches(content: str) -> bool:
        return content.strip() == "/memory" or content.lstrip().startswith("/memory ")

    def execute(self, actor: Actor, content: str) -> MemoryCommandResult:
        try:
            return self._execute(actor, content)
        except MemoryError as exc:
            return _error_result(exc)
        except StoreError:
            return MemoryCommandResult(
                "memory_persistence_unavailable",
                "记忆权威存储暂时不可用，操作未确认成功。",
            )

    def _execute(self, actor: Actor, content: str) -> MemoryCommandResult:
        parts = content.strip().split()
        if not parts or parts[0] != "/memory":
            raise MemoryInvalidCommand
        operation = parts[1] if len(parts) > 1 else "help"
        auth = self._service.command_authorization(
            actor, action="write" if operation == "update" else "manage"
        )
        if operation == "help" and len(parts) in {1, 2}:
            return MemoryCommandResult(
                "memory_help",
                "可用命令：/memory status|list [cursor]|show <id>|update <id> <fact>|forget <id>|revoke-source <source_ref>|disable|enable|delete-all CONFIRM",
            )
        if operation == "status" and len(parts) == 2:
            status = self._service.status(auth)
            return MemoryCommandResult(
                "memory_status",
                f"记忆状态：{status.state}（{status.reason_code}）；待处理 {status.pending}，失败 {status.failed}，事实索引待同步 {status.index_pending}，G1 图待同步 {status.graph_pending}，G1 图失败 {status.graph_failed}。"
                + (
                    f" 安全错误摘要：{status.error_summary}。"
                    if status.error_summary
                    else ""
                ),
            )
        if operation == "list" and len(parts) in {2, 3}:
            page = self._service.list(auth, parts[2] if len(parts) == 3 else None)
            if not page.items:
                return MemoryCommandResult("memory_list", "没有活动长期记忆。")
            lines = [f"{item.memory_id}  {item.fact[:80]}" for item in page.items]
            if page.next_cursor:
                lines.append(f"下一页：/memory list {page.next_cursor}")
            return MemoryCommandResult("memory_list", "\n".join(lines))
        if operation == "show" and len(parts) == 3:
            fact = self._service.show(auth, parts[2])
            sources = "、".join(fact.source_refs) or "无"
            valid_until = (
                fact.valid_until.isoformat() if fact.valid_until else "长期有效"
            )
            return MemoryCommandResult(
                "memory_show",
                f"{fact.memory_id}\n事实：{fact.fact}\n状态：{fact.status}\n事实可用：是\nG1 图待同步：{self._service.status(auth).graph_pending}\n有效期：{valid_until}\n来源：{sources}",
            )
        if operation == "forget" and len(parts) == 3:
            self._service.forget(auth, parts[2])
            return MemoryCommandResult("memory_forgotten", "该记忆已不可召回。")
        if operation == "update" and len(parts) >= 4:
            fact = self._service.update(auth, parts[2], " ".join(parts[3:]))
            status = self._service.status(
                self._service.command_authorization(actor, action="manage")
            )
            suffix = (
                "；事实已可用，G1 图正在后台同步。"
                if status.graph_pending
                else "。"
            )
            return MemoryCommandResult(
                "memory_updated", f"记忆已更新，新 ID：{fact.memory_id}{suffix}"
            )
        if operation == "revoke-source" and len(parts) == 3:
            count, token = self._service.request_revoke_source(auth, parts[2])
            if token is not None:
                return MemoryCommandResult(
                    "memory_source_confirmation_required",
                    f"该来源影响 {count} 条活动记忆。确认撤销：/memory revoke-source {parts[2]} {token}",
                )
            return MemoryCommandResult(
                "memory_source_revoked", f"来源已撤销，{count} 条记忆受到影响。"
            )
        if operation == "revoke-source" and len(parts) == 4:
            count = self._service.confirm_revoke_source(auth, parts[2], parts[3])
            return MemoryCommandResult(
                "memory_source_revoked", f"来源已撤销，{count} 条记忆受到影响。"
            )
        if operation == "disable" and len(parts) == 2:
            self._service.set_enabled(auth, False)
            return MemoryCommandResult(
                "memory_disabled", "记忆已关闭，现有数据未删除。"
            )
        if operation == "enable" and len(parts) == 2:
            self._service.set_enabled(auth, True)
            return MemoryCommandResult("memory_enabled", "记忆已启用。")
        if operation == "delete-all" and len(parts) == 2:
            token, count = self._service.request_delete_all(auth)
            return MemoryCommandResult(
                "memory_delete_confirmation_required",
                f"将删除 {count} 条活动记忆。5 分钟内确认：/memory delete-all {token}",
            )
        if operation == "delete-all" and len(parts) == 3:
            count = self._service.confirm_delete_all(auth, parts[2])
            return MemoryCommandResult(
                "memory_all_deleted", f"全部活动记忆已不可召回，共 {count} 条。"
            )
        raise MemoryInvalidCommand


def _error_result(exc: MemoryError) -> MemoryCommandResult:
    messages = {
        "memory_unauthorized": "当前身份或授权已失效，未执行记忆操作。",
        "memory_disabled": "记忆已关闭，写入未执行。",
        "memory_unsupported": "当前临时身份不支持跨会话记忆。",
        "memory_not_found": "未找到当前账号可管理的活动记忆。",
        "memory_invalid_cursor": "分页游标无效或不属于当前账号。",
        "memory_unsafe_content": "该内容不符合长期事实的持久化规则，未写入。",
        "memory_invalid_command": "命令格式无效，请使用 /memory help 查看可用命令。",
        "memory_confirmation_invalid": "确认 token 无效、已过期、已使用或数据状态已变化，未执行操作。",
        "memory_purge_pending": "记忆仍在完成删除清理，当前不能重新启用。",
        "memory_disable_not_persisted": "当前进程已停止记忆注入，但全局关闭未能持久化，请稍后重试。",
    }
    return MemoryCommandResult(exc.code, messages.get(exc.code, "记忆操作失败。"))
