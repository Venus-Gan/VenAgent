"""通过 M05 application port 执行版本化 policy/recall 样本。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from venagent.memory.recall import MemoryAuthorization
from venagent.memory.service import MemoryService

from .metrics import (
    accuracy,
    duplicate_rate,
    forbidden_recall_rate,
    hit_rate_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def load_cases(path: Path) -> tuple[dict[str, Any], ...]:
    return tuple(
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def evaluate_recall(
    service: MemoryService,
    authorization: MemoryAuthorization,
    cases: tuple[dict[str, Any], ...],
) -> tuple[dict[str, float], ...]:
    results: list[dict[str, float]] = []
    for case in cases:
        ranked = [
            block.block_id.removeprefix("memory:")
            for block in service.context_blocks(authorization, case["query"], limit=5)
        ]
        expected = set(case["expected_memory_ids"])
        forbidden = set(case.get("forbidden_memory_ids", ()))
        results.append(
            {
                "recall_at_5": recall_at_k(expected, ranked, 5),
                "precision_at_5": precision_at_k(expected, ranked, 5),
                "forbidden_recall_rate": forbidden_recall_rate(forbidden, ranked),
                "mrr": reciprocal_rank(expected, ranked),
                "ndcg_at_5": ndcg_at_k(expected, ranked, 5),
                "hit_rate_at_5": hit_rate_at_k(expected, ranked, 5),
                "context_precision": precision_at_k(expected, ranked, 5),
            }
        )
    return tuple(results)


def compare_recall_results(
    direct_results: tuple[dict[str, float], ...],
    g1_results: tuple[dict[str, float], ...],
) -> tuple[dict[str, float], ...]:
    """逐样本比较普通长期事实与 G1，安全指标不并入质量均值。"""
    if len(direct_results) != len(g1_results):
        raise ValueError("direct and g1 result lengths differ")
    quality_metrics = (
        "recall_at_5",
        "precision_at_5",
        "mrr",
        "ndcg_at_5",
        "hit_rate_at_5",
        "context_precision",
    )
    comparisons: list[dict[str, float]] = []
    for direct, g1 in zip(direct_results, g1_results):
        row = {
            f"direct_{metric}": direct[metric]
            for metric in (*quality_metrics, "forbidden_recall_rate")
        }
        row.update(
            {
                f"g1_{metric}": g1[metric]
                for metric in (*quality_metrics, "forbidden_recall_rate")
            }
        )
        row.update(
            {
                f"delta_{metric}": g1[metric] - direct[metric]
                for metric in quality_metrics
            }
        )
        comparisons.append(row)
    return tuple(comparisons)


def build_quality_report(
    *,
    expected_store_actions: list[str],
    actual_store_actions: list[str],
    memory_version_ids: list[str],
    expected_conflict_states: list[str],
    actual_conflict_states: list[str],
    recall_results: tuple[dict[str, float], ...],
    isolation_checks: int,
    isolation_failures: int,
) -> dict[str, float]:
    """按 M05 分层输出可比较指标，不用单一平均分掩盖安全失败。"""
    count = len(recall_results)
    average = lambda key: (  # noqa: E731 - 局部聚合器保持字段声明紧凑
        sum(item[key] for item in recall_results) / count if count else 1.0
    )
    return {
        "storage_accuracy": accuracy(expected_store_actions, actual_store_actions),
        "recall_quality": average("recall_at_5"),
        "mrr": average("mrr"),
        "ndcg_at_5": average("ndcg_at_5"),
        "hit_rate_at_5": average("hit_rate_at_5"),
        "duplicate_rate": duplicate_rate(memory_version_ids),
        "conflict_handling_accuracy": accuracy(
            expected_conflict_states, actual_conflict_states
        ),
        "false_memory_rate": average("forbidden_recall_rate"),
        "context_precision": average("context_precision"),
        "isolation_failure_rate": (
            isolation_failures / isolation_checks if isolation_checks else 0.0
        ),
    }


def build_pipeline_report(
    *,
    extraction_expected: list[str],
    extraction_actual: list[str],
    merge_expected: list[str],
    merge_actual: list[str],
    index_expected: list[bool],
    index_actual: list[bool],
    recall_results: tuple[dict[str, float], ...],
) -> dict[str, dict[str, float]]:
    """分层报告 extraction、merge、index 与 recall，避免总分掩盖失败层。"""
    count = len(recall_results)

    def average(key: str) -> float:
        return (
            sum(item[key] for item in recall_results) / count if count else 1.0
        )

    return {
        "extraction": {
            "accuracy": accuracy(extraction_expected, extraction_actual),
        },
        "merge": {"accuracy": accuracy(merge_expected, merge_actual)},
        "index": {"accuracy": accuracy(index_expected, index_actual)},
        "recall": {
            "recall_at_5": average("recall_at_5"),
            "mrr": average("mrr"),
            "forbidden_recall_rate": average("forbidden_recall_rate"),
        },
    }
