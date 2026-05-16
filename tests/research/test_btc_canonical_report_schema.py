import json
from pathlib import Path

from quant_us.research.btc_canonical import evaluate_canonical_gate_file


REPORT = Path("artifacts/btc_canonical/20260516T061000Z_attribution/btc_perp_dual_trend/canonical_backtest_report.json")


def test_btc_canonical_report_schema_is_complete() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_canonical_backtest_report_v1"
    assert report["evidence_source"] == "canonical_event_ledger"
    for field in [
        "run_id",
        "strategy_id",
        "strategy_version",
        "data_version",
        "data_range",
        "timeframe",
        "cost_model_id",
        "ledger_engine_version",
        "config_hash",
        "code_commit",
        "artifact_hash",
        "metrics",
        "event_ledger_status",
        "no_lookahead_status",
        "promotion_gate_status",
        "fail_reasons",
    ]:
        assert field in report
    for metric in [
        "profit_factor",
        "event_profit_factor",
        "annual_turnover",
        "walk_forward_pass_rate",
        "regime_pass_rate",
        "pbo",
        "dsr",
    ]:
        assert metric in report["metrics"]


def test_gate_can_evaluate_single_canonical_report_file() -> None:
    decision = evaluate_canonical_gate_file(REPORT)

    assert decision.evidence_source == "canonical_backtest_report"
    assert decision.status == "candidate_gate_failed"
    assert "event_profit_factor" in decision.fail_reasons
