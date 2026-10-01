import json
from pathlib import Path

import pandas as pd

from quant_us.research.btc_eventpf_wf import load_btc_1h_frame
from quant_us.research.btc_liquidation_shock_validation import (
    DEFAULT_VALIDATION_CONFIG_PATH,
    liquidation_shock_signal,
    load_validation_config,
)


RUN = Path("artifacts/btc_candidate_validation/20260516T234000Z_liquidation_shock_eventledger")


def test_liquidation_shock_validation_config_is_research_only() -> None:
    config = load_validation_config(DEFAULT_VALIDATION_CONFIG_PATH)

    assert config["strategy_id"] == "btc_liquidation_shock_recovery_v1"
    assert config["mode"] == "event_ledger_candidate_validation"
    assert config["promotion_status"] == "research_candidate"
    assert config["event_ledger_required"] is True
    assert config["paper_ready"] is False
    assert config["live_ready"] is False
    assert config["live_enabled"] is False
    assert config["safety"]["paper_queue"] == "LOCKED"
    assert config["safety"]["live"] == "FROZEN"


def test_liquidation_shock_signal_is_long_only_and_no_orderflow() -> None:
    frame = load_btc_1h_frame().tail(1800)
    signal, diagnostics = liquidation_shock_signal(frame, {"time_exit_bars": 24, "cooldown_bars": 6})

    assert signal.min() >= 0.0
    assert signal.max() <= 1.0
    assert "liquidation_shock" in diagnostics
    assert "recovery_confirmed" in diagnostics
    assert "orderflow" not in "\n".join(diagnostics.keys()).lower()


def test_liquidation_shock_signal_no_lookahead() -> None:
    frame = load_btc_1h_frame().tail(2200)
    mutated = frame.copy()
    cutoff = len(mutated) // 2
    mutated.loc[mutated.index[cutoff:], ["open", "high", "low", "close"]] *= 1.4
    base_signal, _ = liquidation_shock_signal(frame)
    mutated_signal, _ = liquidation_shock_signal(mutated)
    cutoff_ts = frame.index[cutoff - 80]

    pd.testing.assert_series_equal(
        base_signal.loc[base_signal.index <= cutoff_ts],
        mutated_signal.loc[mutated_signal.index <= cutoff_ts],
        check_names=False,
    )


def test_liquidation_shock_event_ledger_artifact_schema() -> None:
    report = json.loads((RUN / "canonical_backtest_report.json").read_text(encoding="utf-8"))
    result = json.loads((RUN / "candidate_validation_result.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == "btc_canonical_backtest_report_v1"
    assert report["evidence_source"] == "canonical_event_ledger"
    assert report["event_ledger_status"]["status"] == "pass"
    assert report["event_ledger_status"]["pnl_source"] == "ledger_fills"
    assert report["diagnostics"]["signal_equity_diagnostic_only"] is True
    assert result["status"] == "candidate_gate_failed"


def test_event_pf_and_cost_stress_gate_block_candidate() -> None:
    report = json.loads((RUN / "canonical_backtest_report.json").read_text(encoding="utf-8"))
    gate = report["gate_decision"]

    assert report["metrics"]["profit_factor"] >= 1.15
    assert report["metrics"]["event_profit_factor"] < 1.15
    assert gate["checks"]["profit_factor"] is True
    assert gate["checks"]["event_profit_factor"] is False
    assert gate["checks"]["cost_stress_base"] is False
    assert "event_profit_factor" in gate["fail_reasons"]
    assert "cost_stress_base" in gate["fail_reasons"]


def test_liquidation_shock_validation_paper_live_locked() -> None:
    promotion = json.loads((RUN / "promotion_decision.json").read_text(encoding="utf-8"))
    safety = json.loads((RUN / "paper_live_safety_status.json").read_text(encoding="utf-8"))

    assert promotion["paper_review"]["paper_review_queue_locked"] is True
    assert promotion["paper_review"]["paper_review_pending"] == []
    assert promotion["paper_review"]["paper_auto_start"] is False
    assert promotion["max_state"] == "candidate_gate_failed"
    assert safety["paper_queue"] == "LOCKED"
    assert safety["live"] == "FROZEN"
    assert safety["real_broker_api_called"] is False
    assert safety["real_orders_created"] is False


def test_liquidation_shock_validation_uses_ledger_segments_for_trades() -> None:
    trades = pd.read_csv(RUN / "trade_ledger.csv")
    report = json.loads((RUN / "canonical_backtest_report.json").read_text(encoding="utf-8"))

    assert set(trades["attribution_source"]) == {"ledger_equity_segments"}
    assert report["metrics"]["avg_holding_bars"] <= 25.0
