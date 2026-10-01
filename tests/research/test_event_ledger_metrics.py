from quant_us.research.btc_alpha_hardening import evaluate_internal_gate


def test_event_ledger_metrics_are_required_for_gate_pass() -> None:
    metrics = {
        "profit_factor": 1.2,
        "event_profit_factor": 1.1,
        "walk_forward_pass_rate": 0.8,
        "regime_pass_rate": 0.75,
        "annual_turnover": 8.0,
        "max_drawdown_pct": -8.0,
        "cost_stress_base_pass": True,
        "cost_stress_harsh_survives": True,
        "no_lookahead_pass": True,
        "event_ledger_pass": False,
        "dsr": 0.2,
        "pbo": 0.2,
    }

    result = evaluate_internal_gate("candidate", metrics)

    assert not result.passed
    assert "event_profit_factor" in result.fail_reasons
    assert "event_ledger" in result.fail_reasons
