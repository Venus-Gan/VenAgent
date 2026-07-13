from types import SimpleNamespace

from internal.agent.agent import ChatOptions, UnifiedAgent
from internal.agent.policy import IntentPolicy
from internal.llm.llm import Message
from internal.tools.tools import build_tavily_tool, default_tools


def test_default_tools_do_not_auto_add_tavily_when_provider_key_exists():
    tools = default_tools(
        cfg=SimpleNamespace(
            search_api_key="tavily-key",
            search_api_url="https://api.tavily.com/search",
        )
    )

    assert [tool.name for tool in tools] == ["get_time", "get_weather", "search_web"]
    assert all(tool.name != "tavily" for tool in tools)


def test_tavily_tool_remains_explicit_only():
    tool = build_tavily_tool(
        SimpleNamespace(
            search_api_key="tavily-key",
            search_api_url="https://api.tavily.com/search",
        )
    )

    assert tool.name == "tavily"
    assert "Tavily" in tool.description


def test_prepare_uses_intent_policy_for_default_cutover(monkeypatch):
    from internal.agent import agent as agent_module

    def _boom(*_args, **_kwargs):
        raise AssertionError("legacy router helper should not be called directly")

    for name in ("need_tool", "need_react", "need_rag", "need_react_from_tools"):
        monkeypatch.setattr(agent_module, name, _boom, raising=False)
    monkeypatch.setattr(agent_module, "async_update_memory", lambda *_args, **_kwargs: None)

    tool_map = {tool.name: tool for tool in default_tools()}

    agent = object.__new__(UnifiedAgent)
    agent.cfg = SimpleNamespace(is_real_llm=lambda: False, long_term_top_k=3)
    agent.llm = SimpleNamespace()
    agent.stm = SimpleNamespace(add=lambda *_args, **_kwargs: None)
    agent.preference = SimpleNamespace(get_all=lambda: {}, save_batch=lambda *_args, **_kwargs: None)
    agent.ltm = SimpleNamespace(recall=lambda *_args, **_kwargs: [], add=lambda *_args, **_kwargs: None)
    agent.rag = SimpleNamespace(loaded=False)
    agent.tool_executor = SimpleNamespace(
        snapshot=lambda: dict(tool_map),
        filter_tools=lambda names: {name: tool_map[name] for name in names if name in tool_map},
    )
    agent.subagents = SimpleNamespace(names=lambda: ())
    agent.intent_policy = IntentPolicy()
    agent._save_chat_history = lambda *_args, **_kwargs: None
    agent._build_memory_system_prefix = lambda _query="": ""
    agent._build_history_messages = lambda query: [Message(role="user", content=query)]

    prepared = agent._prepare("帮我整理这份文档并写成摘要", ChatOptions())

    assert prepared["mode"] == "react"
    assert prepared["query"] == "帮我整理这份文档并写成摘要"
    assert prepared["route_tools"] is None or prepared["route_tools"] == {}
