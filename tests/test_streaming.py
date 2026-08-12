from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from venagent.agent.observation import RunObservationHub
from venagent.agent.runs import AgentRun
from venagent.interfaces.http.streaming import stream_run_events


def test_observation_hub_does_not_replay_tokens_to_late_subscribers() -> None:
    async def scenario() -> None:
        hub = RunObservationHub()
        await hub.publish("run-a", "token", content="old")
        iterator = hub.subscribe("run-a").__aiter__()
        pending = asyncio.create_task(iterator.__anext__())
        await asyncio.sleep(0)
        await hub.publish("run-a", "token", content="new")
        observation = await asyncio.wait_for(pending, 1)
        await iterator.aclose()
        assert observation.payload["content"] == "new"
        assert observation.sequence == 2

    asyncio.run(scenario())


def test_discarding_a_subscriber_does_not_cancel_runtime_work() -> None:
    async def scenario() -> None:
        hub = RunObservationHub()
        iterator = hub.subscribe("run-a").__aiter__()
        pending = asyncio.create_task(iterator.__anext__())
        await asyncio.sleep(0)
        pending.cancel()
        try:
            await pending
        except asyncio.CancelledError:
            pass
        await iterator.aclose()
        await hub.publish("run-a", "completed")

    asyncio.run(scenario())


def test_heartbeat_timeout_keeps_subscription_open_until_snapshot_is_terminal(
    monkeypatch,
) -> None:
    from venagent.interfaces.http import streaming

    monkeypatch.setattr(streaming, "HEARTBEAT_INTERVAL_SECONDS", 0.01)

    async def scenario() -> None:
        now = datetime.now(timezone.utc)
        queued = AgentRun(
            "run-a",
            "conversation-a",
            "owner-a",
            "message-a",
            "grant-a",
            "queued",
            1,
            now,
            now,
        )
        calls = 0

        def load_run() -> AgentRun:
            nonlocal calls
            calls += 1
            return replace(queued, status="succeeded") if calls >= 3 else queued

        iterator = stream_run_events(
            SimpleNamespace(hub=RunObservationHub()),
            load_run,
            lambda run: {"status": run.status},
        ).__aiter__()
        assert "event: snapshot" in await iterator.__anext__()
        assert await iterator.__anext__() == ": heartbeat\n\n"
        assert '"status":"succeeded"' in await iterator.__anext__()
        with pytest.raises(StopAsyncIteration):
            await iterator.__anext__()

    asyncio.run(scenario())
