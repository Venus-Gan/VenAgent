"""M05 首版的确定性资格与关系策略。"""

from __future__ import annotations

import re
from dataclasses import dataclass

SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b(?:bearer|token|password|密码|密钥)\s*[:=：]\s*\S+", re.I),
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
)
SPECIAL_TERMS = {
    "health": ("疾病", "诊断", "病史", "用药", "健康"),
    "finance": ("收入", "负债", "存款", "财务"),
    "legal": ("诉讼", "犯罪", "判决", "法律纠纷"),
}
PREFERENCE_TERMS = ("喜欢", "偏好", "更喜欢", "讨厌", "语气", "风格")


@dataclass(frozen=True)
class FactCandidate:
    subject: str
    slot: str
    fact: str
    sensitivity: str = "normal"
    value: str = ""
    assertion_mode: str = "statement"
    temporal_scope: str = "current"
    confidence: float = 1.0
    source_span: tuple[int, int] | None = None


@dataclass(frozen=True)
class CandidateRejection:
    """单个候选被统一策略拒绝的原因；不携带原始敏感内容。"""

    reason: str
    candidate: FactCandidate | None = None


def evaluate_candidates(
    content: str,
    candidates: tuple[FactCandidate, ...],
    *,
    explicit: bool,
) -> tuple[tuple[FactCandidate, ...], tuple[CandidateRejection, ...]]:
    """在 LLM 拆分完成后只执行一次候选资格判断。"""

    if contains_secret(content):
        return (), (CandidateRejection("secret_or_payment_data"),)
    accepted: list[FactCandidate] = []
    rejected: list[CandidateRejection] = []
    for candidate in candidates:
        reason = candidate_reject_reason(candidate, explicit=explicit)
        if reason is None:
            accepted.append(candidate)
        else:
            rejected.append(CandidateRejection(reason, candidate))
    return tuple(accepted), tuple(rejected)


def candidate_reject_reason(candidate: FactCandidate, *, explicit: bool) -> str | None:
    """只依据当前候选判断，不把同一句中的其他候选混入。"""

    content = candidate.fact
    if any(pattern.search(content) for pattern in SECRET_PATTERNS):
        return "secret_or_payment_data"
    if any(term in content for term in PREFERENCE_TERMS):
        return "preference_not_persisted"
    if re.search(r"(?:如果|假如|要是|假设)", content):
        return "hypothetical_statement"
    if re.search(r"(?:说|表示|声称)[：:]?[“\"]", content) or re.search(
        r"[“\"].+[”\"]", content
    ):
        return "quoted_statement"
    if re.search(r"(?:不|没|并非|不是)(?:叫|住在|负责|从事|患有)", content):
        return "negated_statement"
    if candidate.assertion_mode not in {"statement", "correction"}:
        return {
            "question": "question_not_fact",
            "negation": "negated_statement",
            "hypothesis": "hypothetical_statement",
            "quote": "quoted_statement",
        }.get(candidate.assertion_mode, "unsupported_assertion")
    for category, terms in SPECIAL_TERMS.items():
        if candidate.sensitivity == category or any(term in content for term in terms):
            if candidate.subject != "我" or not explicit:
                return f"{category}_requires_first_party_explicit_intent"
    return None


def reject_reason(content: str, *, explicit: bool, third_party: bool) -> str | None:
    normalized = content.strip()
    if any(pattern.search(normalized) for pattern in SECRET_PATTERNS):
        return "secret_or_payment_data"
    if any(term in normalized for term in PREFERENCE_TERMS):
        return "preference_not_persisted"
    if re.search(r"(?:如果|假如|要是|假设)", normalized):
        return "hypothetical_statement"
    if re.search(r"(?:说|表示|声称)[：:]?[“\"]", normalized) or re.search(
        r"[“\"].+[”\"]", normalized
    ):
        return "quoted_statement"
    if re.search(r"(?:不|没|并非|不是)(?:叫|住在|负责|从事|患有)", normalized):
        return "negated_statement"
    if "?" in normalized or "？" in normalized or re.search(
        r"(?:什么|谁|是否|吗|呢)$", normalized
    ):
        return "question_not_fact"
    for category, terms in SPECIAL_TERMS.items():
        if any(term in normalized for term in terms):
            if third_party or not explicit:
                return f"{category}_requires_first_party_explicit_intent"
    return None


def contains_secret(content: str) -> bool:
    return any(pattern.search(content) for pattern in SECRET_PATTERNS)


def extract_candidate(content: str) -> FactCandidate | None:
    """保守抽取少数稳定、自述事实；不把自由文本整段写入。"""
    value = re.sub(r"^(?:请)?记住[，,:： ]*", "", content.strip())
    patterns = (
        (
            r"我(?:以前|曾经|过去)叫([^，。！？\n]{1,40})",
            "former_name",
            "我",
            "我以前叫{}",
            "historical",
        ),
        (
            r"我(?:改名叫|现在叫|更名为)([^，。！？\n]{1,40})",
            "name",
            "我",
            "我叫{}",
            "correction",
        ),
        (r"我叫([^，。！？\n]{1,40})", "name", "我", "我叫{}", "statement"),
        (r"我(?:目前)?住在([^，。！？\n]{1,80})", "location", "我", "我住在{}", "statement"),
        (r"我(?:目前)?负责([^，。！？\n]{1,120})", "project", "我", "我负责{}", "statement"),
        (
            r"我(?:目前)?的职业是([^，。！？\n]{1,80})",
            "occupation",
            "我",
            "我的职业是{}",
            "statement",
        ),
        (r"我(?:患有|被诊断为)([^，。！？\n]{1,120})", "health", "我", "我患有{}", "statement"),
        (
            r"我的(?:月收入|年收入|收入)是([^，。！？\n]{1,80})",
            "finance",
            "我",
            "我的收入是{}",
            "statement",
        ),
        (
            r"([^，。！？\n]{1,30})(?:患有|被诊断为)([^，。！？\n]{1,120})",
            "health",
            None,
            "{}患有{}",
            "statement",
        ),
        (
            r"([^，。！？\n]{1,30})(?:目前)?住在([^，。！？\n]{1,80})",
            "location",
            None,
            "{}住在{}",
            "statement",
        ),
        (
            r"([^，。！？\n]{1,30})(?:目前)?负责([^，。！？\n]{1,120})",
            "project",
            None,
            "{}负责{}",
            "statement",
        ),
    )
    for pattern, slot, subject, template, assertion_mode in patterns:
        matched = re.search(pattern, value)
        if matched:
            groups = tuple(item.strip() for item in matched.groups())
            resolved_subject = subject or groups[0]
            values = groups if subject is None else (groups[0],)
            sensitivity = slot if slot in SPECIAL_TERMS else "normal"
            return FactCandidate(
                resolved_subject,
                slot,
                template.format(*values),
                sensitivity,
                value=values[-1],
                assertion_mode=assertion_mode,
                temporal_scope="historical" if slot == "former_name" else "current",
            )
    return None


def extract_candidates(content: str) -> tuple[FactCandidate, ...]:
    """提取同一输入中的候选，用于识别同槽位自相冲突。"""
    values: list[FactCandidate] = []
    for part in re.split(r"[，。！？；;\n]+", content):
        candidate = extract_candidate(part)
        if candidate is not None and candidate not in values:
            values.append(candidate)
    if not values:
        candidate = extract_candidate(content)
        if candidate is not None:
            values.append(candidate)
    return tuple(values)


def lexical_similarity(left: str, right: str) -> float:
    left_terms = set(_ngrams(left))
    right_terms = set(_ngrams(right))
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _ngrams(value: str) -> tuple[str, ...]:
    normalized = re.sub(r"\s+", "", value.casefold())
    if len(normalized) < 2:
        return (normalized,) if normalized else ()
    return tuple(normalized[index : index + 2] for index in range(len(normalized) - 1))
