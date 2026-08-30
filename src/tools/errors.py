"""M06 Tool 域稳定错误码。"""

from __future__ import annotations


class ToolError(RuntimeError):
    code = "tool_error"


class ToolNotFound(ToolError):
    code = "tool_not_found"


class ToolNotExposed(ToolError):
    code = "tool_not_exposed"


class ToolBlocked(ToolError):
    code = "tool_blocked"


class ToolUnavailable(ToolError):
    code = "tool_unavailable"


class ToolSchemaInvalid(ToolError):
    code = "tool_schema_invalid"


class OperationNotFound(ToolError):
    code = "operation_not_found"


class OperationDuplicate(ToolError):
    code = "operation_duplicate"


class ApprovalRequired(ToolError):
    code = "approval_required"


class ApprovalExpired(ToolError):
    code = "approval_expired"


class ApprovalRejected(ToolError):
    code = "approval_rejected"


class SandboxUnavailable(ToolError):
    code = "sandbox_unavailable"


class ToolTimeout(ToolError):
    code = "tool_timeout"


class ToolCancelled(ToolError):
    code = "tool_cancelled"


class RunGrantInvalid(ToolError):
    code = "run_grant_invalid"
