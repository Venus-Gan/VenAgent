"""MCP stdio/HTTP 客户端、发现缓存与 HTTP 目录更新契约测试。

装配工厂（tool_control / MCP app / 假 MCP server）在 tests/mcp/conftest.py 就近暴露。
保留契约：假 MCP server 随被测模块就近；catalog_revision 缓存失效单调递增；
Windows 平台 skipif 按原逻辑保留；HTTP 层为发现与目录更新契约的权威断言层。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from venagent.mcp.client import (
    McpClientManager,
    McpConnectionError,
    McpHttpClient,
    McpStdioClient,
)
from venagent.mcp.config import McpServerConfig
from venagent.tools.errors import ToolSchemaInvalid
from venagent.tools.schema import schema_supported, validate_arguments

ORIGIN = {"Origin": "http://localhost:5173"}


def _fake_client(server_path: Path) -> McpStdioClient:
    return McpStdioClient(sys.executable, ("-u", str(server_path)))


def test_stdio_client_discovers_and_calls_fake_server(fake_mcp_server: Path) -> None:
    async def scenario() -> None:
        client = _fake_client(fake_mcp_server)
        await client.start()
        tools = await client.list_tools()
        assert tools[0].name == "read"
        assert tools[0].input_schema["required"] == ["paths"]
        result = await client.call_tool("read", {"paths": ["a.py"]})
        assert result["content"][0]["text"] == "ok"
        await client.stop()

    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows event loop regression")
def test_stdio_client_works_from_windows_selector_event_loop(
    fake_mcp_server: Path,
) -> None:
    async def scenario() -> None:
        client = _fake_client(fake_mcp_server)
        try:
            await client.start()
            tools = await client.list_tools()
            assert tools[0].name == "read"
            result = await client.call_tool("read", {"paths": ["selector.py"]})
            assert result["content"][0]["text"] == "ok"
        finally:
            await client.stop()

    loop = asyncio.SelectorEventLoop()
    try:
        loop.run_until_complete(scenario())
    finally:
        loop.close()


def test_fastctx_json_schema_is_supported_and_validated() -> None:
    schema = {
        "$defs": {
            "Entry": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {
                        "type": ["integer", "null"],
                        "format": "uint",
                        "minimum": 1,
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            }
        },
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "files": {
                "type": ["array", "null"],
                "items": {"$ref": "#/$defs/Entry"},
            },
            "mode": {
                "oneOf": [
                    {"const": "text"},
                    {"const": "image"},
                ]
            },
        },
        "required": ["files"],
        "additionalProperties": False,
    }

    assert schema_supported(schema)
    validate_arguments(
        schema,
        {"files": [{"path": "README.md", "limit": None}], "mode": "text"},
    )
    with pytest.raises(ToolSchemaInvalid):
        validate_arguments(schema, {"files": [{"limit": 2}]})
    assert not schema_supported({"$ref": "https://example.invalid/tool.json"})
    assert not schema_supported(
        {"$dynamicRef": "https://example.invalid/tool.json#entry"}
    )


def test_stdio_client_uses_clean_environment_and_dedicated_cwd(
    monkeypatch: pytest.MonkeyPatch,
    fake_mcp_server: Path,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://must-not-leak")
    client = McpStdioClient(
        sys.executable,
        ("-u", str(fake_mcp_server)),
        env={"FAKE_MCP_TOKEN": "secret-value"},
    )

    async def scenario() -> None:
        await client.start()
        tools = await client.list_tools()
        assert tools[0].description == "secret-value|no-database-url"
        working_directory = client.working_directory
        assert working_directory is not None
        assert Path(working_directory).is_dir()
        await client.stop()
        assert not Path(working_directory).exists()

    asyncio.run(scenario())
    assert "secret-value" not in fake_mcp_server.read_text(encoding="utf-8")


def test_client_manager_requires_declared_environment_refs(
    monkeypatch: pytest.MonkeyPatch,
    fake_mcp_server: Path,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://must-not-leak")
    monkeypatch.setenv("FAKE_MCP_TOKEN", "manager-secret")
    manager = McpClientManager()
    server = McpServerConfig(
        server_id="fake-env",
        name="Fake env",
        transport="stdio",
        enabled=True,
        command=sys.executable,
        args=("-u", str(fake_mcp_server)),
        credential_ref="FAKE_MCP_TOKEN",
    )

    async def scenario() -> None:
        tools = await manager.discover(server)
        assert tools[0].description == "manager-secret|no-database-url"
        missing = McpServerConfig(
            server_id="fake-missing",
            name="Fake missing",
            transport="stdio",
            enabled=True,
            command=sys.executable,
            args=("-u", str(fake_mcp_server)),
            env_refs=("MISSING_MCP_ENV",),
        )
        with pytest.raises(McpConnectionError, match="mcp_environment_ref_missing"):
            await manager.discover(missing)

    asyncio.run(scenario())


def test_client_manager_caches_and_invalidates_discovery(
    fake_mcp_server: Path,
) -> None:
    calls = 0

    def factory(_server: McpServerConfig) -> McpStdioClient:
        nonlocal calls
        calls += 1
        return _fake_client(fake_mcp_server)

    async def scenario() -> None:
        manager = McpClientManager(client_factory=factory)
        server = McpServerConfig(
            server_id="fake",
            name="Fake",
            transport="stdio",
            enabled=True,
            command=sys.executable,
            args=("-u", str(fake_mcp_server)),
        )
        first = await manager.discover(server)
        second = await manager.discover(server)
        assert first == second
        assert calls == 1
        manager.invalidate("fake")
        await manager.discover(server)
        assert calls == 2

    asyncio.run(scenario())


def test_client_manager_force_discovery_bypasses_cache(
    fake_mcp_server: Path,
) -> None:
    calls = 0

    def factory(_server: McpServerConfig) -> McpStdioClient:
        nonlocal calls
        calls += 1
        return _fake_client(fake_mcp_server)

    async def scenario() -> None:
        manager = McpClientManager(client_factory=factory)
        server = McpServerConfig(
            server_id="fake",
            name="Fake",
            transport="stdio",
            enabled=True,
            command=sys.executable,
            args=("-u", str(fake_mcp_server)),
        )

        await manager.discover(server)
        await manager.discover(server, force=True)

        assert calls == 2

    asyncio.run(scenario())


def _http_poster():
    async def poster(
        _url: str,
        payload: dict[str, object],
        _headers: dict[str, str],
    ) -> tuple[int, dict[str, str], bytes]:
        method = payload.get("method")
        request_id = payload.get("id")
        if method == "initialize":
            return (
                200,
                {"mcp-session-id": "session-1"},
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "http-fake", "version": "1"},
                        },
                    }
                ).encode("utf-8"),
            )
        if method == "notifications/initialized":
            return 202, {}, b""
        if method == "tools/list":
            return (
                200,
                {},
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "tools": [
                                {
                                    "name": "read",
                                    "description": "Read",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {},
                                    },
                                }
                            ]
                        },
                    }
                ).encode("utf-8"),
            )
        if method == "tools/call":
            return (
                200,
                {},
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [{"type": "text", "text": "ok"}]
                        },
                    }
                ).encode("utf-8"),
            )
        raise AssertionError(method)

    return poster


def test_http_client_discovers_and_calls_streamable_endpoint() -> None:
    client = McpHttpClient("http://fake.invalid/mcp", poster=_http_poster())

    async def scenario() -> None:
        await client.start()
        tools = await client.list_tools()
        assert tools[0].name == "read"
        result = await client.call_tool("read", {"paths": []})
        assert result["content"][0]["text"] == "ok"
        await client.stop()

    asyncio.run(scenario())


def test_http_discover_spawns_stdio_server_and_updates_catalog(
    tmp_path: Path,
    mcp_app_factory,
    fake_mcp_server: Path,
) -> None:
    app = mcp_app_factory(tmp_path / "servers.json")
    payload = {
        "server_id": "fake",
        "name": "Fake",
        "transport": "stdio",
        "enabled": True,
        "command": sys.executable,
        "args": ["-u", str(fake_mcp_server)],
        "allow": [],
        "deny": [],
        "declared_tools": [],
    }

    with TestClient(app) as client:
        identity = client.post("/api/auth/guest", headers=ORIGIN).json()
        headers = {"Authorization": f"Bearer {identity['access_token']}"}
        created = client.post("/api/mcp/servers", headers=headers, json=payload)
        assert created.status_code == 201
        discovered = client.get(
            "/api/mcp/servers/fake/discover", headers=headers
        )
        assert discovered.status_code == 200
        assert discovered.json()["tools"][0]["name"] == "read"
        catalog = client.get("/api/tools/catalog", headers=headers)
        assert any(
            item["tool_id"] == "read" for item in catalog.json()["tools"]
        )


def test_server_update_invalidates_ready_state_and_discover_forces_refresh(
    tmp_path: Path,
    mcp_app_factory,
    fake_mcp_server: Path,
) -> None:
    calls = 0

    def factory(_server: McpServerConfig) -> McpStdioClient:
        nonlocal calls
        calls += 1
        return _fake_client(fake_mcp_server)

    app = mcp_app_factory(tmp_path / "servers.json", client_factory=factory)
    payload = {
        "server_id": "fake",
        "name": "Fake",
        "transport": "stdio",
        "enabled": True,
        "command": sys.executable,
        "args": ["-u", str(fake_mcp_server)],
        "allow": ["read"],
        "deny": [],
        "declared_tools": [],
    }

    with TestClient(app) as client:
        identity = client.post("/api/auth/guest", headers=ORIGIN).json()
        headers = {"Authorization": f"Bearer {identity['access_token']}"}
        client.post("/api/mcp/servers", headers=headers, json=payload)
        first = client.get("/api/mcp/servers/fake/discover", headers=headers)
        assert first.status_code == 200
        ready_catalog = client.get("/api/tools/catalog", headers=headers).json()
        ready_revision = ready_catalog["catalog_revision"]
        assert next(
            item for item in ready_catalog["tools"] if item["tool_id"] == "read"
        )["exposed"] is True

        updated = {**payload, "name": "Updated", "declared_tools": first.json()["tools"]}
        response = client.patch(
            "/api/mcp/servers/fake", headers=headers, json=updated
        )
        assert response.status_code == 200
        stale_catalog = client.get("/api/tools/catalog", headers=headers).json()
        assert stale_catalog["catalog_revision"] > ready_revision
        stale_tool = next(
            item for item in stale_catalog["tools"] if item["tool_id"] == "read"
        )
        assert stale_tool["exposed"] is False
        assert stale_tool["unavailable_reason"] == "mcp_server_unavailable"

        refreshed = client.get(
            "/api/mcp/servers/fake/discover", headers=headers
        )
        assert refreshed.status_code == 200
        assert calls == 2
        current_catalog = client.get("/api/tools/catalog", headers=headers).json()
        assert current_catalog["catalog_revision"] > stale_catalog["catalog_revision"]
        assert next(
            item for item in current_catalog["tools"] if item["tool_id"] == "read"
        )["exposed"] is True