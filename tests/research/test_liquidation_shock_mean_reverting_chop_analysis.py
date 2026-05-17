import json
from pathlib import Path


RUN = Path("artifacts/btc_candidate_attribution/20260517T010000Z_liquidation_shock_attribution")


def test_liquidation_shock_mean_reverting_chop_report_schema() -> None:
    report = json.loads((RUN / "liquidation_shock_mean_reverting_chop_report.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_liquidation_shock_mean_reverting_chop_report_v1"
    assert "mean_reverting_chop_event_PF" in report
    assert "keepout_assessment" in report
    assert report["keepout_assessment"]["suitable_for_keepout"] is False
    variants = {row["variant"] for row in report["ablation_results"]}
    assert "baseline_v1" in variants
    assert "mean_reverting_chop_keepout" in variants
    assert "mean_reverting_chop_reduce_size_50pct" in variants
    for row in report["ablation_results"]:
        assert "event_PF" in row
        assert "cost_stress_base_pass" in row
        assert "fail_reasons" in row
