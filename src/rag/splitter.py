"""M08 RAG 文本切分：AGI-saber RecursiveSplitter 的 Python 移植。

行为逐条对齐 internal/domain/rag/splitter.go：
- 递归用一组优先级递减的分隔符切分，先强后弱，直到所有片段 <= chunk_size；
- ``` 代码块成对识别为原子单元，超长也不切；
- 分隔符保留在切出的下一段开头（Markdown 标题 / 句末标点不丢失）；
- 过短片段贪心合并到接近 chunk_size；overlap 附在下一段开头。
"""

from __future__ import annotations

import re

# 按"语义强度"从强到弱排列（对齐 Go defaultSeparators）。
DEFAULT_SEPARATORS: tuple[str, ...] = (
    "\n## ",
    "\n### ",
    "\n#### ",
    "\n# ",
    "\n\n",
    "\n",
    "。",
    "！",
    "？",
    ". ",
    "! ",
    "? ",
    "；",
    "; ",
    "，",
    ", ",
    " ",
    "",
)

_CODE_FENCE_RE = re.compile(r"(?m)^```")


class RecursiveSplitter:
    """递归切分器：chunk_size / overlap 按 rune（Unicode 码点）计数。"""

    def __init__(
        self,
        chunk_size: int,
        overlap: int,
        separators: tuple[str, ...] | list[str] | None = None,
    ) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.separators = tuple(
            separators if separators is not None else DEFAULT_SEPARATORS
        )

    def split(self, text: str) -> list[str]:
        pieces: list[str] = []
        for atom in self._protect_code_blocks(text):
            if atom.atomic:
                pieces.append(atom.text)
                continue
            pieces.extend(self._recursive_split(atom.text, self.separators))
        return self._merge(pieces)

    # ── 内部 ────────────────────────────────────────────────────────────

    def _protect_code_blocks(self, text: str) -> list[_Atom]:
        idxs = [m.span() for m in _CODE_FENCE_RE.finditer(text)]
        if len(idxs) < 2:
            return [_Atom(text)]
        atoms: list[_Atom] = []
        cursor = 0
        # 配对处理 fence：偶数下标为开 fence，奇数为闭 fence。
        for i in range(0, len(idxs) - 1, 2):
            open_pos, _ = idxs[i]
            _, close_pos = idxs[i + 1]
            if open_pos > cursor:
                atoms.append(_Atom(text[cursor:open_pos]))
            atoms.append(_Atom(text[open_pos:close_pos], atomic=True))
            cursor = close_pos
        if cursor < len(text):
            atoms.append(_Atom(text[cursor:]))
        return atoms

    def _recursive_split(self, text: str, seps: tuple[str, ...]) -> list[str]:
        if _rune_len(text) <= self.chunk_size:
            if text.strip() == "":
                return []
            return [text]
        if not seps:
            return _hard_split_by_rune(text, self.chunk_size)
        sep = seps[0]
        rest = seps[1:]
        if sep == "":
            return _hard_split_by_rune(text, self.chunk_size)
        out: list[str] = []
        for part in _split_keeping_sep(text, sep):
            if _rune_len(part) <= self.chunk_size:
                if part.strip() != "":
                    out.append(part)
                continue
            out.extend(self._recursive_split(part, rest))
        return out

    def _merge(self, pieces: list[str]) -> list[str]:
        merged: list[str] = []
        buf: list[str] = []
        buf_len = 0

        def flush() -> None:
            nonlocal buf, buf_len
            if buf_len > 0:
                merged.append("".join(buf))
                buf = []
                buf_len = 0

        for piece in pieces:
            pl = _rune_len(piece)
            if buf_len == 0:
                buf.append(piece)
                buf_len = pl
                continue
            if buf_len + pl <= self.chunk_size:
                buf.append(piece)
                buf_len += pl
                continue
            flush()
            buf.append(piece)
            buf_len = pl
        flush()

        if self.overlap > 0 and len(merged) > 1:
            out = [merged[0]]
            for i in range(1, len(merged)):
                out.append(_tail_runes(merged[i - 1], self.overlap) + merged[i])
            return out
        return merged


class _Atom:
    __slots__ = ("text", "atomic")

    def __init__(self, text: str, atomic: bool = False) -> None:
        self.text = text
        self.atomic = atomic


def _split_keeping_sep(text: str, sep: str) -> list[str]:
    """用 sep 切分，但把 sep 保留在切出的下一段开头。"""
    if sep == "":
        return [text]
    parts = text.split(sep)
    if len(parts) <= 1:
        return parts
    out = [parts[0]]
    for i in range(1, len(parts)):
        out.append(sep + parts[i])
    return out


def _hard_split_by_rune(text: str, size: int) -> list[str]:
    runes = list(text)
    return [
        "".join(runes[i : i + size]) for i in range(0, len(runes), size)
    ]


def _rune_len(s: str) -> int:
    return len(s)


def _tail_runes(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[len(s) - n :]
