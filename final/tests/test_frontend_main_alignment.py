import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from config.config import APIConfig
from internal.agent.agent import Response
from internal.handler.handler import setup_routes
from internal.tools.tools import Tool


class _Agent:
    def __init__(self):
        self.cancelled = False
        self.uploaded = ""
        self.deleted = ""
        self.tool = Tool(
            name="rag_search",
            description="从私人黑洞检索",
            params=[{"name": "query", "type": "string", "description": "问题"}],
            func=lambda _args: "ok",
        )

    def process_with_options(self, message, _opts):
        return Response(query=message, answer="回答:" + message, mode="chat")

    def process_stream_with_options(self, message, _opts, _token, on_token=None, on_event=None):
        if on_event:
            on_event("route", {"mode": "chat"})
        if on_token:
            on_token("流")
            on_token("式")
        return Response(query=message, answer="流式", mode="chat")

    def cancel(self):
        self.cancelled = True

    def rag_ingest(self, document):
        self.uploaded = document
        return 3, "fake-doc-hash"

    def get_tools(self):
        return [
            {
                "name": self.tool.name,
                "description": self.tool.description,
                "params": self.tool.params,
                "is_mcp": False,
            }
        ]

    def rag_query(self, question):
        return "知识库回答:" + question, [{"content": "片段", "score": 0.8, "source": "test"}]


class _SnapshotRepo:
    def list(self, limit=50):
        return []


class _RagchunkRepo:
    def __init__(self, infra):
        self.infra = infra

    def delete_by_doc_hash(self, doc_hash):
        self.infra.deleted = doc_hash
        return [1]


class _Infra:
    ready = SimpleNamespace(
        milvus="connected",
        postgresql="connected",
        elasticsearch="connected",
        kafka="disconnected",
    )

    def __init__(self):
        self.deleted = ""
        self.repo = SimpleNamespace(
            snapshot=_SnapshotRepo(),
            ragchunk=_RagchunkRepo(self),
        )


def _client():
    cfg = APIConfig()
    cfg.llm_model = "llm"
    cfg.embedding_model = "embedding"
    return setup_routes(_Agent(), _Infra(), cfg)


class _LegacyUploadAgent(_Agent):
    def rag_ingest(self, document):
        self.uploaded = document
        return 3


def _legacy_upload_client():
    cfg = APIConfig()
    cfg.llm_model = "llm"
    cfg.embedding_model = "embedding"
    return setup_routes(_LegacyUploadAgent(), _Infra(), cfg)


def _request(app, method, path, body=b"", content_type="application/json"):
    async def _run():
        sent = False
        messages = []
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"content-type", content_type.encode())],
            "client": ("test", 1),
            "server": ("testserver", 80),
            "scheme": "http",
        }

        async def receive():
            nonlocal sent
            if sent:
                await asyncio.sleep(1.0)
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        await app(scope, receive, send)
        status = next(m["status"] for m in messages if m["type"] == "http.response.start")
        payload = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        return status, payload

    return asyncio.run(_run())


def test_tools_endpoint_matches_main_frontend_contract():
    status, payload = _request(_client(), "GET", "/api/tools")

    assert status == 200
    data = json.loads(payload)
    assert isinstance(data, list)
    assert data[0]["name"] == "rag_search"
    assert data[0]["params"][0]["name"] == "query"


def test_upload_accepts_main_frontend_json_payload():
    status, payload = _request(_client(), "POST", "/api/upload", json.dumps({"content": "hello rag"}).encode())

    assert status == 200
    data = json.loads(payload)
    assert data["chunk_count"] == 3
    assert data["doc_hash"]


def test_upload_accepts_legacy_int_rag_ingest_result():
    status, payload = _request(
        _legacy_upload_client(),
        "POST",
        "/api/upload",
        json.dumps({"content": "hello rag"}).encode(),
    )

    assert status == 200
    data = json.loads(payload)
    assert data["chunk_count"] == 3
    assert data["doc_hash"]


def test_chat_stream_emits_sse_events_for_main_frontend():
    status, payload = _request(_client(), "POST", "/api/chat/stream", json.dumps({"message": "你好"}).encode())
    body = payload.decode("utf-8")

    assert status == 200
    assert "event: start" in body
    assert "event: route" in body
    assert body.count("event: route") == 1
    assert "event: token" in body
    assert '"content": "流"' in body
    assert '"content": "式"' in body
    assert "event: done" in body
    assert "data: [DONE]" in body
    assert "request_id" in body


def test_legacy_rag_query_route_removed_to_match_main_branch():
    status, _payload = _request(
        _client(),
        "POST",
        "/api/rag/query",
        json.dumps({"question": "old route"}).encode(),
    )

    assert status in {404, 405}


def test_frontend_contains_local_document_library_ui():
    html = Path("frontend/index.html").read_text(encoding="utf-8")

    assert "libraryDocList" in html
    assert "docViewer" in html
    assert "loadLibraryDocs" in html
    assert "fetchDocumentJSON('/api/documents')" in html
    assert "/api/documents/' + encodeURIComponent(id) + '/ingest" in html
    assert "function escAttr" in html


def test_frontend_refreshes_library_after_document_tool_events():
    html = Path("frontend/index.html").read_text(encoding="utf-8")

    assert "function maybeRefreshLibraryAfterTool" in html
    assert "write_document" in html
    assert "ingest_document" in html
    assert "maybeRefreshLibraryAfterTool(data.tool || data.tool_name)" in html
    assert "maybeRefreshLibraryAfterTool(data.tool || data.tool_name || (data.task && data.task.tool_name))" in html


def test_frontend_restores_upload_list_from_document_library():
    html = Path("frontend/index.html").read_text(encoding="utf-8")

    assert "localStorage.removeItem('ai_docs')" not in html
    assert "syncUploadedDocsFromLibrary" in html
    assert "d.source === 'user_upload'" in html


def test_frontend_does_not_show_document_version_as_chunk_count():
    html = Path("frontend/index.html").read_text(encoding="utf-8")

    assert "chunks: Number(d.latest_version || 0)" not in html
    assert "indexed: Number(d.latest_version || 0)" not in html
    assert "d.persisted" in html
    assert "v${d.version || 0}" in html


def test_frontend_overwrites_stale_upload_cache_from_document_library():
    html = Path("frontend/index.html").read_text(encoding="utf-8")

    assert "const uploadKey" in html
    assert "const existingKey" in html
    assert "byKey.set(uploadKey, d)" in html
    assert "byName.has(d.name)" not in html
