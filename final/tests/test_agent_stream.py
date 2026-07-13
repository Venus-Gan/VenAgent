from types import MethodType, SimpleNamespace

from internal.agent.agent import ChatOptions, Response, UnifiedAgent
from internal.llm.llm import Message


class _Token:
    def __init__(self, cancelled=False):
        self.cancelled = cancelled

    def is_cancelled(self):
        return self.cancelled


def _agent_with_stream_fakes(mode="chat"):
    agent = UnifiedAgent.__new__(UnifiedAgent)
    calls = {"prepare": 0, "dispatch_mode": 0, "finalize": 0, "rag_stream": 0, "react_stream": 0}

    def _prepare(self, query, opts):
        calls["prepare"] += 1
        return {
            "query": query,
            "mode": mode,
            "route_tools": {},
            "mem_prefix": "记忆前缀",
            "hist_msgs": [Message(role="user", content=query)],
            "extracted": "偏好信息",
        }

    def _chat_response(self, mem_prefix, hist_msgs):
        return "同步回答"

    def _dispatch_mode(self, pr, resp, token, on_token=None, on_event=None):
        calls["dispatch_mode"] += 1
        resp.answer = "同步回答"

    def _run_rag_query(self, query, token=None, on_token=None, on_event=None):
        calls["rag_stream"] += 1
        if on_event:
            on_event("rag_progress", {"stage": "retrieve", "query": query})
        if on_token:
            on_token("R")
            on_token("A")
            on_token("G")
        return "RAG", [{"content": "rag-hit"}]

    def _run_react_with_tools(self, query, tools_map, mem_prefix, hist_msgs, token, on_token=None, on_event=None):
        calls["react_stream"] += 1
        if on_event:
            on_event("react_progress", {"stage": "final_answer", "count": 1})
        if on_token:
            for ch in "REACT":
                on_token(ch)
        return "REACT", [], {"status": "completed", "graph": {"nodes": []}}

    def _finalize(self, query, resp):
        calls["finalize"] += 1
        resp.short_term_count = 2

    agent._prepare = MethodType(_prepare, agent)
    agent._chat_response = MethodType(_chat_response, agent)
    agent._dispatch_mode = MethodType(_dispatch_mode, agent)
    agent._run_rag_query = MethodType(_run_rag_query, agent)
    agent._run_react_with_tools = MethodType(_run_react_with_tools, agent)
    agent._finalize = MethodType(_finalize, agent)
    agent.rag = SimpleNamespace(
        query_with_history_stream=lambda query, history, ctx=None, on_token=None, on_event=None: (
            "RAG",
            [{"content": "rag-hit"}],
        ),
    )
    agent._cancel_registry = SimpleNamespace(set_task=lambda *_args, **_kwargs: None)
    agent.cfg = SimpleNamespace(is_real_llm=lambda: False, graph_max_parallel=2, graph_race_timeout_ms=30000, graph_enable_racing=True)
    return agent, calls


def test_process_stream_with_options_streams_chat_tokens_once():
    agent, calls = _agent_with_stream_fakes(mode="chat")
    tokens = []
    events = []

    def _chat_response_stream(self, mem_prefix, hist_msgs, token, on_token=None):
        assert mem_prefix == "记忆前缀"
        assert hist_msgs[-1].content == "你好"
        if on_token:
            on_token("你")
            on_token("好")
        return "你好"

    agent._chat_response_stream = MethodType(_chat_response_stream, agent)

    resp = agent.process_stream_with_options(
        "你好",
        ChatOptions(),
        _Token(),
        on_token=tokens.append,
        on_event=lambda event, payload: events.append((event, payload)),
    )

    assert resp.answer == "你好"
    assert resp.mode == "chat"
    assert tokens == ["你", "好"]
    assert events == [
        ("route", {"mode": "chat"}),
        ("memory", {"extracted_info": "偏好信息"}),
    ]
    assert calls["prepare"] == 1
    assert calls["finalize"] == 1


def test_process_stream_with_options_falls_back_without_reprepare_for_non_chat():
    agent, calls = _agent_with_stream_fakes(mode="tool")
    tokens = []
    events = []

    resp = agent.process_stream_with_options(
        "查知识库",
        ChatOptions(),
        _Token(),
        on_token=tokens.append,
        on_event=lambda event, payload: events.append((event, payload)),
    )

    assert resp.answer == "同步回答"
    assert resp.mode == "tool"
    assert tokens == []
    assert events[0] == ("route", {"mode": "tool"})
    assert calls["prepare"] == 1
    assert calls["finalize"] == 1


def test_process_stream_with_options_finalizes_cancelled_start_once():
    agent, calls = _agent_with_stream_fakes(mode="chat")

    resp = agent.process_stream_with_options("你好", ChatOptions(), _Token(cancelled=True))

    assert resp.interrupted is True
    assert resp.answer == "[已中断] 请求在开始前被取消"
    assert calls["prepare"] == 1 and calls["finalize"] == 1
    assert calls["dispatch_mode"] == 0


def test_process_stream_with_options_streams_rag_tokens_and_progress():
    agent, calls = _agent_with_stream_fakes(mode="rag")
    tokens = []
    events = []

    resp = agent.process_stream_with_options(
        "查知识库",
        ChatOptions(use_rag=True, explicit=True),
        _Token(),
        on_token=tokens.append,
        on_event=lambda event, payload: events.append((event, payload)),
    )

    assert resp.answer == "RAG"
    assert resp.mode == "rag"
    assert tokens == ["R", "A", "G"]
    assert any(event == "rag_progress" for event, _ in events)
    assert resp.search_results == [{"content": "rag-hit"}]
    assert calls["rag_stream"] == 1
    assert calls["finalize"] == 1


def test_process_stream_with_options_streams_react_final_answer_and_progress():
    agent, calls = _agent_with_stream_fakes(mode="react")
    tokens = []
    events = []

    resp = agent.process_stream_with_options(
        "搜索 RAG 是什么",
        ChatOptions(selected_tools=["search_web"], explicit=True),
        _Token(),
        on_token=tokens.append,
        on_event=lambda event, payload: events.append((event, payload)),
    )

    assert resp.answer == "REACT"
    assert resp.mode == "react"
    assert tokens == list("REACT")
    assert any(event == "react_progress" for event, _ in events)
    assert calls["react_stream"] == 1
    assert calls["finalize"] == 1
