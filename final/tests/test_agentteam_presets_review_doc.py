import json
from types import SimpleNamespace

from internal.agent.subagents import register_builtin_subagents
from internal.agentteam import PresetTask
from internal.agentteam.presets.doc import DocPreset, build_doc_contract, create_doc_preset
from internal.agentteam.presets.review import ReviewPreset, build_review_contract, create_review_preset
from internal.document.library import Document, DocumentVersion, WriteResult


def test_review_preset_contract_and_fallback_message():
    agent = SimpleNamespace(cfg=SimpleNamespace(is_real_llm=lambda: False))
    preset = create_review_preset(agent)

    assert isinstance(preset, ReviewPreset)
    assert build_review_contract().name == "review_agent"
    assert preset.contract().role == "review"

    output = preset.run(PresetTask(goal="审查报告", query="请检查材料", upstream={"writer_agent": "draft"}))

    assert output == "Review: 内容已整理；建议人工确认关键事实。"


def test_review_preset_uses_llm_path_when_available():
    agent = RecordingReviewAgent()
    preset = create_review_preset(agent)

    output = preset.run(PresetTask(goal="审查报告", query="请检查材料", upstream={"writer_agent": "draft"}))

    assert output == "LLM-REVIEW"
    assert agent.calls[0]["system"].startswith("你是 review_agent")
    assert "## writer_agent" in agent.calls[0]["material"]


def test_doc_preset_contract_and_document_write():
    agent = RecordingDocAgent()
    preset = create_doc_preset(agent)

    assert isinstance(preset, DocPreset)
    assert build_doc_contract().name == "doc_agent"
    assert preset.contract().role == "doc"

    output = preset.run(
        PresetTask(
            id="n4",
            goal="保存报告",
            query="生成一份标题为《AGI周报》的报告",
            upstream={"n2_writer_agent": "# AGI周报\n\n正文", "n3_review_agent": "Review ok"},
        )
    )
    data = json.loads(output)

    assert agent.write_calls[0]["req"].title == "AGI周报"
    assert agent.write_calls[0]["req"].content_md == "# AGI周报\n\n正文"
    assert agent.write_calls[0]["req"].metadata["sub_agent"] == "doc_agent"
    assert agent.write_calls[0]["ingest"] is True
    assert data["document"]["id"] == "doc_1"


def test_register_builtin_subagents_uses_review_and_doc_preset_modules():
    agent = SimpleNamespace(cfg=SimpleNamespace(is_real_llm=lambda: False), write_document=lambda req, ingest_to_rag=False: {"document": {"id": "doc_1"}})
    registry = register_builtin_subagents(agent)

    assert registry.names()[-2:] == ("review_agent", "doc_agent")
    assert registry.get_contract("review_agent").name == "review_agent"
    assert registry.get_contract("doc_agent").name == "doc_agent"
    assert registry.get("review_agent").__class__.__module__ == "internal.agentteam.presets.review"
    assert registry.get("doc_agent").__class__.__module__ == "internal.agentteam.presets.doc"


class RecordingReviewAgent:
    def __init__(self):
        self.cfg = SimpleNamespace(is_real_llm=lambda: True)
        self.calls = []

    def _llm_generate(self, system_prompt, user_msg):
        self.calls.append({"system": system_prompt, "material": user_msg})
        return "LLM-REVIEW"


class RecordingDocAgent:
    def __init__(self):
        self.cfg = SimpleNamespace(is_real_llm=lambda: False)
        self.write_calls = []

    def write_document(self, req, ingest_to_rag=False):
        self.write_calls.append({"req": req, "ingest": ingest_to_rag})
        doc = Document(
            id="doc_1",
            title=req.title,
            doc_type=req.doc_type,
            source=req.source,
            status="active",
            created_by=req.created_by,
            latest_version=1,
            latest_version_id="ver_1",
        )
        ver = DocumentVersion(
            id="ver_1",
            document_id="doc_1",
            version=1,
            content_md=req.content_md,
            summary=req.summary,
            metadata=req.metadata,
        )
        return WriteResult(document=doc, version=ver, created=True)
