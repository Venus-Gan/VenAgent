import json
from types import SimpleNamespace

from internal.agent.cancel import CancelRegistry
from internal.agent.runtime_governance import RuntimeGovernance


class _Cfg:
    llm_model = "chat-model"
    embedding_model = "embed-model"

    def is_real_llm(self):
        return False


class _SnapshotRepo:
    def __init__(self):
        self.saved = []

    def save(self, task_id, state):
        self.saved.append((task_id, state))


def test_runtime_governance_wraps_cancel_snapshot_and_status():
    registry = CancelRegistry()
    snapshot_repo = _SnapshotRepo()
    agent = SimpleNamespace(
        cfg=_Cfg(),
        _cancel_registry=registry,
        inf=SimpleNamespace(
            ready=SimpleNamespace(
                milvus="connected",
                postgresql="connected",
                elasticsearch="disconnected",
                kafka="connected",
            ),
            repo=SimpleNamespace(snapshot=snapshot_repo),
        ),
        rag=SimpleNamespace(
            loaded=True,
            mode=lambda: "hybrid",
            chunks=lambda: [{"id": 1, "content": "x" * 80}],
        ),
        stm=SimpleNamespace(count=lambda: 2),
        ltm=SimpleNamespace(items=[object(), object(), object()]),
        preference=SimpleNamespace(get_all=lambda: {"city": "上海"}),
        get_tools=lambda: [{"name": "a"}, {"name": "b"}],
    )

    governance = RuntimeGovernance(agent)

    token, unregister = governance.register()
    governance.set_task({"task_id": "task-1", "query": "demo", "steps": []})
    governance.append_snapshot({"step": 1})
    snapshots_before = governance.snapshot_list()
    governance.save_snapshot({"task_id": "task-1", "query": "demo"})
    status = governance.status()
    infra = governance.infra_status()
    snapshots_after = governance.snapshot_list()

    governance.cancel()
    unregister()

    assert token.is_cancelled() is True
    assert governance.current_task()["task_id"] == "task-1"
    assert snapshots_before == [{"step": 1}]
    assert snapshots_after == [{"step": 1}, {"task_id": "task-1", "query": "demo"}]
    assert snapshot_repo.saved[0][0] == "task-1"
    assert json.loads(snapshot_repo.saved[0][1])["query"] == "demo"
    assert status["short_term_count"] == 2
    assert status["is_mock"] is True
    assert infra["postgresql"] == "connected"
