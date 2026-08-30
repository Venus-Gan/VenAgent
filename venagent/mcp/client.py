"""MCP stdio/HTTP 客户端契约：JSON-RPC over stdio 的 MVP 实现。"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from collections.abc import Awaitable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from ..tools.redaction import redact_text
from .config import McpServerConfig, McpToolManifest

PROTOCOL_VERSION = "2024-11-05"
_STDERR_LIMIT_BYTES = 65_536
logger = logging.getLogger(__name__)


class McpConnectionError(RuntimeError):
    """MCP 连接失败只暴露稳定错误，不泄露进程输出或配置秘密。"""


HttpPoster = Callable[
    [str, dict[str, Any], dict[str, str]],
    Awaitable[tuple[int, dict[str, str], bytes]],
]

_T = TypeVar("_T")


class _WindowsProactorLoopThread:
    """在 Windows 上为 stdio 子进程提供独立的 Proactor event loop。"""

    def __init__(self) -> None:
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._startup_error: Exception | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="venagent-mcp-stdio",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            raise McpConnectionError("mcp_subprocess_loop_unavailable")
        if self._startup_error is not None or self._loop is None:
            raise McpConnectionError("mcp_subprocess_loop_unavailable") from (
                self._startup_error
            )

    async def submit(self, operation: Coroutine[Any, Any, _T]) -> _T:
        loop = self._loop
        if loop is None or loop.is_closed():
            operation.close()
            raise McpConnectionError("mcp_subprocess_loop_unavailable")
        future = asyncio.run_coroutine_threadsafe(operation, loop)
        return await asyncio.wrap_future(future)

    def close(self) -> None:
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        self._thread.join(timeout=5.0)
        if self._thread.is_alive():
            raise McpConnectionError("mcp_subprocess_loop_shutdown_timeout")
        self._loop = None

    def _run(self) -> None:
        try:
            loop_factory = getattr(asyncio, "ProactorEventLoop", None)
            if loop_factory is None:
                raise RuntimeError("ProactorEventLoop is unavailable")
            loop = loop_factory()
            asyncio.set_event_loop(loop)
            self._loop = loop
        except Exception as exc:
            self._startup_error = exc
            self._ready.set()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.run_until_complete(loop.shutdown_asyncgens())
            asyncio.set_event_loop(None)
            loop.close()


@dataclass
class McpStdioClient:
    """一个 Server 一次连接的 stdio JSON-RPC 客户端。"""

    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    server_id: str = "stdio"
    working_directory: str | None = None
    request_timeout: float = 15.0
    client_name: str = "venagent"
    client_version: str = "0.1.0"
    _process: Any | None = None
    _writer: Any | None = None
    _reader: Any | None = None
    _reader_task: asyncio.Task[None] | None = None
    _stderr_task: asyncio.Task[None] | None = None
    _stderr_tail: str = ""
    _owns_working_directory: bool = False
    _pending: dict[int, asyncio.Future[dict[str, Any]]] | None = None
    _next_id: int = 0
    _loop_worker: _WindowsProactorLoopThread | None = field(
        default=None, init=False, repr=False
    )

    async def start(self) -> None:
        if os.name != "nt":
            await self._start_on_current_loop()
            return
        if self._loop_worker is not None:
            return
        worker = _WindowsProactorLoopThread()
        worker.start()
        self._loop_worker = worker
        try:
            await worker.submit(self._start_on_current_loop())
        except BaseException:
            self._loop_worker = None
            worker.close()
            raise

    async def _start_on_current_loop(self) -> None:
        if self._process is not None:
            return
        if self.working_directory is None:
            self.working_directory = tempfile.mkdtemp(prefix="venagent-mcp-")
            self._owns_working_directory = True
        child_env = _minimal_subprocess_env(
            self.env or {}, temp_dir=self.working_directory
        )
        creation_flags = 0
        process_options: dict[str, Any] = {}
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NO_WINDOW | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            process_options["start_new_session"] = True
        try:
            self._process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creation_flags,
                env=child_env,
                cwd=self.working_directory,
                **process_options,
            )
        except (NotImplementedError, OSError) as exc:
            self._cleanup_working_directory()
            raise McpConnectionError("mcp_process_start_failed") from exc
        self._writer = self._process.stdin
        self._reader = self._process.stdout
        self._pending = {}
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        logger.info(
            "MCP stdio started server_id=%s executable=%s arg_count=%d",
            self.server_id,
            self.command,
            len(self.args),
        )
        try:
            capabilities = await self._request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": self.client_name,
                        "version": self.client_version,
                    },
                },
            )
            if not isinstance(capabilities, dict) or "capabilities" not in capabilities:
                raise McpConnectionError("mcp_initialize_invalid")
            await self._notify("notifications/initialized", {})
        except BaseException:
            await self._stop_on_current_loop()
            raise

    async def stop(self) -> None:
        worker = self._loop_worker
        if worker is None:
            await self._stop_on_current_loop()
            return
        self._loop_worker = None
        try:
            await worker.submit(self._stop_on_current_loop())
        finally:
            worker.close()

    async def _stop_on_current_loop(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        process = self._process
        self._process = None
        if process is not None and process.returncode is None:
            await _terminate_process_tree(process)
        if self._stderr_task is not None:
            try:
                await asyncio.wait_for(self._stderr_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                self._stderr_task.cancel()
            self._stderr_task = None
        self._writer = None
        self._reader = None
        self._pending = None
        self._cleanup_working_directory()

    async def list_tools(self) -> tuple[McpToolManifest, ...]:
        worker = self._loop_worker
        if worker is not None:
            return await worker.submit(self._list_tools_on_current_loop())
        return await self._list_tools_on_current_loop()

    async def _list_tools_on_current_loop(self) -> tuple[McpToolManifest, ...]:
        result = await self._request("tools/list", {})
        tools = result.get("tools", ())
        manifests: list[McpToolManifest] = []
        for item in tools:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            manifests.append(
                McpToolManifest(
                    name=str(item["name"]),
                    description=str(item.get("description", "")),
                    input_schema=dict(item.get("inputSchema", {})),
                    read_only_hint=bool(item.get("readOnlyHint", False)),
                    destructive_hint=bool(item.get("destructiveHint", False)),
                )
            )
        return tuple(manifests)

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        worker = self._loop_worker
        if worker is not None:
            return await worker.submit(
                self._call_tool_on_current_loop(name, arguments)
            )
        return await self._call_tool_on_current_loop(name, arguments)

    async def _call_tool_on_current_loop(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        result = await self._request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        if not isinstance(result, dict):
            raise McpConnectionError("mcp_call_invalid")
        return result

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._process is None or self._writer is None or self._pending is None:
            raise McpConnectionError("mcp_not_connected")
        self._next_id += 1
        request_id = self._next_id
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        self._writer.write(
            (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        )
        await self._writer.drain()
        try:
            response = await asyncio.wait_for(
                future, timeout=self.request_timeout
            )
        except asyncio.TimeoutError as exc:
            raise McpConnectionError("mcp_request_timeout") from exc
        if "error" in response:
            error = response["error"]
            raise McpConnectionError(
                f"mcp_error_{error.get('code', 'unknown')}"
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise McpConnectionError("mcp_response_invalid")
        return result

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        if self._writer is None:
            raise McpConnectionError("mcp_not_connected")
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._writer.write(
            (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        )
        await self._writer.drain()

    async def _read_loop(self) -> None:
        try:
            while self._reader is not None:
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict) or "id" not in message:
                    continue
                request_id = message.get("id")
                pending = self._pending or {}
                future = pending.get(request_id)
                if future is not None and not future.done():
                    future.set_result(message)
        except (asyncio.CancelledError, OSError):
            pass
        finally:
            pending = self._pending or {}
            for future in pending.values():
                if not future.done():
                    future.set_exception(
                        McpConnectionError("mcp_server_closed")
                    )

    async def _read_stderr(self) -> None:
        process = self._process
        reader = None if process is None else process.stderr
        if reader is None:
            return
        captured = b""
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                captured = (captured + chunk)[-_STDERR_LIMIT_BYTES:]
        except (asyncio.CancelledError, OSError):
            return
        finally:
            self._stderr_tail = redact_text(
                captured.decode("utf-8", errors="replace")
            )[-_STDERR_LIMIT_BYTES:]
            if self._stderr_tail:
                logger.warning(
                    "MCP stdio wrote stderr server_id=%s bytes=%d",
                    self.server_id,
                    len(self._stderr_tail.encode("utf-8")),
                )

    def _cleanup_working_directory(self) -> None:
        if not self._owns_working_directory or self.working_directory is None:
            return
        shutil.rmtree(self.working_directory, ignore_errors=True)
        self.working_directory = None
        self._owns_working_directory = False


@dataclass
class McpHttpClient:
    """Streamable HTTP transport 的无 session 优先 JSON-RPC 客户端。"""

    url: str
    request_timeout: float = 15.0
    client_name: str = "venagent"
    client_version: str = "0.1.0"
    extra_headers: dict[str, str] | None = None
    poster: HttpPoster | None = None
    _session_id: str | None = None
    _next_id: int = 0

    async def start(self) -> None:
        result = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": self.client_name,
                    "version": self.client_version,
                },
            },
        )
        if not isinstance(result, dict) or "capabilities" not in result:
            raise McpConnectionError("mcp_initialize_invalid")
        await self._notify("notifications/initialized", {})

    async def stop(self) -> None:
        self._session_id = None

    async def list_tools(self) -> tuple[McpToolManifest, ...]:
        result = await self._request("tools/list", {})
        tools = result.get("tools", ())
        manifests: list[McpToolManifest] = []
        for item in tools:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            manifests.append(
                McpToolManifest(
                    name=str(item["name"]),
                    description=str(item.get("description", "")),
                    input_schema=dict(item.get("inputSchema", {})),
                    read_only_hint=bool(item.get("readOnlyHint", False)),
                    destructive_hint=bool(item.get("destructiveHint", False)),
                )
            )
        return tuple(manifests)

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        result = await self._request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        if not isinstance(result, dict):
            raise McpConnectionError("mcp_call_invalid")
        return result

    async def _request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.extra_headers:
            headers.update(self.extra_headers)
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id
        poster = self.poster or _default_http_poster(self.request_timeout)
        status, response_headers, body = await poster(
            self.url, payload, headers
        )
        if status >= 400:
            raise McpConnectionError(f"mcp_http_{status}")
        session_id = (
            response_headers.get("mcp-session-id")
            or response_headers.get("Mcp-Session-Id")
        )
        if session_id:
            self._session_id = session_id
        message = _parse_http_message(body)
        if "error" in message:
            error = message["error"]
            raise McpConnectionError(
                f"mcp_error_{error.get('code', 'unknown')}"
            )
        result = message.get("result")
        if not isinstance(result, dict):
            raise McpConnectionError("mcp_response_invalid")
        return result

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        poster = self.poster or _default_http_poster(self.request_timeout)
        headers = dict(self.extra_headers or {})
        try:
            await poster(self.url, payload, headers)
        except McpConnectionError:
            pass


@dataclass
class McpClientManager:
    """按 Server 缓存工具发现结果，控制 MCP 子进程生命周期。"""

    client_factory: Callable[[McpServerConfig], McpStdioClient] | None = None
    cache_ttl_seconds: float = 30.0
    # D1：声明式凭据与可执行命令白名单来自 config.yaml（mcp.credentials /
    # mcp.allowed_commands）；运行时仍回退进程环境，兼容 CI 注入。
    credentials: dict[str, str] = field(default_factory=dict)
    allowed_commands: tuple[str, ...] | None = None
    _cache: dict[str, tuple[datetime, tuple[McpToolManifest, ...]]] | None = None
    _ready: set[str] | None = None

    def __post_init__(self) -> None:
        self._cache = {}
        self._ready = set()

    async def discover(
        self, server: McpServerConfig, *, force: bool = False
    ) -> tuple[McpToolManifest, ...]:
        if self._cache is None:
            self._cache = {}
        cached = self._cache.get(server.server_id)
        if cached is not None and not force:
            created, manifests = cached
            if (
                datetime.now(timezone.utc) - created
            ).total_seconds() < self.cache_ttl_seconds:
                return manifests
        client = self._build_client(server)
        try:
            await client.start()
            manifests = await client.list_tools()
            if self._ready is not None:
                self._ready.add(server.server_id)
        except McpConnectionError:
            self._cache.pop(server.server_id, None)
            if self._ready is not None:
                self._ready.discard(server.server_id)
            raise
        finally:
            await client.stop()
        self._cache[server.server_id] = (
            datetime.now(timezone.utc),
            manifests,
        )
        return manifests

    async def refresh(
        self, servers: tuple[McpServerConfig, ...], *, force: bool = False
    ) -> dict[str, tuple[McpToolManifest, ...]]:
        discovered: dict[str, tuple[McpToolManifest, ...]] = {}
        for server in servers:
            if not server.enabled:
                continue
            try:
                discovered[server.server_id] = await self.discover(
                    server, force=force
                )
            except McpConnectionError:
                discovered[server.server_id] = ()
        return discovered

    def invalidate(self, server_id: str) -> None:
        if self._cache is not None:
            self._cache.pop(server_id, None)
        if self._ready is not None:
            self._ready.discard(server_id)

    def ready_servers(self) -> frozenset[str]:
        return frozenset(self._ready or ())

    async def call_tool(
        self,
        server: McpServerConfig,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        client = self._build_client(server)
        try:
            await client.start()
            result = await client.call_tool(name, arguments)
            if self._ready is not None:
                self._ready.add(server.server_id)
            return result
        except McpConnectionError:
            if self._ready is not None:
                self._ready.discard(server.server_id)
            raise
        finally:
            await client.stop()

    def _build_client(self, server: McpServerConfig) -> Any:
        if self.client_factory is not None:
            return self.client_factory(server)
        if server.transport == "streamable_http":
            if not server.url:
                raise McpConnectionError("mcp_transport_unsupported")
            headers = None
            if server.credential_ref:
                secret = self._lookup_secret(server.credential_ref)
                if not secret:
                    raise McpConnectionError("mcp_credential_missing")
                headers = {"Authorization": f"Bearer {secret}"}
            return McpHttpClient(server.url, extra_headers=headers)
        if server.transport != "stdio" or not server.command:
            raise McpConnectionError("mcp_transport_unsupported")
        executable = resolve_trusted_stdio_executable(
            server.command, allowed=self.allowed_commands
        )
        requested_names = tuple(
            dict.fromkeys(
                name
                for name in (server.credential_ref, *server.env_refs)
                if name is not None
            )
        )
        missing = [
            name
            for name in requested_names
            if self._lookup_secret(name) is None
        ]
        if missing:
            raise McpConnectionError("mcp_environment_ref_missing")
        env = {
            name: secret
            for name in requested_names
            if (secret := self._lookup_secret(name)) is not None
        }
        return McpStdioClient(
            executable,
            tuple(server.args),
            env=env,
            server_id=server.server_id,
        )

    def _lookup_secret(self, name: str) -> str | None:
        """凭据查找顺序：config.yaml 声明式凭据 → 进程环境。"""
        value = self.credentials.get(name)
        if value is not None and value != "":
            return value
        return os.environ.get(name)


def _minimal_subprocess_env(
    explicit: dict[str, str], *, temp_dir: str
) -> dict[str, str]:
    """只保留平台启动必需项和 Server 显式引用的环境变量。"""
    child: dict[str, str] = {}
    if os.name == "nt":
        for name in ("SystemRoot", "WINDIR"):
            value = os.environ.get(name)
            if value:
                child[name] = value
    else:
        for name in ("LANG", "LC_ALL"):
            value = os.environ.get(name)
            if value:
                child[name] = value
    child.update(explicit)
    child["TMP"] = temp_dir
    child["TEMP"] = temp_dir
    return child


def resolve_trusted_stdio_executable(
    command: str, *, allowed: tuple[str, ...] | None = None
) -> str:
    from pathlib import Path

    candidate = Path(command)
    resolved_raw = (
        str(candidate)
        if candidate.is_absolute()
        else shutil.which(command)
    )
    if not resolved_raw:
        raise McpConnectionError("mcp_executable_not_found")
    resolved = Path(resolved_raw).resolve()
    if not resolved.is_file():
        raise McpConnectionError("mcp_executable_not_found")
    if allowed is not None:
        allowed_names = {item.strip().casefold() for item in allowed if item.strip()}
    else:
        allowed_names = {
            item.strip().casefold()
            for item in os.environ.get(
                "VENAGENT_MCP_ALLOWED_COMMANDS", "node,python,python3"
            ).split(",")
            if item.strip()
        }
    names = {resolved.name.casefold(), resolved.stem.casefold()}
    current_python = Path(sys.executable).resolve()
    if resolved != current_python and names.isdisjoint(allowed_names):
        raise McpConnectionError("mcp_executable_not_allowed")
    return str(resolved)


async def _terminate_process_tree(process: Any) -> None:
    if process.returncode is not None:
        return
    if os.name == "nt":
        def terminate_windows_tree() -> None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5.0,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

        try:
            await asyncio.to_thread(terminate_windows_tree)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
    except (asyncio.TimeoutError, ProcessLookupError):
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
        else:
            process.kill()
        await process.wait()


def _default_http_poster(timeout_seconds: float) -> HttpPoster:
    async def poster(
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> tuple[int, dict[str, str], bytes]:
        return await asyncio.to_thread(
            _urllib_post, url, payload, headers, timeout_seconds
        )

    return poster


def _urllib_post(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float,
) -> tuple[int, dict[str, str], bytes]:
    _validate_public_https_url(url)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(_NoRedirectHandler())
        with opener.open(request, timeout=timeout_seconds) as response:
            body = response.read(1_048_577)
            if len(body) > 1_048_576:
                raise McpConnectionError("mcp_http_response_too_large")
            return response.status, dict(response.headers), body
    except urllib.error.HTTPError as exc:
        raise McpConnectionError(f"mcp_http_{exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise McpConnectionError("mcp_http_unreachable") from exc


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _validate_public_https_url(url: str) -> None:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username:
        raise McpConnectionError("mcp_http_url_invalid")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
    except OSError as exc:
        raise McpConnectionError("mcp_http_unreachable") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise McpConnectionError("mcp_http_private_address")


def _parse_http_message(body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8", errors="replace")
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        for line in text.splitlines():
            if line.startswith("data:"):
                message = json.loads(line[5:].strip())
                break
        else:
            raise McpConnectionError("mcp_http_response_invalid") from None
    if not isinstance(message, dict):
        raise McpConnectionError("mcp_http_response_invalid")
    return message
