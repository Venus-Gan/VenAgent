"""Pytest-only network safety guard for VenAgent tests.

The default is fail-closed. Set ``VENAGENT_ALLOW_NETWORK_TESTS=1`` only for
an explicitly approved test run that is intended to reach real services.
"""

import os
import socket
from typing import Any

import requests


NETWORK_BYPASS_ENV = "VENAGENT_ALLOW_NETWORK_TESTS"
_ENABLED_VALUE = "1"
_GUARD_INSTALLED = False
_ORIGINAL_CREATE_CONNECTION = socket.create_connection
_ORIGINAL_SOCKET_CONNECT = socket.socket.connect
_ORIGINAL_SOCKET_CONNECT_EX = socket.socket.connect_ex


def network_tests_allowed() -> bool:
    """Return whether this process explicitly opted out of the network guard."""

    return os.environ.get(NETWORK_BYPASS_ENV) == _ENABLED_VALUE


def block_network_request(*args: Any, **kwargs: Any) -> None:
    """Fail with an actionable message instead of opening a real connection."""

    method = args[0] if args else kwargs.get("method", "UNKNOWN")
    url = args[1] if len(args) > 1 else kwargs.get("url", "<unknown>")
    raise RuntimeError(
        "VenAgent 测试网络熔断已开启，已阻止真实 HTTP 请求: "
        f"{method} {url}。仅在明确批准的真实网络测试中设置 "
        f"{NETWORK_BYPASS_ENV}=1。"
    )


def block_network_socket(*args: Any, **kwargs: Any) -> None:
    """Fail closed for socket-level transports used by SDKs and urllib."""

    address = (
        args[1]
        if len(args) > 1
        else args[0]
        if args
        else kwargs.get("address", "<unknown>")
    )
    if _is_local_address(address):
        if len(args) > 1:
            return _ORIGINAL_SOCKET_CONNECT(*args, **kwargs)
        return _ORIGINAL_CREATE_CONNECTION(*args, **kwargs)
    raise RuntimeError(
        "VenAgent 测试网络熔断已开启，已阻止真实 socket 连接: "
        f"{address}。仅在明确批准的真实网络测试中设置 "
        f"{NETWORK_BYPASS_ENV}=1。"
    )


def block_network_socket_ex(*args: Any, **kwargs: Any) -> int:
    address = args[1] if len(args) > 1 else kwargs.get("address", "<unknown>")
    if _is_local_address(address):
        return _ORIGINAL_SOCKET_CONNECT_EX(*args, **kwargs)
    raise RuntimeError(
        "VenAgent 测试网络熔断已开启，已阻止真实 socket 连接: "
        f"{address}。仅在明确批准的真实网络测试中设置 "
        f"{NETWORK_BYPASS_ENV}=1。"
    )


def _is_local_address(address: object) -> bool:
    if isinstance(address, tuple) and address:
        address = address[0]
    value = str(address).strip().lower()
    return value == "localhost" or value == "::1" or value.startswith("127.")


def install_network_guard() -> bool:
    """Install the requests guard and return whether it was enabled."""

    global _GUARD_INSTALLED
    if network_tests_allowed():
        return False
    if not _GUARD_INSTALLED:
        requests.api.request = block_network_request
        requests.sessions.Session.request = block_network_request
        socket.create_connection = block_network_socket
        socket.socket.connect = block_network_socket
        socket.socket.connect_ex = block_network_socket_ex
        _GUARD_INSTALLED = True
    return True
