"""固定 HS256、严格 claims 的短期 access JWT adapter。"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import jwt

from ...ownership.errors import AccessTokenExpired, AccessTokenInvalid
from ...ownership.models import AccessClaims, ActorKind

ALGORITHM = "HS256"
ACCESS_TTL = timedelta(minutes=15)


class JwtAccessTokenCodec:
    def __init__(self, secret: str, *, issuer: str, audience: str) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("JWT secret 至少需要 32 字节")
        self._secret = secret
        self._issuer = issuer
        self._audience = audience

    def issue(
        self,
        owner_id: str,
        actor_kind: ActorKind,
        session_id: str,
        now: datetime,
    ) -> tuple[str, datetime]:
        issued_at = _utc(now)
        expires_at = issued_at + ACCESS_TTL
        payload = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": owner_id,
            "jti": str(uuid4()),
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "actor_kind": actor_kind,
            "sid": session_id,
        }
        return jwt.encode(payload, self._secret, algorithm=ALGORITHM), expires_at

    def decode(self, token: str, now: datetime) -> AccessClaims:
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],
                issuer=self._issuer,
                audience=self._audience,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "sub",
                        "jti",
                        "iat",
                        "exp",
                        "actor_kind",
                        "sid",
                    ],
                    "verify_exp": False,
                    "verify_iat": False,
                },
            )
            actor_kind = payload["actor_kind"]
            if actor_kind not in {"guest", "user", "temporary_guest"}:
                raise ValueError
            issued_at = datetime.fromtimestamp(int(payload["iat"]), timezone.utc)
            expires_at = datetime.fromtimestamp(int(payload["exp"]), timezone.utc)
            owner_id = _canonical_uuid(payload["sub"])
            session_id = _canonical_uuid(payload["sid"])
            token_id = _canonical_uuid(payload["jti"])
            if expires_at <= _utc(now):
                raise AccessTokenExpired
            if issued_at > _utc(now) + timedelta(seconds=30) or expires_at <= issued_at:
                raise ValueError
            return AccessClaims(
                owner_id=owner_id,
                actor_kind=actor_kind,
                session_id=session_id,
                token_id=token_id,
                issued_at=issued_at,
                expires_at=expires_at,
            )
        except AccessTokenExpired:
            raise
        except jwt.ExpiredSignatureError as exc:
            raise AccessTokenExpired from exc
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise AccessTokenInvalid from exc


def temporary_jwt_secret() -> str:
    return secrets.token_urlsafe(48)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _canonical_uuid(value: object) -> str:
    parsed = UUID(str(value))
    canonical = str(parsed)
    if str(value) != canonical:
        raise ValueError
    return canonical
