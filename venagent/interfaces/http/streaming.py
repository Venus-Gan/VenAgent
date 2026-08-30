"""AgentRun SSE 观察协议。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from typing import Any

from ...agent.events import RunEvent
from ...agent.runs import AgentRun
from ...agent.runtime import AgentRuntime

PROTOCOL_VERSION = 3
HEARTBEAT_INTERVAL_SECONDS = 1.0


def encode_event(event: str, run_id: str, data: dict[str, Any]) -> str:
    payload = {"version": PROTOCOL_VERSION, "run_id": run_id, **data}
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {serialized}\n\n"


async def stream_run_events(
    runtime: AgentRuntime,
    load_run: Callable[[], AgentRun],
    serialize_run: Callable[[AgentRun], dict[str, Any]],
    *,
    owner_id: str | None = None,
) -> AsyncIterator[str]:
    run = load_run()
    iterator = runtime.hub.subscribe(run.run_id).__aiter__()
    pending: asyncio.Task[Any] | None = asyncio.create_task(iterator.__anext__())
    try:
        await asyncio.sleep(0)
        history = (
            runtime.run_events(owner_id, run.run_id)
            if owner_id is not None and hasattr(runtime, "run_events")
            else ()
        )
        if owner_id is not None:
            run = load_run()
        last_sequence = 0
        yield encode_event("snapshot", run.run_id, {"run": serialize_run(run)})
        for item in history:
            last_sequence = max(last_sequence, item.sequence)
            for encoded in encode_run_event(item):
                yield encoded
        if run.terminal:
            return

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
            if observation.sequence <= last_sequence:
                continue
            last_sequence = observation.sequence
            for encoded in encode_run_event(observation):
                yield encoded
            if observation.event == "assistant.chunk":
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


def encode_run_event(item: RunEvent) -> tuple[str, ...]:
    common = {
        "sequence": item.sequence,
        "type": item.type,
        "payload": item.payload,
        "created_at": item.created_at.isoformat(),
    }
    encoded = [encode_event("run_event", item.run_id, common)]
    if item.type == "assistant.chunk":
        encoded.append(
            encode_event(
                "assistant_chunk",
                item.run_id,
                {"sequence": item.sequence, **item.payload},
            )
        )
        chunk = item.payload.get("chunk", {})
        if chunk.get("type") == "text_delta":
            encoded.append(
                encode_event(
                    "token",
                    item.run_id,
                    {"sequence": item.sequence, "content": chunk.get("delta", "")},
                )
            )
    elif item.type in {"tool.event", "approval.event"}:
        encoded.append(
            encode_event(item.type.removesuffix(".event"), item.run_id, item.payload)
        )
    return tuple(encoded)
