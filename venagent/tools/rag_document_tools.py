"""rag_search 与文档工具（write/list/read）的描述符与执行体。

设计要点（M07 定稿 Q13/Q14）：
- rag_search：safe 定级 + RAG Loaded 前置检查（不可用时目录层面隐藏）；
- 文档三件套：write_document 落库即索引（M08 语义，无 ingest_to_rag 开关），
  delete/reingest 不做工具，留在 HTTP API 管理面；
- 全部经 ToolGateway 执行（子 Agent 与基线图共用同一权威边界）。
"""

from __future__ import annotations

import json
from typing import Any

from .models import ToolDescriptor, ToolResult

_RAG_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": 512},
    },
    "required": ["query"],
    "additionalProperties": False,
}

_WRITE_DOCUMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "filename": {"type": "string", "minLength": 1, "maxLength": 200},
        "title": {"type": "string", "maxLength": 200},
        "content": {"type": "string", "minLength": 1, "maxLength": 1_000_000},
    },
    "required": ["filename", "content"],
    "additionalProperties": False,
}

_LIST_DOCUMENTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

_READ_DOCUMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "document_id": {"type": "string", "minLength": 1, "maxLength": 100},
    },
    "required": ["document_id"],
    "additionalProperties": False,
}


def rag_search_descriptor(*, available: bool) -> ToolDescriptor:
    return ToolDescriptor(
        tool_id="rag_search",
        public_name="rag_search",
        source="native",
        description=(
            "检索用户私有知识库（三路混合检索），返回带引用编号的相关片段。"
            "回答知识库/文档类问题时优先使用。"
        ),
        input_schema=_RAG_SEARCH_SCHEMA,
        risk="safe",
        exposed=available,
        unavailable_reason=None if available else "rag_unavailable",
    )


def write_document_descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        tool_id="write_document",
        public_name="write_document",
        source="native",
        description=(
            "把 Markdown 文本写入当前用户的本地文档库并自动进入知识库索引，"
            "之后可被 rag_search 检索。"
        ),
        input_schema=_WRITE_DOCUMENT_SCHEMA,
        risk="safe",
    )


def list_documents_descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        tool_id="list_documents",
        public_name="list_documents",
        source="native",
        description="列出当前用户文档库中的文档（id、标题与状态）。",
        input_schema=_LIST_DOCUMENTS_SCHEMA,
        risk="safe",
    )


def read_document_descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        tool_id="read_document",
        public_name="read_document",
        source="native",
        description="按 document_id 读取文档最新版本的正文。",
        input_schema=_READ_DOCUMENT_SCHEMA,
        risk="safe",
    )


async def execute_rag_search(
    rag_search: Any,
    descriptor: ToolDescriptor,
    arguments: dict[str, Any],
    run_id: str,
    owner_id: str,
) -> ToolResult:
    del descriptor
    if rag_search is None or rag_search.mode == "unavailable":
        return _error_result(arguments, "rag_unavailable", "知识库检索不可用。")
    query = str(arguments.get("query", "")).strip()
    if not query:
        return _error_result(arguments, "rag_query_required", "query 不能为空。")
    try:
        result = await _call_search(rag_search, owner_id, query)
    except Exception as exc:  # noqa: BLE001
        return _error_result(arguments, "rag_search_failed", f"检索失败：{exc}")
    if result.mode == "unavailable":
        return _error_result(arguments, "rag_unavailable", "知识库检索不可用。")
    if not result.sources:
        return _empty(arguments, result.mode, "知识库中未找到相关内容。")
    context = "\n\n".join(
        f"[{index + 1}] {source.parent_content or source.chunk_content}"
        for index, source in enumerate(result.sources)
    )
    citations = [
        {
            "index": index + 1,
            "document_id": source.document_id,
            "title": source.title,
            "section": source.section,
        }
        for index, source in enumerate(result.sources)
    ]
    summary = f"命中 {len(result.sources)} 个片段（{result.mode}）"
    return ToolResult(
        tool_call_id="",
        operation_id="",
        status="success",
        summary=summary,
        content=json.dumps(
            {
                "mode": result.mode,
                "degraded": list(result.degraded),
                "context": context,
                "citations": citations,
                "hint": "回答时用 [n] 引用上述编号；不要编造编号之外的内容。",
            },
            ensure_ascii=False,
        ),
    )


async def execute_write_document(
    document_service: Any,
    descriptor: ToolDescriptor,
    arguments: dict[str, Any],
    run_id: str,
    owner_id: str,
) -> ToolResult:
    del descriptor, run_id
    if document_service is None:
        return _error_result(arguments, "document_unavailable", "文档库不可用（需持久化模式）。")
    filename = str(arguments.get("filename", "")).strip()
    content = str(arguments.get("content", ""))
    title = arguments.get("title")
    if not filename or not content:
        return _error_result(arguments, "document_invalid", "filename 与 content 必填。")
    try:
        record = await _call_upload(
            document_service,
            owner_id,
            filename=filename,
            content=content.encode("utf-8"),
            title=title if isinstance(title, str) and title.strip() else None,
            source="agent_generated",
        )
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "document_write_failed")
        return _error_result(arguments, code, f"文档写入失败：{exc}")
    return ToolResult(
        tool_call_id="",
        operation_id="",
        status="success",
        summary=f"文档已入库并索引：{record.title}（chunk {record.chunk_count or 0}）",
        content=json.dumps(
            {
                "document_id": record.document_id,
                "title": record.title,
                "status": record.status,
                "chunk_count": record.chunk_count,
                "indexed_count": record.indexed_count,
            },
            ensure_ascii=False,
        ),
    )


async def execute_list_documents(
    document_service: Any,
    descriptor: ToolDescriptor,
    arguments: dict[str, Any],
    run_id: str,
    owner_id: str,
) -> ToolResult:
    del descriptor, run_id, arguments
    if document_service is None:
        return _error_result({}, "document_unavailable", "文档库不可用（需持久化模式）。")
    try:
        documents = await _call_list(document_service, owner_id)
    except Exception as exc:  # noqa: BLE001
        return _error_result({}, "document_list_failed", f"文档列表失败：{exc}")
    payload = [
        {
            "document_id": item.document_id,
            "title": item.title,
            "status": item.status,
        }
        for item in documents[:50]
    ]
    return ToolResult(
        tool_call_id="",
        operation_id="",
        status="success",
        summary=f"共 {len(payload)} 篇文档",
        content=json.dumps(payload, ensure_ascii=False),
    )


async def execute_read_document(
    document_service: Any,
    descriptor: ToolDescriptor,
    arguments: dict[str, Any],
    run_id: str,
    owner_id: str,
) -> ToolResult:
    del descriptor, run_id
    if document_service is None:
        return _error_result(arguments, "document_unavailable", "文档库不可用（需持久化模式）。")
    document_id = str(arguments.get("document_id", "")).strip()
    if not document_id:
        return _error_result(arguments, "document_invalid", "document_id 必填。")
    try:
        record = await _call_get(document_service, owner_id, document_id)
    except Exception as exc:  # noqa: BLE001
        return _error_result(arguments, "document_read_failed", f"文档读取失败：{exc}")
    if record is None:
        return _error_result(arguments, "document_not_found", "文档不存在。")
    version = await _call_latest_version(document_service, owner_id, document_id)
    content = getattr(version, "content_md", "") or ""
    return ToolResult(
        tool_call_id="",
        operation_id="",
        status="success",
        summary=f"读取文档：{record.title}",
        content=content[:20000],
    )


async def _call_search(rag_search: Any, owner_id: str, query: str) -> Any:
    import asyncio

    return await asyncio.to_thread(rag_search.search, owner_id, query)


async def _call_upload(document_service: Any, owner_id: str, **kwargs: Any) -> Any:
    import asyncio

    return await asyncio.to_thread(document_service.upload, owner_id, **kwargs)


async def _call_list(document_service: Any, owner_id: str) -> Any:
    import asyncio

    return await asyncio.to_thread(document_service.list, owner_id)


async def _call_get(document_service: Any, owner_id: str, document_id: str) -> Any:
    import asyncio

    return await asyncio.to_thread(document_service.get, owner_id, document_id)


async def _call_latest_version(document_service: Any, owner_id: str, document_id: str) -> Any:
    import asyncio

    return await asyncio.to_thread(document_service.latest_version, owner_id, document_id)


def _error_result(arguments: dict[str, Any], code: str, message: str) -> ToolResult:
    del arguments
    return ToolResult(
        tool_call_id="",
        operation_id="",
        status="error",
        summary=message,
        content="",
        error=code,
    )


def _empty(arguments: dict[str, Any], mode: str, message: str) -> ToolResult:
    del arguments
    return ToolResult(
        tool_call_id="",
        operation_id="",
        status="success",
        summary=message,
        content=json.dumps({"mode": mode, "context": "", "citations": []}, ensure_ascii=False),
    )
