"""Run 创建、重试、取消与 SSE routes。"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from ....agent.ports import RunStoreError
from ....agent.runs import AgentRun
from ....agent.runtime import AgentRuntime
from ....agent.state import ClarificationAnswer
from ....command.registry import CommandRegistry
from ....conversation.errors import ConversationError
from ....conversation.models import RunCreation
from ....conversation.ports import ConversationStoreError
from ....conversation.service import ConversationService
from ....memory.ports import MemoryStoreError
from ....ownership.ports import OwnershipStoreError
from ....ownership.service import OwnershipService
from ....tools.control import ToolControlContext
from ....tools.errors import ToolError
from ..auth import current_actor
from ..errors import api_error, persistence_api_error
from ..schemas import (
    CancelRunResponse,
    ClarifyRunRequest,
    ClarifyRunResponse,
    CommandOptionResponse,
    CommandResponse,
    CreateRunRequest,
    RetryRunRequest,
    RunCreationResponse,
    RunEventResponse,
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
    command_registry: CommandRegistry,
    tool_control: ToolControlContext,
) -> None:
    @app.get("/api/commands", response_model=list[CommandOptionResponse])
    def command_options(request: Request) -> list[CommandOptionResponse]:
        current_actor(request, ownership)
        return [
            CommandOptionResponse(
                command=item.command,
                description=item.description,
                parent=item.parent,
            )
            for item in command_registry.options()
        ]

    @app.post(
        "/api/conversations/{conversation_id}/runs",
        response_model=RunCreationResponse | CommandResponse,
        status_code=202,
    )
    def create_run(
        conversation_id: str,
        payload: CreateRunRequest,
        request: Request,
        response: Response,
    ) -> RunCreationResponse | CommandResponse:
        actor = current_actor(request, ownership)
        stripped = payload.message.strip()
        if stripped == "/plan":
            # /plan 不是旁路命令：仍建完整 run（流式/审批/恢复），只是显式进计划层。
            raise HTTPException(
                status_code=422,
                detail={"code": "plan_task_required", "message": "用法：/plan <任务>"},
            )
        try:
            if command_registry.matches(payload.message):
                result = command_registry.execute(actor, payload.message)
                response.status_code = 200
                return CommandResponse(
                    kind=result.kind, code=result.code, message=result.message
                )
            if payload.selected_skill_id is not None:
                try:
                    tool_control.skills.snapshot((payload.selected_skill_id,))
                except ValueError as exc:
                    raise ToolError("skill_unavailable") from exc
            creation = service.create_run(
                actor,
                conversation_id,
                payload.message,
                payload.client_request_id,
            )
            selected_skill = None
            if payload.selected_skill_id is not None:
                snapshot = tool_control.skills.snapshot((payload.selected_skill_id,))
                skill_name = snapshot.selected[0].manifest.name
                tool_control.bind_run_skills(
                    creation.run.run_id,
                    (payload.selected_skill_id,),
                )
                service.set_run_skill(
                    actor,
                    creation.run.run_id,
                    payload.selected_skill_id,
                    skill_name,
                )
                selected_skill = (payload.selected_skill_id, skill_name)
            return creation_response(creation, selected_skill=selected_skill)
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
            source_run = service.get_run(actor, run_id)
            source_skill = (
                (source_run.selected_skill_id, source_run.selected_skill_name)
                if source_run.selected_skill_id
                else None
            )
            creation = service.retry_run(
                actor, run_id, payload.client_request_id
            )
            if source_skill is not None:
                tool_control.bind_run_skills(
                    creation.run.run_id,
                    (source_skill[0],),
                )
                service.set_run_skill(
                    actor,
                    creation.run.run_id,
                    source_skill[0],
                    source_skill[1],
                )
            return creation_response(
                creation, selected_skill=source_skill
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
    async def cancel_run(run_id: str, request: Request) -> CancelRunResponse:
        actor = current_actor(request, ownership)
        current = service.get_run(actor, run_id)
        if current.status == "waiting_approval":
            cancelled = runtime.cancel_waiting_approval(actor.owner_id, run_id)
            await runtime.finalize_cancelled_run(run_id, actor.owner_id)
            return CancelRunResponse(run_id=run_id, status=cancelled.status)
        run = service.request_cancel(actor, run_id)
        if not run.terminal:
            runtime.notify_cancel(run.run_id)
            return CancelRunResponse(run_id=run.run_id, status="cancel_requested")
        return CancelRunResponse(run_id=run.run_id, status=run.status)

    @app.post(
        "/api/runs/{run_id}/clarify",
        response_model=ClarifyRunResponse,
        status_code=202,
    )
    def clarify_run(
        run_id: str, payload: ClarifyRunRequest, request: Request
    ) -> ClarifyRunResponse:
        """M07 澄清答复：答案回填计划层，Planner 带补充重新规划。"""
        actor = current_actor(request, ownership)
        answer = ClarificationAnswer(
            selected=tuple(payload.selected),
            custom=payload.custom,
            skipped=payload.skipped,
        )
        try:
            run = runtime.submit_clarification(actor.owner_id, run_id, answer)
        except STORE_ERRORS as exc:
            raise persistence_api_error() from exc
        return ClarifyRunResponse(run_id=run.run_id, status=run.status)

    @app.get("/api/runs/{run_id}/events", response_class=StreamingResponse)
    async def run_events(run_id: str, request: Request) -> StreamingResponse:
        actor = current_actor(request, ownership)
        service.get_run(actor, run_id)
        return StreamingResponse(
            stream_run_events(
                runtime,
                lambda: service.get_run(actor, run_id),
                lambda run: run_response(run).model_dump(mode="json"),
                owner_id=actor.owner_id,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs/{run_id}/event-log", response_model=list[RunEventResponse])
    def run_event_log(run_id: str, request: Request) -> list[RunEventResponse]:
        actor = current_actor(request, ownership)
        service.get_run(actor, run_id)
        return [
            RunEventResponse(
                run_id=item.run_id,
                sequence=item.sequence,
                type=item.type,
                payload=item.payload,
                created_at=item.created_at,
            )
            for item in runtime.run_events(actor.owner_id, run_id)
        ]


def run_response(
    item: AgentRun,
    *,
    retry_eligible: bool = False,
    selected_skill: tuple[str, str] | None = None,
) -> RunResponse:
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
        selected_skill_id=item.selected_skill_id
        or (selected_skill[0] if selected_skill else None),
        selected_skill_name=item.selected_skill_name
        or (selected_skill[1] if selected_skill else None),
    )


def creation_response(
    item: RunCreation, *, selected_skill: tuple[str, str] | None = None
) -> RunCreationResponse:
    return RunCreationResponse(
        run=run_response(item.run, selected_skill=selected_skill),
        input_message=message_response(item.input_message),
    )
