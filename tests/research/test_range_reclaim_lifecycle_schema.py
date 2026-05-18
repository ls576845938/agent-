import json
from pathlib import Path


RUN = Path("artifacts/btc_hypothesis/20260518T010000Z_range_reclaim_lifecycle")


def test_range_reclaim_lifecycle_report_schema() -> None:
    report = json.loads((RUN / "range_reclaim_lifecycle_report.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_hypothesis_lab_v2_lifecycle_report_v1"
    assert report["hypothesis_id"] == "range_reclaim_momentum_v0"
    for key in [
        "raw_event_PF_proxy",
        "target_active_event_PF_proxy",
        "full_lifecycle_event_PF_proxy",
        "lifecycle_drag",
        "lifecycle_drag_pct",
        "fold_pass_rate_lifecycle",
        "cost_stress_proxy_base",
        "tail_dependency",
        "no_lookahead_status",
        "decision",
    ]:
        assert key in report
    assert report["no_lookahead_status"] == "pass"


def test_range_reclaim_event_table_schema() -> None:
    header = (RUN / "range_reclaim_event_table.csv").read_text(encoding="utf-8").splitlines()[0].split(",")

    for key in [
        "timestamp",
        "fold_id",
        "regime",
        "prior_range_high",
        "range_reclaim",
        "trend_confirmation",
        "is_hypothesis_active",
        "event_return_forward_1h",
        "future_return_used_only_for_label",
    ]:
        assert key in header
