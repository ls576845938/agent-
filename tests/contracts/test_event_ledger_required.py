from quant_us.research.btc_canonical import evaluate_canonical_gate


def _base_report() -> dict[str, object]:
    return {
        "strategy_id": "synthetic",
        "evidence_source": "canonical_event_ledger",
        "metrics": {
            "profit_factor": 1.20,
            "event_profit_factor": 1.20,
            "annual_turnover": 5.0,
            "walk_forward_pass_rate": 0.90,
            "regime_pass_rate": 0.80,
            "max_drawdown": -10.0,
            "pbo": 0.20,
            "dsr": 0.20,
        },
        "cost_stress_base": {"passed": True},
        "cost_stress_harsh": {"survives": True},
        "no_lookahead_status": {"status": "pass"},
        "event_ledger_status": {"status": "pass"},
        "diagnostics": {"signal_equity_diagnostic_only": True},
    }


def test_missing_event_ledger_status_must_not_pass() -> None:
    report = _base_report()
    report.pop("event_ledger_status")

    decision = evaluate_canonical_gate(report)

    assert decision.passed is False
    assert "event_ledger" in decision.fail_reasons


def test_target_active_return_diagnostic_only_must_not_pass() -> None:
    report = _base_report()
    report["evidence_source"] = "signal_equity"
    report["metrics"]["target_active_return"] = 0.18
    report["metrics"]["target_active_event_PF_proxy"] = 1.80

    decision = evaluate_canonical_gate(report)

    assert decision.passed is False
    assert "canonical_source" in decision.fail_reasons


def test_high_plain_profit_factor_with_low_event_profit_factor_must_not_pass() -> None:
    report = _base_report()
    report["metrics"]["profit_factor"] = 3.00
    report["metrics"]["event_profit_factor"] = 1.01

    decision = evaluate_canonical_gate(report)

    assert decision.passed is False
    assert "event_profit_factor" in decision.fail_reasons
    assert "profit_factor" not in decision.fail_reasons
