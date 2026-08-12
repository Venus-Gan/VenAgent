"""身份、session 与账号管理 HTTP routes。"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import BackgroundTasks, FastAPI, Request, Response

from ....config import AppConfig
from ....ownership.errors import RefreshRequired, SessionInactive
from ....ownership.service import OwnershipService
from ..auth import (
    ACCOUNT_COOKIE,
    GUEST_COOKIE,
    TEMPORARY_COOKIE,
    clear_cookie,
    clear_guest_cookies,
    current_actor,
    identity_response,
    optional_actor,
    require_origin,
)
from ..schemas import (
    AccountDeletionResponse,
    ChangePasswordRequest,
    CredentialsRequest,
    DeleteAccountRequest,
    IdentityResponse,
)


def register_auth_routes(
    app: FastAPI,
    ownership: OwnershipService,
    config: AppConfig,
    finish_account_deletion: Callable[[str], None],
) -> None:
    @app.post("/api/auth/guest", response_model=IdentityResponse)
    def guest_identity(request: Request, response: Response) -> IdentityResponse:
        require_origin(request, config)
        if ownership.mode == "durable" and request.cookies.get(ACCOUNT_COOKIE):
            try:
                ownership.assert_refresh_active(
                    request.cookies.get(ACCOUNT_COOKIE), allowed_kinds={"user"}
                )
            except (RefreshRequired, SessionInactive):
                clear_cookie(response, ACCOUNT_COOKIE, config)
            else:
                from ....ownership.errors import IdentityConflict

                raise IdentityConflict
        cookie = (
            request.cookies.get(GUEST_COOKIE)
            if ownership.mode == "durable"
            else request.cookies.get(TEMPORARY_COOKIE)
        )
        return identity_response(ownership.bootstrap_guest(cookie), response, config)

    @app.post("/api/auth/refresh", response_model=IdentityResponse)
    def refresh_identity(request: Request, response: Response) -> IdentityResponse:
        require_origin(request, config)
        if ownership.mode == "temporary":
            result = ownership.refresh(
                request.cookies.get(TEMPORARY_COOKIE),
                allowed_kinds={"temporary_guest"},
            )
        elif request.cookies.get(ACCOUNT_COOKIE):
            try:
                result = ownership.refresh(
                    request.cookies.get(ACCOUNT_COOKIE), allowed_kinds={"user"}
                )
            except (RefreshRequired, SessionInactive):
                clear_cookie(response, ACCOUNT_COOKIE, config)
                result = ownership.refresh(
                    request.cookies.get(GUEST_COOKIE), allowed_kinds={"guest"}
                )
        else:
            result = ownership.refresh(
                request.cookies.get(GUEST_COOKIE), allowed_kinds={"guest"}
            )
        return identity_response(result, response, config)

    @app.get("/api/auth/me", response_model=IdentityResponse)
    def current_identity(request: Request, response: Response) -> IdentityResponse:
        actor = current_actor(request, ownership)
        return identity_response(ownership.renew_access(actor), response, config)

    @app.post("/api/auth/register", response_model=IdentityResponse, status_code=201)
    def register(
        payload: CredentialsRequest, request: Request, response: Response
    ) -> IdentityResponse:
        require_origin(request, config)
        result = ownership.register(
            payload.username,
            payload.password,
            current_actor=optional_actor(request, ownership),
            rate_key=_client_key(request),
        )
        clear_guest_cookies(response, config)
        return identity_response(result, response, config)

    @app.post("/api/auth/login", response_model=IdentityResponse)
    def login(
        payload: CredentialsRequest, request: Request, response: Response
    ) -> IdentityResponse:
        require_origin(request, config)
        result = ownership.login(
            payload.username,
            payload.password,
            current_actor=optional_actor(request, ownership),
            rate_key=_client_key(request),
        )
        clear_guest_cookies(response, config)
        return identity_response(result, response, config)

    @app.post("/api/auth/logout", response_model=IdentityResponse)
    def logout(request: Request, response: Response) -> IdentityResponse:
        require_origin(request, config)
        result, _sessions = ownership.logout(current_actor(request, ownership))
        # 已签发 RunGrant 独立于登录 session，普通 logout 不取消后台 run。
        clear_cookie(response, ACCOUNT_COOKIE, config)
        return identity_response(result, response, config)

    @app.patch("/api/auth/password", response_model=IdentityResponse)
    def change_password(
        payload: ChangePasswordRequest, request: Request, response: Response
    ) -> IdentityResponse:
        require_origin(request, config)
        result, _revoked = ownership.change_password(
            current_actor(request, ownership),
            payload.current_password,
            payload.new_password,
        )
        return identity_response(result, response, config)

    @app.delete(
        "/api/auth/account",
        response_model=AccountDeletionResponse,
        status_code=202,
    )
    def delete_account(
        payload: DeleteAccountRequest,
        request: Request,
        response: Response,
        background: BackgroundTasks,
    ) -> AccountDeletionResponse:
        require_origin(request, config)
        deletion = ownership.request_deletion(
            current_actor(request, ownership),
            payload.current_password,
            payload.confirmed,
        )
        clear_cookie(response, ACCOUNT_COOKIE, config)
        background.add_task(finish_account_deletion, deletion.owner_id)
        return AccountDeletionResponse(status="account_deletion_started")


def _client_key(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"
