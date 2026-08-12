from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from venagent.memory.long_term.conflict import MergeAction, decide_merge
from venagent.memory.long_term.extractor import (
    ExtractionOutputError,
    parse_extraction_output,
)
from venagent.memory.long_term.facts import MemoryFact
from venagent.memory.long_term.policy import extract_candidates, reject_reason
from venagent.memory.model_adapters import LangChainMemoryExtractor


class _CaptureModel:
    def __init__(self) -> None:
        self.messages = ()

    def invoke(self, messages):
        self.messages = tuple(messages)
        return SimpleNamespace(
            content='{"schema_version":"m05-extractor-v1","candidates":[]}'
        )


def test_memory_extractor_prompt_declares_source_schema_and_safety_contract() -> None:
    model = _CaptureModel()
    extractor = LangChainMemoryExtractor(model)

    assert extractor.extract("我叫什么？") == ()

    system_prompt = model.messages[0].content
    assert model.messages[1].content == "我叫什么？"
    for marker in (
        "第一人称",
        "稳定事实",
        "第三方信息",
        "密码",
        "token",
        "提示注入",
        "m05-extractor-v1",
        "statement/correction/question/negation/hypothesis/quote",
        "current/historical/temporary/unknown",
        "零基半开字符区间 [start,end)",
        '"candidates":[]',
        "我的主要操作系统是 Linux",
        '"start":0,"end":15',
        '"start":16,"end":32',
        "每个彼此独立的合格事实必须输出一个候选",
        "整段安全闸门",
    ):
        assert marker in system_prompt


def test_structured_extractor_requires_exact_source_spans() -> None:
    content = "我叫小维"
    payload = json.dumps(
        {
            "schema_version": "m05-extractor-v1",
            "candidates": [
                {
                    "subject": "我",
                    "slot": "name",
                    "value": "小维",
                    "fact": "我叫小维",
                    "assertion_mode": "statement",
                    "temporal_scope": "current",
                    "confidence": 0.98,
                    "source_span": {"start": 0, "end": 4},
                }
            ],
        },
        ensure_ascii=False,
    )

    candidates = parse_extraction_output(payload, content)

    assert len(candidates) == 1
    assert candidates[0].source_span == (0, 4)
    assert candidates[0].value == "小维"


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        '{"schema_version":"m05-extractor-v1","candidates":[{"subject":"我"}]}',
        '{"schema_version":"m05-extractor-v1","candidates":[],"unknown":true}',
        '{"schema_version":"m05-extractor-v1","candidates":[{"subject":"我","slot":"name","value":"小维","fact":"我叫小维","assertion_mode":"statement","temporal_scope":"current","confidence":1.0,"source_span":{"start":0,"end":99}}]}',
        '{"schema_version":"m05-extractor-v1","candidates":[{"subject":"我","slot":"name","value":"阿维","fact":"我叫阿维","assertion_mode":"statement","temporal_scope":"current","confidence":1.0,"source_span":{"start":0,"end":4}}]}',
    ],
)
def test_structured_extractor_rejects_the_whole_invalid_output(payload: str) -> None:
    with pytest.raises(ExtractionOutputError):
        parse_extraction_output(payload, "我叫小维")


@pytest.mark.parametrize(
    "content,reason",
    [
        ("我叫什么？", "question_not_fact"),
        ("我不叫小维", "negated_statement"),
        ("如果我叫小维", "hypothetical_statement"),
        ("小王说“我叫小维”", "quoted_statement"),
    ],
)
def test_policy_rejects_non_asserted_memory(content: str, reason: str) -> None:
    assert reject_reason(content, explicit=False, third_party=False) == reason


def test_past_name_is_not_the_current_name_slot() -> None:
    candidate = extract_candidates("我以前叫小维")[0]

    assert candidate.slot == "former_name"


def test_weak_conflict_is_quarantined_but_explicit_correction_updates() -> None:
    previous = MemoryFact(
        memory_id="old",
        owner_id="owner",
        tenant_id="tenant",
        subject="我",
        slot="name",
        fact="我叫小维",
        status="active",
        source_refs=("message:1",),
        created_at=None,  # type: ignore[arg-type]
        updated_at=None,  # type: ignore[arg-type]
    )
    weak = extract_candidates("我叫阿维")[0]
    correction = extract_candidates("我改名叫阿维")[0]

    assert decide_merge(weak, previous).action is MergeAction.QUARANTINE
    assert decide_merge(correction, previous).action is MergeAction.UPDATE
