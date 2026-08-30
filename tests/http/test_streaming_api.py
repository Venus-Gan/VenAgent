from __future__ import annotations

import asyncio
import threading
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

ORIGIN = {"Origin": "http://localhost:5173"}


class StreamingModel:
    async def astream(self, _messages):
        for part in ("逐", "步", "完成"):
            await asyncio.sleep(0.01)
            yield AIMessageChunk(content=part)


class ReasoningModel:
    async def astream(self, _messages):
        yield AIMessageChunk(
            content="结论",
            additional_kwargs={"reasoning_content": "显式分析"},
        )


class FailingModel:
    async def astream(self, _messages):
        if False:
            yield AIMessageChunk(content="")
        raise RuntimeError("provider secret response")


class SlowModel:
    async def astream(self, _messages):
        for _ in range(100):
            await asyncio.sleep(0.02)
            yield AIMessageChunk(content="慢")


class BlockingFirstTokenModel:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.cancelled = threading.Event()

    async def astream(self, _messages):
        self.started.set()
        try:
            await asyncio.sleep(60)
            yield AIMessageChunk(content="不应到达")
        finally:
            self.cancelled.set()


class LastTokenRaceModel:
    def __init__(self) -> None:
        self.after_last_token = threading.Event()
        self.cancelled = threading.Event()

    async def astream(self, _messages):
        try:
            yield AIMessageChunk(content="末")
            self.after_last_token.set()
            await asyncio.sleep(60)
        finally:
            self.cancelled.set()


def _setup(client: TestClient) -> tuple[dict[str, str], str]:
    identity = client.post("/api/auth/guest", headers=ORIGIN).json()
    headers = {"Authorization": f"Bearer {identity['access_token']}"}
    conversation = client.post("/api/conversations", headers=headers).json()
    return headers, conversation["conversation_id"]


def test_sse_starts_with_snapshot_and_streams_online_tokens(app_factory) -> None:
    with TestClient(app_factory(StreamingModel())) as client:
        headers, conversation_id = _setup(client)
        created = client.post(
            f"/api/conversations/{conversation_id}/runs",
            headers=headers,
            json={"message": "开始", "client_request_id": str(uuid4())},
        ).json()
        run_id = created["run"]["run_id"]
        response = client.get(f"/api/runs/{run_id}/events", headers=headers)

        assert response.status_code == 200
        assert response.text.index("event: snapshot") < response.text.index(
            "event: token"
        )
        assert '"content":"逐"' in response.text
        assert '"status":"succeeded"' in response.text


def test_reasoning_stream_and_final_message_are_structured_and_replayable(
    app_factory,
) -> None:
    with TestClient(app_factory(ReasoningModel())) as client:
        headers, conversation_id = _setup(client)
        created = client.post(
            f"/api/conversations/{conversation_id}/runs",
            headers=headers,
            json={"message": "分析后回答", "client_request_id": str(uuid4())},
        ).json()
        run_id = created["run"]["run_id"]
        response = client.get(f"/api/runs/{run_id}/events", headers=headers)

        assert "event: assistant_chunk" in response.text
        assert '"block_type":"reasoning"' in response.text
        event_log = client.get(f"/api/runs/{run_id}/event-log", headers=headers)
        assert event_log.status_code == 200
        assert any(
            item["type"] == "assistant.chunk"
            and item["payload"]["chunk"].get("block_type") == "reasoning"
            for item in event_log.json()
        )

        detail = client.get(
            f"/api/conversations/{conversation_id}", headers=headers
        ).json()
        assistant = detail["messages"][-1]
        assert assistant["content"] == "结论"
        assert assistant["blocks"] == [
            {"type": "reasoning", "text": "显式分析"},
            {"type": "text", "text": "结论"},
        ]


def test_runtime_failure_persists_only_sanitized_exception_type(
    app_factory,
) -> None:
    with TestClient(app_factory(FailingModel())) as client:
        headers, conversation_id = _setup(client)
        created = client.post(
            f"/api/conversations/{conversation_id}/runs",
            headers=headers,
            json={"message": "触发失败", "client_request_id": str(uuid4())},
        ).json()
        run_id = created["run"]["run_id"]
        for _ in range(100):
            run = client.get(f"/api/runs/{run_id}", headers=headers).json()
            if run["status"] == "failed":
                break
            time.sleep(0.01)

        assert run["terminal_reason_code"] == "model_error"
        event_log = client.get(f"/api/runs/{run_id}/event-log", headers=headers)
        failed = next(
            item for item in event_log.json() if item["type"] == "run.failed"
        )
        assert failed["payload"] == {"error_type": "RuntimeError"}
        assert "provider secret response" not in event_log.text


def test_explicit_cancel_persists_request_and_converges_terminal(
    app_factory,
) -> None:
    with TestClient(app_factory(SlowModel())) as client:
        headers, conversation_id = _setup(client)
        created = client.post(
            f"/api/conversations/{conversation_id}/runs",
            headers=headers,
            json={"message": "取消我", "client_request_id": str(uuid4())},
        ).json()
        run_id = created["run"]["run_id"]
        time.sleep(0.05)
        cancelled = client.post(f"/api/runs/{run_id}/cancel", headers=headers)
        assert cancelled.status_code == 202

        for _ in range(100):
            run = client.get(f"/api/runs/{run_id}", headers=headers).json()
            if run["status"] == "cancelled":
                break
            time.sleep(0.02)
        assert run["status"] == "cancelled"
        detail = client.get(
            f"/api/conversations/{conversation_id}", headers=headers
        ).json()
        assert [item["role"] for item in detail["messages"]] == ["user"]


def test_cancel_interrupts_model_before_first_token(app_factory) -> None:
    model = BlockingFirstTokenModel()
    with TestClient(app_factory(model)) as client:
        headers, conversation_id = _setup(client)
        created = client.post(
            f"/api/conversations/{conversation_id}/runs",
            headers=headers,
            json={"message": "首 token 前取消", "client_request_id": str(uuid4())},
        ).json()
        run_id = created["run"]["run_id"]
        assert model.started.wait(2)

        started = time.perf_counter()
        cancelled = client.post(f"/api/runs/{run_id}/cancel", headers=headers)
        assert cancelled.status_code == 202
        assert cancelled.json()["status"] == "cancel_requested"
        for _ in range(100):
            run = client.get(f"/api/runs/{run_id}", headers=headers).json()
            if run["status"] == "cancelled":
                break
            time.sleep(0.01)

        assert run["status"] == "cancelled"
        assert time.perf_counter() - started < 1
        assert model.cancelled.wait(1)


def test_cancel_after_last_token_does_not_wait_for_lease_recovery(
    app_factory,
) -> None:
    model = LastTokenRaceModel()
    with TestClient(app_factory(model)) as client:
        headers, conversation_id = _setup(client)
        created = client.post(
            f"/api/conversations/{conversation_id}/runs",
            headers=headers,
            json={"message": "最后 token 竞态", "client_request_id": str(uuid4())},
        ).json()
        run_id = created["run"]["run_id"]
        assert model.after_last_token.wait(2)

        client.post(f"/api/runs/{run_id}/cancel", headers=headers)
        for _ in range(100):
            run = client.get(f"/api/runs/{run_id}", headers=headers).json()
            if run["status"] == "cancelled":
                break
            time.sleep(0.01)

        assert run["status"] == "cancelled"
        assert run["output_message_id"] is None
        assert model.cancelled.wait(1)


def test_cancel_after_success_returns_the_existing_terminal_status(
    app_factory,
) -> None:
    with TestClient(app_factory(StreamingModel())) as client:
        headers, conversation_id = _setup(client)
        created = client.post(
            f"/api/conversations/{conversation_id}/runs",
            headers=headers,
            json={"message": "先完成", "client_request_id": str(uuid4())},
        ).json()
        run_id = created["run"]["run_id"]
        for _ in range(100):
            run = client.get(f"/api/runs/{run_id}", headers=headers).json()
            if run["status"] == "succeeded":
                break
            time.sleep(0.01)

        response = client.post(f"/api/runs/{run_id}/cancel", headers=headers)
        assert response.status_code == 202
        assert response.json()["status"] == "succeeded"
        assert (
            client.get(f"/api/runs/{run_id}", headers=headers).json()["status"]
            == "succeeded"
        )
