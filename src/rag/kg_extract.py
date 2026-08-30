"""M08 KG 路实体抽取：7 实体类型 + 7 关系白名单（对齐 AGI-saber kg extractor）。

一期只做抽取与严格解析（response_provider 模式）；Neo4j 图写入与
子图召回（apoc.path.subgraphNodes / searchDirect 降级）在 P3 后半接入
GraphRoute。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

KG_SCHEMA_VERSION = "m08-kg-v1"
MAX_ENTITIES = 32
MAX_RELATIONS = 64

ENTITY_TYPES = frozenset(
    {"Person", "Organization", "Location", "Concept", "Event", "Product", "Unknown"}
)
RELATION_TYPES = frozenset(
    {
        "RELATES_TO",
        "PART_OF",
        "CAUSES",
        "DESCRIBES",
        "MENTIONS",
        "WORKS_FOR",
        "LOCATED_IN",
    }
)

KG_SYSTEM_PROMPT = (
    "你是知识图谱抽取助手。从文本中抽取实体与关系。"
    f"实体类型只能是：{', '.join(sorted(ENTITY_TYPES))}。"
    f"关系类型只能是：{', '.join(sorted(RELATION_TYPES))}。"
    '只返回 JSON object：{"schema_version": "m08-kg-v1", '
    '"entities": [{"name": "...", "type": "..."}], '
    '"relations": [{"source": "...", "target": "...", "relation": "..."}]}，'
    "不要包含其他内容。"
)


class KgExtractionError(ValueError):
    """KG 抽取输出不满足严格 schema。"""


@dataclass(frozen=True)
class KgEntity:
    name: str
    type: str


@dataclass(frozen=True)
class KgRelation:
    source: str
    target: str
    relation: str


@dataclass(frozen=True)
class KgExtraction:
    entities: tuple[KgEntity, ...]
    relations: tuple[KgRelation, ...]

    def by_name(self) -> dict[str, KgEntity]:
        return {entity.name: entity for entity in self.entities}


def parse_kg_output(raw: Any) -> KgExtraction:
    payload = _as_mapping(raw)
    if payload.get("schema_version") != KG_SCHEMA_VERSION:
        raise KgExtractionError("kg schema version is invalid")
    entities = _parse_entities(payload.get("entities"))
    relations = _parse_relations(payload.get("relations"), {e.name for e in entities})
    return KgExtraction(entities, relations)


def _as_mapping(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        stripped = _FENCE.sub("", raw).strip()
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            raise KgExtractionError("kg output is not JSON") from None
    elif isinstance(raw, dict):
        value = raw
    else:
        text = getattr(raw, "text", None)
        if not isinstance(text, str):
            raise KgExtractionError("kg output is not textual")
        return _as_mapping(text)
    if not isinstance(value, dict):
        raise KgExtractionError("kg output is not an object")
    return value


def _parse_entities(raw: Any) -> tuple[KgEntity, ...]:
    if not isinstance(raw, list) or len(raw) > MAX_ENTITIES:
        raise KgExtractionError("kg entities are invalid")
    entities: list[KgEntity] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"name", "type"}:
            raise KgExtractionError("kg entity fields are invalid")
        name = _bounded(str(item["name"]), 120)
        entity_type = str(item["type"])
        if not name or entity_type not in ENTITY_TYPES:
            raise KgExtractionError("kg entity classification is invalid")
        if name in seen:
            continue
        seen.add(name)
        entities.append(KgEntity(name, entity_type))
    return tuple(entities)


def _parse_relations(
    raw: Any, entity_names: set[str]
) -> tuple[KgRelation, ...]:
    if not isinstance(raw, list) or len(raw) > MAX_RELATIONS:
        raise KgExtractionError("kg relations are invalid")
    relations: list[KgRelation] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"source", "target", "relation"}:
            raise KgExtractionError("kg relation fields are invalid")
        source = _bounded(str(item["source"]), 120)
        target = _bounded(str(item["target"]), 120)
        relation = str(item["relation"])
        if (
            not source
            or not target
            or relation not in RELATION_TYPES
            or source not in entity_names
            or target not in entity_names
        ):
            raise KgExtractionError("kg relation classification is invalid")
        key = (source, target, relation)
        if key in seen:
            continue
        seen.add(key)
        relations.append(KgRelation(source, target, relation))
    return tuple(relations)


def _bounded(text: str, limit: int) -> str:
    return text[:limit]


class KgExtractor:
    def __init__(self, response_provider: Any) -> None:
        self._response_provider = response_provider

    def extract(self, content: str) -> KgExtraction:
        return parse_kg_output(self._response_provider(content))


class LangChainKgExtractor(KgExtractor):
    """把 LangChain 模型收敛为 KgExtractor（照 M05 适配模式）。

    构造时不绑定 invoke（流式模型可能没有）；执行时探测，缺失抛错由 GraphRoute 降级。
    """

    def __init__(self, model: Any) -> None:
        super().__init__(self._request)
        self._model = model

    def _request(self, content: str) -> str:
        invoke = getattr(self._model, "invoke", None)
        if invoke is None:
            raise KgExtractionError("model has no invoke")
        from langchain_core.messages import HumanMessage, SystemMessage

        response = invoke(
            (
                SystemMessage(content=KG_SYSTEM_PROMPT),
                HumanMessage(content=content[:4000]),
            )
        )
        text = getattr(response, "text", None)
        if isinstance(text, str):
            return text
        content_value = getattr(response, "content", None)
        if isinstance(content_value, str):
            return content_value
        raise KgExtractionError("kg output is not textual")
