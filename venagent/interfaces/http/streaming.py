"""AgentRun SSE 观察协议。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from typing import Any

from ...agent.runs import AgentRun
from ...agent.runtime import AgentRuntime

PROTOCOL_VERSION = 2
HEARTBEAT_INTERVAL_SECONDS = 1.0


def encode_event(event: str, run_id: str, data: dict[str, Any]) -> str:
    payload = {"version": PROTOCOL_VERSION, "run_id": run_id, **data}
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {serialized}\n\n"


async def stream_run_events(
    runtime: AgentRuntime,
    load_run: Callable[[], AgentRun],
    serialize_run: Callable[[AgentRun], dict[str, Any]],
) -> AsyncIterator[str]:
    run = load_run()
    yield encode_event("snapshot", run.run_id, {"run": serialize_run(run)})
    if run.terminal:
        return

    iterator = runtime.hub.subscribe(run.run_id).__aiter__()
    pending: asyncio.Task[Any] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(iterator.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=HEARTBEAT_INTERVAL_SECONDS)
            if not done:
                current = load_run()
                if current.terminal:
                    yield encode_event(
                        "snapshot", current.run_id, {"run": serialize_run(current)}
                    )
                    return
                yield ": heartbeat\n\n"
                continue
            try:
                observation = pending.result()
            except StopAsyncIteration:
                current = load_run()
                yield encode_event(
                    "snapshot", current.run_id, {"run": serialize_run(current)}
                )
                return
            finally:
                pending = None
            if observation.event == "token":
                yield encode_event(
                    "token",
                    observation.run_id,
                    {
                        "sequence": observation.sequence,
                        "content": observation.payload["content"],
                    },
                )
                continue
            current = load_run()
            yield encode_event(
                "snapshot", current.run_id, {"run": serialize_run(current)}
            )
            if current.terminal:
                return
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending
        await iterator.aclose()
