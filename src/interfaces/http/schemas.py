"""HTTP request/response schemas。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from ...conversation.rules import MAX_MESSAGE_BYTES


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActorResponse(ApiModel):
    kind: Literal["guest", "user", "temporary_guest"]
    owner_id: str
    username: str | None = None


class IdentityResponse(ApiModel):
    actor: ActorResponse
    access_token: str
    access_expires_at: datetime
    mode: Literal["durable", "temporary"]


class CredentialsRequest(ApiModel):
    username: str
    password: str


class ChangePasswordRequest(ApiModel):
    current_password: str
    new_password: str


class DeleteAccountRequest(ApiModel):
    current_password: str
    confirmed: bool


class AccountDeletionResponse(ApiModel):
    status: Literal["account_deletion_started"]


class ConversationResponse(ApiModel):
    conversation_id: str
    title: str
    title_source: Literal["auto", "manual"]
    lifecycle_state: Literal["active", "deleting"]
    created_at: datetime
    updated_at: datetime


class MessageResponse(ApiModel):
    message_id: str
    role: Literal["user", "assistant"]
    content: str
    sequence: int
    created_at: datetime
    source_run_id: str | None = None
    reply_to_message_id: str | None = None
    blocks: list[dict[str, str]] = []


class RunEventResponse(ApiModel):
    run_id: str
    sequence: int
    type: str
    payload: dict[str, Any]
    created_at: datetime


class RunResponse(ApiModel):
    run_id: str
    conversation_id: str
    input_message_id: str
    output_message_id: str | None
    status: str
    phase: str | None
    terminal_reason_code: str | None
    terminal_message: str | None
    cancel_requested_at: datetime | None
    created_at: datetime
    updated_at: datetime
    retry_eligible: bool = False
    selected_skill_id: str | None = None
    selected_skill_name: str | None = None


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse]
    runs: list[RunResponse]


class ConversationListResponse(ApiModel):
    items: list[ConversationResponse]
    next_cursor: str | None


class RenameConversationRequest(ApiModel):
    title: str


class CreateRunRequest(ApiModel):
    message: str
    client_request_id: str
    selected_skill_id: str | None = None

    @field_validator("message")
    @classmethod
    def validate_message_size(cls, value: str) -> str:
        if len(value.strip().encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise ValueError("message exceeds the maximum size")
        return value


class CommandOptionResponse(ApiModel):
    command: str
    description: str
    parent: str | None = None


class RetryRunRequest(ApiModel):
    client_request_id: str


class RunCreationResponse(ApiModel):
    run: RunResponse
    input_message: MessageResponse


class CommandResponse(ApiModel):
    kind: Literal["memory_command", "mcp_command", "rag_command"]
    code: str
    message: str


# 兼容旧引用的别名；新命令统一使用 CommandResponse。
MemoryCommandResponse = CommandResponse


class CancelRunResponse(ApiModel):
    run_id: str
    status: Literal[
        "cancel_requested", "succeeded", "failed", "cancelled", "incompatible"
    ]


class ClarifyRunRequest(ApiModel):
    """M07 澄清答复：单选/多选/其他自填/忽略。"""

    selected: list[str] = []
    custom: str | None = None
    skipped: bool = False

    @field_validator("selected")
    @classmethod
    def validate_selected(cls, value: list[str]) -> list[str]:
        if len(value) > 10:
            raise ValueError("selected items exceed limit")
        return value

    @field_validator("custom")
    @classmethod
    def validate_custom(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 2000:
            raise ValueError("custom answer too long")
        return value


class ClarifyRunResponse(ApiModel):
    run_id: str
    status: str


class ErrorBody(ApiModel):
    code: str
    message: str


class ErrorResponse(ApiModel):
    error: ErrorBody
