"""kg_extract 解析测试：白名单校验 / 重复去重 / 非法输出。"""

from __future__ import annotations

import pytest

from src.rag.kg_extract import KgExtractionError, parse_kg_output

VALID = (
    '{"schema_version": "m08-kg-v1", '
    '"entities": [{"name": "杭州", "type": "Location"}, '
    '{"name": "林舟", "type": "Person"}, {"name": "火星项目", "type": "Concept"}], '
    '"relations": [{"source": "林舟", "target": "杭州", "relation": "LOCATED_IN"}, '
    '{"source": "林舟", "target": "火星项目", "relation": "WORKS_FOR"}]}'
)


def test_parse_valid_extraction():
    extraction = parse_kg_output(VALID)
    assert len(extraction.entities) == 3
    assert len(extraction.relations) == 2
    assert extraction.by_name()["杭州"].type == "Location"


def test_tolerates_json_fence():
    fenced = f"```json\n{VALID}\n```"
    assert len(parse_kg_output(fenced).entities) == 3


def test_rejects_unknown_relation():
    raw = VALID.replace("WORKS_FOR", "WORKS_AT")
    with pytest.raises(KgExtractionError):
        parse_kg_output(raw)


def test_rejects_unknown_entity_type():
    raw = VALID.replace('"Location"', '"Place"')
    with pytest.raises(KgExtractionError):
        parse_kg_output(raw)


def test_rejects_relation_with_unknown_entity():
    raw = VALID.replace('"target": "杭州"', '"target": "未知城市"')
    with pytest.raises(KgExtractionError):
        parse_kg_output(raw)


def test_rejects_non_json():
    with pytest.raises(KgExtractionError):
        parse_kg_output("not json")


def test_rejects_wrong_schema_version():
    with pytest.raises(KgExtractionError):
        parse_kg_output(VALID.replace("m08-kg-v1", "m08-kg-v0"))


def test_deduplicates_entities_and_relations():
    raw = (
        '{"schema_version": "m08-kg-v1", '
        '"entities": [{"name": "杭州", "type": "Location"}, '
        '{"name": "杭州", "type": "Location"}], '
        '"relations": [{"source": "杭州", "target": "杭州", "relation": "RELATES_TO"}, '
        '{"source": "杭州", "target": "杭州", "relation": "RELATES_TO"}]}'
    )
    extraction = parse_kg_output(raw)
    assert len(extraction.entities) == 1
    assert len(extraction.relations) == 1
