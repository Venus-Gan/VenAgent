from __future__ import annotations

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from venagent.interfaces.http.app import create_app
from venagent.platform.runtime import build_persistence_runtime

ORIGIN = {"Origin": "http://localhost:5173"}


class FixedModel:
    def invoke(self, _messages):
        return AIMessage(content="ok")


def _app():
    return create_app(FixedModel(), persistence_runtime=build_persistence_runtime({}))


def test_temporary_guest_refresh_preserves_owner_and_rotates_access_token() -> None:
    with TestClient(_app()) as client:
        first = client.post("/api/auth/guest", headers=ORIGIN)
        refreshed = client.post("/api/auth/refresh", headers=ORIGIN)

        assert first.status_code == refreshed.status_code == 200
        assert first.json()["mode"] == "temporary"
        assert (
            first.json()["actor"]["owner_id"] == refreshed.json()["actor"]["owner_id"]
        )
        assert first.json()["access_token"] != refreshed.json()["access_token"]


def test_private_api_requires_an_access_token() -> None:
    with TestClient(_app()) as client:
        response = client.post("/api/conversations")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "access_token_missing"


def test_state_changing_auth_route_rejects_untrusted_origin() -> None:
    with TestClient(_app()) as client:
        response = client.post(
            "/api/auth/guest", headers={"Origin": "https://evil.example"}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "origin_not_allowed"


def test_account_operations_fail_closed_in_temporary_mode() -> None:
    with TestClient(_app()) as client:
        guest = client.post("/api/auth/guest", headers=ORIGIN).json()
        response = client.post(
            "/api/auth/register",
            headers={
                **ORIGIN,
                "Authorization": f"Bearer {guest['access_token']}",
            },
            json={"username": "alice", "password": "correct-horse"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "account_service_unavailable"
