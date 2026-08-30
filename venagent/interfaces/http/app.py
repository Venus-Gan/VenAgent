"""Conversation Context 的 HTTP 与 Web UI 入口。"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ...agent.ports import MessageInvoker, RunStoreError
from ...agent.runs import RunError
from ...agent.runtime import AgentRuntime
from ...bootstrap import build_application
from ...config import AppConfig
from ...conversation.ports import ConversationStoreError
from ...conversation.service import ConversationService
from ...mcp.client import McpClientManager, McpConnectionError
from ...mcp.config import McpConfigStore
from ...memory.jobs import MemoryMaintenanceWorker
from ...memory.ports import MemoryStoreError
from ...memory.service import MemoryService
from ...ownership.errors import OwnershipError
from ...ownership.ports import OwnershipStoreError
from ...ownership.service import OwnershipService
from ...platform.observability import log_startup_report
from ...platform.runtime import PersistenceRuntime
from ...skills.github import SkillHubUnavailable
from ...skills.hub import SkillHubService
from ...tools.control import ToolControlContext
from ...tools.errors import ToolError
from .errors import RUN_ERRORS, ApiError, ownership_api_error
from .routes import register_routes
from .schemas import ErrorBody, ErrorResponse

LOGGER = logging.getLogger("venagent.startup")

TOOL_ERRORS = {
    "approval_required": (409, "该工具调用需要先完成用户审批。"),
    "approval_expired": (409, "审批已过期，请重新发起调用。"),
    "tool_blocked": (403, "该工具被本地策略禁止。"),
    "tool_not_exposed": (403, "该工具未在当前快照中暴露。"),
    "tool_not_found": (404, "未找到该工具。"),
    "tool_schema_invalid": (422, "工具参数不符合 Schema。"),
    "tool_unavailable": (503, "工具当前不可用。"),
    "sandbox_unavailable": (503, "Sandbox 当前不可用，未执行命令。"),
    "skill_unavailable": (400, "所选 Skill 不可用或已停用。"),
}


def create_app(
    model: MessageInvoker | None = None,
    *,
    conversation_service: ConversationService | None = None,
    ownership_service: OwnershipService | None = None,
    persistence_runtime: PersistenceRuntime | None = None,
    config: AppConfig | None = None,
    frontend_dist: Path | None = None,
    tool_control: ToolControlContext | None = None,
    mcp_config_store: McpConfigStore | None = None,
    mcp_manager: McpClientManager | None = None,
    skill_hub: SkillHubService | None = None,
) -> FastAPI:
    """创建独立于旧 `final/` 运行时的线程化 Web 应用。"""
    application = build_application(
        model,
        conversation_service=conversation_service,
        ownership_service=ownership_service,
        persistence_runtime=persistence_runtime,
        config=config,
        tool_control=tool_control,
        mcp_config_store=mcp_config_store,
        mcp_manager=mcp_manager,
        skill_hub=skill_hub,
    )
    service = application.service
    ownership = application.ownership
    memory_maintenance = MemoryMaintenanceWorker(application.memory)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            await application.open()
        except BaseException:
            application.close()
            raise
        stop = asyncio.Event()
        maintenance = asyncio.create_task(
            _maintenance_loop(
                service, application.runtime, ownership, application.memory, stop
            )
        )
        # lifespan 在每个应用进程进入服务态前输出一次已聚合的启动快照。
        log_startup_report(application.startup_report, logger=LOGGER)
        memory_maintenance.start()
        application.runtime.start()
        try:
            yield
        finally:
            stop.set()
            maintenance.cancel()
            try:
                await maintenance
            except asyncio.CancelledError:
                pass
            await application.runtime.stop()
            await memory_maintenance.stop()
            await application.aclose()

    app = FastAPI(title="VenAgent", version="0.3.0", lifespan=lifespan)
    app.state.conversation_service = service
    app.state.agent_runtime = application.runtime
    app.state.persistence_runtime = application.persistence
    app.state.ownership_service = ownership
    app.state.memory_service = application.memory
    app.state.memory_maintenance = memory_maintenance
    app.state.memory_capabilities = application.memory_capabilities
    app.state.neo4j_runtime = application.graph
    app.state.document_service = application.document_service
    app.state.tool_control = application.tool_control
    app.state.mcp_store = application.mcp_store
    app.state.mcp_manager = application.mcp_manager
    app.state.skill_hub = application.skill_hub
    app.add_middleware(
        CORSMiddleware,
        allow_origins=application.config.auth.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def prevent_private_api_caching(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    resolved_frontend_dist = frontend_dist or Path(__file__).parents[3] / "web" / "dist"
    frontend_index = resolved_frontend_dist / "index.html"
    frontend_assets = resolved_frontend_dist / "assets"
    frontend_available = frontend_index.is_file() and frontend_assets.is_dir()

    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        payload = ErrorResponse(error=ErrorBody(code=exc.code, message=exc.message))
        return JSONResponse(
            status_code=exc.status_code,
            content=payload.model_dump(),
            headers=exc.headers,
        )

    @app.exception_handler(OwnershipError)
    async def ownership_error_handler(
        _request: Request, exc: OwnershipError
    ) -> JSONResponse:
        mapped = ownership_api_error(exc)
        payload = ErrorResponse(
            error=ErrorBody(code=mapped.code, message=mapped.message)
        )
        return JSONResponse(
            status_code=mapped.status_code,
            content=payload.model_dump(),
            headers={"Cache-Control": "no-store", **mapped.headers},
        )

    @app.exception_handler(ConversationStoreError)
    @app.exception_handler(RunStoreError)
    @app.exception_handler(OwnershipStoreError)
    @app.exception_handler(MemoryStoreError)
    async def ownership_store_error_handler(
        _request: Request, _exc: Exception
    ) -> JSONResponse:
        payload = ErrorResponse(
            error=ErrorBody(
                code="persistence_unavailable",
                message="持久化服务暂时不可用，操作未执行",
            )
        )
        return JSONResponse(
            status_code=503,
            content=payload.model_dump(),
            headers={"Cache-Control": "no-store"},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        payload = ErrorResponse(
            error=ErrorBody(code="invalid_request", message="请求参数无效")
        )
        return JSONResponse(status_code=422, content=payload.model_dump())

    @app.exception_handler(RunError)
    async def run_error_handler(_request: Request, exc: RunError) -> JSONResponse:
        status_code, message = RUN_ERRORS.get(type(exc), (500, "运行处理失败"))
        payload = ErrorResponse(error=ErrorBody(code=exc.code, message=message))
        return JSONResponse(status_code=status_code, content=payload.model_dump())

    @app.exception_handler(ToolError)
    async def tool_error_handler(
        _request: Request, exc: ToolError
    ) -> JSONResponse:
        status_code, message = TOOL_ERRORS.get(
            exc.code, (400, "工具控制操作失败。")
        )
        payload = ErrorResponse(error=ErrorBody(code=exc.code, message=message))
        return JSONResponse(status_code=status_code, content=payload.model_dump())

    @app.exception_handler(McpConnectionError)
    async def mcp_connection_error_handler(
        _request: Request, _exc: McpConnectionError
    ) -> JSONResponse:
        payload = ErrorResponse(
            error=ErrorBody(
                code="mcp_unavailable",
                message="MCP 服务暂时不可用，请稍后重试。",
            )
        )
        return JSONResponse(
            status_code=502,
            content=payload.model_dump(),
            headers={"Cache-Control": "no-store"},
        )

    @app.exception_handler(SkillHubUnavailable)
    async def skill_hub_error_handler(
        _request: Request, exc: SkillHubUnavailable
    ) -> JSONResponse:
        from ...skills.github import SkillRateLimited, SkillSourceNotFound

        if isinstance(exc, SkillRateLimited):
            code = "skill_hub_rate_limited"
            message = "Skill 广场暂时被限流，请稍后重试。"
            status_code = 429
        elif isinstance(exc, SkillSourceNotFound):
            code = "skill_source_not_found"
            message = "该仓库固定位置没有可校验的 SKILL.md。"
            status_code = 404
        else:
            code = "skill_hub_unavailable"
            message = "Skill 广场暂时不可用，已保留已安装技能。"
            status_code = 502
        payload = ErrorResponse(error=ErrorBody(code=code, message=message))
        return JSONResponse(
            status_code=status_code,
            content=payload.model_dump(),
            headers={"Cache-Control": "no-store"},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(
        _request: Request, exc: Exception
    ) -> JSONResponse:
        # 只记录异常类型，避免将请求正文、provider 响应或凭据写入日志。
        LOGGER.error(
            "HTTP 请求出现未处理异常。",
            extra={"error_type": type(exc).__name__},
        )
        payload = ErrorResponse(
            error=ErrorBody(
                code="internal_error",
                message="服务暂时无法完成请求，请稍后重试",
            )
        )
        return JSONResponse(
            status_code=500,
            content=payload.model_dump(),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/health")
    def health_status() -> dict[str, object]:
        return application.health

    @app.get("/", include_in_schema=False)
    def web_ui() -> Response:
        if not frontend_available:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "frontend_unavailable",
                        "message": "前端构建产物不可用，请先在 web 目录运行 npm run build。",
                    }
                },
            )
        return FileResponse(frontend_index)

    register_routes(
        app,
        service,
        application.runtime,
        ownership,
        application.command_registry,
        application.config,
        lambda owner_id: _finish_account_deletion(
            service, application.runtime, ownership, owner_id
        ),
        application.tool_control,
        application.mcp_store,
        application.mcp_manager,
        application.skill_hub,
        document_service=application.document_service,
    )
    if frontend_available:
        app.mount(
            "/assets", StaticFiles(directory=frontend_assets), name="frontend-assets"
        )

    return app


def _finish_account_deletion(
    service: ConversationService,
    runtime: AgentRuntime,
    ownership: OwnershipService,
    owner_id: str,
) -> None:
    try:
        for conversation_id in service.store.owner_conversation_ids(owner_id):
            for run_id in service.mark_owner_conversation_deleting(
                owner_id, conversation_id
            ):
                runtime.notify_cancel(run_id)
    except Exception:
        # owner 保持 deleting；lifespan 维护循环会继续同一收敛过程。
        return


async def _maintenance_loop(
    service: ConversationService,
    runtime: AgentRuntime,
    ownership: OwnershipService,
    memory: MemoryService,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            for owner_id, conversation_id in service.store.deleting_conversations():
                runs = service.store.conversation_runs(owner_id, conversation_id)
                for run in runs:
                    if not run.terminal:
                        runtime.notify_cancel(run.run_id)
                if runs and not all(run.terminal for run in runs):
                    continue
                # 先清 checkpoint，再删除业务行；失败时整个对象留给下一轮。
                for run in runs:
                    await runtime.delete_checkpoint(run.run_id)
                service.finish_conversation_deletion(owner_id, conversation_id)
            for owner_id in ownership.deleting_owner_ids():
                if not service.store.owner_conversation_ids(owner_id):
                    if memory.prepare_owner_deletion(owner_id):
                        ownership.finish_deletion(owner_id)
            ownership.cleanup_orphan_guests()
        except Exception:
            # 单轮故障不伪造删除完成，下一轮从权威事实继续。
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            continue


app = create_app()
