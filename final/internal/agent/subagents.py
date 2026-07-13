"""Compatibility layer for document-oriented subagents."""

from internal.agentteam import PresetRegistry, PresetTask, build_preset_contract
from internal.agentteam.presets.doc import DocAgent, build_doc_contract
from internal.agentteam.presets.research import ResearchAgent
from internal.agentteam.presets.review import ReviewAgent, build_review_contract
from internal.agentteam.presets.writer import WriterAgent


SubAgentTask = PresetTask
SubAgentRegistry = PresetRegistry
ResearchPreset = ResearchAgent
ReviewPreset = ReviewAgent
DocPreset = DocAgent
WriterPreset = WriterAgent


def register_builtin_subagents(agent) -> SubAgentRegistry:
    registry = SubAgentRegistry()
    for subagent in [
        ResearchAgent(agent),
        WriterAgent(agent),
        ReviewAgent(agent),
        DocAgent(agent),
    ]:
        registry.register(
            subagent.name(),
            subagent,
            _contract_for(subagent),
        )
    return registry


def _contract_for(subagent) -> object:
    contract = getattr(subagent, "contract", None)
    if callable(contract):
        return contract()

    name = subagent.name()
    if name == "review_agent":
        return build_review_contract()
    if name == "doc_agent":
        return build_doc_contract()
    return build_preset_contract(
        name=name,
        role="compat",
        purpose=subagent.description(),
        input_fields=("id", "goal", "query", "upstream"),
        output_fields=("status", "result", "notes", "follow_up", "used_tools"),
        tool_permissions=(),
        memory_policy="task_memory",
        retrieval_policy="upstream",
        prompt_template="Compatibility preset.",
    )
