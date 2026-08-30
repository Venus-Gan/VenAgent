"""M08 文档解析：txt/md 直收，PDF 走 pdfplumber（<阈值 rune/页 → needs_ocr）。"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import DocumentConfig


class DocumentParseError(ValueError):
    """解析失败（HTTP 层映射 422/500；PDF 超页数、非法编码等）。"""

    def __init__(self, message: str, reason: str = "parse_error") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ParseResult:
    text: str
    doc_type: str
    needs_ocr: bool = False


def parse_document(
    filename: str, content: bytes, config: DocumentConfig
) -> ParseResult:
    """按扩展名分发解析；无扩展名 / 非 PDF 一律按纯文本处理。"""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _parse_pdf(content, config)
    return _parse_text(content)


def _parse_text(content: bytes) -> ParseResult:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentParseError("文档不是有效的 UTF-8 文本") from exc
    return ParseResult(text=text, doc_type="text")


def _parse_pdf(content: bytes, config: DocumentConfig) -> ParseResult:
    try:
        import io

        import pdfplumber
    except ImportError as exc:  # pragma: no cover - 依赖缺失时的显式降级
        raise DocumentParseError(
            "PDF 解析依赖 pdfplumber 未安装"
        ) from exc
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = list(pdf.pages)
            if len(pages) > config.max_pdf_pages:
                raise DocumentParseError(
                    f"PDF 超过 {config.max_pdf_pages} 页上限",
                    reason="pdf_too_large",
                )
            parts: list[str] = []
            for index, page in enumerate(pages, start=1):
                text = page.extract_text() or ""
                # 统计有效字符数占比（改进 CJK 判断逻辑）
                total_len = len(text)
                if total_len > 0:
                    meaningful_count = sum(1 for ch in text if _is_meaningful_char(ch))
                    meaningful_ratio = meaningful_count / total_len
                    if meaningful_ratio < config.ocr_reject_threshold:
                        raise DocumentParseError(
                            "该 PDF 为扫描件/图片型，需要 OCR 支持",
                            reason="needs_ocr",
                        )
                parts.append(f"--- page {index} ---\n{text}")
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError("PDF 解析失败") from exc
    return ParseResult(text="\n".join(parts), doc_type="pdf")


def _is_meaningful_char(ch: str) -> bool:
    """判断字符是否为有效文本字符（支持 CJK）。"""
    if ch.isalnum():
        return True
    code = ord(ch)
    # CJK 统一表意文字 (U+4E00–U+9FFF) + 日文假名 (U+3040–U+30FF)
    return (0x4E00 <= code <= 0x9FFF) or (0x3040 <= code <= 0x30FF)
