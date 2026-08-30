"""Agent run 的稳定错误归属。"""


class RunError(Exception):
    code = "run_error"


class InvalidRunId(RunError):
    code = "invalid_run_id"


class RunNotFound(RunError):
    code = "run_not_found"


class InvalidRunTransition(RunError):
    code = "invalid_run_transition"


class RunAuthorizationInvalid(RunError):
    code = "run_authorization_invalid"


class RunCancelled(Exception):
    """worker 收到取消信号时使用的进程内控制异常。"""
