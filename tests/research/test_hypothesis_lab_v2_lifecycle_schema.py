import json
from pathlib import Path


RUN = Path("artifacts/btc_hypothesis/20260517T020000Z_hypothesis_lab_v2_lifecycle")


def test_hypothesis_lab_v2_lifecycle_schema() -> None:
    report = json.loads((RUN / "lifecycle_aware_distribution_report.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_hypothesis_lab_v2_lifecycle_report_v1"
    assert report["hypothesis_id"] == "compression_expansion_breakout_v0"
    for key in [
        "raw_event_return_distribution",
        "target_active_distribution",
        "full_lifecycle_distribution",
        "raw_event_PF_proxy",
        "target_active_event_PF_proxy",
        "full_lifecycle_event_PF_proxy",
        "lifecycle_drag",
        "lifecycle_drag_pct",
        "cost_stress_proxy_base",
        "fold_pass_rate_lifecycle",
        "tail_dependency",
        "no_lookahead_status",
        "decision",
    ]:
        assert key in report
    assert report["raw_event_PF_proxy"] > 1.15
    assert report["target_active_event_PF_proxy"] > 1.15
    assert report["full_lifecycle_event_PF_proxy"] < 1.10
