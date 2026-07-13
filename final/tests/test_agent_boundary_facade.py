from types import SimpleNamespace

from internal.agent.agent import ChatOptions, Response, UnifiedAgent
from internal.agent.status import status as build_status


class _GovernanceStub:
    def __init__(self):
        self.calls = []
        self.task = {
            "task_id": "task-9",
            "query": "hello",
            "status": "running",
            "phase": "prepare",
            "steps": [{"type": "step"}],
            "current_step": 1,
            "interrupted_at": "",
        }

    def register(self):
        self.calls.append("register")

        class _Token:
            def __init__(self):
                self.cancelled = False

            def is_cancelled(self):
                return self.cancelled

            def cancel(self):
                self.cancelled = True

        token = _Token()

        def unregister():
            self.calls.append("unregister")
            token.cancel()

        return token, unregister

    def cancel(self):
        self.calls.append("cancel")

    def save_snapshot(self, task):
        self.calls.append(("save_snapshot", dict(task)))

    def snapshot_list(self):
        self.calls.append("snapshot_list")
        return [{"task_id": "task-1"}]

    def status(self):
        self.calls.append("status")
        return {"status": "governed"}

    def infra_status(self):
        self.calls.append("infra_status")
        return {"postgresql": "connected"}

    def current_task(self):
        self.calls.append("current_task")
        return dict(self.task)

    def set_task(self, task):
        self.calls.append(("set_task", dict(task) if isinstance(task, dict) else task))

    def append_snapshot(self, snapshot):
        self.calls.append(("append_snapshot", dict(snapshot)))


def test_unified_agent_uses_runtime_governance_for_control_surface():
    agent = object.__new__(UnifiedAgent)
    governance = _GovernanceStub()
    agent.governance = governance
    agent._dispatch = lambda query, opts, token: Response(query=query, mode="chat", answer="ok")

    resp = agent.process_with_options("hello", ChatOptions())
    agent.cancel()
    assert agent.snapshot_list() == [{"task_id": "task-1"}]
    assert agent.status() == {"status": "governed"}
    assert agent.infra_status() == {"postgresql": "connected"}
    snapshot = agent._planner_snapshot()
    agent.save_snapshot({"task_id": "task-2", "foo": "bar"})

    assert resp.answer == "ok"
    assert governance.calls[0] == "register"
    assert "unregister" in governance.calls
    assert "cancel" in governance.calls
    assert "snapshot_list" in governance.calls
    assert "status" in governance.calls
    assert "infra_status" in governance.calls
    assert "current_task" in governance.calls
    assert snapshot.task_id == "task-9"
    assert ("save_snapshot", {"task_id": "task-2", "foo": "bar"}) in governance.calls


def test_handler_status_contract_stays_stable():
    agent = SimpleNamespace(
        cfg=SimpleNamespace(llm_model="chat-model", embedding_model="embed-model", is_real_llm=lambda: False),
        inf=SimpleNamespace(
            ready=SimpleNamespace(
                milvus="connected",
                postgresql="connected",
                elasticsearch="disconnected",
                kafka="connected",
            )
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

    out = {"status": "running", **build_status(agent)}

    assert out["status"] == "running"
    assert out["rag_loaded"] is True
    assert out["tools_count"] == 2
