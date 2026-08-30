"""M06 ToolControlContext 控制面契约（单点）。

- 上下文投影包含 M06 能力块（exec / Sandbox / Skill）：本文件单点。
- HTTP 控制面（catalog / mcp / operations）owner 作用域：本文件单点。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.interfaces.http.app import create_app
from src.platform.runtime import build_persistence_runtime
from src.promptctx.assembler import ContextProjectionService
from src.promptctx.schema import FOUNDATION_POLICY

ORIGIN = {"Origin": "http://localhost:5173"}


def test_prompt_projection_includes_m06_capability_blocks(tools_harness) -> None:
    control = tools_harness.tool_control(sandbox_ready=True)
    control.available_servers = frozenset({"tavily"})
    blocks = control.collect_blocks()
    projected = ContextProjectionService().project(
        FOUNDATION_POLICY, blocks, input_budget=16_000
    )
    text = "\n".join(projected.system_messages)
    assert "exec_command" in text
    assert "Sandbox 状态" in text
    assert "Skill" in text


def _app(tmp_path: Path, tools_harness):
    from src.mcp.config import McpConfigStore as Store

    store = Store(tmp_path / "servers.json")
    control = tools_harness.tool_control(sandbox_ready=False)
    return create_app(
        persistence_runtime=build_persistence_runtime({}),
        tool_control=control,
        mcp_config_store=store,
    )


def test_http_control_surface_is_owner_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tools_harness,
) -> None:
    monkeypatch.setenv("VENAGENT_MCP_ALLOWED_COMMANDS", "npx")
    with TestClient(_app(tmp_path, tools_harness)) as client:
        identity = client.post("/api/auth/guest", headers=ORIGIN).json()
        headers = {"Authorization": f"Bearer {identity['access_token']}"}

        catalog = client.get("/api/tools/catalog", headers=headers)
        assert catalog.status_code == 200
        assert catalog.json()["sandbox_state"] == "unavailable"
        assert all(
            item["exposed"] is False
            for item in catalog.json()["tools"]
            if item["tool_id"] == "exec_command"
        )

        created = client.post(
            "/api/mcp/servers",
            headers=headers,
            json={
                "server_id": "tavily",
                "name": "Tavily",
                "transport": "stdio",
                "enabled": True,
                "command": "npx",
                "args": ["-y", "tavily-mcp"],
                "credential_ref": "TAVILY_API_KEY",
                "allow": ["tavily_search"],
                "declared_tools": [
                    {
                        "name": "tavily_search",
                        "description": "Search",
                        "input_schema": {"type": "object", "properties": {}},
                    }
                ],
            },
        )
        assert created.status_code == 201
        listed = client.get("/api/mcp/servers", headers=headers)
        assert listed.status_code == 200
        assert listed.json()[0]["server_id"] == "tavily"
        refreshed = client.get("/api/tools/catalog", headers=headers)
        assert any(
            item["tool_id"] == "tavily_search"
            and item["exposed"] is False
            and item["unavailable_reason"] == "mcp_server_unavailable"
            for item in refreshed.json()["tools"]
        )
        operations = client.get("/api/operations", headers=headers)
        assert operations.status_code == 200
        assert operations.json() == []