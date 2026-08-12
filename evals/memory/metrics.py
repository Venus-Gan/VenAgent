"""M05 评测的可复现集合指标。"""

from __future__ import annotations

from math import log2


def recall_at_k(expected: set[str], ranked: list[str], k: int) -> float:
    if not expected:
        return 1.0
    return len(expected.intersection(ranked[:k])) / len(expected)


def precision_at_k(expected: set[str], ranked: list[str], k: int) -> float:
    selected = ranked[:k]
    if not selected:
        return 1.0 if not expected else 0.0
    return len(expected.intersection(selected)) / len(selected)


def forbidden_recall_rate(forbidden: set[str], ranked: list[str]) -> float:
    if not forbidden:
        return 0.0
    return len(forbidden.intersection(ranked)) / len(forbidden)


def hit_rate_at_k(expected: set[str], ranked: list[str], k: int) -> float:
    return float(bool(expected.intersection(ranked[:k])))


def reciprocal_rank(expected: set[str], ranked: list[str]) -> float:
    for index, item in enumerate(ranked, start=1):
        if item in expected:
            return 1.0 / index
    return 0.0


def ndcg_at_k(expected: set[str], ranked: list[str], k: int) -> float:
    if not expected:
        return 1.0
    dcg = sum(
        1.0 / log2(index + 2)
        for index, item in enumerate(ranked[:k])
        if item in expected
    )
    ideal = sum(1.0 / log2(index + 2) for index in range(min(len(expected), k)))
    return dcg / ideal if ideal else 0.0


def classification_metrics(
    expected: list[bool], predicted: list[bool]
) -> dict[str, float]:
    if len(expected) != len(predicted):
        raise ValueError("expected and predicted lengths differ")
    true_positive = sum(
        wanted and actual for wanted, actual in zip(expected, predicted)
    )
    false_positive = sum(
        not wanted and actual for wanted, actual in zip(expected, predicted)
    )
    false_negative = sum(
        wanted and not actual for wanted, actual in zip(expected, predicted)
    )
    precision = _ratio(true_positive, true_positive + false_positive, empty=1.0)
    recall = _ratio(true_positive, true_positive + false_negative, empty=1.0)
    f1 = _ratio(2 * precision * recall, precision + recall, empty=0.0)
    return {"precision": precision, "recall": recall, "f1": f1}


def duplicate_rate(memory_ids: list[str]) -> float:
    if not memory_ids:
        return 0.0
    return 1.0 - len(set(memory_ids)) / len(memory_ids)


def accuracy(expected: list[str], actual: list[str]) -> float:
    if len(expected) != len(actual):
        raise ValueError("expected and actual lengths differ")
    return _ratio(
        sum(left == right for left, right in zip(expected, actual)),
        len(expected),
        empty=1.0,
    )


def isolation_failure_rate(forbidden_hits: int, checks: int) -> float:
    return _ratio(forbidden_hits, checks, empty=0.0)


def _ratio(numerator: float, denominator: float, *, empty: float) -> float:
    return numerator / denominator if denominator else empty
