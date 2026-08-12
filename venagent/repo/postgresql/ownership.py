"""PostgreSQL owner、user 与 session adapter。"""

from __future__ import annotations

# ruff: noqa: F401
from datetime import datetime
from typing import Any
from uuid import uuid4

from psycopg import errors
from psycopg_pool import ConnectionPool

from ...ownership.errors import SessionInactive, UsernameTaken
from ...ownership.models import (
    Actor,
    ActorKind,
    ExecutionAuthorization,
    OwnerRecord,
    RefreshLookup,
    SessionRecord,
    UserRecord,
)
from ...ownership.ports import OwnershipStoreError as StoreError


def owner_from_row(row: Any) -> OwnerRecord:
    return OwnerRecord(
        str(row["owner_id"]),
        str(row["kind"]),
        str(row["lifecycle_state"]),
        int(row["authorization_epoch"]),
    )


def user_from_row(row: Any) -> UserRecord:
    return UserRecord(
        str(row["owner_id"]),
        str(row["username_normalized"]),
        str(row["username_display"]),
        str(row["password_hash"]),
    )


def session_from_row(row: Any, kind: ActorKind) -> SessionRecord:
    return SessionRecord(
        session_id=str(row["session_id"]),
        owner_id=str(row["owner_id"]),
        actor_kind=kind,
        refresh_hash=str(row["refresh_hash"]),
        expires_at=row["expires_at"],
        revoked_at=row.get("revoked_at"),
        previous_refresh_hash=row.get("previous_refresh_hash"),
        previous_valid_until=row.get("previous_valid_until"),
    )


def guest_session_from_row(row: Any) -> SessionRecord:
    mapped = dict(row)
    mapped["owner_id"] = mapped["guest_owner_id"]
    return session_from_row(mapped, "guest")


class PostgresOwnershipStore:
    account_available = True
    mode = "durable"

    def __init__(self, pool: ConnectionPool[Any]) -> None:
        self._pool = pool

    def create_guest(
        self,
        *,
        actor_kind: ActorKind,
        refresh_hash: str,
        expires_at: datetime,
    ) -> tuple[OwnerRecord, SessionRecord]:
        if actor_kind != "guest":
            raise StoreError("durable store only creates guest owners")
        owner_id, session_id = str(uuid4()), str(uuid4())
        try:
            with self._pool.connection() as conn, conn.transaction():
                conn.execute(
                    "INSERT INTO owners (owner_id,kind) VALUES (%s,'guest')",
                    (owner_id,),
                )
                row = conn.execute(
                    """INSERT INTO guest_sessions
                    (session_id,guest_owner_id,refresh_hash,expires_at)
                    VALUES (%s,%s,%s,%s)
                    RETURNING *""",
                    (session_id, owner_id, refresh_hash, expires_at),
                ).fetchone()
            return OwnerRecord(owner_id, "guest", "active"), guest_session_from_row(row)
        except Exception as exc:
            raise StoreError("unable to create guest session") from exc

    def find_refresh(self, refresh_hash: str, now: datetime) -> RefreshLookup | None:
        queries = (
            (
                "auth_sessions",
                "user_owner_id",
                "user",
            ),
            (
                "guest_sessions",
                "guest_owner_id",
                "guest",
            ),
        )
        try:
            with self._pool.connection() as conn:
                for table, owner_column, kind in queries:
                    row = conn.execute(
                        f"""SELECT *,{owner_column} AS owner_id FROM {table}
                        WHERE refresh_hash=%s OR
                        (previous_refresh_hash=%s AND previous_valid_until>%s)
                        LIMIT 1""",
                        (refresh_hash, refresh_hash, now),
                    ).fetchone()
                    if row is not None:
                        session = session_from_row(row, kind)
                        return RefreshLookup(
                            session,
                            session.previous_refresh_hash == refresh_hash,
                        )
            return None
        except Exception as exc:
            raise StoreError("unable to read refresh session") from exc

    def rotate_refresh(
        self,
        session_id: str,
        *,
        expected_hash: str,
        new_hash: str,
        previous_valid_until: datetime,
    ) -> SessionRecord:
        for table, owner_column, kind in (
            ("auth_sessions", "user_owner_id", "user"),
            ("guest_sessions", "guest_owner_id", "guest"),
        ):
            try:
                with self._pool.connection() as conn:
                    row = conn.execute(
                        f"""UPDATE {table}
                        SET previous_refresh_hash=refresh_hash,
                            previous_valid_until=%s,refresh_hash=%s,updated_at=now()
                        WHERE session_id=%s AND refresh_hash=%s AND revoked_at IS NULL
                        RETURNING *,{owner_column} AS owner_id""",
                        (previous_valid_until, new_hash, session_id, expected_hash),
                    ).fetchone()
                if row is not None:
                    return session_from_row(row, kind)
            except errors.UniqueViolation as exc:
                raise SessionInactive from exc
            except Exception as exc:
                raise StoreError("unable to rotate refresh session") from exc
        raise SessionInactive

    def get_session(self, session_id: str) -> SessionRecord | None:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """SELECT *,user_owner_id AS owner_id FROM auth_sessions
                    WHERE session_id=%s""",
                    (session_id,),
                ).fetchone()
                if row is not None:
                    return session_from_row(row, "user")
                row = conn.execute(
                    """SELECT *,guest_owner_id AS owner_id FROM guest_sessions
                    WHERE session_id=%s""",
                    (session_id,),
                ).fetchone()
            return None if row is None else session_from_row(row, "guest")
        except Exception as exc:
            raise StoreError("unable to read session") from exc

    def get_owner(self, owner_id: str) -> OwnerRecord | None:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """SELECT owner_id,kind,lifecycle_state,authorization_epoch
                    FROM owners WHERE owner_id=%s""",
                    (owner_id,),
                ).fetchone()
            return None if row is None else owner_from_row(row)
        except Exception as exc:
            raise StoreError("unable to read owner") from exc

    def revoke_session(self, session_id: str, now: datetime) -> None:
        try:
            with self._pool.connection() as conn, conn.transaction():
                conn.execute(
                    """UPDATE auth_sessions SET revoked_at=COALESCE(revoked_at,%s),updated_at=now()
                    WHERE session_id=%s""",
                    (now, session_id),
                )
                conn.execute(
                    """UPDATE guest_sessions SET revoked_at=COALESCE(revoked_at,%s),updated_at=now()
                    WHERE session_id=%s""",
                    (now, session_id),
                )
        except Exception as exc:
            raise StoreError("unable to revoke session") from exc

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
        owner_id, session_id = str(uuid4()), str(uuid4())
        try:
            with self._pool.connection() as conn, conn.transaction():
                conn.execute(
                    "INSERT INTO owners (owner_id,kind) VALUES (%s,'user')",
                    (owner_id,),
                )
                user_row = conn.execute(
                    """INSERT INTO users
                    (owner_id,username_normalized,username_display,password_hash)
                    VALUES (%s,%s,%s,%s) RETURNING *""",
                    (owner_id, username_normalized, username_display, password_hash),
                ).fetchone()
                session_row = conn.execute(
                    """INSERT INTO auth_sessions
                    (session_id,user_owner_id,refresh_hash,expires_at)
                    VALUES (%s,%s,%s,%s)
                    RETURNING *,user_owner_id AS owner_id""",
                    (session_id, owner_id, refresh_hash, expires_at),
                ).fetchone()
                if revoke_session_id is not None:
                    conn.execute(
                        """UPDATE guest_sessions
                        SET revoked_at=COALESCE(revoked_at,%s),updated_at=now()
                        WHERE session_id=%s""",
                        (revoke_at, revoke_session_id),
                    )
            return user_from_row(user_row), session_from_row(session_row, "user")
        except errors.UniqueViolation as exc:
            raise UsernameTaken from exc
        except Exception as exc:
            raise StoreError("unable to register user") from exc

    def find_user_by_name(self, username_normalized: str) -> UserRecord | None:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    "SELECT * FROM users WHERE username_normalized=%s",
                    (username_normalized,),
                ).fetchone()
            return None if row is None else user_from_row(row)
        except Exception as exc:
            raise StoreError("unable to read user") from exc

    def get_user(self, owner_id: str) -> UserRecord | None:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    "SELECT * FROM users WHERE owner_id=%s", (owner_id,)
                ).fetchone()
            return None if row is None else user_from_row(row)
        except Exception as exc:
            raise StoreError("unable to read user") from exc

    def create_account_session(
        self,
        *,
        owner_id: str,
        refresh_hash: str,
        expires_at: datetime,
        revoke_session_id: str | None,
        revoke_at: datetime,
    ) -> SessionRecord:
        try:
            with self._pool.connection() as conn, conn.transaction():
                row = conn.execute(
                    """INSERT INTO auth_sessions
                    (session_id,user_owner_id,refresh_hash,expires_at)
                    SELECT %s,%s,%s,%s FROM owners
                    WHERE owner_id=%s AND kind='user' AND lifecycle_state='active'
                    RETURNING *,user_owner_id AS owner_id""",
                    (str(uuid4()), owner_id, refresh_hash, expires_at, owner_id),
                ).fetchone()
                if row is not None and revoke_session_id is not None:
                    conn.execute(
                        """UPDATE guest_sessions
                        SET revoked_at=COALESCE(revoked_at,%s),updated_at=now()
                        WHERE session_id=%s""",
                        (revoke_at, revoke_session_id),
                    )
            if row is None:
                raise SessionInactive
            return session_from_row(row, "user")
        except SessionInactive:
            raise
        except Exception as exc:
            raise StoreError("unable to create account session") from exc

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
        try:
            with self._pool.connection() as conn, conn.transaction():
                conn.execute(
                    """UPDATE users SET password_hash=%s,password_changed_at=%s,updated_at=now()
                    WHERE owner_id=%s""",
                    (password_hash, now, owner_id),
                )
                revoked = tuple(
                    str(row["session_id"])
                    for row in conn.execute(
                        """UPDATE auth_sessions SET revoked_at=%s,updated_at=now()
                        WHERE user_owner_id=%s AND session_id<>%s AND revoked_at IS NULL
                        RETURNING session_id""",
                        (now, owner_id, current_session_id),
                    ).fetchall()
                )
                row = conn.execute(
                    """UPDATE auth_sessions
                    SET previous_refresh_hash=refresh_hash,previous_valid_until=%s,
                        refresh_hash=%s,updated_at=now()
                    WHERE session_id=%s AND user_owner_id=%s AND revoked_at IS NULL
                    RETURNING *,user_owner_id AS owner_id""",
                    (previous_valid_until, refresh_hash, current_session_id, owner_id),
                ).fetchone()
            if row is None:
                raise SessionInactive
            return session_from_row(row, "user"), revoked
        except SessionInactive:
            raise
        except Exception as exc:
            raise StoreError("unable to change password") from exc

    def mark_owner_deleting(self, owner_id: str, now: datetime) -> tuple[str, ...]:
        try:
            with self._pool.connection() as conn, conn.transaction():
                row = conn.execute(
                    """UPDATE owners SET lifecycle_state='deleting',
                        authorization_epoch=authorization_epoch+1,
                        delete_requested_at=COALESCE(delete_requested_at,%s),updated_at=now()
                    WHERE owner_id=%s AND kind='user' RETURNING owner_id""",
                    (now, owner_id),
                ).fetchone()
                if row is None:
                    raise SessionInactive
                sessions = tuple(
                    str(item["session_id"])
                    for item in conn.execute(
                        """UPDATE auth_sessions SET revoked_at=COALESCE(revoked_at,%s),updated_at=now()
                        WHERE user_owner_id=%s RETURNING session_id""",
                        (now, owner_id),
                    ).fetchall()
                )
            return sessions
        except SessionInactive:
            raise
        except Exception as exc:
            raise StoreError("unable to mark account deleting") from exc

    def deleting_owner_ids(self) -> tuple[str, ...]:
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    "SELECT owner_id FROM owners WHERE lifecycle_state='deleting' ORDER BY created_at"
                ).fetchall()
            return tuple(str(row["owner_id"]) for row in rows)
        except Exception as exc:
            raise StoreError("unable to list deleting owners") from exc

    def delete_owner(self, owner_id: str) -> None:
        try:
            with self._pool.connection() as conn:
                conn.execute(
                    "DELETE FROM owners WHERE owner_id=%s AND lifecycle_state='deleting'",
                    (owner_id,),
                )
        except Exception as exc:
            raise StoreError("unable to delete owner") from exc

    def delete_orphan_guests(self, now: datetime) -> int:
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    """DELETE FROM owners owner
                    WHERE owner.kind='guest'
                      AND NOT EXISTS (
                        SELECT 1 FROM conversations conversation
                        WHERE conversation.owner_id=owner.owner_id)
                      AND NOT EXISTS (
                        SELECT 1 FROM guest_sessions session
                        WHERE session.guest_owner_id=owner.owner_id
                          AND session.revoked_at IS NULL
                          AND session.expires_at>%s)
                    RETURNING owner_id""",
                    (now,),
                ).fetchall()
            return len(rows)
        except Exception as exc:
            raise StoreError("unable to delete orphan guests") from exc
