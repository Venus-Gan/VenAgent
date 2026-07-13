"""Preset runner implementations for agentteam compat."""

from .doc import DocAgent, DocPreset, build_doc_contract, create_doc_preset
from .research import ResearchAgent, ResearchPreset, build_research_contract, create_research_preset
from .review import ReviewAgent, ReviewPreset, build_review_contract, create_review_preset
from .writer import WriterAgent, WriterPreset, build_writer_contract, create_writer_preset

__all__ = [
    "DocAgent",
    "DocPreset",
    "ResearchAgent",
    "ResearchPreset",
    "ReviewAgent",
    "ReviewPreset",
    "WriterAgent",
    "WriterPreset",
    "build_doc_contract",
    "build_research_contract",
    "build_review_contract",
    "build_writer_contract",
    "create_doc_preset",
    "create_research_preset",
    "create_review_preset",
    "create_writer_preset",
]
