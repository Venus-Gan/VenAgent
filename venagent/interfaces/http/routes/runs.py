"""Run 创建、重试、取消与 SSE routes。"""

from __future__ import annotations

from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from ....agent.ports import RunStoreError
from ....agent.runs import AgentRun
from ....agent.runtime import AgentRuntime
from ....conversation.errors import ConversationError
from ....conversation.models import RunCreation
from ....conversation.ports import ConversationStoreError
from ....conversation.service import ConversationService
from ....memory.command_adapter import MemoryCommandAdapter
from ....memory.ports import MemoryStoreError
from ....ownership.ports import OwnershipStoreError
from ....ownership.service import OwnershipService
from ..auth import current_actor
from ..errors import api_error, persistence_api_error
from ..schemas import (
    CancelRunResponse,
    CreateRunRequest,
    MemoryCommandResponse,
    RetryRunRequest,
    RunCreationResponse,
    RunResponse,
)
from ..streaming import stream_run_events
from .conversations import message_response

STORE_ERRORS = (
    ConversationStoreError,
    RunStoreError,
    OwnershipStoreError,
    MemoryStoreError,
)


def register_run_routes(
    app: FastAPI,
    service: ConversationService,
    runtime: AgentRuntime,
    ownership: OwnershipService,
    memory_commands: MemoryCommandAdapter,
) -> None:
    @app.post(
        "/api/conversations/{conversation_id}/runs",
        response_model=RunCreationResponse | MemoryCommandResponse,
        status_code=202,
    )
    def create_run(
        conversation_id: str,
        payload: CreateRunRequest,
        request: Request,
        response: Response,
    ) -> RunCreationResponse | MemoryCommandResponse:
        actor = current_actor(request, ownership)
        try:
            if memory_commands.matches(payload.message):
                result = memory_commands.execute(actor, payload.message)
                response.status_code = 200
                return MemoryCommandResponse(code=result.code, message=result.message)
            return creation_response(
                service.create_run(
                    actor,
                    conversation_id,
                    payload.message,
                    payload.client_request_id,
                )
            )
        except ConversationError as exc:
            raise api_error(exc) from exc
        except STORE_ERRORS as exc:
            raise persistence_api_error() from exc

    @app.get("/api/runs/{run_id}", response_model=RunResponse)
    def get_run(run_id: str, request: Request) -> RunResponse:
        return run_response(service.get_run(current_actor(request, ownership), run_id))

    @app.post(
        "/api/runs/{run_id}/retry",
        response_model=RunCreationResponse,
        status_code=202,
    )
    def retry_run(
        run_id: str, payload: RetryRunRequest, request: Request
    ) -> RunCreationResponse:
        actor = current_actor(request, ownership)
        try:
            return creation_response(
                service.retry_run(actor, run_id, payload.client_request_id)
            )
        except ConversationError as exc:
            raise api_error(exc) from exc
        except STORE_ERRORS as exc:
            raise persistence_api_error() from exc

    @app.post(
        "/api/runs/{run_id}/cancel",
        response_model=CancelRunResponse,
        status_code=202,
    )
    def cancel_run(run_id: str, request: Request) -> CancelRunResponse:
        run = service.request_cancel(current_actor(request, ownership), run_id)
        if not run.terminal:
            runtime.notify_cancel(run.run_id)
            return CancelRunResponse(run_id=run.run_id, status="cancel_requested")
        return CancelRunResponse(run_id=run.run_id, status=run.status)

    @app.get("/api/runs/{run_id}/events", response_class=StreamingResponse)
    async def run_events(run_id: str, request: Request) -> StreamingResponse:
        actor = current_actor(request, ownership)
        service.get_run(actor, run_id)
        return StreamingResponse(
            stream_run_events(
                runtime,
                lambda: service.get_run(actor, run_id),
                lambda run: run_response(run).model_dump(mode="json"),
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )


def run_response(item: AgentRun, *, retry_eligible: bool = False) -> RunResponse:
    return RunResponse(
        run_id=item.run_id,
        conversation_id=item.conversation_id,
        input_message_id=item.input_message_id,
        output_message_id=item.output_message_id,
        status=item.status,
        phase=item.phase,
        terminal_reason_code=item.terminal_reason_code,
        terminal_message=item.terminal_message,
        cancel_requested_at=item.cancel_requested_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
        retry_eligible=retry_eligible,
    )


def creation_response(item: RunCreation) -> RunCreationResponse:
    return RunCreationResponse(
        run=run_response(item.run), input_message=message_response(item.input_message)
    )
