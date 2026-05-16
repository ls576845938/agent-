import json
from pathlib import Path


RUN = Path("artifacts/btc_hypothesis/20260516T122000Z_compression_expansion")


def test_compression_expansion_distribution_report_schema() -> None:
    report = json.loads((RUN / "distribution_report.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_hypothesis_lab_distribution_report_v1"
    for field in [
        "overall",
        "direction_breakdown",
        "selected_direction",
        "selected_direction_distribution",
        "fold_stability",
        "regime_breakdown",
        "horizon_analysis",
        "tail_dependency",
        "failure_analysis",
    ]:
        assert field in report
    assert report["selected_direction"] == "upside_breakout"
    assert "upside_breakout" in report["direction_breakdown"]
    assert "short_label_proxy" in report["direction_breakdown"]


def test_compression_expansion_fold_and_horizon_reports_exist() -> None:
    report = json.loads((RUN / "distribution_report.json").read_text(encoding="utf-8"))

    assert report["fold_stability"]["fold_count"] == 4
    assert report["fold_stability"]["pass_rate"] >= 0.75
    assert set(report["horizon_analysis"]) == {"1h", "4h", "12h", "24h", "48h"}
