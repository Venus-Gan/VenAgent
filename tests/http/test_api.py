from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk

ORIGIN = {"Origin": "http://localhost:5173"}


class FixedModel:
    def invoke(self, _messages):
        return AIMessage(content="固定回答")


class SlowModel:
    async def astream(self, _messages):
        for _ in range(100):
            await asyncio.sleep(0.02)
            yield AIMessageChunk(content="慢")


def _identity(client: TestClient) -> dict:
    response = client.post("/api/auth/guest", headers=ORIGIN)
    assert response.status_code == 200
    return response.json()


def _headers(identity: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {identity['access_token']}"}


def _wait_terminal(client: TestClient, headers: dict[str, str], run_id: str) -> dict:
    for _ in range(100):
        response = client.get(f"/api/runs/{run_id}", headers=headers)
        assert response.status_code == 200
        run = response.json()
        if run["status"] in {"succeeded", "failed", "cancelled", "incompatible"}:
            return run
        time.sleep(0.02)
    raise AssertionError("run did not reach a terminal state")


def test_unhandled_http_error_is_always_a_safe_json_envelope(app_factory) -> None:
    app = app_factory()

    @app.get("/api/test-unhandled")
    def fail() -> None:
        raise RuntimeError("private provider response")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/test-unhandled")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "服务暂时无法完成请求，请稍后重试",
        }
    }
    assert "private provider response" not in response.text


def test_create_run_returns_202_and_worker_publishes_formal_messages(
    app_factory,
) -> None:
    with TestClient(app_factory(FixedModel())) as client:
        identity = _identity(client)
        headers = _headers(identity)
        conversation = client.post("/api/conversations", headers=headers).json()
        request_id = str(uuid4())
        created = client.post(
            f"/api/conversations/{conversation['conversation_id']}/runs",
            headers=headers,
            json={"message": "你好", "client_request_id": request_id},
        )

        assert created.status_code == 202
        replay = client.post(
            f"/api/conversations/{conversation['conversation_id']}/runs",
            headers=headers,
            json={"message": "你好", "client_request_id": request_id},
        )
        assert replay.status_code == 202
        assert replay.json()["run"]["run_id"] == created.json()["run"]["run_id"]

        run = _wait_terminal(client, headers, created.json()["run"]["run_id"])
        detail = client.get(
            f"/api/conversations/{conversation['conversation_id']}", headers=headers
        ).json()

        assert run["status"] == "succeeded"
        assert [item["content"] for item in detail["messages"]] == ["你好", "固定回答"]
        assert len(detail["runs"]) == 1


def test_conversation_and_run_are_owner_scoped(app_factory) -> None:
    with TestClient(app_factory()) as client:
        alice = _identity(client)
        conversation = client.post("/api/conversations", headers=_headers(alice)).json()
        created = client.post(
            f"/api/conversations/{conversation['conversation_id']}/runs",
            headers=_headers(alice),
            json={"message": "私有", "client_request_id": str(uuid4())},
        ).json()
        client.cookies.clear()
        bob = _identity(client)

        assert (
            client.get(
                f"/api/conversations/{conversation['conversation_id']}",
                headers=_headers(bob),
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"/api/runs/{created['run']['run_id']}", headers=_headers(bob)
            ).status_code
            == 404
        )


def test_old_thread_and_chat_api_are_not_compatible_surfaces(
    app_factory,
) -> None:
    with TestClient(app_factory()) as client:
        identity = _identity(client)
        headers = _headers(identity)
        assert client.post("/api/threads", headers=headers).status_code == 404
        assert (
            client.post(
                "/api/chat",
                headers=headers,
                json={"thread_id": str(uuid4()), "message": "x"},
            ).status_code
            == 404
        )


def test_message_size_is_rejected_before_run_creation(app_factory) -> None:
    with TestClient(app_factory()) as client:
        identity = _identity(client)
        headers = _headers(identity)
        conversation = client.post("/api/conversations", headers=headers).json()
        response = client.post(
            f"/api/conversations/{conversation['conversation_id']}/runs",
            headers=headers,
            json={"message": "界" * 11000, "client_request_id": str(uuid4())},
        )
        assert response.status_code == 422


def test_memory_command_returns_text_without_message_or_run(
    app_factory,
) -> None:
    with TestClient(app_factory()) as client:
        identity = _identity(client)
        headers = _headers(identity)
        conversation = client.post("/api/conversations", headers=headers).json()

        response = client.post(
            f"/api/conversations/{conversation['conversation_id']}/runs",
            headers=headers,
            json={"message": "/memory status", "client_request_id": str(uuid4())},
        )
        detail = client.get(
            f"/api/conversations/{conversation['conversation_id']}", headers=headers
        ).json()

        assert response.status_code == 200
        assert response.json()["kind"] == "memory_command"
        assert response.json()["code"] == "memory_status"
        assert detail["messages"] == []
        assert detail["runs"] == []


def test_explicit_memory_intent_uses_normal_run_for_temporary_identity(
    app_factory,
) -> None:
    with TestClient(app_factory()) as client:
        identity = _identity(client)
        headers = _headers(identity)
        conversation = client.post("/api/conversations", headers=headers).json()

        response = client.post(
            f"/api/conversations/{conversation['conversation_id']}/runs",
            headers=headers,
            json={"message": "记住，我叫小维", "client_request_id": str(uuid4())},
        )
        detail = client.get(
            f"/api/conversations/{conversation['conversation_id']}", headers=headers
        ).json()

        assert response.status_code == 202
        assert "kind" not in response.json()
        assert len(detail["messages"]) >= 1
        assert len(detail["runs"]) == 1


def test_deleting_active_conversation_cancels_before_physical_cleanup(
    app_factory,
) -> None:
    app = app_factory(SlowModel())
    with TestClient(app) as client:
        identity = _identity(client)
        headers = _headers(identity)
        conversation = client.post("/api/conversations", headers=headers).json()
        created = client.post(
            f"/api/conversations/{conversation['conversation_id']}/runs",
            headers=headers,
            json={"message": "删除竞态", "client_request_id": str(uuid4())},
        ).json()
        time.sleep(0.15)

        deleted = client.delete(
            f"/api/conversations/{conversation['conversation_id']}",
            headers=headers,
        )
        assert deleted.status_code == 204
        assert (
            client.get(
                f"/api/conversations/{conversation['conversation_id']}",
                headers=headers,
            ).status_code
            == 404
        )

        # 已删除对话的 run 物理清理完成；worker 仍是活跃调度器，
        # 能接续新任务（公开可观察行为，不再断言内部 _worker_task）。
        for _ in range(100):
            if (
                client.get(
                    f"/api/runs/{created['run']['run_id']}", headers=headers
                ).status_code
                == 404
            ):
                break
            time.sleep(0.02)

        followup = client.post("/api/conversations", headers=headers).json()
        resumed = client.post(
            f"/api/conversations/{followup['conversation_id']}/runs",
            headers=headers,
            json={"message": "存活", "client_request_id": str(uuid4())},
        ).json()
        for _ in range(100):
            resumed_id = resumed["run"]["run_id"]
            state = client.get(f"/api/runs/{resumed_id}", headers=headers).json()
            if state["status"] in {"running", "succeeded"}:
                break
            time.sleep(0.02)
        assert state["status"] in {"running", "succeeded"}
