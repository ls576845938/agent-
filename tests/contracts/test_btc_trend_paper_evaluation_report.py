from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.build_btc_trend_paper_evaluation_report import build_btc_trend_paper_evaluation_report


def test_btc_trend_paper_evaluation_under_30_days_observing_not_live_ready(tmp_path: Path) -> None:
    ledger = tmp_path / "data/paper_ledger/btc_trend_v0"
    ledger.mkdir(parents=True)
    backtest = tmp_path / "backtest_ledger.csv"
    timestamp = "2021-01-04T00:00:00Z"
    signal_timestamp = "2021-01-03T00:00:00Z"
    target = {
        "timestamp": timestamp,
        "strategy_id": "twelve_month_momentum_intended",
        "symbol": "BTCUSDT",
        "target_exposure": 1.0,
        "prior_exposure": 0.0,
        "raw_signal": 1.0,
        "signal_timestamp": signal_timestamp,
        "effective_timestamp": timestamp,
        "reason": "twelve_month_momentum_positive_t_plus_1",
    }
    fill = {
        "timestamp": timestamp,
        "strategy_id": "twelve_month_momentum_intended",
        "symbol": "BTCUSDT",
        "turnover": 1.0,
        "simulated_fee": 5.0,
    }
    snapshot = {
        "timestamp": timestamp,
        "strategy_id": "twelve_month_momentum_intended",
        "symbol": "BTCUSDT",
        "prior_equity": 10_000.0,
        "equity": 10_095.0,
        "target_exposure": 1.0,
        "daily_return": 0.01,
        "turnover": 1.0,
        "simulated_fee": 5.0,
    }
    _append_jsonl(ledger / "target_positions.jsonl", target)
    _append_jsonl(ledger / "fills.jsonl", fill)
    _append_jsonl(ledger / "portfolio_snapshots.jsonl", snapshot)
    (ledger / "validation_state.json").write_text(
        json.dumps({"strategy_id": "twelve_month_momentum_intended", "days_completed": 1}),
        encoding="utf-8",
    )
    with backtest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp", "strategy_id", "exposure", "signal_timestamp"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerow(
            {
                "timestamp": timestamp,
                "strategy_id": "twelve_month_momentum_intended",
                "exposure": 1.0,
                "signal_timestamp": signal_timestamp,
            }
        )

    payload = build_btc_trend_paper_evaluation_report(
        repo_root=tmp_path,
        ledger_root=ledger,
        backtest_position_ledger=backtest,
        output=tmp_path / "eval.json",
        markdown_output=tmp_path / "eval.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "trend_paper_observing"
    assert payload["metrics"]["paper_days"] == 1
    assert payload["metrics"]["simulated_fill_count"] == 1
    assert payload["ledger_consistency"]["passed"] is True
    assert payload["signal_consistency"]["passed"] is True
    assert payload["guardrails"]["paper_evaluation_is_forward_record_not_alpha_validation"] is True
    assert payload["guardrails"]["live_ready"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    markdown = (tmp_path / "eval.md").read_text(encoding="utf-8")
    assert "不输出 live-ready" in markdown


def _append_jsonl(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True))
        handle.write("\n")
