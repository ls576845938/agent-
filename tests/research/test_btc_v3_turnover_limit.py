import json
from pathlib import Path

from quant_us.research.btc_canonical import evaluate_canonical_gate


def test_turnover_above_v3_limit_blocks_promotion() -> None:
    report = json.loads(
        Path("artifacts/btc_canonical/20260516T061000Z_attribution/btc_perp_dual_trend_v2/canonical_backtest_report.json").read_text(
            encoding="utf-8"
        )
    )
    report["metrics"]["annual_turnover"] = 10.01
    report["metrics"]["event_profit_factor"] = 1.2
    report["metrics"]["profit_factor"] = 1.2
    report["metrics"]["regime_pass_rate"] = 0.8

    decision = evaluate_canonical_gate(report)

    assert not decision.passed
    assert "annual_turnover" in decision.fail_reasons
