from quant_us.research.btc_canonical import evaluate_canonical_gate


def test_gate_fails_when_ordinary_pf_passes_but_event_pf_fails() -> None:
    report = {
        "strategy_id": "synthetic",
        "evidence_source": "canonical_event_ledger",
        "metrics": {
            "profit_factor": 3.0,
            "event_profit_factor": 1.01,
            "annual_turnover": 1.0,
            "walk_forward_pass_rate": 1.0,
            "regime_pass_rate": 1.0,
            "max_drawdown": -2.0,
            "pbo": 0.0,
            "dsr": 1.0,
        },
        "cost_stress_base": {"passed": True},
        "cost_stress_harsh": {"survives": True},
        "no_lookahead_status": {"status": "pass"},
        "event_ledger_status": {"status": "pass"},
        "diagnostics": {"signal_equity_diagnostic_only": True},
    }

    decision = evaluate_canonical_gate(report)

    assert decision.passed is False
    assert "event_profit_factor" in decision.fail_reasons
    assert "profit_factor" not in decision.fail_reasons
