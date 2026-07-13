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


def test_react_runtime_runs_main_path_to_completion_with_thread_id():
    graph = TaskGraph(
        [
            Node(id="n1", type=NodeType.TOOL, tool_name="first"),
            Node(id="n2", type=NodeType.TOOL, tool_name="second", depends_on=["n1"]),
        ]
    )
    saver = InMemorySaver()
    agent = _Agent()
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
    )

    result = runtime.invoke(CancelToken(), {"configurable": {"thread_id": "thread-1"}})

    assert result.interrupted is False
    assert result.observations == ["A", "B"]
    assert graph.nodes["n1"].status == NodeStatus.DONE
    assert graph.nodes["n2"].status == NodeStatus.DONE
    assert saver.get("thread-1") is not None
