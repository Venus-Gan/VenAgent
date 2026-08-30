"""DSML / responses 工具调用协议解析契约（M06 单点）。

这些测试只断言「chunk 流 → ModelToolCall 归一化」这一个契约面；
闭环执行/审批/沙箱时序分别在 test_agent_tool_loop.py、
test_agent_sandbox_lifecycle.py 各自单点断言。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessageChunk

from src.tools.langchain import ModelToolCallInvalid, model_tool_calls_from_chunks
from src.tools.models import ModelToolCall


def test_deepseek_dsml_responses_tool_call_is_normalized() -> None:
    dsml = (
        '<｜｜DSML｜｜tool_calls>\n'
        '<｜｜DSML｜｜invoke name="exec_command">\n'
        '<｜｜DSML｜｜parameter name="command" string="true">'
        'printf M06_REAL_TOOL_marker'
        '<｜｜DSML｜｜parameter>\n'
        '<｜｜DSML｜｜invoke>\n'
        '<｜｜DSML｜｜tool_calls>'
    )
    chunks = tuple(AIMessageChunk(content=part) for part in (dsml[:70], dsml[70:]))
    calls = model_tool_calls_from_chunks(chunks)
    assert calls == (
        ModelToolCall(
            id="dsml-call-1",
            name="exec_command",
            arguments={"command": "printf M06_REAL_TOOL_marker"},
        ),
    )


def test_responses_duplicate_tool_call_views_are_merged_by_id() -> None:
    chunks = (
        AIMessageChunk(
            content=[
                {
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": "",
                    "call_id": "call_1",
                    "index": 1,
                }
            ],
            tool_call_chunks=[
                {"name": "exec_command", "args": "", "id": "call_1", "index": 1}
            ],
        ),
        AIMessageChunk(
            content=[{"type": "function_call", "arguments": '{"command":"printf marker"}', "index": 1}],
            tool_call_chunks=[
                {"name": None, "args": '{"command":"printf marker"}', "id": None, "index": 1}
            ],
        ),
    )
    assert model_tool_calls_from_chunks(chunks) == (
        ModelToolCall("call_1", "exec_command", {"command": "printf marker"}),
    )


def test_dsml_parser_rejects_incomplete_or_unbounded_calls() -> None:
    with pytest.raises(ModelToolCallInvalid, match="incomplete"):
        model_tool_calls_from_chunks(
            (AIMessageChunk(content="<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke"),)
        )


def test_responses_json_tool_envelope_is_normalized_only_with_protocol_prefix() -> None:
    chunks = (
        AIMessageChunk(
            content=(
                'AI执行轨迹+```json\n'
                '{"tool":"exec_command","args":{"command":"printf marker"}}'
                '\n```'
            )
        ),
    )
    assert model_tool_calls_from_chunks(chunks) == (
        ModelToolCall("json-call-1", "exec_command", {"command": "printf marker"}),
    )
    assert model_tool_calls_from_chunks((AIMessageChunk(content='{"tool":"exec_command"}'),)) == ()
    oversized = "x" * (64 * 1024 + 1)
    with pytest.raises(ModelToolCallInvalid, match="exceeds"):
        model_tool_calls_from_chunks(
            (
                AIMessageChunk(
                    content=(
                        '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="exec_command">'
                        '<｜｜DSML｜｜parameter name="command" string="true">'
                        f"{oversized}<｜｜DSML｜｜parameter>"
                        '<｜｜DSML｜｜invoke><｜｜DSML｜｜tool_calls>'
                    )
                ),
            )
        )