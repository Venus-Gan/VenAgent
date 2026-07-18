import pytest
import requests
import socket

from network_guard import (
    NETWORK_BYPASS_ENV,
    block_network_request,
    network_tests_allowed,
)


def test_network_tests_are_blocked_by_default(monkeypatch):
    monkeypatch.delenv(NETWORK_BYPASS_ENV, raising=False)

    assert network_tests_allowed() is False


def test_network_tests_can_be_explicitly_enabled(monkeypatch):
    monkeypatch.setenv(NETWORK_BYPASS_ENV, "1")

    assert network_tests_allowed() is True


def test_block_message_explains_how_to_opt_out():
    with pytest.raises(RuntimeError, match=NETWORK_BYPASS_ENV):
        block_network_request("POST", "https://example.com")


def test_requests_are_blocked_by_default(monkeypatch):
    if network_tests_allowed():
        pytest.skip("network guard explicitly disabled for this process")
    monkeypatch.delenv(NETWORK_BYPASS_ENV, raising=False)

    with pytest.raises(RuntimeError, match="网络熔断"):
        requests.get("https://example.com", timeout=1)


def test_socket_connections_are_blocked_by_default(monkeypatch):
    if network_tests_allowed():
        pytest.skip("network guard explicitly disabled for this process")
    monkeypatch.delenv(NETWORK_BYPASS_ENV, raising=False)

    with pytest.raises(RuntimeError, match="网络熔断"):
        socket.create_connection(("example.com", 443), timeout=1)
