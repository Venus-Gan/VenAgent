"""in-memory 模式的 owner、user 与 session adapter。"""

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
from .state import InMemoryPlatformState


class InMemoryOwnershipStore:
    def __init__(
        self,
        state: InMemoryPlatformState | None = None,
        *,
        account_available: bool = False,
        mode: str = "temporary",
    ) -> None:
        self.state = state or InMemoryPlatformState()
        self.account_available = account_available
        self.mode = mode

    def create_guest(
        self,
        *,
        actor_kind: ActorKind,
        refresh_hash: str,
        expires_at: datetime,
    ) -> tuple[OwnerRecord, SessionRecord]:
        owner = OwnerRecord(str(uuid4()), actor_kind, "active")
        session = SessionRecord(
            str(uuid4()), owner.owner_id, actor_kind, refresh_hash, expires_at
        )
        with self.state.lock:
            self.state.owners[owner.owner_id] = owner
            self.state.sessions[session.session_id] = session
        return owner, session

    def find_refresh(self, refresh_hash: str, now: datetime) -> RefreshLookup | None:
        with self.state.lock:
            for session in self.state.sessions.values():
                if session.refresh_hash == refresh_hash:
                    return RefreshLookup(session, False)
                if (
                    session.previous_refresh_hash == refresh_hash
                    and session.previous_valid_until is not None
                    and session.previous_valid_until > now
                ):
                    return RefreshLookup(session, True)
        return None

    def rotate_refresh(
        self,
        session_id: str,
        *,
        expected_hash: str,
        new_hash: str,
        previous_valid_until: datetime,
    ) -> SessionRecord:
        with self.state.lock:
            session = self.state.sessions.get(session_id)
            if session is None or session.refresh_hash != expected_hash:
                raise SessionInactive
            updated = replace(
                session,
                refresh_hash=new_hash,
                previous_refresh_hash=session.refresh_hash,
                previous_valid_until=previous_valid_until,
            )
            self.state.sessions[session_id] = updated
            return updated

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self.state.lock:
            return self.state.sessions.get(session_id)

    def get_owner(self, owner_id: str) -> OwnerRecord | None:
        with self.state.lock:
            return self.state.owners.get(owner_id)

    def revoke_session(self, session_id: str, now: datetime) -> None:
        with self.state.lock:
            session = self.state.sessions.get(session_id)
            if session is not None and session.revoked_at is None:
                self.state.sessions[session_id] = replace(session, revoked_at=now)

    def register_user(
        self,
        *,
        username_normalized: str,
        username_display: str,
        password_hash: str,
        refresh_hash: str,
        expires_at: datetime,
        revoke_session_id: str | None,
        revoke_at: datetime,
    ) -> tuple[UserRecord, SessionRecord]:
        with self.state.lock:
            if username_normalized in self.state.users_by_name:
                raise UsernameTaken
            owner = OwnerRecord(str(uuid4()), "user", "active")
            user = UserRecord(
                owner.owner_id,
                username_normalized,
                username_display,
                password_hash,
            )
            session = SessionRecord(
                str(uuid4()), owner.owner_id, "user", refresh_hash, expires_at
            )
            self.state.owners[owner.owner_id] = owner
            self.state.users[owner.owner_id] = user
            self.state.users_by_name[username_normalized] = owner.owner_id
            self.state.sessions[session.session_id] = session
            self._revoke_if_active(revoke_session_id, revoke_at)
            return user, session

    def find_user_by_name(self, username_normalized: str) -> UserRecord | None:
        with self.state.lock:
            owner_id = self.state.users_by_name.get(username_normalized)
            return None if owner_id is None else self.state.users.get(owner_id)

    def get_user(self, owner_id: str) -> UserRecord | None:
        with self.state.lock:
            return self.state.users.get(owner_id)

    def create_account_session(
        self,
        *,
        owner_id: str,
        refresh_hash: str,
        expires_at: datetime,
        revoke_session_id: str | None,
        revoke_at: datetime,
    ) -> SessionRecord:
        session = SessionRecord(
            str(uuid4()), owner_id, "user", refresh_hash, expires_at
        )
        with self.state.lock:
            owner = self.state.owners.get(owner_id)
            if owner is None or owner.lifecycle_state != "active":
                raise SessionInactive
            self.state.sessions[session.session_id] = session
            self._revoke_if_active(revoke_session_id, revoke_at)
        return session

    def change_password(
        self,
        *,
        owner_id: str,
        current_session_id: str,
        password_hash: str,
        refresh_hash: str,
        previous_valid_until: datetime,
        now: datetime,
    ) -> tuple[SessionRecord, tuple[str, ...]]:
        with self.state.lock:
            user = self.state.users[owner_id]
            self.state.users[owner_id] = replace(user, password_hash=password_hash)
            revoked: list[str] = []
            for session_id, session in tuple(self.state.sessions.items()):
                if session.owner_id != owner_id:
                    continue
                if session_id == current_session_id:
                    self.state.sessions[session_id] = replace(
                        session,
                        refresh_hash=refresh_hash,
                        previous_refresh_hash=session.refresh_hash,
                        previous_valid_until=previous_valid_until,
                    )
                elif session.revoked_at is None:
                    self.state.sessions[session_id] = replace(session, revoked_at=now)
                    revoked.append(session_id)
            return self.state.sessions[current_session_id], tuple(revoked)

    def mark_owner_deleting(self, owner_id: str, now: datetime) -> tuple[str, ...]:
        with self.state.lock:
            owner = self.state.owners.get(owner_id)
            if owner is None:
                return ()
            self.state.owners[owner_id] = replace(
                owner,
                lifecycle_state="deleting",
                authorization_epoch=owner.authorization_epoch + 1,
            )
            sessions: list[str] = []
            for session_id, session in tuple(self.state.sessions.items()):
                if session.owner_id == owner_id:
                    sessions.append(session_id)
                    self.state.sessions[session_id] = replace(session, revoked_at=now)
            return tuple(sessions)

    def deleting_owner_ids(self) -> tuple[str, ...]:
        with self.state.lock:
            return tuple(
                owner_id
                for owner_id, owner in self.state.owners.items()
                if owner.lifecycle_state == "deleting"
            )

    def delete_owner(self, owner_id: str) -> None:
        with self.state.lock:
            user = self.state.users.pop(owner_id, None)
            if user is not None:
                self.state.users_by_name.pop(user.username_normalized, None)
            for session_id, session in tuple(self.state.sessions.items()):
                if session.owner_id == owner_id:
                    self.state.sessions.pop(session_id, None)
            self.state.owners.pop(owner_id, None)

    def delete_orphan_guests(self, now: datetime) -> int:
        with self.state.lock:
            referenced = {item.owner_id for item in self.state.conversations.values()}
            candidates = [
                owner_id
                for owner_id, owner in self.state.owners.items()
                if owner.kind != "user"
                and owner_id not in referenced
                and not any(
                    session.owner_id == owner_id
                    and session.revoked_at is None
                    and session.expires_at > now
                    for session in self.state.sessions.values()
                )
            ]
            for owner_id in candidates:
                for session_id, session in tuple(self.state.sessions.items()):
                    if session.owner_id == owner_id:
                        self.state.sessions.pop(session_id, None)
                self.state.owners.pop(owner_id, None)
                self.state.guest_creates.pop(owner_id, None)
            return len(candidates)

    def _revoke_if_active(self, session_id: str | None, now: datetime) -> None:
        if session_id is None:
            return
        previous = self.state.sessions.get(session_id)
        if previous is not None and previous.revoked_at is None:
            self.state.sessions[session_id] = replace(previous, revoked_at=now)
