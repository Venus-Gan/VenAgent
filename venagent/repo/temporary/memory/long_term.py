"""temporary 长期事实、来源、设置与删除操作。"""

from __future__ import annotations

# ruff: noqa: F401
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from threading import RLock
from uuid import uuid4

from ....memory.capabilities import MemorySettings
from ....memory.long_term.facts import MemoryFact, MemorySource
from ....memory.ports import MemoryStoreError as StoreError
from .fact_state import _ids_hash, _redacted


class _TemporaryLongTermMixin:
    def enabled(self, owner_id: str) -> bool:
        return self.durable and self.settings(owner_id).enabled

    def settings(self, owner_id: str) -> MemorySettings:
        with self._lock:
            current = self._settings.get(
                owner_id,
                MemorySettings(
                    enabled=self.durable, deletion_generation=0, purge_pending=False
                ),
            )
            pending = sum(
                item.owner_id == owner_id and item.status in {"pending", "running"}
                for item in self._jobs.values()
            )
            failed = sum(
                item.owner_id == owner_id and item.status == "failed"
                for item in self._jobs.values()
            )
            index_pending = sum(
                item.owner_id == owner_id
                and item.active
                and item.index_status != "ready"
                for item in self._facts.values()
            )
            graph_pending = sum(
                item.owner_id == owner_id
                and item.operation in {"project", "purge"}
                and item.status in {"pending", "running"}
                for item in self._jobs.values()
            )
            graph_failed = sum(
                item.owner_id == owner_id
                and item.operation in {"project", "purge"}
                and item.status == "failed"
                for item in self._jobs.values()
            )
            return replace(
                current,
                pending_jobs=pending,
                failed_jobs=failed,
                index_pending=index_pending,
                graph_pending=graph_pending,
                graph_failed=graph_failed,
            )

    def set_enabled(self, owner_id: str, enabled: bool, now: datetime) -> None:
        with self._lock:
            current = self._settings.get(owner_id, MemorySettings(True, 0, False))
            if enabled and current.purge_pending:
                raise StoreError("memory purge is pending")
            if current.enabled != enabled:
                self._settings[owner_id] = replace(current, enabled=enabled)
                tenants = {
                    fact.tenant_id
                    for fact in self._facts.values()
                    if fact.owner_id == owner_id
                } or {"default"}
                for tenant_id in tenants:
                    self._enqueue_projection(owner_id, tenant_id, now)

    def set_index_status(
        self, owner_id: str, memory_ids: tuple[str, ...], status: str, now: datetime
    ) -> None:
        with self._lock:
            for memory_id in memory_ids:
                fact = self._facts.get(memory_id)
                if fact is not None and fact.owner_id == owner_id and fact.active:
                    self._facts[memory_id] = replace(
                        fact, index_status=status, updated_at=now
                    )

    def list_facts(
        self,
        owner_id: str,
        tenant_id: str,
        *,
        before: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[MemoryFact, ...]:
        with self._lock:
            values = [
                item
                for item in self._facts.values()
                if item.owner_id == owner_id
                and item.tenant_id == tenant_id
                and item.active
                and (before is None or (item.updated_at, item.memory_id) < before)
            ]
        return tuple(
            sorted(
                values, key=lambda item: (item.updated_at, item.memory_id), reverse=True
            )[:limit]
        )

    def get_fact(self, owner_id: str, memory_id: str) -> MemoryFact | None:
        with self._lock:
            fact = self._facts.get(memory_id)
            return fact if fact is not None and fact.owner_id == owner_id else None

    def find_active_by_slot(
        self, owner_id: str, tenant_id: str, subject: str, slot: str
    ) -> MemoryFact | None:
        with self._lock:
            matches = [
                item
                for item in self._facts.values()
                if item.owner_id == owner_id
                and item.tenant_id == tenant_id
                and item.subject == subject
                and item.slot == slot
                and item.active
            ]
        return max(
            matches, key=lambda item: (item.updated_at, item.memory_id), default=None
        )

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
            targets = [
                item
                for item in self._facts.values()
                if item.owner_id == owner_id
                and item.tenant_id == tenant_id
                and item.subject == subject
                and item.slot == slot
                and item.status == "quarantine"
            ]
            for item in targets:
                self._facts[item.memory_id] = replace(
                    item, status="superseded", updated_at=now
                )
            if targets:
                self._enqueue_projection(owner_id, tenant_id, now)
            return len(targets)

    def save_fact(
        self, fact: MemoryFact, source: MemorySource, now: datetime
    ) -> MemoryFact:
        with self._lock:
            existing = self._facts.get(fact.memory_id)
            if existing is not None:
                return existing
            self._save_source(source)
            self._facts[fact.memory_id] = fact
            if fact.active:
                self._enqueue_projection(fact.owner_id, fact.tenant_id, now)
            return fact

    def add_source(
        self, fact: MemoryFact, source: MemorySource, now: datetime
    ) -> MemoryFact:
        with self._lock:
            current = self._facts.get(fact.memory_id)
            if current is None or not current.active:
                return fact
            self._save_source(source)
            refs = tuple(sorted({*current.source_refs, source.source_ref}))
            updated = replace(current, source_refs=refs, updated_at=now)
            self._facts[fact.memory_id] = updated
            self._enqueue_projection(fact.owner_id, fact.tenant_id, now)
            return updated

    def replace_fact(
        self,
        previous: MemoryFact,
        replacement: MemoryFact,
        source: MemorySource,
        now: datetime,
    ) -> MemoryFact:
        with self._lock:
            current = self._facts.get(previous.memory_id)
            if current is None or not current.active:
                return replacement
            self._facts[previous.memory_id] = replace(
                current, status="superseded", updated_at=now
            )
            self._save_source(source)
            self._facts[replacement.memory_id] = replacement
            self._enqueue_projection(
                replacement.owner_id, replacement.tenant_id, now
            )
            return replacement

    def deactivate_fact(
        self, owner_id: str, memory_id: str, status: str, now: datetime
    ) -> bool:
        with self._lock:
            current = self._facts.get(memory_id)
            if current is None or current.owner_id != owner_id or not current.active:
                return False
            self._facts[memory_id] = _redacted(current, status, now)
            self._enqueue_projection(owner_id, current.tenant_id, now)
            return True

    def delete_all(self, owner_id: str, now: datetime) -> int:
        with self._lock:
            active_targets = [
                item.memory_id
                for item in self._facts.values()
                if item.owner_id == owner_id and item.active
            ]
            # 删除 owner 数据时同时抹除 superseded/quarantine 内容，不能只隐藏当前 active 事实。
            redact_targets = [
                item.memory_id
                for item in self._facts.values()
                if item.owner_id == owner_id
                and item.status not in {"deleted", "expired"}
            ]
            for memory_id in redact_targets:
                current = self._facts[memory_id]
                self._facts[memory_id] = _redacted(current, "deleted", now)
            current = self._settings.get(owner_id, MemorySettings(True, 0, False))
            generation = current.deletion_generation + 1
            self._settings[owner_id] = replace(
                current,
                enabled=False,
                deletion_generation=generation,
                purge_pending=True,
            )
            self._summaries = {
                key: value
                for key, value in self._summaries.items()
                if value.owner_id != owner_id
            }
            tenants = {
                fact.tenant_id
                for fact in self._facts.values()
                if fact.owner_id == owner_id
            } or {"default"}
            for tenant_id in tenants:
                self._enqueue_purge(owner_id, tenant_id, generation, now)
            return len(active_targets)

    def revoke_source(self, owner_id: str, source_ref: str, now: datetime) -> int:
        with self._lock:
            source = self._sources.get(source_ref)
            if source is None or source.owner_id != owner_id or not source.active:
                return 0
            self._sources[source_ref] = replace(source, active=False)
            affected = 0
            affected_tenants: set[str] = set()
            for memory_id, fact in tuple(self._facts.items()):
                if (
                    fact.owner_id != owner_id
                    or not fact.active
                    or source_ref not in fact.source_refs
                ):
                    continue
                affected += 1
                affected_tenants.add(fact.tenant_id)
                remaining = tuple(
                    ref
                    for ref in fact.source_refs
                    if ref != source_ref and self._sources.get(ref, source).active
                )
                if remaining:
                    self._facts[memory_id] = replace(
                        fact, source_refs=remaining, updated_at=now
                    )
                else:
                    self._facts[memory_id] = _redacted(fact, "deleted", now)
            for tenant_id in affected_tenants:
                self._enqueue_projection(owner_id, tenant_id, now)
            return affected

    def source_impact(self, owner_id: str, source_ref: str) -> tuple[str, ...]:
        with self._lock:
            source = self._sources.get(source_ref)
            if source is None or source.owner_id != owner_id or not source.active:
                return ()
            return tuple(
                sorted(
                    item.memory_id
                    for item in self._facts.values()
                    if item.owner_id == owner_id
                    and item.active
                    and source_ref in item.source_refs
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
            self._confirmations[token_hash] = (
                owner_id,
                operation,
                target_ref,
                state_hash,
                expires_at,
            )

    def confirm_delete_all(
        self, owner_id: str, token_hash: str, state_hash: str, now: datetime
    ) -> int | None:
        with self._lock:
            if not self._consume_confirmation(
                owner_id, "delete-all", "*", token_hash, state_hash, now
            ):
                return None
            if self._active_state_hash(owner_id) != state_hash:
                return None
            count = self.delete_all(owner_id, now)
            return count

    def confirm_revoke_source(
        self,
        owner_id: str,
        source_ref: str,
        token_hash: str,
        state_hash: str,
        now: datetime,
    ) -> int | None:
        with self._lock:
            if not self._consume_confirmation(
                owner_id, "revoke-source", source_ref, token_hash, state_hash, now
            ):
                return None
            if _ids_hash(self.source_impact(owner_id, source_ref)) != state_hash:
                return None
            return self.revoke_source(owner_id, source_ref, now)

    def source(self, owner_id: str, source_ref: str) -> MemorySource | None:
        with self._lock:
            source = self._sources.get(source_ref)
            return (
                source if source is not None and source.owner_id == owner_id else None
            )

    def active_facts(self, owner_id: str, tenant_id: str) -> tuple[MemoryFact, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for item in self._facts.values()
                        if item.owner_id == owner_id
                        and item.tenant_id == tenant_id
                        and item.active
                    ),
                    key=lambda item: (item.created_at, item.memory_id),
                )
            )

    def _save_source(self, source: MemorySource) -> None:
        existing = self._sources.get(source.source_ref)
        if existing is not None and (
            existing.owner_id != source.owner_id
            or existing.tenant_id != source.tenant_id
            or existing.source_kind != source.source_kind
        ):
            raise StoreError("source reference authorization scope mismatch")
        self._sources.setdefault(source.source_ref, source)

    def _consume_confirmation(
        self,
        owner_id: str,
        operation: str,
        target_ref: str,
        token_hash: str,
        state_hash: str,
        now: datetime,
    ) -> bool:
        value = self._confirmations.pop(token_hash, None)
        if value is None:
            return False
        stored_owner, stored_operation, stored_target, stored_state, expires_at = value
        return (
            stored_owner == owner_id
            and stored_operation == operation
            and stored_target == target_ref
            and stored_state == state_hash
            and expires_at > now
        )

    def _active_state_hash(self, owner_id: str) -> str:
        return _ids_hash(
            tuple(
                sorted(
                    item.memory_id
                    for item in self._facts.values()
                    if item.owner_id == owner_id and item.active
                )
            )
        )
