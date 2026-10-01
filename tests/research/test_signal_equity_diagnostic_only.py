import json
from pathlib import Path

from quant_us.research.btc_canonical import evaluate_canonical_gate


def test_signal_equity_is_diagnostic_only_and_required_for_gate() -> None:
    report = json.loads(
        Path("artifacts/btc_canonical/20260516T061000Z_attribution/btc_perp_dual_trend_v2/canonical_backtest_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert "signal_equity" not in report["metrics"]
    assert report["diagnostics"]["signal_equity_diagnostic_only"] is True

    report["diagnostics"]["signal_equity_diagnostic_only"] = False
    decision = evaluate_canonical_gate(report)

    assert not decision.passed
    assert "signal_equity_diagnostic_only" in decision.fail_reasons
