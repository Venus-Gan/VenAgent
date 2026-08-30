"""LangChain 适配层：只把给定 ToolCatalogSnapshot 投影为模型 tool schema。"""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any
from uuid import uuid4

from .models import ModelToolCall, ToolCatalogSnapshot
from .redaction import redact_text

logger = logging.getLogger(__name__)


class ModelToolCallInvalid(ValueError):
    """模型返回的 tool call 无法归一化或缺少必要字段。"""


_DSML_TOOL_CALLS = "<｜｜DSML｜｜tool_calls>"
_DSML_INVOKE_CLOSE = "<｜｜DSML｜｜invoke>"
_DSML_PARAMETER_CLOSE = "<｜｜DSML｜｜parameter>"
_DSML_INVOKE_OPEN = re.compile(
    r'<｜｜DSML｜｜invoke name="(?P<name>[A-Za-z0-9_.:-]+)">'
)
_DSML_PARAMETER_OPEN = re.compile(
    r'<｜｜DSML｜｜parameter name="(?P<name>[A-Za-z0-9_.:-]+)" '
    r'string="(?P<string>true|false)">'
)
_JSON_TOOL_CALL_ENVELOPE = re.compile(
    r"^AI执行轨迹\+\s*```json\s*(?P<body>\{.*\})\s*```\s*$",
    re.DOTALL,
)
_MAX_DSML_ARGUMENT_BYTES = 64 * 1024


def snapshot_to_langchain_tools(
    snapshot: ToolCatalogSnapshot,
) -> tuple[dict[str, Any], ...]:
    """返回 provider tool dict；不建立连接、不执行、不授予权限。"""

    return tuple(
        {
            # tool_id carries the stable Server prefix when MCP names collide.
            "name": item.tool_id,
            "description": item.description,
            "parameters": item.input_schema,
        }
        for item in snapshot.exposed_tools()
    )


def model_tool_calls_from_chunks(chunks: tuple[Any, ...]) -> tuple[ModelToolCall, ...]:
    """从一次模型调用的全部 chunk 中聚合 tool calls。

    支持 LangChain 流式 `AIMessageChunk.tool_call_chunks` 与普通
    `AIMessage.tool_calls` 两种表示。
    """
    aggregated: dict[int, dict[str, str]] = {}
    for chunk in chunks:
        for raw in getattr(chunk, "tool_call_chunks", None) or ():
            if not isinstance(raw, dict):
                continue
            index = _tool_call_index(aggregated, raw)
            entry = aggregated.setdefault(index, {"id": "", "name": "", "args": ""})
            if raw.get("id"):
                entry["id"] = str(raw["id"])
            if raw.get("name"):
                entry["name"] += str(raw["name"])
            if raw.get("args"):
                entry["args"] += str(raw["args"])
        for raw in getattr(chunk, "tool_calls", None) or ():
            if not isinstance(raw, dict):
                continue
            # 部分 provider 每个分片平行携带空骨架视图（无 id 无 name），
            # 会在聚合中制造新条目并污染参数，直接忽略。
            if not raw.get("id") and not raw.get("name"):
                continue
            index = _tool_call_index(aggregated, raw)
            has_existing_entry = index in aggregated
            entry = aggregated.setdefault(index, {"id": "", "name": "", "args": ""})
            if raw.get("id"):
                entry["id"] = str(raw["id"])
            if raw.get("name"):
                entry["name"] = str(raw["name"])
            args = raw.get("args", raw.get("arguments", {}))
            if isinstance(args, str):
                entry["args"] = args
            elif isinstance(args, dict) and (args or not has_existing_entry):
                entry["args"] = json.dumps(args, ensure_ascii=False, sort_keys=True)

    calls: list[ModelToolCall] = []
    for index in sorted(aggregated):
        raw = aggregated[index]
        # 残余的 id/name 双空条目（即便被骨架写入了 args）不是真实调用。
        if not raw["id"] and not raw["name"]:
            continue
        # id 缺失只影响调用身份（provider 流式增量可能从不携带），合成即可。
        if not raw["name"]:
            raise ModelToolCallInvalid("tool call missing name")
        tool_call_id = raw["id"] or str(uuid4())
        try:
            arguments = json.loads(raw["args"]) if raw["args"] else {}
        except json.JSONDecodeError:
            # 部分provider流式视图会与增量片段交错，聚合串可能不是合法 JSON；
            # 先修复再放弃，保留脱敏日志便于观察 provider 行为。
            repaired = _repair_json_arguments(raw["args"])
            if repaired is None:
                logger.warning(
                    "tool call arguments not valid JSON: len=%s preview=%r",
                    len(raw["args"]),
                    redact_text(raw["args"][:120]),
                )
                raise ModelToolCallInvalid("tool call arguments are not valid JSON")
            logger.warning(
                "tool call arguments repaired from provider stream: len=%s",
                len(raw["args"]),
            )
            arguments = repaired
        if not isinstance(arguments, dict):
            raise ModelToolCallInvalid("tool call arguments must be an object")
        calls.append(ModelToolCall(tool_call_id, raw["name"], arguments))
    if calls:
        return tuple(calls)

    # Some OpenAI-compatible Responses providers (including DeepSeek) emit the
    # tool call as a DSML text envelope instead of LangChain tool_call_chunks.
    # Parse only the complete, exact envelope; ordinary assistant text is never
    # interpreted as a tool call.
    dsml_text = "".join(_chunk_text(chunk) for chunk in chunks).strip()
    dsml_calls = _model_tool_calls_from_dsml(dsml_text)
    if dsml_calls:
        return dsml_calls
    return _model_tool_calls_from_json_envelope(dsml_text)


def _tool_call_index(
    aggregated: dict[int, dict[str, str]], raw: dict[str, Any]
) -> int:
    """Merge Responses' duplicate tool-call views before validating calls."""
    raw_id = raw.get("id")
    if raw_id:
        for index, entry in aggregated.items():
            if entry["id"] == str(raw_id):
                return index
    raw_index = raw.get("index")
    if raw_index is not None:
        try:
            return int(raw_index)
        except (TypeError, ValueError) as exc:
            raise ModelToolCallInvalid("tool call index is invalid") from exc
    if len(aggregated) == 1:
        return next(iter(aggregated))
    return max(aggregated, default=-1) + 1


def _repair_json_arguments(text: str) -> dict[str, Any] | None:
    """尽力修复 provider 流式聚合出的坏参数 JSON。

    覆盖两类已知形态：完整对象后跟重复/残余片段（取第一个完整对象），
    以及被截断的未闭合对象（按栈补全闭合符）。修不出字典则返回 None。
    """
    if not text:
        return None
    stripped = text.strip()
    decoder = json.JSONDecoder()
    first: dict[str, Any] | None = None
    idx = 0
    while idx < len(stripped):
        while idx < len(stripped) and stripped[idx] in " \t\r\n":
            idx += 1
        if idx >= len(stripped):
            break
        try:
            value, end = decoder.raw_decode(stripped, idx)
        except json.JSONDecodeError:
            break
        if isinstance(value, dict):
            first = value if first is None else first
            return first
        idx = end
    return _close_unbalanced_json(stripped)


def _close_unbalanced_json(text: str) -> dict[str, Any] | None:
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if stack:
                stack.pop()
    if in_string:
        text += '"'
    for opener in reversed(stack):
        text += "}" if opener == "{" else "]"
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _model_tool_calls_from_dsml(text: str) -> tuple[ModelToolCall, ...]:
    if not text or not text.startswith(_DSML_TOOL_CALLS):
        return ()
    if not text.endswith(_DSML_TOOL_CALLS):
        raise ModelToolCallInvalid("DSML tool call envelope is incomplete")

    body = text[len(_DSML_TOOL_CALLS) : -len(_DSML_TOOL_CALLS)].strip()
    if not body:
        raise ModelToolCallInvalid("DSML tool call envelope is empty")

    calls: list[ModelToolCall] = []
    cursor = 0
    while cursor < len(body):
        cursor = _skip_ascii_whitespace(body, cursor)
        opening = _DSML_INVOKE_OPEN.match(body, cursor)
        if opening is None:
            raise ModelToolCallInvalid("DSML invoke header is invalid")
        name = opening.group("name")
        cursor = opening.end()
        arguments: dict[str, Any] = {}
        while True:
            cursor = _skip_ascii_whitespace(body, cursor)
            if body.startswith(_DSML_INVOKE_CLOSE, cursor):
                cursor += len(_DSML_INVOKE_CLOSE)
                break
            parameter = _DSML_PARAMETER_OPEN.match(body, cursor)
            if parameter is None:
                raise ModelToolCallInvalid("DSML parameter header is invalid")
            parameter_name = parameter.group("name")
            if parameter_name in arguments:
                raise ModelToolCallInvalid("DSML parameter is duplicated")
            cursor = parameter.end()
            end = body.find(_DSML_PARAMETER_CLOSE, cursor)
            if end < 0:
                raise ModelToolCallInvalid("DSML parameter is incomplete")
            value = html.unescape(body[cursor:end])
            if "\x00" in value or len(value.encode("utf-8")) > _MAX_DSML_ARGUMENT_BYTES:
                raise ModelToolCallInvalid("DSML parameter exceeds the limit")
            arguments[parameter_name] = value
            cursor = end + len(_DSML_PARAMETER_CLOSE)
        if not arguments:
            raise ModelToolCallInvalid("DSML invoke has no parameters")
        calls.append(ModelToolCall(f"dsml-call-{len(calls) + 1}", name, arguments))
    return tuple(calls)


def _model_tool_calls_from_json_envelope(text: str) -> tuple[ModelToolCall, ...]:
    if not text or not text.startswith("AI执行轨迹+"):
        return ()
    match = _JSON_TOOL_CALL_ENVELOPE.fullmatch(text)
    if match is None:
        raise ModelToolCallInvalid("JSON tool call envelope is invalid")
    body = match.group("body")
    if len(body.encode("utf-8")) > _MAX_DSML_ARGUMENT_BYTES or "\x00" in body:
        raise ModelToolCallInvalid("JSON tool call envelope exceeds the limit")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ModelToolCallInvalid("JSON tool call envelope is invalid") from exc
    if not isinstance(payload, dict) or set(payload) - {"id", "tool", "args"}:
        raise ModelToolCallInvalid("JSON tool call envelope fields are invalid")
    name = payload.get("tool")
    arguments = payload.get("args")
    if not isinstance(name, str) or not name or not isinstance(arguments, dict):
        raise ModelToolCallInvalid("JSON tool call envelope is missing fields")
    call_id = payload.get("id") or "json-call-1"
    if not isinstance(call_id, str) or not call_id:
        raise ModelToolCallInvalid("JSON tool call envelope id is invalid")
    encoded_arguments = json.dumps(arguments, ensure_ascii=False)
    if "\x00" in encoded_arguments or len(encoded_arguments.encode("utf-8")) > _MAX_DSML_ARGUMENT_BYTES:
        raise ModelToolCallInvalid("JSON tool call arguments exceed the limit")
    return (ModelToolCall(call_id, name, arguments),)


def _skip_ascii_whitespace(text: str, cursor: int) -> int:
    while cursor < len(text) and text[cursor] in " \t\r\n":
        cursor += 1
    return cursor


def _chunk_text(chunk: Any) -> str:
    if isinstance(chunk, str):
        return chunk
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            value = item.get("text", item.get("content"))
            if isinstance(value, str):
                parts.append(value)
    return "".join(parts)


def model_tool_calls_from_message(message: Any) -> tuple[ModelToolCall, ...]:
    """从非流式消息对象提取归一化 tool calls。"""
    calls: list[ModelToolCall] = []
    for raw in getattr(message, "tool_calls", None) or ():
        if not isinstance(raw, dict):
            continue
        tool_call_id = raw.get("id") or raw.get("tool_call_id")
        name = raw.get("name") or raw.get("tool_name")
        if not tool_call_id or not name:
            raise ModelToolCallInvalid("tool call missing id or name")
        arguments = raw.get("args", raw.get("arguments", {}))
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ModelToolCallInvalid(
                    "tool call arguments are not valid JSON"
                ) from exc
        if not isinstance(arguments, dict):
            raise ModelToolCallInvalid("tool call arguments must be an object")
        calls.append(ModelToolCall(str(tool_call_id), str(name), arguments))
    return tuple(calls)
