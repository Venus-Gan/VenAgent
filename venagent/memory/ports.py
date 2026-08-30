"""记忆领域消费方定义的持久化端口。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from .embedding.index import MemoryIndexStore
from .long_term.facts import MemoryFact, MemorySource
from .short_term import MemorySummary

if TYPE_CHECKING:
    from .graph_memory import MemoryEdge
    from .jobs import MemoryJob
    from .management import MemorySettings


class MemoryStoreError(RuntimeError):
    """memory adapter 的安全失败，不向业务层泄露存储细节。"""


class MemoryGraphSnapshotError(MemoryStoreError):
    """权威 facts/sources 可重读，但 graph 部分未形成一致快照。"""


class GraphProjectionStatus(StrEnum):
    APPLIED = "applied"
    CURRENT = "current"
    STALE = "stale"


@dataclass(frozen=True)
class G1RecallSnapshot:
    """同一 owner/tenant 在一个 adapter 读快照中的 G1 召回数据。"""

    owner_id: str
    tenant_id: str
    settings: MemorySettings
    facts: tuple[MemoryFact, ...]
    sources: tuple[MemorySource, ...]
    authority_revision: int = 0


@dataclass(frozen=True)
class G1GraphSnapshot:
    owner_id: str
    tenant_id: str
    applied_revision: int
    deletion_generation: int
    registry_version: str
    edges: tuple[MemoryEdge, ...]


@dataclass(frozen=True)
class ConsolidationCursor:
    """每对话的沉淀游标：已抽取到哪条 sequence、最新用户消息到哪条。"""

    owner_id: str
    tenant_id: str
    conversation_id: str
    last_consolidated_sequence: int
    last_message_sequence: int
    last_activity_at: datetime
    deletion_generation: int


class MemoryAuthorizationStore(Protocol):
    """授权边界只读取 owner 的记忆开关与 fencing 版本。"""

    durable: bool

    def enabled(self, owner_id: str) -> bool: ...

    def settings(self, owner_id: str) -> MemorySettings: ...

    def authority_revision(self, owner_id: str, tenant_id: str) -> int: ...


class MemoryFactWriteStore(Protocol):
    """长期事实写入用例所需的最小原子操作集合。"""

    def get_fact(self, owner_id: str, memory_id: str) -> MemoryFact | None: ...

    def find_active_by_slot(
        self, owner_id: str, tenant_id: str, subject: str, slot: str
    ) -> MemoryFact | None: ...

    def resolve_quarantine(
        self,
        owner_id: str,
        tenant_id: str,
        subject: str,
        slot: str,
        chosen_fact: str,
        now: datetime,
    ) -> int: ...

    def save_fact(
        self, fact: MemoryFact, source: MemorySource, now: datetime
    ) -> MemoryFact: ...

    def add_source(
        self, fact: MemoryFact, source: MemorySource, now: datetime
    ) -> MemoryFact: ...

    def replace_fact(
        self,
        previous: MemoryFact,
        replacement: MemoryFact,
        source: MemorySource,
        now: datetime,
    ) -> MemoryFact: ...


class MemoryManagementStore(
    MemoryAuthorizationStore, MemoryFactWriteStore, Protocol
):
    """用户管理面所需的查询、确认和生命周期操作。"""

    def set_enabled(self, owner_id: str, enabled: bool, now: datetime) -> None: ...

    def set_index_status(
        self, owner_id: str, memory_ids: tuple[str, ...], status: str, now: datetime
    ) -> None: ...

    def list_facts(
        self,
        owner_id: str,
        tenant_id: str,
        *,
        before: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[MemoryFact, ...]: ...

    def deactivate_fact(
        self, owner_id: str, memory_id: str, status: str, now: datetime
    ) -> bool: ...

    def delete_all(self, owner_id: str, now: datetime) -> int: ...

    def revoke_source(self, owner_id: str, source_ref: str, now: datetime) -> int: ...

    def source_impact(self, owner_id: str, source_ref: str) -> tuple[str, ...]: ...

    def issue_confirmation(
        self,
        owner_id: str,
        operation: str,
        target_ref: str,
        token_hash: str,
        state_hash: str,
        expires_at: datetime,
        now: datetime,
    ) -> None: ...

    def confirm_delete_all(
        self, owner_id: str, token_hash: str, state_hash: str, now: datetime
    ) -> int | None: ...

    def confirm_revoke_source(
        self,
        owner_id: str,
        source_ref: str,
        token_hash: str,
        state_hash: str,
        now: datetime,
    ) -> int | None: ...

    def source(self, owner_id: str, source_ref: str) -> MemorySource | None: ...

    def active_facts(self, owner_id: str, tenant_id: str) -> tuple[MemoryFact, ...]: ...

    def expire_due(self, now: datetime) -> int: ...


class MemoryRecallStore(MemoryAuthorizationStore, Protocol):
    """召回侧读取一致快照并维护短期摘要。"""

    def recall_snapshot(self, owner_id: str, tenant_id: str) -> G1RecallSnapshot: ...

    def get_summary(
        self, owner_id: str, conversation_id: str
    ) -> MemorySummary | None: ...

    def save_summary(self, summary: MemorySummary) -> None: ...

    def expire_due(self, now: datetime) -> int: ...


class MemoryGraphAuthorityStore(Protocol):
    """可重建图只依赖关系数据库提供的权威召回快照。"""

    def recall_snapshot(self, owner_id: str, tenant_id: str) -> G1RecallSnapshot: ...


class MemoryJobStore(MemoryAuthorizationStore, Protocol):
    """后台任务 claim、重试与 purge fencing 所需的持久操作。"""

    def enqueue_job(self, job: MemoryJob) -> bool: ...

    def get_fact(self, owner_id: str, memory_id: str) -> MemoryFact | None: ...

    def set_index_status(
        self, owner_id: str, memory_ids: tuple[str, ...], status: str, now: datetime
    ) -> None: ...

    def claim_jobs(self, now: datetime, *, limit: int) -> tuple[MemoryJob, ...]: ...

    def complete_job(self, job_id: str, claim_token: str, now: datetime) -> bool: ...

    def retry_job(
        self,
        job_id: str,
        claim_token: str,
        error_code: str,
        available_at: datetime,
        now: datetime,
    ) -> bool: ...

    def cancel_job(self, job_id: str, claim_token: str, now: datetime) -> bool: ...

    def requeue_failed(self, owner_id: str, now: datetime) -> int: ...

    def finish_purge(self, owner_id: str, generation: int, now: datetime) -> bool: ...

    def expire_due(self, now: datetime) -> int: ...

    def source(self, owner_id: str, source_ref: str) -> MemorySource | None: ...

    # --- 沉淀式写入（M05 consolidation）游标面 ---

    def upsert_consolidation_cursor(
        self,
        owner_id: str,
        tenant_id: str,
        conversation_id: str,
        sequence: int,
        now: datetime,
        deletion_generation: int,
    ) -> ConsolidationCursor | None: ...

    def get_consolidation_cursor(
        self, owner_id: str, tenant_id: str, conversation_id: str
    ) -> ConsolidationCursor | None: ...

    def advance_consolidation_cursor(
        self, owner_id: str, conversation_id: str, sequence: int, now: datetime
    ) -> bool: ...

    def find_idle_consolidations(
        self, now: datetime, idle_before: datetime, limit: int
    ) -> tuple[ConsolidationCursor, ...]: ...


class MemoryStore(
    MemoryManagementStore,
    MemoryRecallStore,
    MemoryJobStore,
    MemoryIndexStore,
    Protocol,
):
    """完整 adapter 契约；业务协作者应依赖上方各自的窄端口。"""


class MemoryGraphStore(Protocol):
    configured: bool

    def read_edges(
        self,
        owner_id: str,
        tenant_id: str,
        seed_ids: tuple[str, ...],
        expected_revision: int,
        deletion_generation: int,
        registry_version: str,
    ) -> G1GraphSnapshot: ...

    def replace_graph(
        self,
        owner_id: str,
        tenant_id: str,
        edges: tuple[MemoryEdge, ...],
        target_revision: int,
        deletion_generation: int,
        registry_version: str,
    ) -> GraphProjectionStatus: ...

    def purge_graph(
        self,
        owner_id: str,
        tenant_id: str,
        target_revision: int,
        deletion_generation: int,
    ) -> None: ...
