import json
from pathlib import Path


RUN = Path("artifacts/btc_hypothesis/20260517T020000Z_hypothesis_lab_v2_lifecycle")


def test_compression_expansion_lifecycle_report_fields() -> None:
    report = json.loads((RUN / "compression_expansion_lifecycle_report.json").read_text(encoding="utf-8"))

    assert report["hypothesis_id"] == "compression_expansion_breakout_v0"
    assert report["old_hypothesis_decision"] == "hypothesis_passed_for_strategy_skeleton"
    assert report["raw_event_PF_proxy"] == 1.359072
    assert report["target_active_event_PF_proxy"] == 1.188471
    assert report["full_lifecycle_event_PF_proxy"] == 1.0241
    assert report["fold_pass_rate_raw"] == 0.75
    assert report["fold_pass_rate_lifecycle"] == 0.5
    assert report["cost_stress_proxy_base"]["passed"] is True
    assert report["decision"] == "hypothesis_rejected"
