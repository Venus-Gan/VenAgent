"""M06 控制面 HTTP routes：目录、MCP、Skill 与 Operation/Approval。"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, field_validator

from ....agent.runtime import AgentRuntime
from ....mcp.catalog import McpToolCatalog
from ....mcp.client import (
    McpClientManager,
    McpConnectionError,
    resolve_trusted_stdio_executable,
)
from ....mcp.config import (
    McpConfigStore,
    McpServerConfig,
    McpToolManifest,
    McpToolPolicy,
)
from ....ownership.service import OwnershipService
from ....skills.github import SkillHubUnavailable
from ....skills.hub import SkillHubCandidate, SkillHubService
from ....tools.control import ToolControlContext
from ....tools.errors import ApprovalExpired
from ....tools.models import ApprovalItem, Operation
from ..auth import current_actor


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class McpToolManifestRequest(_ApiModel):
    name: str
    description: str = ""
    input_schema: dict[str, object] = {}
    read_only_hint: bool = False
    destructive_hint: bool = False


class McpServerRequest(_ApiModel):
    server_id: str
    name: str
    transport: str
    enabled: bool = False
    command: str | None = None
    args: list[str] = []
    url: str | None = None
    credential_ref: str | None = None
    env_refs: list[str] = []
    allow: list[str] = []
    deny: list[str] = []
    declared_tools: list[McpToolManifestRequest] = []

    @field_validator("server_id")
    @classmethod
    def validate_server_id(cls, value: str) -> str:
        if not value or any(character in value for character in " /\\"):
            raise ValueError("invalid server_id")
        return value

    @field_validator("credential_ref")
    @classmethod
    def validate_credential_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is None:
            raise ValueError("credential_ref must be an environment variable name")
        return value

    @field_validator("env_refs")
    @classmethod
    def validate_env_refs(cls, values: list[str]) -> list[str]:
        if len(values) > 16 or len(set(values)) != len(values):
            raise ValueError("env_refs must contain unique environment names")
        if any(
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is None
            for value in values
        ):
            raise ValueError("env_refs must contain environment variable names")
        return values


class McpServerResponse(_ApiModel):
    server_id: str
    name: str
    transport: str
    enabled: bool
    command: str | None = None
    args: list[str] = []
    url: str | None = None
    credential_ref: str | None = None
    env_refs: list[str] = []
    allow: list[str] = []
    deny: list[str] = []
    declared_tools: list[McpToolManifestResponse] = []


class ToolResponse(_ApiModel):
    tool_id: str
    public_name: str
    source: str
    risk: str
    exposed: bool
    unavailable_reason: str | None = None


class CatalogResponse(_ApiModel):
    snapshot_id: str
    catalog_revision: int
    sandbox_state: str
    policy_version: str
    tools: list[ToolResponse]


class SkillResponse(_ApiModel):
    skill_id: str
    name: str
    version: str
    description: str
    enabled: bool
    compatible: bool


class SkillPatchRequest(_ApiModel):
    enabled: bool


class OperationResponse(_ApiModel):
    operation_id: str
    run_id: str
    tool_id: str
    tool_call_id: str
    status: str
    risk: str
    approval_id: str | None = None
    error_code: str | None = None
    result_summary: str | None = None
    source: str
    server_id: str | None = None
    arguments_summary: str | None = None
    risk_reason: str | None = None
    timing_ms: int | None = None
    artifacts: list[str] = []
    events: list[dict[str, object]] = []


class ApprovalDecisionRequest(_ApiModel):
    approved: bool
    rejected_reason: str | None = None


class ApprovalResponse(_ApiModel):
    approval_id: str
    run_id: str
    tool_id: str
    tool_call_id: str
    risk: str
    reason: str
    status: str
    expires_at: str


class McpToolManifestResponse(_ApiModel):
    name: str
    description: str
    input_schema: dict[str, object] = {}
    read_only_hint: bool = False
    destructive_hint: bool = False


class McpDiscoverResponse(_ApiModel):
    server_id: str
    tools: list[McpToolManifestResponse]


class SkillHubCandidateResponse(_ApiModel):
    skill_id: str
    name: str
    source: str
    repo_full_name: str
    description: str
    topics: list[str]
    stars: int
    source_url: str
    updated_at: str | None = None


class SkillHubSearchResponse(_ApiModel):
    featured: list[SkillHubCandidateResponse]
    items: list[SkillHubCandidateResponse]
    degraded: bool
    reason: str | None = None
    stale: bool = False


class SkillHubDetailResponse(_ApiModel):
    skill_id: str
    repo_full_name: str
    name: str
    version: str
    description: str
    digest_sha256: str
    size_bytes: int
    preview: str


class SkillInstallRequest(_ApiModel):
    skill_id: str


class SkillInstallResponse(_ApiModel):
    skill_id: str
    name: str
    version: str
    source_url: str


def register_control_routes(
    app: FastAPI,
    ownership: OwnershipService,
    tool_control: ToolControlContext,
    mcp_store: McpConfigStore,
    mcp_manager: McpClientManager,
    skill_hub: SkillHubService,
    runtime: AgentRuntime,
) -> None:
    @app.get("/api/tools/catalog", response_model=CatalogResponse)
    def tool_catalog(request: Request) -> CatalogResponse:
        current_actor(request, ownership)
        snapshot = tool_control.snapshot()
        return CatalogResponse(
            snapshot_id=snapshot.snapshot_id,
            catalog_revision=snapshot.catalog_revision,
            sandbox_state=snapshot.sandbox_state,
            policy_version=snapshot.policy_version,
            tools=[
                ToolResponse(
                    tool_id=item.tool_id,
                    public_name=item.public_name,
                    source=item.source,
                    risk=item.risk,
                    exposed=item.exposed,
                    unavailable_reason=item.unavailable_reason,
                )
                for item in snapshot.tools
            ],
        )

    @app.get("/api/mcp/servers", response_model=list[McpServerResponse])
    def list_mcp_servers(request: Request) -> list[McpServerResponse]:
        current_actor(request, ownership)
        return [_server_response(item) for item in mcp_store.load()]

    @app.post("/api/mcp/servers", response_model=McpServerResponse, status_code=201)
    def upsert_mcp_server(
        payload: McpServerRequest, request: Request
    ) -> McpServerResponse:
        current_actor(request, ownership)
        server = _to_server_config(payload)
        try:
            _validate_server_config(server)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        servers = mcp_store.upsert(server)
        mcp_manager.invalidate(server.server_id)
        _refresh_mcp_tools(tool_control, mcp_store, mcp_manager, servers)
        return _server_response(server)

    @app.patch(
        "/api/mcp/servers/{server_id}", response_model=McpServerResponse
    )
    def patch_mcp_server(
        server_id: str, payload: McpServerRequest, request: Request
    ) -> McpServerResponse:
        current_actor(request, ownership)
        if payload.server_id != server_id:
            raise ValueError("server_id mismatch")
        server = _to_server_config(payload)
        try:
            _validate_server_config(server)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        servers = mcp_store.upsert(server)
        mcp_manager.invalidate(server.server_id)
        _refresh_mcp_tools(tool_control, mcp_store, mcp_manager, servers)
        return _server_response(server)

    @app.delete("/api/mcp/servers/{server_id}", status_code=204)
    def delete_mcp_server(server_id: str, request: Request) -> None:
        current_actor(request, ownership)
        mcp_manager.invalidate(server_id)
        servers = mcp_store.remove(server_id)
        _refresh_mcp_tools(tool_control, mcp_store, mcp_manager, servers)

    @app.get(
        "/api/mcp/servers/{server_id}/discover",
        response_model=McpDiscoverResponse,
    )
    async def discover_mcp_server(
        server_id: str, request: Request
    ) -> McpDiscoverResponse:
        current_actor(request, ownership)
        servers = {item.server_id: item for item in mcp_store.load()}
        server = servers.get(server_id)
        if server is None:
            raise ValueError("server not found")
        try:
            manifests = await mcp_manager.discover(server, force=True)
        except McpConnectionError as exc:
            _refresh_mcp_tools(
                tool_control, mcp_store, mcp_manager, tuple(servers.values())
            )
            raise McpConnectionError(exc.args[0]) from exc
        updated = McpServerConfig(
            server_id=server.server_id,
            name=server.name,
            transport=server.transport,
            enabled=server.enabled,
            tools=server.tools,
            command=server.command,
            args=server.args,
            url=server.url,
            credential_ref=server.credential_ref,
            env_refs=server.env_refs,
            declared_tools=manifests,
        )
        servers = mcp_store.upsert(updated)
        _refresh_mcp_tools(tool_control, mcp_store, mcp_manager, servers)
        return McpDiscoverResponse(
            server_id=server.server_id,
            tools=[
                McpToolManifestResponse(
                    name=item.name,
                    description=item.description,
                    input_schema=item.input_schema,
                    read_only_hint=item.read_only_hint,
                    destructive_hint=item.destructive_hint,
                )
                for item in manifests
            ],
        )

    @app.get("/api/skills", response_model=list[SkillResponse])
    def list_skills(request: Request) -> list[SkillResponse]:
        current_actor(request, ownership)
        return [
            SkillResponse(
                skill_id=item.skill_id,
                name=item.manifest.name,
                version=item.manifest.version,
                description=item.manifest.description,
                enabled=item.enabled,
                compatible="venagent" in item.manifest.compatible_runtimes,
            )
            for item in tool_control.skills.list()
        ]

    @app.patch("/api/skills/{skill_id}", response_model=SkillResponse)
    def patch_skill(
        skill_id: str, payload: SkillPatchRequest, request: Request
    ) -> SkillResponse:
        current_actor(request, ownership)
        item = tool_control.skills.set_enabled(skill_id, payload.enabled)
        return SkillResponse(
            skill_id=item.skill_id,
            name=item.manifest.name,
            version=item.manifest.version,
            description=item.manifest.description,
            enabled=item.enabled,
            compatible="venagent" in item.manifest.compatible_runtimes,
        )

    @app.delete("/api/skills/{skill_id}", status_code=204)
    def uninstall_skill(skill_id: str, request: Request) -> Response:
        current_actor(request, ownership)
        if not tool_control.skills.uninstall(skill_id):
            raise HTTPException(status_code=404, detail="skill_not_installed")
        return Response(status_code=204)

    @app.get("/api/skills/hub", response_model=SkillHubSearchResponse)
    async def skill_hub_search(
        request: Request, query: str = Query(default="")
    ) -> SkillHubSearchResponse:
        current_actor(request, ownership)
        candidates = await skill_hub.search(query)
        return SkillHubSearchResponse(
            featured=[_skill_hub_candidate(item) for item in skill_hub.featured()],
            items=[_skill_hub_candidate(item) for item in candidates],
            degraded=skill_hub.degraded_reason is not None,
            reason=skill_hub.degraded_reason,
            stale=skill_hub.stale,
        )

    @app.get(
        "/api/skills/hub/detail",
        response_model=SkillHubDetailResponse,
    )
    async def skill_hub_detail(
        request: Request, skill_id: str = Query()
    ) -> SkillHubDetailResponse:
        current_actor(request, ownership)
        try:
            detail = await skill_hub.detail(skill_id)
        except SkillHubUnavailable:
            raise
        return SkillHubDetailResponse(
            skill_id=detail.candidate.skill_id,
            repo_full_name=detail.candidate.repo_full_name,
            name=detail.manifest.name,
            version=detail.manifest.version,
            description=detail.manifest.description,
            digest_sha256=detail.manifest.digest_sha256,
            size_bytes=detail.manifest.size_bytes,
            preview=detail.preview,
        )

    @app.post(
        "/api/skills/hub/install",
        response_model=SkillInstallResponse,
        status_code=201,
    )
    async def skill_hub_install(
        payload: SkillInstallRequest, request: Request
    ) -> SkillInstallResponse:
        current_actor(request, ownership)
        try:
            item = await skill_hub.install(payload.skill_id, tool_control.skills)
        except SkillHubUnavailable:
            raise
        return SkillInstallResponse(
            skill_id=item.skill_id,
            name=item.manifest.name,
            version=item.manifest.version,
            source_url=item.manifest.source_url,
        )

    @app.get("/api/operations", response_model=list[OperationResponse])
    def list_operations(
        request: Request,
        run_id: str | None = Query(default=None),
    ) -> list[OperationResponse]:
        actor = current_actor(request, ownership)
        return [
            _operation_response(
                item, tool_control.operations.events_for(item.operation_id)
            )
            for item in tool_control.operations.list_by_owner(
                actor.owner_id, run_id=run_id
            )
        ]

    @app.get("/api/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str, request: Request) -> Response:
        actor = current_actor(request, ownership)
        operation = next(
            (
                item
                for item in tool_control.operations.list_by_owner(actor.owner_id)
                if any(ref.artifact_id == artifact_id for ref in item.artifacts)
            ),
            None,
        )
        if operation is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        artifact = next(
            ref for ref in operation.artifacts if ref.artifact_id == artifact_id
        )
        content = tool_control.gateway.load_artifact(artifact_id)
        if content is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return Response(
            content,
            media_type=artifact.content_type,
            headers={"Content-Disposition": f'inline; filename="{artifact_id}.txt"'},
        )

    @app.post(
        "/api/approvals/{approval_id}/decide",
        response_model=ApprovalResponse,
    )
    async def decide_approval(
        approval_id: str,
        payload: ApprovalDecisionRequest,
        request: Request,
    ) -> ApprovalResponse:
        actor = current_actor(request, ownership)
        try:
            item, run, changed, conflict = runtime.decide_approval(
                actor.owner_id,
                approval_id,
                payload.approved,
                rejected_reason=payload.rejected_reason,
            )
        except ApprovalExpired:
            raise
        if item.status == "cancelled" or (changed and run is not None and run.terminal):
            raise HTTPException(status_code=409, detail="run_terminal")
        if conflict:
            raise HTTPException(status_code=409, detail="approval_already_decided")
        if changed:
            await runtime.hub.publish(
                item.run_id,
                "approval.event",
                approval_id=item.approval_id,
                status=item.status,
                tool_id=item.tool_id,
                tool_call_id=item.tool_call_id,
            )
        return _approval_response(item)


def _to_server_config(payload: McpServerRequest) -> McpServerConfig:
    return McpServerConfig(
        server_id=payload.server_id,
        name=payload.name or payload.server_id,
        transport=payload.transport,  # type: ignore[arg-type]
        enabled=payload.enabled,
        command=payload.command,
        args=tuple(payload.args),
        url=payload.url,
        credential_ref=payload.credential_ref,
        env_refs=tuple(payload.env_refs),
        tools=McpToolPolicy(
            allow=tuple(payload.allow),
            deny=tuple(payload.deny),
        ),
        declared_tools=tuple(
            McpToolManifest(
                name=item.name,
                description=item.description,
                input_schema=item.input_schema,
                read_only_hint=item.read_only_hint,
                destructive_hint=item.destructive_hint,
            )
            for item in payload.declared_tools
        ),
    )


def _validate_server_config(server: McpServerConfig) -> None:
    if server.transport == "stdio" and not server.command:
        raise ValueError("stdio transport requires command")
    if server.transport == "stdio" and server.command:
        try:
            resolve_trusted_stdio_executable(server.command)
        except McpConnectionError as exc:
            raise ValueError(str(exc)) from exc
        if any("\x00" in item or len(item) > 4096 for item in server.args):
            raise ValueError("stdio argument is invalid")
    if server.transport == "streamable_http" and not server.url:
        raise ValueError("streamable_http transport requires url")
    if server.transport == "streamable_http" and server.url:
        parsed = urlparse(server.url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username:
            raise ValueError("streamable_http URL must use HTTPS without credentials")
        hostname = parsed.hostname.casefold()
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise ValueError("streamable_http URL cannot target localhost")


def _refresh_mcp_tools(
    tool_control: ToolControlContext,
    store: McpConfigStore,
    manager: McpClientManager,
    servers: tuple[McpServerConfig, ...],
) -> None:
    """配置变化后重建 MCP 来源，并保留 Native Tool。"""
    tool_control.refresh_servers(servers, ready_servers=manager.ready_servers())
    catalog = McpToolCatalog(servers)
    tool_control.catalog.remove_by_source("mcp")
    catalog.register_all(tool_control.catalog)
    tool_control.mark_catalog_refreshed()


def _skill_hub_candidate(item: SkillHubCandidate) -> SkillHubCandidateResponse:
    return SkillHubCandidateResponse(
        skill_id=item.skill_id,
        name=item.name,
        source=item.source,
        repo_full_name=item.repo_full_name,
        description=item.description,
        topics=list(item.topics),
        stars=item.stars,
        source_url=item.source_url,
        updated_at=item.updated_at,
    )


def _server_response(item: McpServerConfig) -> McpServerResponse:
    return McpServerResponse(
        server_id=item.server_id,
        name=item.name,
        transport=item.transport,
        enabled=item.enabled,
        command=item.command,
        args=list(item.args),
        url=item.url,
        credential_ref=item.credential_ref,
        env_refs=list(item.env_refs),
        allow=list(item.tools.allow),
        deny=list(item.tools.deny),
        declared_tools=[
            McpToolManifestResponse(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
                read_only_hint=tool.read_only_hint,
                destructive_hint=tool.destructive_hint,
            )
            for tool in item.declared_tools
        ],
    )


def _operation_response(
    item: Operation, events: tuple[dict[str, object], ...] = ()
) -> OperationResponse:
    return OperationResponse(
        operation_id=item.operation_id,
        run_id=item.run_id,
        tool_id=item.tool_id,
        tool_call_id=item.tool_call_id,
        status=item.status,
        risk=item.risk,
        approval_id=item.approval_id,
        error_code=item.error_code,
        result_summary=item.result_summary,
        source=item.source,
        server_id=item.server_id,
        arguments_summary=item.arguments_summary,
        risk_reason=item.risk_reason,
        timing_ms=item.timing_ms,
        artifacts=[artifact.artifact_id for artifact in item.artifacts],
        events=list(events),
    )


def _approval_response(item: ApprovalItem) -> ApprovalResponse:
    return ApprovalResponse(
        approval_id=item.approval_id,
        run_id=item.run_id,
        tool_id=item.tool_id,
        tool_call_id=item.tool_call_id,
        risk=item.risk,
        reason=item.reason,
        status=item.status,
        expires_at=item.expires_at.isoformat(),
    )
