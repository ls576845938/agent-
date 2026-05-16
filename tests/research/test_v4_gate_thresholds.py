import json
from pathlib import Path


RUN = Path("artifacts/btc_canonical/20260516T080000Z_eventpf_wf")


def test_v4_cannot_pass_when_event_pf_or_wf_fails() -> None:
    result = json.loads((RUN / "btc_perp_dual_trend_v4_eventpf_wf_results.json").read_text(encoding="utf-8"))
    v4 = result["v4_report"]["metrics"]

    assert v4["event_profit_factor"] < 1.15
    assert v4["walk_forward_pass_rate"] < 0.80
    assert v4["regime_pass_rate"] >= 0.75
    assert result["gate_status"] == "candidate_gate_failed"
    assert set(result["fail_reasons"]) >= {
        "event_profit_factor",
        "walk_forward_pass_rate",
    }


def test_v4_turnover_remains_below_target_but_does_not_override_gate() -> None:
    result = json.loads((RUN / "btc_perp_dual_trend_v4_eventpf_wf_results.json").read_text(encoding="utf-8"))
    v4 = result["v4_report"]["metrics"]

    assert v4["annual_turnover"] <= 10.0
    assert result["gate_status"] != "candidate_passed_internal_gate"
