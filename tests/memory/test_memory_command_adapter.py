"""memory 命令适配器契约：/memory 子命令经公开 execute 接口的行为结果（原 test_memory_context.py 拆分二）。"""

from __future__ import annotations

from venagent.memory.management import MemoryCommandAdapter


def test_memory_update_command_can_read_its_authorized_target(memory_service) -> None:
    service, store, actor, _state = memory_service()
    adapter = MemoryCommandAdapter(service)
    remembered = service.remember(
        service.command_authorization(actor, action="write"),
        "我叫小维",
        source_ref="message:update-command",
        source_order=1,
        explicit=True,
    )

    assert remembered is not None
    original = store.active_facts(actor.owner_id, "default")[0]

    updated = adapter.execute(actor, f"/memory update {original.memory_id} 我叫阿维")

    assert updated.code == "memory_updated"
    assert store.get_fact(actor.owner_id, original.memory_id).status == "superseded"

def test_memory_command_is_deterministic_and_does_not_create_a_run(memory_service) -> None:
    service, store, actor, _state = memory_service()
    adapter = MemoryCommandAdapter(service)
    auth = service.command_authorization(actor)
    fact = service.remember(
        auth,
        "我住在杭州",
        source_ref="message:location",
        source_order=1,
        explicit=False,
    )
    assert fact is not None

    result = adapter.execute(actor, "/memory list")
    forgotten = adapter.execute(actor, f"/memory forget {fact.memory_id}")

    assert result.code == "memory_list" and fact.memory_id in result.message
    assert forgotten.code == "memory_forgotten"
    assert store.get_fact(actor.owner_id, fact.memory_id).status == "deleted"