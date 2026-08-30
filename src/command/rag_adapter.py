"""把 M08 HybridSearchService 包装为 /rag 聊天命令（照 memory_adapter 模式）。

执行：search → LLM 生成引用回答（[n] 编号仅允许引用给定片段，来源不足必须说明）
→ CommandResult(kind="rag_command", message=回答 + 引用结构)。
"""

from __future__ import annotations

from ..ownership.models import Actor
from ..rag import CitationSource, HybridSearchService
from .registry import CommandOption, CommandResult

RAG_ANSWER_SYSTEM_PROMPT = (
    "你是一个基于知识库回答问题的助手。请仅根据提供的上下文内容回答问题，"
    "不要编造信息。引用编号 [n] 只能引用给定的编号。如果上下文不足以回答，"
    "请明确说明。回答使用中文。"
)


class RagCommandAdapter:
    def __init__(
        self,
        search_service: HybridSearchService,
        model=None,
    ) -> None:
        self._search = search_service
        self._model = model

    @staticmethod
    def matches(content: str) -> bool:
        return content.strip().startswith("/rag ")

    def execute(self, actor: Actor, content: str) -> CommandResult:
        query = content.strip()[len("/rag ") :].strip()
        if not query:
            return CommandResult(
                kind="rag_command",
                code="rag_query_required",
                message="用法：/rag <问题>",
            )
        try:
            result = self._search.search(actor.owner_id, query)
        except Exception:
            return CommandResult(
                kind="rag_command",
                code="rag_unavailable",
                message="知识库检索当前不可用，请稍后重试。",
            )
        if result.mode == "unavailable":
            return CommandResult(
                kind="rag_command",
                code="rag_unavailable",
                message="知识库检索未配置（Milvus/Elasticsearch 均不可用）。",
            )
        if not result.sources:
            return CommandResult(
                kind="rag_command",
                code="rag_no_result",
                message="知识库中未找到相关内容。",
            )
        answer = self._generate_answer(query, result.sources)
        message = self._compose(answer, result)
        return CommandResult(
            kind="rag_command", code="rag_ok", message=message
        )

    def _generate_answer(self, query: str, sources: tuple[CitationSource, ...]) -> str:
        if self._model is None:
            return "检索到以下相关内容。"
        from langchain_core.messages import HumanMessage, SystemMessage

        context = "\n\n".join(
            f"[{index + 1}] {source.parent_content or source.chunk_content}"
            for index, source in enumerate(sources)
        )
        try:
            response = self._model.invoke(
                (
                    SystemMessage(content=RAG_ANSWER_SYSTEM_PROMPT),
                    HumanMessage(
                        content=f"上下文：\n{context}\n\n问题：{query}"
                    ),
                )
            )
            text = getattr(response, "text", None)
            if isinstance(text, str):
                return text
            content = getattr(response, "content", None)
            if isinstance(content, str):
                return content
        except Exception:
            pass
        return "检索到以下相关内容。"

    @staticmethod
    def _compose(answer: str, result) -> str:
        lines = [answer.strip()]
        flags = []
        if result.degraded:
            flags.append("检索降级：" + ",".join(result.degraded))
        if result.reranked:
            flags.append("已重排")
        lines.append(f"（来源：{result.mode}" + ("，" + "；".join(flags) if flags else "") + "）")
        citations = []
        for index, source in enumerate(result.sources):
            title = source.title or source.document_id
            section = f" / {source.section}" if source.section else ""
            citations.append(f"[{index + 1}] {title}{section}")
        lines.append("\n".join(citations))
        return "\n".join(lines)

    @staticmethod
    def options() -> tuple[CommandOption, ...]:
        return (
            CommandOption("/rag <问题>", "检索知识库并回答"),
        )


def _citation_json(source: CitationSource) -> dict[str, object]:
    return {
        "chunk_id": source.chunk_id,
        "document_id": source.document_id,
        "title": source.title,
        "section": source.section,
        "chunk_idx": source.chunk_idx,
        "content": source.parent_content or source.chunk_content,
        "score": source.score,
        "route": source.route,
    }


def _result_json(result) -> dict[str, object]:
    return {
        "question": result.question,
        "mode": result.mode,
        "degraded": list(result.degraded),
        "reranked": result.reranked,
        "sources": [_citation_json(item) for item in result.sources],
    }
