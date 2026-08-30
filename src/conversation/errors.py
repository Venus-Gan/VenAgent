"""Conversation 能力可安全映射到 HTTP 的稳定错误。"""


class ConversationError(Exception):
    code = "conversation_error"


class InvalidConversationId(ConversationError):
    code = "invalid_conversation_id"


class InvalidMessage(ConversationError):
    code = "invalid_message"


class ConversationNotFound(ConversationError):
    code = "conversation_not_found"


class ConversationBusy(ConversationError):
    code = "conversation_busy"


class ConversationDeleting(ConversationError):
    code = "conversation_deleting"


class IdempotencyConflict(ConversationError):
    code = "idempotency_conflict"


class InvalidClientRequestId(ConversationError):
    code = "invalid_client_request_id"


class InvalidTitle(ConversationError):
    code = "invalid_title"


class RetryNotAllowed(ConversationError):
    code = "retry_not_allowed"


class AnonymousLimitExceeded(ConversationError):
    code = "anonymous_limit_exceeded"
