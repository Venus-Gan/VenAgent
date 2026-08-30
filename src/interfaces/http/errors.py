"""领域/运行错误到稳定 HTTP 错误的翻译。"""

from ...agent.runs import InvalidRunId, RunError, RunNotFound
from ...conversation.errors import (
    AnonymousLimitExceeded,
    ConversationBusy,
    ConversationDeleting,
    ConversationError,
    ConversationNotFound,
    IdempotencyConflict,
    InvalidClientRequestId,
    InvalidConversationId,
    InvalidMessage,
    InvalidTitle,
    RetryNotAllowed,
)
from ...ownership.errors import (
    AccessTokenExpired,
    AccessTokenInvalid,
    AccessTokenMissing,
    AccountRequired,
    AccountServiceUnavailable,
    AuthRateLimited,
    IdentityConflict,
    InvalidCredentials,
    InvalidPassword,
    InvalidUsername,
    OriginNotAllowed,
    OwnershipError,
    RefreshRequired,
    SessionInactive,
    UsernameTaken,
)


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}


ERRORS: dict[type[ConversationError], tuple[int, str]] = {
    InvalidConversationId: (400, "conversation_id 格式无效"),
    InvalidMessage: (400, "message 不能为空"),
    ConversationNotFound: (404, "对话不存在或不可访问"),
    ConversationBusy: (409, "该对话已有运行中的任务"),
    ConversationDeleting: (409, "该对话正在删除"),
    InvalidClientRequestId: (400, "client_request_id 格式无效"),
    IdempotencyConflict: (409, "client_request_id 已用于不同请求"),
    InvalidTitle: (400, "标题格式无效"),
    RetryNotAllowed: (409, "当前运行不满足重试条件"),
    AnonymousLimitExceeded: (429, "匿名对话数量或创建频率已达上限"),
}

OWNERSHIP_ERRORS: dict[type[OwnershipError], tuple[int, str]] = {
    AccessTokenMissing: (401, "缺少访问令牌"),
    AccessTokenInvalid: (401, "访问令牌无效"),
    AccessTokenExpired: (401, "访问令牌已过期"),
    SessionInactive: (401, "登录会话已失效"),
    RefreshRequired: (401, "需要重新建立会话"),
    InvalidCredentials: (401, "用户名或密码错误"),
    InvalidUsername: (400, "用户名格式无效"),
    InvalidPassword: (400, "密码长度必须为 8 到 128 个字符"),
    UsernameTaken: (409, "用户名已存在"),
    AccountRequired: (403, "此操作需要注册账号"),
    OriginNotAllowed: (403, "请求来源不受信任"),
    IdentityConflict: (409, "当前身份与操作冲突"),
    AuthRateLimited: (429, "认证尝试过于频繁，请稍后再试"),
    AccountServiceUnavailable: (503, "持久化当前不可用，账号操作未执行"),
}

RUN_ERRORS: dict[type[RunError], tuple[int, str]] = {
    InvalidRunId: (400, "run_id 格式无效"),
    RunNotFound: (404, "运行不存在或不可访问"),
}


def api_error(error: ConversationError) -> ApiError:
    status_code, message = ERRORS.get(type(error), (500, "请求处理失败"))
    headers = (
        {"Retry-After": "600"} if isinstance(error, AnonymousLimitExceeded) else None
    )
    return ApiError(status_code, error.code, message, headers=headers)


def ownership_api_error(error: OwnershipError) -> ApiError:
    status_code, message = OWNERSHIP_ERRORS.get(type(error), (500, "身份处理失败"))
    headers = {"Retry-After": "600"} if isinstance(error, AuthRateLimited) else None
    return ApiError(status_code, error.code, message, headers=headers)


def persistence_api_error() -> ApiError:
    return ApiError(503, "persistence_unavailable", "持久化服务暂时不可用，请稍后重试")
