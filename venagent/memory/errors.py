"""记忆用例的稳定错误。"""


class MemoryError(RuntimeError):
    code = "memory_error"


class MemoryUnauthorized(MemoryError):
    code = "memory_unauthorized"


class MemoryDisabled(MemoryError):
    code = "memory_disabled"


class MemoryUnsupported(MemoryError):
    code = "memory_unsupported"


class MemoryNotFound(MemoryError):
    code = "memory_not_found"


class MemoryInvalidCommand(MemoryError):
    code = "memory_invalid_command"


class MemoryUnsafeContent(MemoryError):
    code = "memory_unsafe_content"


class MemoryInvalidCursor(MemoryError):
    code = "memory_invalid_cursor"


class MemoryConfirmationInvalid(MemoryError):
    code = "memory_confirmation_invalid"


class MemoryPurgePending(MemoryError):
    code = "memory_purge_pending"


class MemoryDisableNotPersisted(MemoryError):
    code = "memory_disable_not_persisted"
