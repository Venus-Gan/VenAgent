"""Conversation 查询、重命名与删除 HTTP routes。"""

from __future__ import annotations

from fastapi import FastAPI, Query, Request, Response

from ....agent.ports import RunStoreError
from ....agent.runtime import AgentRuntime
from ....conversation.errors import ConversationError
from ....conversation.models import Conversation, ConversationMessage
from ....conversation.ports import ConversationStoreError
from ....conversation.service import ConversationService
from ....memory.ports import MemoryStoreError
from ....ownership.ports import OwnershipStoreError
from ....ownership.service import OwnershipService
from ..auth import current_actor
from ..errors import api_error, persistence_api_error
from ..schemas import (
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationResponse,
    MessageResponse,
    RenameConversationRequest,
)

STORE_ERRORS = (
    ConversationStoreError,
    RunStoreError,
    OwnershipStoreError,
    MemoryStoreError,
)


def register_conversation_routes(
    app: FastAPI,
    service: ConversationService,
    runtime: AgentRuntime,
    ownership: OwnershipService,
) -> None:
    @app.post(
        "/api/conversations", response_model=ConversationResponse, status_code=201
    )
    def create_conversation(request: Request) -> ConversationResponse:
        actor = current_actor(request, ownership)
        try:
            return conversation_response(service.create_conversation(actor))
        except ConversationError as exc:
            raise api_error(exc) from exc
        except STORE_ERRORS as exc:
            raise persistence_api_error() from exc

    @app.get("/api/conversations", response_model=ConversationListResponse)
    def list_conversations(
        request: Request,
        cursor: str | None = None,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> ConversationListResponse:
        actor = current_actor(request, ownership)
        try:
            page = service.list_conversations(actor, cursor=cursor, limit=limit)
            return ConversationListResponse(
                items=[conversation_response(item) for item in page.items],
                next_cursor=page.next_cursor,
            )
        except ConversationError as exc:
            raise api_error(exc) from exc
        except STORE_ERRORS as exc:
            raise persistence_api_error() from exc

    @app.get(
        "/api/conversations/{conversation_id}",
        response_model=ConversationDetailResponse,
    )
    def conversation_detail(
        conversation_id: str, request: Request
    ) -> ConversationDetailResponse:
        actor = current_actor(request, ownership)
        try:
            detail = service.get_conversation(actor, conversation_id)
            latest_user = next(
                (
                    item.message_id
                    for item in reversed(detail.messages)
                    if item.role == "user"
                ),
                None,
            )
            active = any(not run.terminal for run in detail.runs)
            from .runs import run_response

            return ConversationDetailResponse(
                **conversation_response(detail.conversation).model_dump(),
                messages=[message_response(item) for item in detail.messages],
                runs=[
                    run_response(
                        run,
                        retry_eligible=(
                            run.status in {"failed", "cancelled", "incompatible"}
                            and run.input_message_id == latest_user
                            and not active
                        ),
                    )
                    for run in detail.runs
                ],
            )
        except ConversationError as exc:
            raise api_error(exc) from exc
        except STORE_ERRORS as exc:
            raise persistence_api_error() from exc

    @app.patch(
        "/api/conversations/{conversation_id}", response_model=ConversationResponse
    )
    def rename_conversation(
        conversation_id: str,
        payload: RenameConversationRequest,
        request: Request,
    ) -> ConversationResponse:
        actor = current_actor(request, ownership)
        try:
            return conversation_response(
                service.rename_conversation(actor, conversation_id, payload.title)
            )
        except ConversationError as exc:
            raise api_error(exc) from exc
        except STORE_ERRORS as exc:
            raise persistence_api_error() from exc

    @app.delete("/api/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: str, request: Request) -> Response:
        actor = current_actor(request, ownership)
        try:
            for run_id in service.delete_conversation(actor, conversation_id):
                runtime.notify_cancel(run_id)
        except ConversationError as exc:
            raise api_error(exc) from exc
        except STORE_ERRORS as exc:
            raise persistence_api_error() from exc
        return Response(status_code=204)


def conversation_response(item: Conversation) -> ConversationResponse:
    return ConversationResponse(
        conversation_id=item.conversation_id,
        title=item.title,
        title_source=item.title_source,
        lifecycle_state=item.lifecycle_state,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def message_response(item: ConversationMessage) -> MessageResponse:
    return MessageResponse(
        message_id=item.message_id,
        role=item.role,
        content=item.content,
        sequence=item.sequence,
        created_at=item.created_at,
        source_run_id=item.source_run_id,
        reply_to_message_id=item.reply_to_message_id,
        blocks=list(item.content_blocks),
    )
