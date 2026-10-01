from quant_us.research.btc_alpha_hardening import evaluate_internal_gate, regime_pass_rate


def test_regime_pass_rate_and_gate_threshold() -> None:
    rows = [
        {"passed": True},
        {"passed": True},
        {"passed": True},
        {"passed": False},
        {"passed": False},
    ]
    metrics = {
        "profit_factor": 1.2,
        "event_profit_factor": 1.2,
        "walk_forward_pass_rate": 0.8,
        "regime_pass_rate": regime_pass_rate(rows),
        "annual_turnover": 8.0,
        "max_drawdown_pct": -8.0,
        "cost_stress_base_pass": True,
        "cost_stress_harsh_survives": True,
        "no_lookahead_pass": True,
        "event_ledger_pass": True,
        "dsr": 0.2,
        "pbo": 0.2,
    }

    result = evaluate_internal_gate("candidate", metrics)

    assert metrics["regime_pass_rate"] == 0.6
    assert not result.passed
    assert "regime_pass_rate" in result.fail_reasons
