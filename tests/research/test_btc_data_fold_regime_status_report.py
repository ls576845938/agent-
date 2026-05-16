import json
from pathlib import Path


RUN = Path("artifacts/btc_candidate_validation/20260516T133000Z_compression_expansion_eventledger")


def test_btc_data_fold_regime_status_report_schema() -> None:
    report = json.loads((RUN / "btc_data_fold_regime_status_report.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_data_fold_regime_status_report_v1"
    assert report["sqlite"]["symbol"] == "BTCUSDT"
    assert report["sqlite"]["status"] == "pass"
    assert report["manifest_lineage"]["status"] == "pass"


def test_btc_multitimeframe_sqlite_completeness_is_recorded() -> None:
    report = json.loads((RUN / "btc_data_fold_regime_status_report.json").read_text(encoding="utf-8"))
    intervals = {row["interval"]: row for row in report["intervals"]}

    assert set(intervals) == {"5m", "15m", "1h", "4h", "1d"}
    for interval, row in intervals.items():
        assert row["status"] == "pass", interval
        assert row["manifest_status"] == "pass", interval
        assert row["missing_rows"] == 0, interval
        assert row["row_count"] == row["expected_rows"], interval
        assert row["data_version"].startswith(f"qs-sqlite-BTCUSDT-{interval}-")


def test_btc_regime_status_remains_failed_for_candidate() -> None:
    report = json.loads((RUN / "btc_data_fold_regime_status_report.json").read_text(encoding="utf-8"))

    assert report["regime_status"]["status"] == "fail"
    assert report["regime_status"]["gate_pass_rate"] < 0.75
    assert "trending_down" in report["regime_status"]["dragging_regimes"]
