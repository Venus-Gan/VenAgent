"""可安全映射到 HTTP 的稳定身份错误。"""


class OwnershipError(Exception):
    code = "ownership_error"


class AccessTokenMissing(OwnershipError):
    code = "access_token_missing"


class AccessTokenInvalid(OwnershipError):
    code = "access_token_invalid"


class AccessTokenExpired(OwnershipError):
    code = "access_token_expired"


class SessionInactive(OwnershipError):
    code = "session_inactive"


class RefreshRequired(OwnershipError):
    code = "refresh_required"


class InvalidCredentials(OwnershipError):
    code = "invalid_credentials"


class UsernameTaken(OwnershipError):
    code = "username_taken"


class InvalidUsername(OwnershipError):
    code = "invalid_username"


class InvalidPassword(OwnershipError):
    code = "invalid_password"


class AccountRequired(OwnershipError):
    code = "account_required"


class AccountServiceUnavailable(OwnershipError):
    code = "account_service_unavailable"


class IdentityConflict(OwnershipError):
    code = "identity_conflict"


class OriginNotAllowed(OwnershipError):
    code = "origin_not_allowed"


class AuthRateLimited(OwnershipError):
    code = "auth_rate_limited"
