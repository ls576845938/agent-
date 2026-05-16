import json
from pathlib import Path


RUN = Path("artifacts/btc_canonical/20260516T080000Z_eventpf_wf")


def test_event_pf_bridge_report_schema_is_complete() -> None:
    report = json.loads((RUN / "event_pf_bridge_report.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_event_pf_bridge_report_v1"
    for field in [
        "run_id",
        "source_run_id",
        "strategy_id",
        "ordinary_PF",
        "event_PF",
        "trade_level_PF",
        "fill_level_PF",
        "position_level_PF",
        "cashflow_level_PF",
        "root_cause_summary",
        "recommended_metric_contract",
    ]:
        assert field in report
    assert report["recommended_metric_contract"]["promotion_gate_metric"] == "event_PF"
    assert report["event_PF"] == report["fill_level_PF"]
    assert report["ordinary_PF"] != report["event_PF"]


def test_event_pf_bridge_table_exists() -> None:
    assert (RUN / "event_pf_bridge_table.csv").exists()
