import json
from pathlib import Path


RUN = Path("artifacts/btc_canonical/20260516T080000Z_eventpf_wf")


def test_pf_and_event_pf_are_separate_gate_fields() -> None:
    gate_input = json.loads((RUN / "btc_perp_dual_trend_v4_eventpf_wf_gate_input.json").read_text(encoding="utf-8"))
    report = gate_input["report"]
    metrics = report["metrics"]

    assert "profit_factor" in metrics
    assert "event_profit_factor" in metrics
    assert report["PF"] == metrics["profit_factor"]
    assert report["event_PF"] == metrics["event_profit_factor"]
    assert metrics["profit_factor"] != metrics["event_profit_factor"]
    assert "event_profit_factor" in gate_input["gate"]["fail_reasons"]


def test_bridge_metric_contract_keeps_ordinary_pf_diagnostic_only() -> None:
    bridge = json.loads((RUN / "event_pf_bridge_report.json").read_text(encoding="utf-8"))

    assert bridge["metric_definition_notes"]["ordinary_PF"].endswith("diagnostic only")
    assert bridge["recommended_metric_contract"]["ordinary_PF_status"] == "diagnostic_only"
