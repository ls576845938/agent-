import json
from pathlib import Path


RUN = Path("artifacts/btc_hypothesis/20260517T020000Z_hypothesis_lab_v2_lifecycle")


def test_hypothesis_lab_v2_rejects_raw_edge_without_lifecycle_edge() -> None:
    report = json.loads((RUN / "lifecycle_aware_distribution_report.json").read_text(encoding="utf-8"))
    decision = json.loads((RUN / "hypothesis_decision_v2.json").read_text(encoding="utf-8"))

    assert report["raw_event_PF_proxy"] >= 1.15
    assert report["target_active_event_PF_proxy"] >= 1.15
    assert report["full_lifecycle_event_PF_proxy"] < 1.10
    assert decision["checks"]["raw_event_PF_proxy"] is True
    assert decision["checks"]["target_active_event_PF_proxy"] is True
    assert decision["checks"]["full_lifecycle_event_PF_proxy"] is False
    assert decision["decision"] == "hypothesis_rejected"
    assert decision["strategy_skeleton_generated"] is False


def test_hypothesis_lab_v2_rejects_lifecycle_fold_instability() -> None:
    decision = json.loads((RUN / "hypothesis_decision_v2.json").read_text(encoding="utf-8"))

    assert decision["checks"]["fold_pass_rate_lifecycle"] is False
    assert "fold_pass_rate_lifecycle" in decision["reasons"]
