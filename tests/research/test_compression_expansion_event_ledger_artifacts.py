import json
from pathlib import Path

import pandas as pd


RUN = Path("artifacts/btc_candidate_validation/20260516T133000Z_compression_expansion_eventledger")


def test_compression_expansion_canonical_gate_uses_event_pf() -> None:
    report = json.loads((RUN / "canonical_backtest_report.json").read_text(encoding="utf-8"))
    gate = report["gate_decision"]

    assert report["evidence_source"] == "canonical_event_ledger"
    assert report["metrics"]["profit_factor"] >= 1.15
    assert report["metrics"]["event_profit_factor"] < 1.15
    assert gate["checks"]["profit_factor"] is True
    assert gate["checks"]["event_profit_factor"] is False
    assert "event_profit_factor" in gate["fail_reasons"]


def test_compression_expansion_paper_live_stays_locked_after_failed_gate() -> None:
    promotion = json.loads((RUN / "promotion_decision.json").read_text(encoding="utf-8"))
    safety = json.loads((RUN / "paper_live_safety_status.json").read_text(encoding="utf-8"))

    assert promotion["candidate_passed_internal_gate_count"] == 0
    assert promotion["paper_review"]["paper_review_queue_locked"] is True
    assert promotion["paper_review"]["paper_review_pending"] == []
    assert promotion["paper_review"]["paper_auto_start"] is False
    assert safety["paper_queue"] == "LOCKED"
    assert safety["live"] == "FROZEN"
    assert safety["real_broker_api_called"] is False
    assert safety["real_orders_created"] is False


def test_compression_expansion_walk_forward_and_regime_failures_are_recorded() -> None:
    result = json.loads((RUN / "candidate_validation_result.json").read_text(encoding="utf-8"))
    walk_forward = json.loads((RUN / "walk_forward_report.json").read_text(encoding="utf-8"))
    regime = json.loads((RUN / "regime_report.json").read_text(encoding="utf-8"))

    assert result["status"] == "candidate_gate_failed"
    assert "walk_forward_pass_rate" in result["gate_fail_reasons"]
    assert "regime_pass_rate" in result["gate_fail_reasons"]
    assert walk_forward["pass_rate"] == 0.5
    assert [row["fold"] for row in walk_forward["windows"] if not row["passed"]] == [3, 4]
    assert regime["pass_rate"] < 0.75
    assert "trending_down" in regime["dragging_regimes"]


def test_compression_expansion_trade_ledger_is_ledger_segment_based() -> None:
    trades = pd.read_csv(RUN / "trade_ledger.csv")

    assert not trades.empty
    assert set(trades["attribution_source"]) == {"ledger_equity_segments"}
    assert trades["holding_bars"].median() == 48.0
