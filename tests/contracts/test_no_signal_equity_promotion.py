import pytest

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


def test_signal_equity_only_evidence_must_not_pass() -> None:
    report = _base_report()
    report["evidence_source"] = "signal_equity"

    decision = evaluate_canonical_gate(report)

    assert decision.passed is False
    assert "canonical_source" in decision.fail_reasons


@pytest.mark.parametrize(
    ("patch", "expected_reason"),
    [
        ({"no_lookahead_status": {}}, "no_lookahead"),
        ({"diagnostics": {"signal_equity_diagnostic_only": False}}, "signal_equity_diagnostic_only"),
    ],
)
def test_gate_requires_no_lookahead_and_signal_equity_diagnostic_only(
    patch: dict[str, dict[str, object]],
    expected_reason: str,
) -> None:
    report = _base_report()
    for key, value in patch.items():
        report[key] = value

    decision = evaluate_canonical_gate(report)

    assert decision.passed is False
    assert expected_reason in decision.fail_reasons
