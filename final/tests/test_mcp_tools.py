from internal.tools.tools import Tool, ToolExecutor, new_mcp_tool


def _tool(name: str, description: str = "工具", params=None, is_mcp: bool = False) -> Tool:
    return Tool(
        name=name,
        description=description,
        params=params if params is not None else [{"name": "query", "type": "string", "description": "关键词"}],
        func=lambda _params: "ok",
        is_mcp=is_mcp,
    )


def test_tool_executor_descriptions_use_canonical_params_contract():
    executor = ToolExecutor([_tool("search_web", "网络搜索")])

    descriptions = executor.get_tool_descriptions()

    assert descriptions[0]["name"] == "search_web"
    assert descriptions[0]["description"] == "网络搜索"
    assert descriptions[0]["params"] == [{"name": "query", "type": "string", "description": "关键词"}]
    assert descriptions[0]["parameters"] == descriptions[0]["params"]
    assert descriptions[0]["is_mcp"] is False


def test_registering_mcp_tool_keeps_canonical_params_contract():
    executor = ToolExecutor([_tool("base", "基础工具", params=[])])
    executor.add_tool(
        new_mcp_tool(
            name="dynamic_mcp",
            description="动态 MCP",
            params=[{"name": "query", "type": "string", "description": "关键词"}],
            func=lambda _params: "registered",
        )
    )

    descriptions = executor.get_tool_descriptions()
    mcp_tools = [tool for tool in descriptions if tool["name"] == "dynamic_mcp"]

    assert len(mcp_tools) == 1
    assert mcp_tools[0]["is_mcp"] is True
    assert mcp_tools[0]["params"] == [{"name": "query", "type": "string", "description": "关键词"}]
