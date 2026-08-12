from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from venagent.memory.job_worker import MemoryMaintenanceWorker
from venagent.memory.service import MemoryService
from venagent.ownership.models import Actor, OwnerRecord, SessionRecord
from venagent.repo.temporary import (
    TemporaryOwnershipStore,
    TemporaryPlatformState,
)
from venagent.repo.temporary.memory import TemporaryMemoryStore

NOW = datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)


def test_maintenance_worker_projects_graph_without_agent_run_activity() -> None:
    async def scenario() -> None:
        owner_id = "11111111-1111-1111-1111-111111111111"
        session_id = "22222222-2222-2222-2222-222222222222"
        state = TemporaryPlatformState(
            owners={owner_id: OwnerRecord(owner_id, "user", "active", 1)},
            sessions={
                session_id: SessionRecord(
                    session_id,
                    owner_id,
                    "user",
                    "hash",
                    NOW + timedelta(days=1),
                )
            },
        )
        store = TemporaryMemoryStore(durable=True)
        service = MemoryService(
            store,
            TemporaryOwnershipStore(
                state, account_available=True, mode="durable"
            ),
            cursor_secret="x" * 32,
            clock=lambda: NOW,
        )
        actor = Actor(owner_id, "user", session_id, "alice", "durable")
        auth = service.command_authorization(actor)
        assert service.remember(
            auth,
            "我住在杭州",
            source_ref="message:maintenance",
            source_order=1,
            explicit=False,
        ) is not None
        assert service.status(auth).graph_pending == 1

        worker = MemoryMaintenanceWorker(
            service, poll_interval=0.01, batch_size=4
        )
        worker.start()
        try:
            for _ in range(50):
                if service.status(auth).graph_pending == 0:
                    break
                await asyncio.sleep(0.01)
        finally:
            await worker.stop()

        assert service.status(auth).graph_pending == 0

    asyncio.run(scenario())
