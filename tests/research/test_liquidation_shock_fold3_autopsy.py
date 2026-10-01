import json
from pathlib import Path


RUN = Path("artifacts/btc_candidate_attribution/20260517T010000Z_liquidation_shock_attribution")


def test_liquidation_shock_fold3_autopsy_has_root_cause_and_action() -> None:
    report = json.loads((RUN / "liquidation_shock_fold3_autopsy.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_liquidation_shock_fold3_autopsy_v1"
    assert report["fold_id"] == "3"
    assert report["event_PF"] < 1.0
    assert report["largest_negative_events"]
    assert report["root_cause"]
    assert report["recommended_action"]
    assert report["whether_failure_is_fixable"] is False
