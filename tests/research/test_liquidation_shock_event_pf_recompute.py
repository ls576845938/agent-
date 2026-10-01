import json
from pathlib import Path

import pandas as pd


RUN = Path("artifacts/btc_candidate_attribution/20260517T010000Z_liquidation_shock_attribution")
SOURCE = Path("artifacts/btc_candidate_validation/20260516T234000Z_liquidation_shock_eventledger")


def test_liquidation_shock_event_pf_recomputes_from_event_returns() -> None:
    report = json.loads((RUN / "liquidation_shock_event_return_attribution.json").read_text(encoding="utf-8"))
    table = pd.read_csv(RUN / "liquidation_shock_event_return_table.csv")
    returns = pd.to_numeric(table["event_return"], errors="coerce").fillna(0.0)
    positive = returns[returns > 0.0].sum()
    negative = -returns[returns < 0.0].sum()
    recomputed = positive / negative

    assert round(float(recomputed), 6) == report["event_PF_recomputed"]
    assert abs(report["event_PF_recomputed"] - report["event_PF"]) < 0.001


def test_liquidation_shock_gate_uses_event_pf_not_ordinary_pf() -> None:
    canonical = json.loads((SOURCE / "canonical_backtest_report.json").read_text(encoding="utf-8"))
    gate = canonical["gate_decision"]

    assert canonical["metrics"]["profit_factor"] >= 1.15
    assert canonical["metrics"]["event_profit_factor"] < 1.15
    assert gate["checks"]["profit_factor"] is True
    assert gate["checks"]["event_profit_factor"] is False
    assert "event_profit_factor" in gate["fail_reasons"]
