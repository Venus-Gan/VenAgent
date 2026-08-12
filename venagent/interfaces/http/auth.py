"""HTTP Bearer、Origin 与 refresh Cookie 映射。"""

from __future__ import annotations

from datetime import timezone
from urllib.parse import urlsplit

from fastapi import Request, Response

from ...config import AppConfig
from ...ownership.errors import AccessTokenInvalid, OriginNotAllowed
from ...ownership.models import Actor, IdentityResult
from ...ownership.service import OwnershipService
from .schemas import ActorResponse, IdentityResponse

ACCOUNT_COOKIE = "venagent_account_refresh"
GUEST_COOKIE = "venagent_guest_refresh"
TEMPORARY_COOKIE = "venagent_temporary_refresh"
COOKIE_PATH = "/api/auth"


def current_actor(request: Request, ownership: OwnershipService) -> Actor:
    return ownership.resolve_access(_bearer(request))


def optional_actor(request: Request, ownership: OwnershipService) -> Actor | None:
    authorization = request.headers.get("Authorization", "")
    if not authorization:
        return None
    return ownership.resolve_access(_bearer(request))


def require_origin(request: Request, config: AppConfig) -> None:
    origin = request.headers.get("Origin")
    if not origin:
        raise OriginNotAllowed
    allowed = {_origin(value) for value in config.auth.allowed_origins}
    allowed.add(_origin(str(request.base_url)))
    if _origin(origin) not in allowed:
        raise OriginNotAllowed


def identity_response(
    result: IdentityResult,
    response: Response,
    config: AppConfig,
) -> IdentityResponse:
    if result.refresh_token is not None:
        set_refresh_cookie(response, result, config)
    response.headers["Cache-Control"] = "no-store"
    return IdentityResponse(
        actor=ActorResponse(
            kind=result.actor.kind,
            owner_id=result.actor.owner_id,
            username=result.actor.username,
        ),
        access_token=result.access_token,
        access_expires_at=result.access_expires_at,
        mode=result.actor.mode,
    )


def set_refresh_cookie(
    response: Response,
    result: IdentityResult,
    config: AppConfig,
) -> None:
    name = cookie_name(result.actor.kind)
    response.set_cookie(
        name,
        result.refresh_token or "",
        expires=result.refresh_expires_at.astimezone(timezone.utc),
        httponly=True,
        secure=config.auth.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )


def clear_cookie(response: Response, name: str, config: AppConfig) -> None:
    response.set_cookie(
        name,
        "",
        max_age=0,
        expires=0,
        httponly=True,
        secure=config.auth.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )


def clear_guest_cookies(response: Response, config: AppConfig) -> None:
    clear_cookie(response, GUEST_COOKIE, config)
    clear_cookie(response, TEMPORARY_COOKIE, config)


def cookie_name(kind: str) -> str:
    if kind == "user":
        return ACCOUNT_COOKIE
    if kind == "guest":
        return GUEST_COOKIE
    return TEMPORARY_COOKIE


def _bearer(request: Request) -> str:
    value = request.headers.get("Authorization", "")
    scheme, separator, token = value.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        if not value:
            from ...ownership.errors import AccessTokenMissing

            raise AccessTokenMissing
        raise AccessTokenInvalid
    return token.strip()


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OriginNotAllowed
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
