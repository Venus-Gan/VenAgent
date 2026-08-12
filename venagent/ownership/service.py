"""匿名、账号与可撤销 session 的业务编排。"""

from __future__ import annotations

import hashlib
import secrets
import unicodedata
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from threading import RLock

from .errors import (
    AccessTokenInvalid,
    AccountRequired,
    AccountServiceUnavailable,
    AuthRateLimited,
    IdentityConflict,
    InvalidCredentials,
    InvalidPassword,
    InvalidUsername,
    RefreshRequired,
    SessionInactive,
    UsernameTaken,
)
from .models import Actor, ActorKind, DeletionRequest, IdentityResult, SessionRecord
from .ports import AccessTokenPort, OwnershipStore, PasswordPort

GUEST_TTL = timedelta(days=7)
ACCOUNT_SESSION_TTL = timedelta(days=30)
REFRESH_GRACE = timedelta(seconds=30)
_ALLOWED_USERNAME_EXTRA = frozenset({"_", "-"})


class OwnershipService:
    def __init__(
        self,
        store: OwnershipStore,
        passwords: PasswordPort,
        tokens: AccessTokenPort,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._passwords = passwords
        self._tokens = tokens
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._attempts = _AttemptLimiter(self._clock)

    @property
    def mode(self) -> str:
        return self._store.mode

    @property
    def account_available(self) -> bool:
        return self._store.account_available

    def bootstrap_guest(self, refresh_token: str | None = None) -> IdentityResult:
        expected: ActorKind = (
            "guest" if self._store.mode == "durable" else "temporary_guest"
        )
        if refresh_token:
            try:
                return self.refresh(refresh_token, allowed_kinds={expected})
            except (RefreshRequired, SessionInactive):
                pass
        raw_refresh = new_refresh_token()
        now = self._now()
        owner, session = self._store.create_guest(
            actor_kind=expected,
            refresh_hash=refresh_hash(raw_refresh),
            expires_at=now + GUEST_TTL,
        )
        return self._identity(owner.owner_id, expected, session, raw_refresh)

    def refresh(
        self,
        raw_refresh: str | None,
        *,
        allowed_kinds: set[ActorKind] | None = None,
    ) -> IdentityResult:
        if not raw_refresh:
            raise RefreshRequired
        now = self._now()
        lookup = self._store.find_refresh(refresh_hash(raw_refresh), now)
        if lookup is None:
            raise RefreshRequired
        session = lookup.session
        if allowed_kinds is not None and session.actor_kind not in allowed_kinds:
            raise RefreshRequired
        self._assert_session_active(session, now)
        owner = self._store.get_owner(session.owner_id)
        if owner is None or owner.lifecycle_state != "active":
            raise SessionInactive

        next_refresh: str | None = None
        if not lookup.matched_previous:
            next_refresh = new_refresh_token()
            session = self._store.rotate_refresh(
                session.session_id,
                expected_hash=refresh_hash(raw_refresh),
                new_hash=refresh_hash(next_refresh),
                previous_valid_until=now + REFRESH_GRACE,
            )
        return self._identity(
            session.owner_id,
            session.actor_kind,
            session,
            next_refresh,
        )

    def assert_refresh_active(
        self,
        raw_refresh: str | None,
        *,
        allowed_kinds: set[ActorKind] | None = None,
    ) -> None:
        """只读确认 refresh session 有效，不轮换凭据。"""
        if not raw_refresh:
            raise RefreshRequired
        now = self._now()
        lookup = self._store.find_refresh(refresh_hash(raw_refresh), now)
        if lookup is None:
            raise RefreshRequired
        session = lookup.session
        if allowed_kinds is not None and session.actor_kind not in allowed_kinds:
            raise RefreshRequired
        self._assert_session_active(session, now)
        owner = self._store.get_owner(session.owner_id)
        if owner is None or owner.lifecycle_state != "active":
            raise SessionInactive

    def resolve_access(self, access_token: str | None) -> Actor:
        if not access_token:
            from .errors import AccessTokenMissing

            raise AccessTokenMissing
        now = self._now()
        claims = self._tokens.decode(access_token, now)
        session = self._store.get_session(claims.session_id)
        if session is None:
            raise SessionInactive
        self._assert_session_active(session, now)
        if (
            session.owner_id != claims.owner_id
            or session.actor_kind != claims.actor_kind
        ):
            raise AccessTokenInvalid
        owner = self._store.get_owner(claims.owner_id)
        if owner is None or owner.lifecycle_state != "active":
            raise SessionInactive
        return self._actor(session.owner_id, session.actor_kind, session.session_id)

    def renew_access(self, actor: Actor) -> IdentityResult:
        session = self._store.get_session(actor.session_id)
        if session is None:
            raise SessionInactive
        self._assert_session_active(session, self._now())
        return self._identity(
            actor.owner_id,
            actor.kind,
            session,
            None,
        )

    def register(
        self,
        username: str,
        password: str,
        *,
        current_actor: Actor | None = None,
        rate_key: str = "local",
    ) -> IdentityResult:
        self._require_accounts()
        if current_actor is not None and current_actor.kind == "user":
            raise IdentityConflict
        self._attempts.require(
            f"register:{rate_key}", limit=5, window=timedelta(minutes=10)
        )
        normalized, display = normalize_username(username)
        validate_password(password)
        raw_refresh = new_refresh_token()
        now = self._now()
        try:
            user, session = self._store.register_user(
                username_normalized=normalized,
                username_display=display,
                password_hash=self._passwords.hash(password),
                refresh_hash=refresh_hash(raw_refresh),
                expires_at=now + ACCOUNT_SESSION_TTL,
                revoke_session_id=(
                    current_actor.session_id if current_actor is not None else None
                ),
                revoke_at=now,
            )
        except UsernameTaken:
            raise
        return self._identity(user.owner_id, "user", session, raw_refresh)

    def login(
        self,
        username: str,
        password: str,
        *,
        current_actor: Actor | None = None,
        rate_key: str = "local",
    ) -> IdentityResult:
        self._require_accounts()
        if current_actor is not None and current_actor.kind == "user":
            raise IdentityConflict
        try:
            normalized, _display = normalize_username(username)
        except InvalidUsername:
            self._passwords.verify_dummy(password)
            raise InvalidCredentials from None
        self._attempts.require(
            f"login:{rate_key}:{normalized}",
            limit=10,
            window=timedelta(minutes=10),
        )
        user = self._store.find_user_by_name(normalized)
        if user is None:
            self._passwords.verify_dummy(password)
            raise InvalidCredentials
        if not self._passwords.verify(user.password_hash, password):
            raise InvalidCredentials
        raw_refresh = new_refresh_token()
        now = self._now()
        session = self._store.create_account_session(
            owner_id=user.owner_id,
            refresh_hash=refresh_hash(raw_refresh),
            expires_at=now + ACCOUNT_SESSION_TTL,
            revoke_session_id=(
                current_actor.session_id if current_actor is not None else None
            ),
            revoke_at=now,
        )
        return self._identity(user.owner_id, "user", session, raw_refresh)

    def logout(self, actor: Actor) -> tuple[IdentityResult, tuple[str, ...]]:
        self._require_user(actor)
        self._store.revoke_session(actor.session_id, self._now())
        return self.bootstrap_guest(), (actor.session_id,)

    def change_password(
        self,
        actor: Actor,
        current_password: str,
        new_password: str,
    ) -> tuple[IdentityResult, tuple[str, ...]]:
        self._require_accounts()
        self._require_user(actor)
        user = self._store.get_user(actor.owner_id)
        if user is None or not self._passwords.verify(
            user.password_hash, current_password
        ):
            raise InvalidCredentials
        validate_password(new_password)
        now = self._now()
        raw_refresh = new_refresh_token()
        session, revoked_sessions = self._store.change_password(
            owner_id=actor.owner_id,
            current_session_id=actor.session_id,
            password_hash=self._passwords.hash(new_password),
            refresh_hash=refresh_hash(raw_refresh),
            previous_valid_until=now + REFRESH_GRACE,
            now=now,
        )
        return (
            self._identity(actor.owner_id, "user", session, raw_refresh),
            revoked_sessions,
        )

    def request_deletion(
        self,
        actor: Actor,
        current_password: str,
        confirmed: bool,
    ) -> DeletionRequest:
        self._require_accounts()
        self._require_user(actor)
        if not confirmed:
            raise InvalidCredentials
        user = self._store.get_user(actor.owner_id)
        if user is None or not self._passwords.verify(
            user.password_hash, current_password
        ):
            raise InvalidCredentials
        sessions = self._store.mark_owner_deleting(actor.owner_id, self._now())
        return DeletionRequest(actor.owner_id, sessions)

    def deleting_owner_ids(self) -> tuple[str, ...]:
        return self._store.deleting_owner_ids()

    def finish_deletion(self, owner_id: str) -> None:
        self._store.delete_owner(owner_id)

    def cleanup_orphan_guests(self) -> int:
        """回收已无 thread 且没有有效 session 的匿名 owner。"""
        return self._store.delete_orphan_guests(self._now())

    def _identity(
        self,
        owner_id: str,
        actor_kind: ActorKind,
        session: SessionRecord,
        refresh_token: str | None,
    ) -> IdentityResult:
        actor = self._actor(owner_id, actor_kind, session.session_id)
        token, expires_at = self._tokens.issue(
            owner_id,
            actor_kind,
            session.session_id,
            self._now(),
        )
        return IdentityResult(
            actor,
            token,
            expires_at,
            refresh_token,
            session.expires_at,
        )

    def _actor(self, owner_id: str, kind: ActorKind, session_id: str) -> Actor:
        username = None
        if kind == "user":
            user = self._store.get_user(owner_id)
            if user is None:
                raise SessionInactive
            username = user.username_display
        return Actor(
            owner_id=owner_id,
            kind=kind,
            session_id=session_id,
            username=username,
            mode="durable" if self._store.mode == "durable" else "temporary",
        )

    def _assert_session_active(self, session: SessionRecord, now: datetime) -> None:
        if session.revoked_at is not None or session.expires_at <= now:
            raise SessionInactive

    def _require_accounts(self) -> None:
        if not self._store.account_available:
            raise AccountServiceUnavailable

    @staticmethod
    def _require_user(actor: Actor) -> None:
        if actor.kind != "user":
            raise AccountRequired

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def normalize_username(username: str) -> tuple[str, str]:
    if not isinstance(username, str):
        raise InvalidUsername
    display = username.strip()
    normalized_display = unicodedata.normalize("NFKC", display)
    normalized = normalized_display.casefold()
    if not 3 <= len(normalized) <= 32:
        raise InvalidUsername
    if not all(
        character in _ALLOWED_USERNAME_EXTRA
        or unicodedata.category(character)[0] in {"L", "N"}
        for character in normalized
    ):
        raise InvalidUsername
    return normalized, display


def validate_password(password: str) -> None:
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise InvalidPassword


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def refresh_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class _AttemptLimiter:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._entries: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = RLock()

    def require(self, key: str, *, limit: int, window: timedelta) -> None:
        now = self._clock()
        cutoff = now - window
        with self._lock:
            attempts = self._entries[key]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= limit:
                raise AuthRateLimited
            attempts.append(now)
