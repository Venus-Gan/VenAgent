"""最终模型上下文投影的稳定错误。"""


class ContextProjectionError(RuntimeError):
    code = "context_projection_error"


class ContextOverflow(ContextProjectionError):
    code = "context_overflow"


class ProjectionConfigurationError(ContextProjectionError):
    code = "projection_configuration_error"
