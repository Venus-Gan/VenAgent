"""平台连接池、迁移与 schema compatibility 错误。"""


class PlatformError(RuntimeError):
    code = "platform_error"


class PersistenceError(PlatformError):
    code = "persistence_error"
