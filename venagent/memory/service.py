"""M05 稳定 façade，以显式组合委托授权、管理、写入、任务与召回。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal

from ..conversation.models import ConversationMessage
from ..ownership.models import Actor, ExecutionAuthorization
from ..ownership.ports import OwnershipStore
from ..promptctx.context import ContextBlock, conservative_token_count
from ..promptctx.recall_provider import MemoryRecallProvider
from .embedding.index import MemoryIndex
from .errors import MemoryDisabled, MemoryError, MemoryUnsupported
from .graph_memory import DisabledGraphMemoryStore, GraphMemory
from .jobs import MemoryJobs
from .long_term.facts import ConflictJudge, MemoryFact, MemoryPage
from .long_term.writer import LongTermWriter
from .management import MemoryCapabilityRegistry, MemoryHealth, MemoryManager
from .model_adapters import StructuredMemoryExtractor
from .ports import MemoryGraphStore, MemoryStore
from .ports import MemoryStoreError as StoreError
from .recall import (
    MemoryAuthorization,
    MemoryAuthorizer,
    MemoryRecall,
    MemoryRequestSnapshot,
)
from .short_term import SummaryBuilder

if TYPE_CHECKING:
    from ..conversation.ports import ConversationStore

NaturalMemoryOperation = Literal["remember", "forget"]
NaturalMemoryStatus = Literal[
    "saved",
    "partial",
    "rejected",
    "disabled",
    "unavailable",
    "deleted",
    "ambiguous",
    "not_found",
]


@dataclass(frozen=True)
class NaturalMemoryOutcome:
    operation: NaturalMemoryOperation
    status: NaturalMemoryStatus
    saved_count: int = 0
    rejected_count: int = 0
    reason_codes: tuple[str, ...] = ()

    def context_block(self, run_id: str) -> ContextBlock:
        reasons = ",".join(sorted(set(self.reason_codes))) or "none"
        content = (
            "当前用户消息包含自然语言记忆操作。以下结果来自记忆权威用例，必须作为最终回复的事实依据：\n"
            f"operation={self.operation}\nstatus={self.status}\n"
            f"saved_count={self.saved_count}\nrejected_count={self.rejected_count}\n"
            f"reason_codes={reasons}\n"
            "请结合用户原话自然回复。只能根据 status 表达已保存、部分保存、未保存、已删除、"
            "未找到或无法确认；不得声称未实际完成的保存或删除。不要输出内部字段名、ID 或策略元数据。"
        )
        return ContextBlock(
            f"natural-memory-outcome:{run_id}",
            "output_contract",
            "memory-service",
            content,
            100,
            True,
            conservative_token_count(content),
        )


class MemoryService:
    def __init__(
        self,
        store: MemoryStore,
        ownership: OwnershipStore,
        *,
        graph_store: MemoryGraphStore | None = None,
        cursor_secret: str,
        clock: Callable[[], datetime] | None = None,
        summary_builder: SummaryBuilder | None = None,
        capability_registry: MemoryCapabilityRegistry | None = None,
        quarantine_ttl: timedelta = timedelta(days=30),
        extractor: StructuredMemoryExtractor | None = None,
        conflict_judge: ConflictJudge | None = None,
        memory_index: MemoryIndex | None = None,
        conversation: ConversationStore | None = None,
        window_messages: int = 5,
        idle_seconds: int = 600,
        max_input_tokens: int = 4000,
    ) -> None:
        self._store = store
        self._extractor = extractor
        self._capabilities = capability_registry
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._local_disabled: set[str] = set()

        resolved_graph = graph_store
        if resolved_graph is None and all(
            hasattr(store, name)
            for name in ("read_edges", "replace_graph", "purge_graph")
        ):
            resolved_graph = store  # type: ignore[assignment]
        graph_memory = GraphMemory(
            store, resolved_graph or DisabledGraphMemoryStore()
        )
        authorizer = MemoryAuthorizer(
            store,
            ownership,
            self._local_disabled,
            self._now,
            capability_registry,
        )
        writer = LongTermWriter(
            store,
            authorizer,
            self._now,
            self._transition,
            quarantine_ttl=quarantine_ttl,
            conflict_judge=conflict_judge,
        )
        self._authorizer = authorizer
        self._manager = MemoryManager(
            store,
            ownership,
            authorizer,
            writer,
            self._local_disabled,
            cursor_secret.encode("utf-8"),
            self._now,
        )
        self._writer = writer
        self._jobs = MemoryJobs(
            store,
            ownership,
            graph_memory,
            authorizer,
            writer,
            self._now,
            self._transition,
            extractor,
            memory_index,
            conversation,
            window_messages=window_messages,
            idle_seconds=idle_seconds,
            max_input_tokens=max_input_tokens,
        )
        self._recall = MemoryRecall(
            store,
            ownership,
            graph_memory,
            authorizer,
            self._local_disabled,
            self._now,
            self._transition,
            summary_builder,
            memory_index,
        )
        self._recall_provider = MemoryRecallProvider(self._recall)

    @property
    def store(self) -> MemoryStore:
        return self._store

    def command_authorization(
        self, actor: Actor, *, action: str = "manage"
    ) -> MemoryAuthorization:
        return self._authorizer.command_authorization(actor, action=action)

    def run_authorization(
        self, authorization: ExecutionAuthorization, *, action: str
    ) -> MemoryAuthorization:
        return self._authorizer.run_authorization(authorization, action=action)

    def capture_snapshot(
        self, auth: MemoryAuthorization, *, allow_disabled: bool = False
    ) -> MemoryRequestSnapshot:
        return self._authorizer.capture_snapshot(
            auth, allow_disabled=allow_disabled
        )

    def status(self, auth: MemoryAuthorization) -> MemoryHealth:
        return self._manager.status(auth)

    def set_enabled(self, auth: MemoryAuthorization, enabled: bool) -> None:
        self._manager.set_enabled(auth, enabled)

    def list(
        self, auth: MemoryAuthorization, cursor: str | None = None
    ) -> MemoryPage:
        return self._manager.list(auth, cursor)

    def show(self, auth: MemoryAuthorization, memory_id: str) -> MemoryFact:
        return self._manager.show(auth, memory_id)

    def forget(self, auth: MemoryAuthorization, memory_id: str) -> None:
        previous = self._manager.show(auth, memory_id)
        self._manager.forget(auth, memory_id)
        current = self._store.get_fact(auth.owner_id, previous.memory_id)
        if current is not None:
            self._jobs.enqueue_index(current)

    def forget_matching(
        self, auth: MemoryAuthorization, query: str
    ) -> tuple[MemoryFact, ...]:
        forgotten = self._manager.forget_matching(auth, query)
        for fact in forgotten:
            current = self._store.get_fact(auth.owner_id, fact.memory_id)
            if current is not None:
                self._jobs.enqueue_index(current)
        return forgotten

    def delete_all(self, auth: MemoryAuthorization) -> int:
        return self._manager.delete_all(auth)

    def request_delete_all(self, auth: MemoryAuthorization) -> tuple[str, int]:
        return self._manager.request_delete_all(auth)

    def confirm_delete_all(self, auth: MemoryAuthorization, token: str) -> int:
        return self._manager.confirm_delete_all(auth, token)

    def revoke_source(self, auth: MemoryAuthorization, source_ref: str) -> int:
        return self._manager.revoke_source(auth, source_ref)

    def request_revoke_source(
        self, auth: MemoryAuthorization, source_ref: str
    ) -> tuple[int, str | None]:
        return self._manager.request_revoke_source(auth, source_ref)

    def confirm_revoke_source(
        self, auth: MemoryAuthorization, source_ref: str, token: str
    ) -> int:
        return self._manager.confirm_revoke_source(auth, source_ref, token)

    def update(
        self, auth: MemoryAuthorization, memory_id: str, content: str
    ) -> MemoryFact:
        previous = self._manager.show(auth, memory_id)
        replacement = self._manager.update(auth, memory_id, content)
        stale = self._store.get_fact(auth.owner_id, previous.memory_id)
        if stale is not None:
            self._jobs.enqueue_index(stale)
        self._jobs.enqueue_index(replacement)
        return self._store.get_fact(auth.owner_id, replacement.memory_id) or replacement

    def remember(
        self,
        auth: MemoryAuthorization,
        content: str,
        *,
        source_ref: str,
        source_order: int,
        explicit: bool,
        source_kind: str = "user_message",
    ) -> MemoryFact | None:
        fact = self._writer.remember(
            auth,
            content,
            source_ref=source_ref,
            source_order=source_order,
            explicit=explicit,
            source_kind=source_kind,
        )
        if fact is not None:
            self._jobs.enqueue_index(fact)
            return self._store.get_fact(auth.owner_id, fact.memory_id) or fact
        return None

    @staticmethod
    def natural_intent(content: str) -> NaturalMemoryOperation | None:
        normalized = content.strip()
        if normalized.startswith(("记住", "请记住")):
            return "remember"
        if normalized.startswith("忘记"):
            return "forget"
        return None

    def process_natural_intent(
        self,
        authorization: ExecutionAuthorization,
        content: str,
        *,
        source_ref: str,
        source_order: int,
    ) -> NaturalMemoryOutcome | None:
        """在正常 run 内先取得权威结果，再由回答模型组织自然回复。"""

        operation = self.natural_intent(content)
        if operation is None:
            return None
        try:
            if operation == "forget":
                query = content.strip().removeprefix("忘记").strip(" ，,:：")
                if not query:
                    return NaturalMemoryOutcome(
                        "forget", "rejected", rejected_count=1,
                        reason_codes=("missing_forget_query",),
                    )
                auth = self.run_authorization(authorization, action="delete")
                matches = self.forget_matching(auth, query)
                if len(matches) == 1:
                    return NaturalMemoryOutcome("forget", "deleted")
                if matches:
                    return NaturalMemoryOutcome(
                        "forget", "ambiguous", rejected_count=len(matches),
                        reason_codes=("multiple_matches",),
                    )
                return NaturalMemoryOutcome(
                    "forget", "not_found", reason_codes=("no_match",)
                )

            auth = self.run_authorization(authorization, action="write")
            candidates = (
                self._extractor.extract(content)
                if self._extractor is not None
                else None
            )
            result = self._writer.remember_all_result(
                auth,
                content,
                source_ref=source_ref,
                source_order=source_order,
                explicit=True,
                extracted_candidates=candidates,
            )
            for fact in result.saved:
                self._jobs.enqueue_index(fact)
            saved = len(result.saved)
            rejected = len(result.rejected)
            if saved and rejected:
                status: NaturalMemoryStatus = "partial"
            elif saved:
                status = "saved"
            else:
                status = "rejected"
            return NaturalMemoryOutcome(
                "remember",
                status,
                saved_count=saved,
                rejected_count=rejected,
                reason_codes=tuple(item.reason for item in result.rejected),
            )
        except (MemoryDisabled, MemoryUnsupported) as exc:
            return NaturalMemoryOutcome(
                operation, "disabled", reason_codes=(exc.code,)
            )
        except (MemoryError, StoreError):
            return NaturalMemoryOutcome(
                operation, "unavailable", reason_codes=("operation_unavailable",)
            )
        except Exception:
            return NaturalMemoryOutcome(
                operation, "unavailable", reason_codes=("provider_unavailable",)
            )

    def enqueue_extraction(
        self,
        auth: MemoryAuthorization,
        content: str,
        *,
        source_ref: str,
        source_order: int,
        source_kind: str = "user_message",
    ) -> bool:
        return self._jobs.enqueue_extraction(
            auth,
            content,
            source_ref=source_ref,
            source_order=source_order,
            source_kind=source_kind,
        )

    def record_user_message_for_consolidation(
        self,
        auth: MemoryAuthorization,
        *,
        conversation_id: str,
        sequence: int,
        now: datetime | None = None,
    ) -> bool:
        """沉淀式写入（D1）：用户消息推进对话游标，攒满窗口才入队抽取。"""
        return self._jobs.record_user_message_for_consolidation(
            auth,
            conversation_id=conversation_id,
            sequence=sequence,
            now=now,
        )

    def process_pending_jobs(self, *, limit: int = 8) -> int:
        return self._jobs.process_pending_jobs(limit=limit)

    def replay_failed_jobs(self, auth: MemoryAuthorization) -> int:
        return self._jobs.replay_failed_jobs(auth)

    def context_blocks(
        self,
        auth: MemoryAuthorization,
        query: str,
        *,
        limit: int = 5,
        snapshot: MemoryRequestSnapshot | None = None,
    ) -> tuple[ContextBlock, ...]:
        return self._recall_provider.context_blocks(
            auth, query, limit=limit, snapshot=snapshot
        )

    def conversation_context(
        self,
        auth: MemoryAuthorization,
        messages: tuple[ConversationMessage, ...],
        input_message_id: str,
        *,
        token_budget: int = 20_000,
        snapshot: MemoryRequestSnapshot | None = None,
    ) -> tuple[ConversationMessage, ...]:
        return self._recall.conversation_context(
            auth,
            messages,
            input_message_id,
            token_budget=token_budget,
            snapshot=snapshot,
        )

    def summary_blocks(
        self,
        auth: MemoryAuthorization,
        messages: tuple[ConversationMessage, ...],
        input_message_id: str,
        *,
        token_budget: int = 20_000,
        snapshot: MemoryRequestSnapshot | None = None,
    ) -> tuple[ContextBlock, ...]:
        return self._recall_provider.summary_blocks(
            auth,
            messages,
            input_message_id,
            token_budget=token_budget,
            snapshot=snapshot,
        )

    def note_provider_timeout(self, component: str) -> None:
        self._recall.note_provider_timeout(component)

    def note_provider_ready(self, component: str, reason_code: str) -> None:
        self._recall.note_provider_ready(component, reason_code)

    def prepare_owner_deletion(self, owner_id: str) -> bool:
        """仅在 owner 图清理持久收敛后返回 true。"""

        settings = self._store.settings(owner_id)
        if settings.enabled or settings.deletion_generation == 0:
            self._store.delete_all(owner_id, self._now())
            return False
        return not settings.purge_pending

    def _transition(self, component: str, state: str, reason_code: str) -> None:
        if self._capabilities is not None:
            self._capabilities.transition(component, state, reason_code)  # type: ignore[arg-type]

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
