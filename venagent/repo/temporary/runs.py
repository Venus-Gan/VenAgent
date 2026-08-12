"""Temporary run 创建、claim、fencing 与终态提交行为。"""

from __future__ import annotations

# ruff: noqa: F401
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from threading import RLock
from uuid import uuid4

from ...agent.graph import RUNTIME_CONTRACT_VERSION
from ...agent.runs import (
    ACTIVE_RUN_STATUSES,
    AgentRun,
    InvalidRunTransition,
    RunAuthorizationInvalid,
    RunNotFound,
)
from ...conversation.errors import (
    AnonymousLimitExceeded,
    ConversationBusy,
    ConversationDeleting,
    ConversationNotFound,
    IdempotencyConflict,
    RetryNotAllowed,
)
from ...conversation.models import Conversation, ConversationMessage, RunCreation
from ...conversation.rules import automatic_title
from ...ownership.errors import SessionInactive, UsernameTaken
from ...ownership.models import (
    Actor,
    ActorKind,
    ExecutionAuthorization,
    OwnerRecord,
    RefreshLookup,
    RunGrant,
    SessionRecord,
    UserRecord,
)
from .state import TemporaryPlatformState, _RequestRecord


class _TemporaryRunMixin:
    state: TemporaryPlatformState

    def create_run(
        self,
        actor: Actor,
        conversation_id: str,
        message: str,
        client_request_id: str,
        now: datetime,
    ) -> RunCreation:
        with self.state.lock:
            conversation = self._require_conversation(actor.owner_id, conversation_id)
            self._require_active_owner_if_known(actor.owner_id)
            key = (conversation_id, client_request_id)
            replay = self.state.requests.get(key)
            if replay is not None:
                if replay.operation != "create" or replay.payload != message:
                    raise IdempotencyConflict
                return self._creation(replay.run_id, replay.input_message_id)
            if conversation.lifecycle_state != "active":
                raise ConversationDeleting
            self._require_no_active_run(conversation_id)
            message_record = ConversationMessage(
                str(uuid4()),
                conversation_id,
                actor.owner_id,
                "user",
                message,
                self._next_sequence(conversation_id),
                now,
                client_request_id=client_request_id,
            )
            run = self._new_run(actor, conversation_id, message_record.message_id, now)
            self.state.messages[conversation_id].append(message_record)
            self.state.runs[run.run_id] = run
            self.state.requests[key] = _RequestRecord(
                "create", message, run.run_id, message_record.message_id
            )
            self.state.conversations[conversation_id] = replace(
                conversation, updated_at=now
            )
            return RunCreation(run, message_record)

    def retry_run(
        self,
        actor: Actor,
        source_run_id: str,
        client_request_id: str,
        now: datetime,
    ) -> RunCreation:
        with self.state.lock:
            source = self.state.runs.get(source_run_id)
            if source is None or source.owner_id != actor.owner_id:
                raise RunNotFound
            key = (source.conversation_id, client_request_id)
            operation = f"retry:{source_run_id}"
            replay = self.state.requests.get(key)
            if replay is not None:
                if replay.operation != operation:
                    raise IdempotencyConflict
                return self._creation(replay.run_id, replay.input_message_id)
            if source.status not in {"failed", "cancelled", "incompatible"}:
                raise RetryNotAllowed
            self._require_conversation(actor.owner_id, source.conversation_id)
            self._require_active_owner_if_known(actor.owner_id)
            user_messages = [
                item
                for item in self.state.messages[source.conversation_id]
                if item.role == "user"
            ]
            if (
                not user_messages
                or user_messages[-1].message_id != source.input_message_id
            ):
                raise RetryNotAllowed
            self._require_no_active_run(source.conversation_id)
            input_message = next(
                item
                for item in self.state.messages[source.conversation_id]
                if item.message_id == source.input_message_id
            )
            run = self._new_run(
                actor,
                source.conversation_id,
                source.input_message_id,
                now,
                retry_of_run_id=source_run_id,
            )
            self.state.runs[run.run_id] = run
            self.state.requests[key] = _RequestRecord(
                operation, "", run.run_id, source.input_message_id
            )
            return RunCreation(run, input_message)

    def get_run(self, owner_id: str, run_id: str) -> AgentRun | None:
        with self.state.lock:
            run = self.state.runs.get(run_id)
            return run if run is not None and run.owner_id == owner_id else None

    def get_run_internal(self, run_id: str) -> AgentRun | None:
        with self.state.lock:
            return self.state.runs.get(run_id)

    def authorize_run(self, run_id: str, now: datetime) -> ExecutionAuthorization:
        with self.state.lock:
            run = self.state.runs.get(run_id)
            if run is None:
                raise RunNotFound
            grant = self.state.grants.get(run.grant_id)
            owner = self.state.owners.get(run.owner_id)
            if (
                grant is None
                or grant.run_id != run.run_id
                or grant.owner_id != run.owner_id
                or grant.conversation_id != run.conversation_id
                or grant.revoked_at is not None
                or grant.expires_at <= now
                or (owner is not None and owner.lifecycle_state != "active")
                or (
                    owner is not None
                    and grant.authorization_epoch != owner.authorization_epoch
                )
            ):
                raise RunAuthorizationInvalid
            return ExecutionAuthorization(
                run.run_id,
                grant.owner_id,
                grant.tenant_id,
                grant.conversation_id,
                grant.allowed_data_scopes,
                grant.allowed_action_classes,
                grant.authorization_epoch,
            )

    def claim_next(
        self, worker_id: str, now: datetime, lease_duration: timedelta
    ) -> AgentRun | None:
        with self.state.lock:
            owner_running: dict[str, int] = defaultdict(int)
            for item in self.state.runs.values():
                if item.status == "running" and (
                    item.lease_expires_at is None or item.lease_expires_at > now
                ):
                    owner_running[item.owner_id] += 1
            candidates = sorted(
                (
                    item
                    for item in self.state.runs.values()
                    if item.status == "queued"
                    or (
                        item.status == "running"
                        and item.lease_expires_at is not None
                        and item.lease_expires_at <= now
                    )
                ),
                key=lambda item: (item.created_at, item.run_id),
            )
            for run in candidates:
                if owner_running[run.owner_id] >= 2:
                    continue
                claimed = replace(
                    run,
                    status="running",
                    started_at=run.started_at or now,
                    updated_at=now,
                    claimed_by=worker_id,
                    claim_token=str(uuid4()),
                    lease_expires_at=now + lease_duration,
                    execution_attempt=run.execution_attempt + 1,
                    phase=run.phase or "synthesizing",
                )
                self.state.runs[run.run_id] = claimed
                return claimed
            return None

    def heartbeat(
        self,
        run_id: str,
        worker_id: str,
        claim_token: str,
        execution_attempt: int,
        now: datetime,
        lease_duration: timedelta,
    ) -> AgentRun:
        with self.state.lock:
            run = self._require_current_claim(
                run_id, claim_token, execution_attempt, worker_id
            )
            updated = replace(
                run, updated_at=now, lease_expires_at=now + lease_duration
            )
            self.state.runs[run_id] = updated
            return updated

    def request_cancel(self, owner_id: str, run_id: str, now: datetime) -> AgentRun:
        with self.state.lock:
            run = self.state.runs.get(run_id)
            if run is None or run.owner_id != owner_id:
                raise RunNotFound
            if run.terminal or run.cancel_requested_at is not None:
                return run
            updated = replace(run, cancel_requested_at=now, updated_at=now)
            self.state.runs[run_id] = updated
            return updated

    def succeed_run(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        answer: str,
        now: datetime,
    ) -> AgentRun:
        with self.state.lock:
            existing = self.state.runs.get(run_id)
            if existing is None:
                raise RunNotFound
            if existing.status == "succeeded":
                return existing
            run = self._require_current_claim(run_id, claim_token, execution_attempt)
            if run.cancel_requested_at is not None:
                raise InvalidRunTransition("cancel was requested before finalization")
            conversation = self.state.conversations.get(run.conversation_id)
            if conversation is None or conversation.lifecycle_state != "active":
                raise InvalidRunTransition("conversation is unavailable")
            prior = next(
                (
                    item
                    for item in self.state.messages[run.conversation_id]
                    if item.source_run_id == run_id
                    or item.reply_to_message_id == run.input_message_id
                ),
                None,
            )
            if prior is None:
                output = ConversationMessage(
                    str(uuid4()),
                    run.conversation_id,
                    run.owner_id,
                    "assistant",
                    answer,
                    self._next_sequence(run.conversation_id),
                    now,
                    source_run_id=run_id,
                    reply_to_message_id=run.input_message_id,
                )
                self.state.messages[run.conversation_id].append(output)
            else:
                output = prior
            title = conversation.title
            if conversation.title_source == "auto" and not any(
                item.role == "assistant" and item.message_id != output.message_id
                for item in self.state.messages[run.conversation_id]
            ):
                source = next(
                    item
                    for item in self.state.messages[run.conversation_id]
                    if item.message_id == run.input_message_id
                )
                title = automatic_title(source.content)
            finished = replace(
                run,
                status="succeeded",
                output_message_id=output.message_id,
                completed_at=now,
                updated_at=now,
                terminal_reason_code=None,
                terminal_message=None,
                completed_nodes=run.total_nodes,
                claimed_by=None,
                claim_token=None,
                lease_expires_at=None,
            )
            self.state.runs[run_id] = finished
            self.state.conversations[run.conversation_id] = replace(
                conversation,
                title=title,
                updated_at=now,
                last_successful_at=now,
            )
            return finished

    def fail_run(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        reason_code: str,
        message: str,
        now: datetime,
    ) -> AgentRun:
        with self.state.lock:
            existing = self.state.runs.get(run_id)
            if existing is None:
                raise RunNotFound
            if existing.status == "failed":
                return existing
            run = self._require_current_claim(run_id, claim_token, execution_attempt)
            failed = replace(
                run,
                status="failed",
                completed_at=now,
                updated_at=now,
                terminal_reason_code=reason_code,
                terminal_message=message,
                claimed_by=None,
                claim_token=None,
                lease_expires_at=None,
            )
            self.state.runs[run_id] = failed
            return failed

    def cancel_run(
        self,
        run_id: str,
        worker_id: str,
        claim_token: str,
        execution_attempt: int,
        reason_code: str,
        now: datetime,
    ) -> AgentRun:
        with self.state.lock:
            run = self.state.runs.get(run_id)
            if run is None:
                raise RunNotFound
            if run.status == "cancelled":
                return run
            run = self._require_current_claim(
                run_id, claim_token, execution_attempt, worker_id
            )
            cancelled = replace(
                run,
                status="cancelled",
                completed_at=now,
                updated_at=now,
                terminal_reason_code=reason_code,
                terminal_message="运行已取消",
                claimed_by=None,
                claim_token=None,
                lease_expires_at=None,
            )
            self.state.runs[run_id] = cancelled
            return cancelled

    def incompatible_run(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        message: str,
        now: datetime,
    ) -> AgentRun:
        with self.state.lock:
            run = self._require_current_claim(run_id, claim_token, execution_attempt)
            incompatible = replace(
                run,
                status="incompatible",
                completed_at=now,
                updated_at=now,
                terminal_reason_code="runtime_contract_mismatch",
                terminal_message=message,
                claimed_by=None,
                claim_token=None,
                lease_expires_at=None,
            )
            self.state.runs[run_id] = incompatible
            return incompatible

    def _new_run(
        self,
        actor: Actor,
        conversation_id: str,
        input_message_id: str,
        now: datetime,
        *,
        retry_of_run_id: str | None = None,
    ) -> AgentRun:
        run_id = str(uuid4())
        owner = self.state.owners.get(actor.owner_id)
        grant = RunGrant(
            str(uuid4()),
            run_id,
            actor.owner_id,
            "default",
            conversation_id,
            (f"conversation:{conversation_id}", "owner:memory"),
            ("model.invoke", "memory.read", "memory.write"),
            owner.authorization_epoch if owner is not None else 1,
            actor.session_id,
            now + timedelta(days=7),
        )
        run = AgentRun(
            run_id,
            conversation_id,
            actor.owner_id,
            input_message_id,
            grant.grant_id,
            "queued",
            RUNTIME_CONTRACT_VERSION,
            now,
            now,
            retry_of_run_id=retry_of_run_id,
        )
        self.state.grants[grant.grant_id] = grant
        return run

    def _creation(self, run_id: str, input_message_id: str) -> RunCreation:
        run = self.state.runs[run_id]
        message = next(
            item
            for item in self.state.messages[run.conversation_id]
            if item.message_id == input_message_id
        )
        return RunCreation(run, message)

    def _require_no_active_run(self, conversation_id: str) -> None:
        if any(
            run.conversation_id == conversation_id and run.status in ACTIVE_RUN_STATUSES
            for run in self.state.runs.values()
        ):
            raise ConversationBusy

    def _require_current_claim(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        worker_id: str | None = None,
    ) -> AgentRun:
        run = self.state.runs.get(run_id)
        if run is None:
            raise RunNotFound
        if (
            run.status != "running"
            or run.claim_token != claim_token
            or run.execution_attempt != execution_attempt
            or (worker_id is not None and run.claimed_by != worker_id)
        ):
            raise InvalidRunTransition("stale or invalid run claim")
        return run
