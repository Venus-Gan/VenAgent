from fixtures.phase0_behavior_cases import BEHAVIOR_CASES


def test_phase0_behavior_fixtures_cover_required_legacy_surfaces():
    kinds = {case["kind"] for case in BEHAVIOR_CASES}

    assert {"chat", "rag", "tool", "document"} <= kinds
    assert all(case["id"] and case["input"] is not None for case in BEHAVIOR_CASES)
    assert all(case["expected"] for case in BEHAVIOR_CASES)
