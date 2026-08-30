"""M06 支持的有界 JSON Schema 子集及参数复核。"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import validator_for

from .errors import ToolSchemaInvalid

MAX_SCHEMA_NODES = 10_000
MAX_SCHEMA_DEPTH = 64
REFERENCE_KEYWORDS = ("$ref", "$dynamicRef", "$recursiveRef")


def schema_supported(schema: dict[str, Any]) -> bool:
    if not isinstance(schema, dict) or not _references_are_local_and_resolvable(schema):
        return False
    try:
        validator_class = validator_for(schema, default=Draft202012Validator)
        validator_class.check_schema(schema)
    except (SchemaError, TypeError, ValueError):
        return False
    return True


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    if not schema_supported(schema):
        raise ToolSchemaInvalid
    try:
        validator_class = validator_for(schema, default=Draft202012Validator)
        validator_class(schema).validate(arguments)
    except (SchemaError, ValidationError, TypeError, ValueError):
        raise ToolSchemaInvalid from None


def _references_are_local_and_resolvable(schema: dict[str, Any]) -> bool:
    stack: list[tuple[Any, int]] = [(schema, 0)]
    node_count = 0
    while stack:
        value, depth = stack.pop()
        node_count += 1
        if node_count > MAX_SCHEMA_NODES or depth > MAX_SCHEMA_DEPTH:
            return False
        if isinstance(value, dict):
            for keyword in REFERENCE_KEYWORDS:
                reference = value.get(keyword)
                if reference is not None and not _local_reference_resolves(
                    schema, reference
                ):
                    return False
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
    return True


def _local_reference_resolves(schema: dict[str, Any], reference: Any) -> bool:
    if not isinstance(reference, str) or not reference.startswith("#"):
        return False
    if reference == "#":
        return True
    if not reference.startswith("#/"):
        return False
    current: Any = schema
    for raw_token in reference[2:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
            continue
        if isinstance(current, list) and token.isdigit():
            index = int(token)
            if index < len(current):
                current = current[index]
                continue
        return False
    return True
