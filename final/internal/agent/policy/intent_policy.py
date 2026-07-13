from __future__ import annotations

from typing import Mapping

from .registry import PROFILE_REGISTRY, ProfileSpec
from .types import CapabilityScope, ExecutionProfile, IntentDecision, IntentSignal
from ..router import detect_tool, need_react, need_tool

POLICY_VERSION = "v1"

_GREETING_HINTS = (
    "你好",
    "您好",
    "hello",
    "hi",
    "早上好",
    "下午好",
    "晚上好",
    "谢谢",
    "辛苦了",
)

_DOCUMENT_HINTS = (
    "文档",
    "文稿",
    "报告",
    "摘要",
    "提纲",
    "草稿",
    "方案",
    "说明书",
    "readme",
    "markdown",
    "md",
)

_AMBIGUOUS_HINTS = (
    "这个",
    "那个",
    "怎么",
    "如何",
    "帮我",
    "处理",
    "弄",
    "安排",
)

_KNOWLEDGE_HINTS = (
    "知识库",
    "资料",
    "百科",
    "参考",
    "依据",
    "背景",
    "原理",
    "解释",
)

_DEFAULT_TOOL_MAP = {
    "search_web": True,
    "get_time": True,
    "get_weather": True,
    "rag_search": True,
    "write_document": True,
    "read_document": True,
    "list_documents": True,
    "ingest_document": True,
    "exec_command": True,
}


class IntentPolicy:
    def __init__(
        self,
        registry: Mapping[ExecutionProfile, ProfileSpec] | None = None,
        *,
        policy_version: str = POLICY_VERSION,
    ) -> None:
        self._registry = dict(PROFILE_REGISTRY if registry is None else registry)
        self._policy_version = policy_version

    def resolve(self, signal: IntentSignal) -> IntentDecision:
        profile, reason, confidence = self._classify(signal)
        spec = self._registry[profile]

        scope = self._build_scope(profile, signal, spec)
        clarify_needed = spec.clarify_needed or profile is ExecutionProfile.CLARIFY

        if profile is ExecutionProfile.CLARIFY:
            confidence = min(confidence, spec.confidence)

        return IntentDecision(
            policy_version=self._policy_version,
            intent_class=spec.intent_class,
            execution_profile=profile,
            prompt_schema_key=spec.prompt_schema_key,
            graph_entry=spec.graph_entry,
            capability_scope=scope,
            clarify_needed=clarify_needed,
            confidence=confidence,
            reason=reason,
        )

    def _classify(self, signal: IntentSignal) -> tuple[ExecutionProfile, str, float]:
        requested = ExecutionProfile.coerce(signal.requested_profile)
        if signal.selected_tools:
            if signal.available_tools:
                filtered = self._filter_items(signal.selected_tools, signal.available_tools)
                if not filtered:
                    return (
                        ExecutionProfile.CLARIFY,
                        "explicit tool selection is unavailable",
                        0.2,
                    )
            return (
                ExecutionProfile.SINGLE_TOOL,
                "explicit selected_tools",
                0.96,
            )

        if requested is not None:
            return self._classify_requested_profile(requested, signal)

        if signal.explicit and signal.use_rag:
            if signal.rag_loaded:
                return (
                    ExecutionProfile.KNOWLEDGE_ANSWER,
                    "explicit RAG request",
                    0.95,
                )
            return (
                ExecutionProfile.CLARIFY,
                "explicit RAG request but rag is unavailable",
                0.25,
            )

        query = self._normalized_query(signal.query)
        if self._looks_like_document(query) and signal.allow_documents:
            return (
                ExecutionProfile.DOCUMENT_FLOW,
                "document workflow detected",
                0.84,
            )

        if need_react(query):
            return (
                ExecutionProfile.WORKFLOW_TASK,
                "multi-step workflow detected",
                0.82,
            )

        if self._looks_like_knowledge(query):
            if signal.rag_loaded:
                return (
                    ExecutionProfile.KNOWLEDGE_ANSWER,
                    "knowledge retrieval detected",
                    0.78,
                )
            return (
                ExecutionProfile.CLARIFY,
                "knowledge request without rag support",
                0.35,
            )

        tool_name = self._detect_tool(query, signal.available_tools)
        if tool_name is not None:
            if tool_name == "rag_search":
                if signal.rag_loaded:
                    return (
                        ExecutionProfile.KNOWLEDGE_ANSWER,
                        "rag_search detected",
                        0.8,
                    )
                return (
                    ExecutionProfile.CLARIFY,
                    "rag_search detected but rag is unavailable",
                    0.3,
                )
            return (
                ExecutionProfile.SINGLE_TOOL,
                f"tool keyword detected: {tool_name}",
                0.76,
            )

        if need_tool(query):
            return (
                ExecutionProfile.SINGLE_TOOL,
                "generic tool keyword detected",
                0.7,
            )

        if self._looks_like_greeting(query):
            return (
                ExecutionProfile.DEFAULT_CHAT,
                "greeting detected",
                0.82,
            )

        if self._looks_ambiguous(query):
            return (
                ExecutionProfile.CLARIFY,
                "ambiguous request",
                0.32,
            )

        return (
            ExecutionProfile.DEFAULT_CHAT,
            "safe conversational default",
            0.74,
        )

    def _classify_requested_profile(
        self,
        profile: ExecutionProfile,
        signal: IntentSignal,
    ) -> tuple[ExecutionProfile, str, float]:
        if profile is ExecutionProfile.CLARIFY:
            return profile, "requested clarify profile", 0.3
        if profile is ExecutionProfile.SINGLE_TOOL:
            tool_name = self._detect_tool(signal.query, signal.available_tools)
            if tool_name is not None:
                return (
                    profile,
                    f"requested profile normalized to single tool: {tool_name}",
                    0.94,
                )
            if signal.selected_tools:
                return profile, "requested single tool profile", 0.94
            if need_tool(self._normalized_query(signal.query)):
                return profile, "requested single tool profile", 0.9
            return profile, "requested single tool profile", 0.9
        if profile is ExecutionProfile.KNOWLEDGE_ANSWER:
            if signal.rag_loaded:
                return profile, "requested knowledge profile", 0.93
            return ExecutionProfile.CLARIFY, "requested knowledge profile without rag", 0.25
        if profile is ExecutionProfile.DOCUMENT_FLOW:
            if signal.allow_documents:
                return profile, "requested document profile", 0.9
            return ExecutionProfile.CLARIFY, "requested document profile disabled", 0.25
        if profile is ExecutionProfile.WORKFLOW_TASK:
            return profile, "requested workflow profile", 0.9
        return profile, f"requested profile normalized to {profile.value}", 0.88

    def _build_scope(
        self,
        profile: ExecutionProfile,
        signal: IntentSignal,
        spec: ProfileSpec,
    ) -> CapabilityScope:
        scope = spec.capability_scope
        if profile is ExecutionProfile.SINGLE_TOOL:
            tools = self._selected_tool_scope(signal, scope)
            return scope.narrowed(
                tools=tools,
                agents=tuple(self._filter_items(scope.agents, signal.available_agents)) or scope.agents,
            )

        tools = self._narrow_to_available(scope.tools, signal.available_tools)
        agents = self._narrow_to_available(scope.agents, signal.available_agents)
        return scope.narrowed(tools=tools, agents=agents)

    def _selected_tool_scope(
        self,
        signal: IntentSignal,
        fallback: CapabilityScope,
    ) -> tuple[str, ...]:
        selected = tuple(signal.selected_tools)
        if signal.available_tools:
            filtered = self._filter_items(selected, signal.available_tools)
            if filtered:
                return filtered
            return fallback.tools
        if selected:
            return selected
        tool_name = self._detect_tool(signal.query, signal.available_tools)
        if tool_name is not None and tool_name != "rag_search":
            return (tool_name,)
        if need_tool(self._normalized_query(signal.query)):
            return ("search_web",)
        return fallback.tools

    def _narrow_to_available(
        self,
        items: tuple[str, ...],
        available: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not available:
            return items
        filtered = self._filter_items(items, available)
        return filtered if filtered else items

    @staticmethod
    def _filter_items(
        items: tuple[str, ...],
        available: tuple[str, ...],
    ) -> tuple[str, ...]:
        available_set = set(available)
        return tuple(item for item in items if item in available_set)

    @staticmethod
    def _normalized_query(query: str) -> str:
        return query.strip().lower()

    def _detect_tool(
        self,
        query: str,
        available_tools: tuple[str, ...],
    ) -> str | None:
        tool_map = dict.fromkeys(available_tools or _DEFAULT_TOOL_MAP.keys(), True)
        return detect_tool(query, tool_map)

    @staticmethod
    def _looks_like_greeting(query: str) -> bool:
        return any(hint in query for hint in _GREETING_HINTS)

    @staticmethod
    def _looks_like_document(query: str) -> bool:
        return any(hint in query for hint in _DOCUMENT_HINTS)

    @staticmethod
    def _looks_like_knowledge(query: str) -> bool:
        return any(hint in query for hint in _KNOWLEDGE_HINTS)

    def _looks_ambiguous(self, query: str) -> bool:
        if self._looks_like_greeting(query):
            return False
        if self._looks_like_document(query):
            return False
        if self._looks_like_knowledge(query):
            return False
        if need_react(query) or need_tool(query):
            return False
        return any(hint in query for hint in _AMBIGUOUS_HINTS)
