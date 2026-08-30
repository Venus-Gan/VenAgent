"""Ownership 消费方定义的安全与持久化端口。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import (
    AccessClaims,
    ActorKind,
    OwnerRecord,
    RefreshLookup,
    SessionRecord,
    UserRecord,
)


class OwnershipStoreError(RuntimeError):
    """ownership adapter 的安全失败，不包含凭据或数据库细节。"""


class PasswordPort(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...

    def verify_dummy(self, password: str) -> None: ...


class AccessTokenPort(Protocol):
    def issue(
        self,
        owner_id: str,
        actor_kind: ActorKind,
        session_id: str,
        now: datetime,
    ) -> tuple[str, datetime]: ...

    def decode(self, token: str, now: datetime) -> AccessClaims: ...


class OwnershipStore(Protocol):
    account_available: bool
    mode: str

    def create_guest(
        self,
        *,
        actor_kind: ActorKind,
        refresh_hash: str,
        expires_at: datetime,
    ) -> tuple[OwnerRecord, SessionRecord]: ...

    def find_refresh(
        self, refresh_hash: str, now: datetime
    ) -> RefreshLookup | None: ...

    def rotate_refresh(
        self,
        session_id: str,
        *,
        expected_hash: str,
        new_hash: str,
        previous_valid_until: datetime,
    ) -> SessionRecord: ...

    def get_session(self, session_id: str) -> SessionRecord | None: ...

    def get_owner(self, owner_id: str) -> OwnerRecord | None: ...

    def revoke_session(self, session_id: str, now: datetime) -> None: ...

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
    ) -> tuple[UserRecord, SessionRecord]: ...

    def find_user_by_name(self, username_normalized: str) -> UserRecord | None: ...

    def get_user(self, owner_id: str) -> UserRecord | None: ...

    def create_account_session(
        self,
        *,
        owner_id: str,
        refresh_hash: str,
        expires_at: datetime,
        revoke_session_id: str | None,
        revoke_at: datetime,
    ) -> SessionRecord: ...

    def change_password(
        self,
        *,
        owner_id: str,
        current_session_id: str,
        password_hash: str,
        refresh_hash: str,
        previous_valid_until: datetime,
        now: datetime,
    ) -> tuple[SessionRecord, tuple[str, ...]]: ...

    def mark_owner_deleting(self, owner_id: str, now: datetime) -> tuple[str, ...]: ...

    def deleting_owner_ids(self) -> tuple[str, ...]: ...

    def delete_owner(self, owner_id: str) -> None: ...

    def delete_orphan_guests(self, now: datetime) -> int: ...
