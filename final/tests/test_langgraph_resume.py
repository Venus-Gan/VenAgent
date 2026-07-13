from types import SimpleNamespace

from internal.agent.cancel import CancelToken
from internal.agent.graph_runtime import GraphConfig
from internal.agent.langgraph.runtime import InMemorySaver, ReactRuntime
from internal.graph.task_graph import Node, NodeStatus, NodeType, TaskGraph


class _Tool:
    def __init__(self, func):
        self.func = func
        self.description = "fake"
        self.params = []


class _Agent:
    def __init__(self):
        self.cfg = SimpleNamespace(max_retries=1, retry_delay_ms=1)
        self.snapshots = []

    def save_snapshot(self, task):
        self.snapshots.append(dict(task))


def test_react_runtime_checkpoints_and_resumes_with_thread_id():
    graph = TaskGraph(
        [
            Node(id="n1", type=NodeType.TOOL, tool_name="first"),
            Node(id="n2", type=NodeType.TOOL, tool_name="second", depends_on=["n1"]),
        ]
    )
    saver = InMemorySaver()
    events = []
    agent = _Agent()
    config = {"configurable": {"thread_id": "thread-1"}}

    def on_event(payload):
        events.append(payload)

    token = CancelToken()

    def cancel_after_first_level(payload):
        on_event(payload)
        if payload.get("type") == "level_done" and payload.get("level") == 0:
            token.cancel()

    runtime = ReactRuntime(
        graph,
        agent,
        GraphConfig(max_parallel=1),
        {
            "first": _Tool(lambda _params: "A"),
            "second": _Tool(lambda _params: "B"),
        },
        {"task_id": "task-1"},
        checkpointer=saver,
        on_event=cancel_after_first_level,
    )

    interrupted = runtime.invoke(token, config)

    assert interrupted.interrupted is True
    assert graph.nodes["n1"].status == NodeStatus.DONE
    assert saver.get("thread-1") is not None
    assert events or agent.snapshots

    resumed = ReactRuntime(
        graph,
        agent,
        GraphConfig(max_parallel=1),
        {
            "first": _Tool(lambda _params: "A"),
            "second": _Tool(lambda _params: "B"),
        },
        {"task_id": "task-1"},
        checkpointer=saver,
    ).resume(CancelToken(), config)

    assert resumed.interrupted is False
    assert graph.nodes["n1"].status == NodeStatus.DONE
    assert graph.nodes["n2"].status == NodeStatus.DONE
    assert resumed.observations == ["A", "B"]


def test_react_runtime_uses_separate_thread_ids_for_isolated_checkpoints():
    graph_a = TaskGraph([Node(id="n1", type=NodeType.TOOL, tool_name="first")])
    graph_b = TaskGraph([Node(id="n1", type=NodeType.TOOL, tool_name="first")])
    saver = InMemorySaver()
    agent = _Agent()
    config_a = {"configurable": {"thread_id": "thread-a"}}
    config_b = {"configurable": {"thread_id": "thread-b"}}

    ReactRuntime(
        graph_a,
        agent,
        GraphConfig(max_parallel=1),
        {"first": _Tool(lambda _params: "A")},
        {"task_id": "task-a"},
        checkpointer=saver,
    ).invoke(CancelToken(), config_a)
    ReactRuntime(
        graph_b,
        agent,
        GraphConfig(max_parallel=1),
        {"first": _Tool(lambda _params: "B")},
        {"task_id": "task-b"},
        checkpointer=saver,
    ).invoke(CancelToken(), config_b)

    assert saver.get("thread-a") is not None
    assert saver.get("thread-b") is not None
    assert saver.get("thread-a").task["task_id"] == "task-a"
    assert saver.get("thread-b").task["task_id"] == "task-b"
