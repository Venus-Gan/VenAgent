# handler — HTTP API 路由处理（FastAPI + Pydantic + CORS）
import asyncio
import hashlib
import json
import logging
import os
import threading
import uuid
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config.config import APIConfig
from internal.agent.agent import ChatOptions, Response, UnifiedAgent
from internal.document.library import DOCUMENT_SOURCE_UPLOAD, WriteRequest
from internal.document.parser import parse_bytes
from internal.infra.infra import Infrastructure
from internal.tools.mcp_catalog import normalize_tool_params

logger = logging.getLogger(__name__)

# ─── 请求 / 响应 模型 ──────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户输入")
    use_rag: bool = False
    selected_tools: Optional[List[str]] = None
    explicit: bool = False


class MCPParam(BaseModel):
    name: str
    description: str = ""
    required: bool = False


class MCPRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    endpoint: str = Field(..., min_length=1)
    params: List[Dict[str, Any]] = Field(default_factory=list)


class DocsDeleteRequest(BaseModel):
    doc_hash: str = Field(..., min_length=1)


class UploadJSONRequest(BaseModel):
    content: str = Field(..., min_length=1)


# ─── 工具函数 ───────────────────────────────────────────────────────────────

def _response_to_dict(resp: Response) -> Dict[str, Any]:
    return {
        "query": resp.query,
        "answer": resp.answer,
        "mode": resp.mode,
        "steps": [
            {
                "type": s.type,
                "content": s.content,
                "tool": s.tool,
                "params": s.params,
            }
            for s in resp.steps
        ],
        "tool_call": resp.tool_call,
        "search_results": [_rag_result_to_main_contract(r) for r in resp.search_results],
        "task": resp.task,
        "extracted_info": resp.extracted_info,
        "short_term_count": resp.short_term_count,
        "long_term_count": resp.long_term_count,
        "preferences": resp.preferences,
        "interrupted": resp.interrupted,
        "success": True,
    }


def _rag_result_to_main_contract(result: Dict[str, Any]) -> Dict[str, Any]:
    content = result.get("content", "")
    score = result.get("score", result.get("similarity", 0.0))
    try:
        similarity = float(score)
    except Exception:
        similarity = 0.0
    return {
        **result,
        "content": content,
        "score": score,
        "similarity": similarity,
        "chunk": result.get("chunk") or {"content": content},
        "source": result.get("source", "unknown"),
    }


def _tool_to_main_contract(tool: Dict[str, Any]) -> Dict[str, Any]:
    """工具参数转前端契约格式：工具参数字段叫 params。"""
    params = tool.get("params")
    if params is None:
        params = tool.get("parameters", [])
    return {
        "name": tool.get("name", ""),
        "description": tool.get("description", tool.get("desc", "")),
        "is_mcp": tool.get("is_mcp", False),
        "params": params or [],
    }


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _jsonable(value: Any) -> Any:
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return _jsonable(asdict(value))
    return value


def _normalize_ingest_result(result: Any, text: str, document_id: str = "", version_id: str = "", section: str = "") -> Dict[str, Any]:
    doc_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""
    if isinstance(result, tuple):
        chunk_count = result[0] if len(result) > 0 else 0
        if len(result) > 1 and result[1]:
            doc_hash = result[1]
    elif isinstance(result, dict):
        out = dict(result)
        out.setdefault("chunk_count", 0)
        out.setdefault("doc_hash", doc_hash)
        if document_id:
            out.setdefault("document_id", document_id)
        if version_id:
            out.setdefault("version_id", version_id)
        if section:
            out.setdefault("section", section)
        return out
    else:
        chunk_count = result or 0
    return {
        "chunk_count": int(chunk_count or 0),
        "parent_count": 0,
        "indexed_count": int(chunk_count or 0),
        "doc_hash": doc_hash,
        "document_id": document_id,
        "version_id": version_id,
        "section": section,
    }


# ─── 路由组装 ───────────────────────────────────────────────────────────────

def setup_routes(agent: UnifiedAgent, inf: Infrastructure, cfg: APIConfig) -> FastAPI:
    app = FastAPI(title="AGI Assistant", version="1.0")

    # CORS：开发期允许全部，生产可由 cfg.cors_origins 收紧
    origins = getattr(cfg, "cors_origins", None) or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "milvus": inf.ready.milvus,
            "postgresql": inf.ready.postgresql,
            "elasticsearch": inf.ready.elasticsearch,
            "kafka": inf.ready.kafka,
        }

    @app.post("/api/chat")
    async def chat(req: ChatRequest):
        try:
            opts = ChatOptions(
                use_rag=req.use_rag,
                selected_tools=req.selected_tools,
                explicit=req.explicit,
            )
            resp = agent.process_with_options(req.message, opts)
            return _response_to_dict(resp)
        except HTTPException:
            raise
        except Exception as e:
            logger.error("聊天接口错误: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/chat/stream")
    async def chat_stream(req: ChatRequest):
        """SSE 流式：chat 模式转发 LLM 真 token，复杂模式保持兼容路径。"""

        opts = ChatOptions(
            use_rag=req.use_rag,
            selected_tools=req.selected_tools,
            explicit=req.explicit,
        )
        request_id = uuid.uuid4().hex

        registry = getattr(agent, "_cancel_registry", None)
        if registry is not None:
            token, unregister = registry.register()
        else:
            token = SimpleNamespace(is_cancelled=lambda: False, cancel=lambda: None)
            unregister = lambda: None

        async def _generate():
            loop = asyncio.get_running_loop()
            events: asyncio.Queue[tuple] = asyncio.Queue(maxsize=256)
            emitted_singleton_events = set()
            streamed_parts: List[str] = []
            closed = threading.Event()

            def _with_request_id(payload: Dict[str, Any]) -> Dict[str, Any]:
                return {**payload, "request_id": request_id}

            def _put_event(item: tuple) -> None:
                if closed.is_set():
                    return
                if token.is_cancelled() and item[0] not in {"response", "error"}:
                    return
                try:
                    events.put_nowait(item)
                except asyncio.QueueFull:
                    token.cancel()
                    if item[0] in {"response", "error"}:
                        try:
                            events.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        try:
                            events.put_nowait(item)
                        except asyncio.QueueFull:
                            pass

            def _send_from_worker(item: tuple) -> None:
                loop.call_soon_threadsafe(_put_event, item)

            def _on_token(content: str) -> None:
                _send_from_worker(("token", content))

            def _on_event(event: str, payload: Dict[str, Any]) -> None:
                _send_from_worker(("event", event, _with_request_id(payload)))

            def _worker() -> None:
                try:
                    if hasattr(agent, "process_stream_with_options"):
                        resp = agent.process_stream_with_options(
                            req.message,
                            opts,
                            token,
                            on_token=_on_token,
                            on_event=_on_event,
                        )
                    elif hasattr(agent, "_dispatch") and registry is not None:
                        resp = agent._dispatch(req.message, opts, token)
                    else:
                        resp = agent.process_with_options(req.message, opts)
                    _send_from_worker(("response", resp))
                except Exception as e:
                    logger.exception("流式聊天执行失败 request_id=%s", request_id)
                    _send_from_worker(("error", e))

            thread = threading.Thread(target=_worker, name=f"chat-stream:{request_id}", daemon=True)
            thread.start()

            yield _sse("start", {"message": req.message, "request_id": request_id})
            try:
                while True:
                    item = await events.get()
                    kind = item[0]
                    if kind == "event":
                        _, event_name, payload = item
                        if event_name in {"route", "memory"}:
                            emitted_singleton_events.add(event_name)
                        yield _sse(event_name, payload)
                    elif kind == "token":
                        _, content = item
                        streamed_parts.append(content)
                        yield _sse("token", {"content": content, "request_id": request_id})
                    elif kind == "response":
                        _, resp = item
                        data = _with_request_id(_response_to_dict(resp))
                        if token.is_cancelled():
                            data["interrupted"] = True

                        if "route" not in emitted_singleton_events:
                            yield _sse("route", {"mode": resp.mode, "request_id": request_id})
                        if resp.extracted_info and "memory" not in emitted_singleton_events:
                            yield _sse("memory", {"extracted_info": resp.extracted_info, "request_id": request_id})
                        for step in resp.steps:
                            yield _sse("step", {
                                "type": step.type,
                                "content": step.content,
                                "tool": step.tool,
                                "params": step.params,
                                "request_id": request_id,
                            })
                        if resp.tool_call:
                            yield _sse("tool_call", _with_request_id(resp.tool_call))
                        if resp.search_results:
                            yield _sse("rag_result", {
                                "search_results": data["search_results"],
                                "request_id": request_id,
                            })

                        streamed_text = "".join(streamed_parts)
                        if resp.answer and not data["interrupted"]:
                            suffix = ""
                            if not streamed_text:
                                suffix = resp.answer
                            elif resp.answer.startswith(streamed_text):
                                suffix = resp.answer[len(streamed_text):]
                            for ch in suffix:
                                if token.is_cancelled():
                                    data["interrupted"] = True
                                    break
                                yield _sse("token", {"content": ch, "request_id": request_id})
                                await asyncio.sleep(0)

                        yield _sse("done", data)
                        yield "data: [DONE]\n\n"
                        return
                    elif kind == "error":
                        yield _sse("done", {
                            "answer": "请求失败，请稍后重试",
                            "interrupted": False,
                            "success": False,
                            "request_id": request_id,
                        })
                        yield "data: [DONE]\n\n"
                        return
            finally:
                closed.set()
                try:
                    token.cancel()
                except Exception:
                    pass
                try:
                    unregister()
                except Exception:
                    pass
                if thread.is_alive():
                    await asyncio.to_thread(thread.join, 0.5)

        return StreamingResponse(_generate(), media_type="text/event-stream")

    @app.post("/api/chat/cancel")
    async def chat_cancel():
        try:
            agent.cancel()
            return {"ok": True, "message": "已发送取消信号"}
        except Exception as e:
            logger.error("取消失败: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/docs/delete")
    async def docs_delete(req: DocsDeleteRequest):
        try:
            rag = getattr(agent, "rag", None)
            if rag and hasattr(rag, "delete"):
                rag.delete(req.doc_hash)
            return {"ok": True, "doc_hash": req.doc_hash}
        except HTTPException:
            raise
        except Exception as e:
            logger.error("删除文档失败: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/upload")
    async def upload(request: Request):
        try:
            content_type = request.headers.get("content-type", "")
            filename = "upload.txt"
            upload_content_type = "text/plain"
            if "application/json" in content_type:
                payload = await request.json()
                raw_text = str((payload or {}).get("content", ""))
                parsed = parse_bytes(filename, upload_content_type, raw_text.encode("utf-8"))
            else:
                form = await request.form()
                file = form.get("file")
                if file is None:
                    raise HTTPException(status_code=400, detail="缺少 file 或 content")
                content = await file.read()
                filename = getattr(file, "filename", None) or filename
                upload_content_type = getattr(file, "content_type", None) or upload_content_type
                parsed = parse_bytes(filename, upload_content_type, content)

            text = parsed.content
            if parsed.needs_ocr:
                return {
                    "filename": parsed.filename,
                    "content_type": parsed.content_type,
                    "parser": parsed.parser,
                    "pages": parsed.pages,
                    "text_chars": parsed.text_chars,
                    "needs_ocr": True,
                    "chunk_count": 0,
                    "parent_count": 0,
                    "indexed_count": 0,
                    "doc_hash": "",
                    "chunks": None,
                    "message": "PDF 文本抽取结果过少，可能是扫描件，需要 OCR 后再入库",
                }
            if not text.strip():
                return {"chunk_count": 0, "doc_hash": "", "success": False, "message": "文件内容为空"}
            doc_result = None
            ingest_result = None
            if hasattr(agent, "write_document"):
                doc_result = agent.write_document(
                    WriteRequest(
                        title=filename,
                        doc_type="upload",
                        source=DOCUMENT_SOURCE_UPLOAD,
                        created_by="user",
                        content_md=text,
                        metadata={
                            "filename": parsed.filename,
                            "content_type": parsed.content_type,
                            "parser": parsed.parser,
                            "pages": parsed.pages,
                            "text_chars": parsed.text_chars,
                        },
                    ),
                    True,
                )
                ingest_result = (doc_result or {}).get("ingest")
            else:
                ingest_result = agent.rag_ingest(text)
            doc_json = _jsonable((doc_result or {}).get("document")) if isinstance(doc_result, dict) else None
            ver_json = _jsonable((doc_result or {}).get("version")) if isinstance(doc_result, dict) else None
            ingest = _normalize_ingest_result(
                ingest_result,
                text,
                document_id=(doc_json or {}).get("id", "") if isinstance(doc_json, dict) else "",
                version_id=(ver_json or {}).get("id", "") if isinstance(ver_json, dict) else "",
                section="upload",
            )
            return {
                "filename": parsed.filename,
                "content_type": parsed.content_type,
                "parser": parsed.parser,
                "pages": parsed.pages,
                "text_chars": parsed.text_chars,
                "needs_ocr": parsed.needs_ocr,
                "chunk_count": ingest.get("chunk_count", 0),
                "parent_count": ingest.get("parent_count", 0),
                "indexed_count": ingest.get("indexed_count", ingest.get("chunk_count", 0)),
                "chunk_preview": ingest.get("chunk_preview"),
                "doc_hash": ingest.get("doc_hash", ""),
                "chunks": ingest.get("chunks"),
                "document": doc_json,
                "version": ver_json,
                "success": True,
            }
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error("上传接口错误: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/documents")
    async def documents_list():
        try:
            docs = _jsonable(agent.list_documents())
            store = getattr(getattr(getattr(agent, "inf", None), "repo", None), "documents", None)
            if store is None:
                store = getattr(getattr(inf, "repo", None), "documents", None)
            if store is not None and hasattr(store, "get_version"):
                enriched = []
                for doc in docs or []:
                    latest_metadata = {}
                    latest_content_chars = 0
                    latest_parser = ""
                    try:
                        latest_version_id = str((doc or {}).get("latest_version_id", "") or "")
                        if latest_version_id:
                            ver = _jsonable(store.get_version(latest_version_id))
                            if isinstance(ver, dict):
                                latest_metadata = ver.get("metadata") or {}
                                latest_content_chars = len(str(ver.get("content_md", "") or ""))
                                latest_parser = str((latest_metadata or {}).get("parser", "") or "")
                    except Exception:
                        latest_metadata = {}
                    item = dict(doc or {})
                    item["latest_metadata"] = latest_metadata
                    item["latest_content_chars"] = latest_content_chars
                    item["latest_parser"] = latest_parser
                    enriched.append(item)
                docs = enriched
            return {"documents": docs}
        except Exception as e:
            logger.error("文档列表失败: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/documents")
    async def documents_write(request: Request):
        try:
            payload = await request.json()
            res = agent.write_document(
                WriteRequest(
                    document_id=str((payload or {}).get("document_id", "") or ""),
                    title=str((payload or {}).get("title", "") or ""),
                    doc_type=str((payload or {}).get("doc_type", "") or ""),
                    source=str((payload or {}).get("source", "") or ""),
                    created_by=str((payload or {}).get("created_by", "") or ""),
                    content_md=str((payload or {}).get("content_md", "") or ""),
                    summary=str((payload or {}).get("summary", "") or ""),
                    metadata=(payload or {}).get("metadata") or {},
                ),
                bool((payload or {}).get("ingest_to_rag")),
            )
            out = _jsonable(res)
            if isinstance(out, dict) and "ingest" in out and not isinstance(out.get("ingest"), dict):
                version = out.get("version") or {}
                document = out.get("document") or {}
                out["ingest"] = _normalize_ingest_result(
                    out.get("ingest"),
                    str(version.get("content_md", "")) if isinstance(version, dict) else "",
                    document_id=str(document.get("id", "")) if isinstance(document, dict) else "",
                    version_id=str(version.get("id", "")) if isinstance(version, dict) else "",
                    section=str(document.get("doc_type", "")) if isinstance(document, dict) else "",
                )
            return out
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error("文档写入失败: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/documents/{document_id}")
    async def documents_get(document_id: str):
        try:
            return _jsonable(agent.get_document(document_id))
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            logger.error("读取文档失败: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/documents/{document_id}/ingest")
    async def documents_ingest(document_id: str, request: Request):
        try:
            payload = {}
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            version_id = str((payload or {}).get("version_id", "") or "")
            res = _jsonable(agent.ingest_document(document_id, version_id))
            if not isinstance(res, dict):
                res = _normalize_ingest_result(
                    res,
                    "",
                    document_id=document_id,
                    version_id=version_id,
                    section="document",
                )
            return res
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error("文档入库失败: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/tools/mcp")
    async def register_mcp_tool(req: MCPRegisterRequest):
        try:
            name = req.name.strip()
            description = req.description.strip()
            endpoint = req.endpoint.strip()
            if not name or not endpoint:
                raise HTTPException(status_code=400, detail="缺少 name 或 endpoint 参数")

            def _mcp_func(args: Dict[str, str]) -> str:
                return f"MCP 工具 {name} 已注册，端点: {endpoint}，参数: {args}"

            agent.register_mcp_tool(name, description, normalize_tool_params(req.params), _mcp_func)
            return {"success": True, "ok": True}
        except HTTPException:
            raise
        except Exception as e:
            logger.error("注册 MCP 工具失败: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/status")
    async def status():
        return {"status": "running", **agent.status()}

    @app.get("/api/tools")
    async def tools():
        return agent.get_tools()

    @app.get("/api/memory")
    async def memory():
        return {
            "short_term_turns": agent.stm.count(),
            "long_term_count": len(agent.ltm.items),
            "preferences": agent.preference.get_all(),
        }

    @app.get("/api/snapshots")
    async def snapshots(limit: int = 50):
        try:
            return {"snapshots": inf.repo.snapshot.list(limit=limit), "success": True}
        except Exception as e:
            logger.error("加载快照失败: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    # 静态前端：仅在目录存在时挂载，避免容器内缺失目录直接崩
    frontend_dir = os.environ.get("FRONTEND_DIR", "frontend")
    if os.path.isdir(frontend_dir):
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    else:
        logger.warning("⚠️  frontend 目录不存在: %s（跳过静态挂载）", frontend_dir)

    return app
