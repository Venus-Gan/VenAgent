"""Memory 操作级授权值对象与授权校验用例。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ..ownership.models import Actor, ExecutionAuthorization
from ..ownership.ports import OwnershipStore
from .capabilities import MemoryCapabilityRegistry
from .errors import MemoryDisabled, MemoryUnauthorized, MemoryUnsupported
from .ports import MemoryAuthorizationStore

MemoryAction = Literal["read", "write", "manage", "delete"]
MemorySourceKind = Literal["run", "command"]
MEMORY_SCOPE = "owner:memory"
READ_ACTIONS = {"memory.read", "memory.manage"}
WRITE_ACTIONS = {"memory.write", "memory.manage"}


@dataclass(frozen=True)
class MemoryAuthorization:
    owner_id: str
    tenant_id: str
    allowed_data_scopes: tuple[str, ...]
    allowed_action_classes: tuple[str, ...]
    authorization_epoch: int
    source_kind: MemorySourceKind
    action: MemoryAction
    session_id: str | None = None
    run_id: str | None = None
    conversation_id: str | None = None


@dataclass(frozen=True)
class MemoryRequestSnapshot:
    owner_id: str
    tenant_id: str
    authorization_epoch: int
    enabled: bool
    deletion_generation: int
    captured_at: datetime
    capability_states: tuple[tuple[str, str], ...] = ()
    authority_revision: int = 0


class MemoryAuthorizer:
    def __init__(
        self,
        store: MemoryAuthorizationStore,
        ownership: OwnershipStore,
        local_disabled: set[str],
        now: Callable[[], datetime],
        capabilities: MemoryCapabilityRegistry | None = None,
    ) -> None:
        self._store = store
        self._ownership = ownership
        self._local_disabled = local_disabled
        self._now = now
        self._capabilities = capabilities

    def command_authorization(
        self, actor: Actor, *, action: str = "manage"
    ) -> MemoryAuthorization:
        session = self._ownership.get_session(actor.session_id)
        owner = self._ownership.get_owner(actor.owner_id)
        if (
            session is None
            or session.owner_id != actor.owner_id
            or session.revoked_at is not None
            or session.expires_at <= self._now()
            or owner is None
            or owner.lifecycle_state != "active"
        ):
            raise MemoryUnauthorized
        return MemoryAuthorization(
            owner_id=actor.owner_id,
            tenant_id="default",
            allowed_data_scopes=(MEMORY_SCOPE,),
            allowed_action_classes=("memory.read", "memory.write", "memory.manage"),
            authorization_epoch=owner.authorization_epoch,
            source_kind="command",
            action=action,  # type: ignore[arg-type]
            session_id=actor.session_id,
        )

    def run_authorization(
        self, authorization: ExecutionAuthorization, *, action: str
    ) -> MemoryAuthorization:
        return MemoryAuthorization(
            owner_id=authorization.owner_id,
            tenant_id=authorization.tenant_id,
            allowed_data_scopes=authorization.allowed_data_scopes,
            allowed_action_classes=authorization.allowed_action_classes,
            authorization_epoch=authorization.authorization_epoch,
            source_kind="run",
            action=action,  # type: ignore[arg-type]
            run_id=authorization.run_id,
            conversation_id=authorization.conversation_id,
        )

    def capture_snapshot(
        self, auth: MemoryAuthorization, *, allow_disabled: bool = False
    ) -> MemoryRequestSnapshot:
        self.authorize(auth, write=auth.action == "write", allow_disabled=True)
        settings = self._store.settings(auth.owner_id)
        enabled = (
            settings.enabled
            and not settings.purge_pending
            and auth.owner_id not in self._local_disabled
        )
        if not enabled and not allow_disabled:
            raise MemoryDisabled
        return MemoryRequestSnapshot(
            auth.owner_id,
            auth.tenant_id,
            auth.authorization_epoch,
            enabled,
            settings.deletion_generation,
            self._now(),
            tuple(
                (item.component, item.state)
                for item in (
                    self._capabilities.snapshot() if self._capabilities else ()
                )
            ),
            self._store.authority_revision(auth.owner_id, auth.tenant_id),
        )

    def authorize(
        self, auth: MemoryAuthorization, *, write: bool, allow_disabled: bool = False
    ) -> None:
        owner = self._ownership.get_owner(auth.owner_id)
        if (
            owner is None
            or owner.lifecycle_state != "active"
            or owner.authorization_epoch != auth.authorization_epoch
            or MEMORY_SCOPE not in auth.allowed_data_scopes
        ):
            raise MemoryUnauthorized
        actions = set(auth.allowed_action_classes)
        required = WRITE_ACTIONS if write else READ_ACTIONS
        operation_matches = auth.action in (
            {"write", "manage"} if write else {"read", "write", "manage", "delete"}
        )
        if not operation_matches or not actions.intersection(required):
            raise MemoryUnauthorized
        if write and owner.kind != "user":
            raise MemoryUnsupported
        if write and (
            not self._store.durable
            or auth.owner_id in self._local_disabled
            or not self._store.enabled(auth.owner_id)
        ):
            raise MemoryDisabled if self._store.durable else MemoryUnsupported
        if not allow_disabled and (
            auth.owner_id in self._local_disabled
            or not self._store.enabled(auth.owner_id)
        ):
            raise MemoryDisabled

    @staticmethod
    def validate_snapshot(
        auth: MemoryAuthorization, snapshot: MemoryRequestSnapshot
    ) -> None:
        if (
            snapshot.owner_id != auth.owner_id
            or snapshot.tenant_id != auth.tenant_id
            or snapshot.authorization_epoch != auth.authorization_epoch
        ):
            raise MemoryUnauthorized
