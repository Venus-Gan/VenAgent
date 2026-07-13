from types import SimpleNamespace

from internal.agent.subagents import register_builtin_subagents
from internal.agentteam import PresetTask
from internal.agentteam.presets.research import ResearchPreset, build_research_contract, create_research_preset
from internal.agentteam.presets.writer import WriterPreset, build_writer_contract, create_writer_preset


class FakeSearchTool:
    def func(self, payload):
        return {"query": payload["query"], "hits": ["alpha", "beta"]}


class FakeToolExecutor:
    def snapshot(self):
        return {"search_web": FakeSearchTool()}


def test_research_preset_contract_and_fallback_search():
    agent = SimpleNamespace(cfg=SimpleNamespace(is_real_llm=lambda: False), tool_executor=FakeToolExecutor(), rag=None)
    preset = create_research_preset(agent)

    assert isinstance(preset, ResearchPreset)
    assert build_research_contract().name == "research_agent"
    assert preset.contract().role == "research"

    output = preset.run(PresetTask(goal="调研 FastAPI", query="FastAPI 是什么", upstream={}))

    assert output.startswith("## Research Findings")
    assert "Query: 调研 FastAPI" in output
    assert "Search Result:" in output


def test_writer_preset_contract_and_markdown_fallback():
    agent = SimpleNamespace(cfg=SimpleNamespace(is_real_llm=lambda: False))
    preset = create_writer_preset(agent)

    assert isinstance(preset, WriterPreset)
    assert build_writer_contract().name == "writer_agent"
    assert preset.contract().role == "writer"

    output = preset.run(
        PresetTask(
            goal="撰写周报",
            query="请整理研究材料",
            upstream={"research_agent": "证据 A" + chr(10) + "证据 B"},
        )
    )

    assert output.startswith("# 周报")
    assert "## research_agent" in output
    assert "证据 A" in output


def test_register_builtin_subagents_uses_preset_modules_for_research_and_writer():
    agent = SimpleNamespace(cfg=SimpleNamespace(is_real_llm=lambda: False), tool_executor=FakeToolExecutor(), rag=None)
    registry = register_builtin_subagents(agent)

    assert registry.names()[:2] == ("research_agent", "writer_agent")
    assert registry.get_contract("research_agent").name == "research_agent"
    assert registry.get_contract("writer_agent").name == "writer_agent"
    assert registry.get("research_agent").__class__.__module__ == "internal.agentteam.presets.research"
    assert registry.get("writer_agent").__class__.__module__ == "internal.agentteam.presets.writer"
