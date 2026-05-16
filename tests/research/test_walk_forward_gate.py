from quant_us.research.btc_alpha_hardening import evaluate_internal_gate


def _passing_metrics() -> dict[str, float | bool]:
    return {
        "profit_factor": 1.2,
        "event_profit_factor": 1.2,
        "walk_forward_pass_rate": 0.8,
        "regime_pass_rate": 0.75,
        "annual_turnover": 8.0,
        "max_drawdown_pct": -8.0,
        "cost_stress_base_pass": True,
        "cost_stress_harsh_survives": True,
        "no_lookahead_pass": True,
        "event_ledger_pass": True,
        "dsr": 0.2,
        "pbo": 0.2,
    }


def test_walk_forward_gate_is_hard_threshold() -> None:
    metrics = _passing_metrics()
    metrics["walk_forward_pass_rate"] = 0.75

    result = evaluate_internal_gate("candidate", metrics)

    assert not result.passed
    assert result.status == "candidate_gate_failed"
    assert "walk_forward_pass_rate" in result.fail_reasons
