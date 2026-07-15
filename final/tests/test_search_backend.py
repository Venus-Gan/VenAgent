from types import SimpleNamespace

from internal.tools.tools import default_tools, search_web_factory


def test_search_web_factory_ignores_provider_key_and_uses_fallback(monkeypatch):
    def _unexpected_tavily_search(*_args, **_kwargs):
        raise AssertionError("default search_web should not call Tavily")

    monkeypatch.setattr("internal.tools.tavily.tavily_search", _unexpected_tavily_search)

    cfg = SimpleNamespace(
        search_api_key="tavily-key",
        search_api_url="https://api.tavily.com/search",
    )
    search_web = search_web_factory(cfg=cfg, llm=None)

    assert search_web({"query": "AI应用工程师"}) == (
        "AI 应用工程师是将 AI 技术落地到业务的工程师，需具备 ML 基础、API 开发、Prompt 工程等能力。"
    )


def test_default_tools_search_description_is_provider_agnostic():
    search_tool = next(tool for tool in default_tools() if tool.name == "search_web")

    assert "Tavily" not in search_tool.description
    assert "LLM" in search_tool.description or "mock" in search_tool.description
