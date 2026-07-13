from internal.agent.langgraph.builder import END, START, StateGraph, build_react_graph
from internal.agent.langgraph.state import initial_react_state, merge_react_state
from internal.graph.task_graph import Node, NodeType, TaskGraph


def test_merge_react_state_appends_list_fields_without_overwriting():
    state = initial_react_state("search weather")
    state = merge_react_state(
        state,
        {
            "messages": [{"role": "assistant", "content": "A"}],
            "steps": [{"id": "n1"}],
            "results": ["r1"],
            "events": [{"type": "e1"}],
        },
    )
    state = merge_react_state(
        state,
        {
            "messages": [{"role": "assistant", "content": "B"}],
            "steps": [{"id": "n2"}],
            "results": ["r2"],
            "events": [{"type": "e2"}],
        },
    )

    assert [message["content"] for message in state["messages"]][-2:] == ["A", "B"]
    assert [step["id"] for step in state["steps"]] == ["n1", "n2"]
    assert state["results"] == ["r1", "r2"]
    assert [event["type"] for event in state["events"]] == ["e1", "e2"]


def test_state_graph_routes_conditional_edges_based_on_route_field():
    def classify(state):
        route = "tool" if "weather" in state["query"].lower() else "general"
        return {
            "route": route,
            "events": [{"type": "classify", "route": route}],
        }

    def tool(state):
        return {
            "results": ["tool-result"],
            "steps": [{"id": "tool"}],
            "messages": [{"role": "assistant", "content": "tool"}],
            "events": [{"type": "tool"}],
        }

    def general(state):
        return {
            "results": ["general-result"],
            "steps": [{"id": "general"}],
            "messages": [{"role": "assistant", "content": "general"}],
            "events": [{"type": "general"}],
        }

    graph = StateGraph()
    graph.add_node("classify", classify)
    graph.add_node("tool", tool)
    graph.add_node("general", general)
    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", lambda state: state["route"], ["tool", "general"])
    graph.add_edge("tool", END)
    graph.add_edge("general", END)

    result = graph.compile().invoke(initial_react_state("What is the weather?"))

    assert result["route"] == "tool"
    assert result["results"] == ["tool-result"]
    assert [step["id"] for step in result["steps"]] == ["tool"]
    assert [event["type"] for event in result["events"]] == ["classify", "tool"]
    assert result["messages"][-1]["content"] == "tool"


def test_build_react_graph_from_task_graph_executes_nodes_in_dependency_order():
    task_graph = TaskGraph([
        Node(id="n1", type=NodeType.TOOL, tool_name="first"),
        Node(id="n2", type=NodeType.TOOL, tool_name="second", depends_on=["n1"]),
    ])

    def node_factory(node):
        def runner(_state):
            return {
                "steps": [{"id": node.id}],
                "results": [node.tool_name],
                "events": [{"type": node.id}],
            }

        return runner

    result = build_react_graph(task_graph, node_factory=node_factory).invoke(
        initial_react_state("do work")
    )

    assert [step["id"] for step in result["steps"]] == ["n1", "n2"]
    assert result["results"] == ["first", "second"]
    assert [event["type"] for event in result["events"]] == ["n1", "n2"]
