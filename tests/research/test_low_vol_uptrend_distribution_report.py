import json
from pathlib import Path


RUN = Path("artifacts/btc_hypothesis/20260516T120000Z_lowvol_uptrend")


def test_low_vol_uptrend_distribution_report_schema() -> None:
    report = json.loads((RUN / "low_vol_uptrend_distribution_report.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_low_vol_uptrend_distribution_report_v1"
    for field in [
        "overall_distribution",
        "fold_stability",
        "regime_breakdown",
        "holding_horizon_analysis",
        "failure_analysis",
    ]:
        assert field in report

    overall = report["overall_distribution"]
    for field in [
        "active_event_count",
        "positive_event_rate_1h",
        "positive_event_rate_4h",
        "positive_event_rate_12h",
        "positive_event_rate_24h",
        "mean_return",
        "median_return",
        "positive_sum",
        "negative_sum",
        "event_PF_proxy",
        "downside_tail_5pct",
    ]:
        assert field in overall


def test_low_vol_uptrend_fold_stability_is_present() -> None:
    report = json.loads((RUN / "low_vol_uptrend_distribution_report.json").read_text(encoding="utf-8"))
    fold_stability = report["fold_stability"]

    assert fold_stability["fold_count"] == 4
    assert fold_stability["pass_rate"] == 0.25
    assert {row["fold_id"] for row in fold_stability["folds"]} == {"1", "2", "3", "4"}
    assert [row["fold_id"] for row in fold_stability["folds"] if row["passed"]] == ["2"]
