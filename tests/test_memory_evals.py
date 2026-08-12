import pytest

from evals.memory.metrics import (
    classification_metrics,
    hit_rate_at_k,
    ndcg_at_k,
    reciprocal_rank,
)
from evals.memory.runner import (
    build_pipeline_report,
    build_quality_report,
    compare_recall_results,
)


def test_recall_metrics_cover_rank_and_hit_quality() -> None:
    expected = {"m2", "m4"}
    ranked = ["m1", "m2", "m3", "m4"]

    assert reciprocal_rank(expected, ranked) == 0.5
    assert hit_rate_at_k(expected, ranked, 1) == 0.0
    assert hit_rate_at_k(expected, ranked, 2) == 1.0
    assert 0.0 < ndcg_at_k(expected, ranked, 4) < 1.0
    assert classification_metrics([True, False], [True, True]) == {
        "precision": 0.5,
        "recall": 1.0,
        "f1": 2 / 3,
    }


def test_quality_report_keeps_safety_and_quality_dimensions_separate() -> None:
    report = build_quality_report(
        expected_store_actions=["ADD", "REJECT"],
        actual_store_actions=["ADD", "REJECT"],
        memory_version_ids=["v1", "v1"],
        expected_conflict_states=["superseded", "quarantine"],
        actual_conflict_states=["superseded", "quarantine"],
        recall_results=(
            {
                "recall_at_5": 1.0,
                "mrr": 1.0,
                "ndcg_at_5": 1.0,
                "hit_rate_at_5": 1.0,
                "forbidden_recall_rate": 0.25,
                "context_precision": 0.5,
            },
        ),
        isolation_checks=4,
        isolation_failures=1,
    )

    assert report["storage_accuracy"] == 1.0
    assert report["duplicate_rate"] == 0.5
    assert report["conflict_handling_accuracy"] == 1.0
    assert report["false_memory_rate"] == 0.25
    assert report["context_precision"] == 0.5
    assert report["isolation_failure_rate"] == 0.25


def test_g1_comparison_keeps_quality_delta_and_safety_absolute() -> None:
    direct = (
        {
            "recall_at_5": 0.5,
            "precision_at_5": 0.5,
            "mrr": 0.5,
            "ndcg_at_5": 0.5,
            "hit_rate_at_5": 1.0,
            "context_precision": 0.5,
            "forbidden_recall_rate": 0.0,
        },
    )
    g1 = (
        {
            "recall_at_5": 1.0,
            "precision_at_5": 0.5,
            "mrr": 1.0,
            "ndcg_at_5": 1.0,
            "hit_rate_at_5": 1.0,
            "context_precision": 0.5,
            "forbidden_recall_rate": 0.25,
        },
    )

    comparison = compare_recall_results(direct, g1)[0]

    assert comparison["delta_recall_at_5"] == 0.5
    assert comparison["delta_mrr"] == 0.5
    assert comparison["g1_forbidden_recall_rate"] == 0.25


def test_g1_comparison_rejects_unpaired_cases() -> None:
    with pytest.raises(ValueError, match="result lengths differ"):
        compare_recall_results((), ({},))


def test_pipeline_report_keeps_each_semantic_stage_separate() -> None:
    report = build_pipeline_report(
        extraction_expected=["ADD", "REJECT"],
        extraction_actual=["ADD", "REJECT"],
        merge_expected=["UPDATE", "QUARANTINE"],
        merge_actual=["UPDATE", "QUARANTINE"],
        index_expected=[True, False],
        index_actual=[True, False],
        recall_results=(
            {
                "recall_at_5": 1.0,
                "mrr": 0.5,
                "forbidden_recall_rate": 0.0,
            },
        ),
    )

    assert report == {
        "extraction": {"accuracy": 1.0},
        "merge": {"accuracy": 1.0},
        "index": {"accuracy": 1.0},
        "recall": {
            "recall_at_5": 1.0,
            "mrr": 0.5,
            "forbidden_recall_rate": 0.0,
        },
    }
