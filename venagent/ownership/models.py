"""所有权用例使用的不可变值对象。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ActorKind = Literal["guest", "user", "temporary_guest"]
RuntimeMode = Literal["durable", "temporary"]


@dataclass(frozen=True)
class Actor:
    owner_id: str
    kind: ActorKind
    session_id: str
    username: str | None = None
    mode: RuntimeMode = "temporary"

    @property
    def is_user(self) -> bool:
        return self.kind == "user"


@dataclass(frozen=True)
class OwnerRecord:
    owner_id: str
    kind: ActorKind
    lifecycle_state: str
    authorization_epoch: int = 1


@dataclass(frozen=True)
class UserRecord:
    owner_id: str
    username_normalized: str
    username_display: str
    password_hash: str


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    owner_id: str
    actor_kind: ActorKind
    refresh_hash: str
    expires_at: datetime
    revoked_at: datetime | None = None
    previous_refresh_hash: str | None = None
    previous_valid_until: datetime | None = None


@dataclass(frozen=True)
class RefreshLookup:
    session: SessionRecord
    matched_previous: bool


@dataclass(frozen=True)
class AccessClaims:
    owner_id: str
    actor_kind: ActorKind
    session_id: str
    token_id: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class IdentityResult:
    actor: Actor
    access_token: str
    access_expires_at: datetime
    refresh_token: str | None
    refresh_expires_at: datetime


@dataclass(frozen=True)
class DeletionRequest:
    owner_id: str
    session_ids: tuple[str, ...]


@dataclass(frozen=True)
class RunGrant:
    grant_id: str
    run_id: str
    owner_id: str
    tenant_id: str
    conversation_id: str
    allowed_data_scopes: tuple[str, ...]
    allowed_action_classes: tuple[str, ...]
    authorization_epoch: int
    requested_by_session_id: str
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class ExecutionAuthorization:
    run_id: str
    owner_id: str
    tenant_id: str
    conversation_id: str
    allowed_data_scopes: tuple[str, ...]
    allowed_action_classes: tuple[str, ...]
    authorization_epoch: int
