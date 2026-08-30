"""DocumentService 测试：状态机 / 版本化 / 删除级联 / per-owner 隔离。"""

from __future__ import annotations

import pytest

from tests.document._store import FailingDocumentStore, InMemoryDocumentStore
from venagent.config import DocumentConfig, RagConfig
from venagent.document.parser import DocumentParseError
from venagent.document.ports import DocumentStoreError
from venagent.document.service import DocumentService, DocumentUploadError

OWNER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OWNER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

CONTENT = (
    "# 火星项目\n\n"
    "我们负责火星项目的轨道计算与燃料规划。\n"
    "团队分布在杭州与深圳两地，每周同步一次进度。\n"
    "关键里程碑包括 2026 年着陆窗口与 2027 年样本返回。\n"
) * 20


@pytest.fixture
def service() -> DocumentService:
    return DocumentService(
        InMemoryDocumentStore(),
        DocumentConfig(),
        RagConfig(),
    )


def test_upload_txt_reaches_ready(service):
    record = service.upload(
        OWNER_A, filename="project.md", content=CONTENT.encode("utf-8")
    )
    assert record.status == "ready"
    assert record.chunk_count > 0
    assert record.indexed_count == record.chunk_count
    chunks = service.chunks(OWNER_A, record.document_id)
    assert len(chunks) == record.chunk_count
    # small-to-big：子块带父块上下文与 section 溯源。
    assert all(chunk.parent_content for chunk in chunks)
    assert any(chunk.section == "火星项目" for chunk in chunks)
    assert all(len(chunk.content) <= 200 + 50 for chunk in chunks)


def test_upload_empty_rejected(service):
    with pytest.raises(DocumentUploadError) as exc_info:
        service.upload(OWNER_A, filename="a.txt", content=b"")
    assert exc_info.value.code == "document_empty"


def test_upload_too_large_rejected(service):
    small = DocumentService(
        InMemoryDocumentStore(),
        DocumentConfig(max_upload_bytes=1024),
        RagConfig(),
    )
    with pytest.raises(DocumentUploadError) as exc_info:
        small.upload(OWNER_A, filename="big.txt", content=b"x" * 2048)
    assert exc_info.value.code == "document_too_large"


def test_upload_parse_failure_marks_document_failed(service, monkeypatch):
    from venagent.document import service as service_module

    def fake_parse(filename, content, config):
        raise DocumentParseError("该 PDF 为扫描件/图片型，需要 OCR 支持", reason="needs_ocr")

    monkeypatch.setattr(service_module, "parse_document", fake_parse)
    record = service.upload(OWNER_A, filename="scan.pdf", content=b"%PDF-fake")
    assert record.status == "failed"
    assert record.failure_reason == "needs_ocr"


def test_reingest_appends_version_and_replaces_chunks(service):
    first = service.upload(
        OWNER_A, filename="project.md", content=CONTENT.encode("utf-8")
    )
    first_version = service.latest_version(OWNER_A, first.document_id)
    assert first_version is not None and first_version.version == 1

    new_content = "# 火星项目\n\n二期规划：载人着陆任务细节。" * 30
    second = service.reingest(
        OWNER_A, first.document_id, filename="project.md",
        content=new_content.encode("utf-8"),
    )
    assert second.status == "ready"
    second_version = service.latest_version(OWNER_A, first.document_id)
    assert second_version is not None and second_version.version == 2
    # 旧版本 chunks 被清，chunks 只对应新版本。
    chunks = service.chunks(OWNER_A, first.document_id)
    assert chunks
    assert all(chunk.version_id == second_version.version_id for chunk in chunks)
    assert all("载人着陆" in chunk.content or "载人着陆" in (chunk.parent_content or "") for chunk in chunks)


def test_delete_soft_then_purge(service):
    record = service.upload(
        OWNER_A, filename="project.md", content=CONTENT.encode("utf-8")
    )
    chunk_ids = service.delete(OWNER_A, record.document_id)
    assert chunk_ids
    assert service.get(OWNER_A, record.document_id) is None
    assert service.chunks(OWNER_A, record.document_id) == ()


def test_delete_missing_document_raises(service):
    with pytest.raises(DocumentStoreError):
        service.delete(OWNER_A, "doc-missing")


def test_delete_purge_failure_is_observable(service):
    failing = DocumentService(
        FailingDocumentStore(),
        DocumentConfig(),
        RagConfig(),
    )
    record = failing.upload(
        OWNER_A, filename="project.md", content=CONTENT.encode("utf-8")
    )
    with pytest.raises(DocumentStoreError):
        failing.delete(OWNER_A, record.document_id)


def test_cross_owner_isolation(service):
    record = service.upload(
        OWNER_A, filename="project.md", content=CONTENT.encode("utf-8")
    )
    assert service.get(OWNER_B, record.document_id) is None
    assert service.list(OWNER_B) == ()
    with pytest.raises(DocumentStoreError):
        service.delete(OWNER_B, record.document_id)


def test_list_filters_status_and_orders(service):
    first = service.upload(OWNER_A, filename="a.md", content=CONTENT.encode("utf-8"))
    second = service.upload(
        OWNER_A, filename="b.md", content=("火星。" * 500).encode("utf-8")
    )
    items = service.list(OWNER_A)
    assert [item.document_id for item in items] == [
        second.document_id,
        first.document_id,
    ]
    assert [item.document_id for item in service.list(OWNER_A, status="ready")] == [
        second.document_id,
        first.document_id,
    ]
    assert service.list(OWNER_A, status="failed") == ()


def test_parse_pdf_needs_ocr_rejects_short_pages(monkeypatch):
    import sys

    from venagent.document import parser as parser_module

    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakePdf:
        def __init__(self, pages) -> None:
            self.pages = pages

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

    fake = type("fake_pdfplumber", (), {"open": staticmethod(lambda _content: FakePdf([FakePage("只有几个字!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")]))})
    monkeypatch.setitem(sys.modules, "pdfplumber", fake)
    config = DocumentConfig()
    with pytest.raises(DocumentParseError) as exc_info:
        parser_module.parse_document("scan.pdf", b"%PDF", config)
    assert exc_info.value.reason == "needs_ocr"


def test_parse_pdf_too_many_pages(monkeypatch):
    import sys

    from venagent.document import parser as parser_module

    class FakePage:
        def extract_text(self) -> str:
            return "足够长的页面文本。" * 30

    class FakePdf:
        def __init__(self, pages) -> None:
            self.pages = pages

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

    pages = [FakePage() for _ in range(300)]
    fake = type("fake_pdfplumber", (), {"open": staticmethod(lambda _content: FakePdf(pages))})
    monkeypatch.setitem(sys.modules, "pdfplumber", fake)
    config = DocumentConfig(max_pdf_pages=200)
    with pytest.raises(DocumentParseError) as exc_info:
        parser_module.parse_document("big.pdf", b"%PDF", config)
    assert exc_info.value.reason == "pdf_too_large"


def test_parse_pdf_ok(monkeypatch):
    import sys

    from venagent.document import parser as parser_module

    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakePdf:
        def __init__(self, pages) -> None:
            self.pages = pages

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

    text = "火星项目规划。轨道计算与燃料规划。\n" * 20
    fake = type("fake_pdfplumber", (), {"open": staticmethod(lambda _content: FakePdf([FakePage(text)]))})
    monkeypatch.setitem(sys.modules, "pdfplumber", fake)
    result = parser_module.parse_document("plan.pdf", b"%PDF", DocumentConfig())
    assert result.doc_type == "pdf"
    assert "--- page 1 ---" in result.text
    assert not result.needs_ocr
