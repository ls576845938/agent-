import json
from pathlib import Path


RUN = Path("artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha")


def test_failed_fold_autopsy_contains_fold_3_and_4_root_causes() -> None:
    autopsy = json.loads((RUN / "failed_fold_autopsy.json").read_text(encoding="utf-8"))

    assert autopsy["schema_version"] == "btc_failed_fold_autopsy_v1"
    folds = {row["fold_id"]: row for row in autopsy["failed_folds"]}
    assert set(folds) == {3, 4}
    for fold in folds.values():
        for field in [
            "event_PF",
            "total_return",
            "largest_negative_events",
            "worst_regime",
            "worst_side",
            "terminal_exposure_contribution",
            "whether_failure_is_rule_fixable",
            "recommended_action",
        ]:
            assert field in fold
        assert fold["recommended_action"] == "archive_alpha"


def test_failed_fold_autopsy_rejects_single_rule_patch() -> None:
    autopsy = json.loads((RUN / "failed_fold_autopsy.json").read_text(encoding="utf-8"))

    assert autopsy["fold_3_4_same_pattern"] is False
    assert autopsy["recommended_action"] == "archive_alpha"
