from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.run_btc_trend_daily_paper_roll import run_btc_trend_daily_paper_roll


def test_btc_trend_daily_paper_roll_blocks_without_ready_gate_and_writes_no_fills(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    gate = tmp_path / "gate.json"
    freeze = tmp_path / "freeze.json"
    gate.write_text(
        json.dumps(
            {
                "status": "research_only",
                "paper_candidate_ready": False,
                "selected_candidate": {"strategy_id": "twelve_month_momentum_intended"},
                "ledger_audit": {"complete": True, "lookahead_pass": True},
                "guardrails": {
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "broker_calls_allowed": False,
                    "live_order_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    _write_frozen(freeze)
    ledger = tmp_path / "data/paper_ledger/btc_trend_v0"

    payload = run_btc_trend_daily_paper_roll(
        repo_root=tmp_path,
        bundle_dir=bundle,
        ledger_root=ledger,
        promotion_gate=gate,
        freeze_report=freeze,
        readiness_report=tmp_path / "readiness.json",
        output=tmp_path / "roll.json",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert payload["cycle_status"] == "NOT_RUN"
    assert not (ledger / "fills.jsonl").exists()


def test_btc_trend_daily_paper_roll_uses_t_plus_one_signal_and_simulated_fill(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    gate = tmp_path / "gate.json"
    freeze = tmp_path / "freeze.json"
    _write_ready_gate(gate)
    _write_frozen(freeze)
    ledger = tmp_path / "data/paper_ledger/btc_trend_v0"

    payload = run_btc_trend_daily_paper_roll(
        repo_root=tmp_path,
        bundle_dir=bundle,
        ledger_root=ledger,
        promotion_gate=gate,
        freeze_report=freeze,
        readiness_report=tmp_path / "readiness.json",
        output=tmp_path / "roll.json",
        as_of="2021-01-04T00:00:00Z",
        initial_capital=10_000.0,
        fee_bps=5.0,
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "PASS"
    assert payload["strategy_id"] == "twelve_month_momentum_intended"
    assert payload["cycle"]["signal_timestamp"] < payload["cycle"]["effective_timestamp"]
    assert payload["target_exposure"] == 1.0
    assert payload["turnover"] == 1.0
    assert payload["simulated_fee"] == 5.0
    assert payload["fill"]["simulated_only"] is True
    assert payload["fill"]["broker_order_id"] == ""
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["target_position"]["reason"]
    assert (ledger / "target_positions.jsonl").exists()
    assert (ledger / "fills.jsonl").exists()
    assert (ledger / "portfolio_snapshots.jsonl").exists()
    assert (ledger / "validation_state.json").exists()


def test_btc_trend_daily_paper_roll_snapshot_reconciles_from_simulated_fill(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    gate = tmp_path / "gate.json"
    freeze = tmp_path / "freeze.json"
    _write_ready_gate(gate)
    _write_frozen(freeze)

    payload = run_btc_trend_daily_paper_roll(
        repo_root=tmp_path,
        bundle_dir=bundle,
        ledger_root=tmp_path / "data/paper_ledger/btc_trend_v0",
        promotion_gate=gate,
        freeze_report=freeze,
        readiness_report=tmp_path / "readiness.json",
        output=tmp_path / "roll.json",
        as_of="2021-01-04T00:00:00Z",
        initial_capital=10_000.0,
        fee_bps=5.0,
        generated_at="2026-06-23T00:00:00Z",
    )

    snapshot = payload["portfolio_snapshot"]
    expected = snapshot["prior_equity"] * (
        1.0 + snapshot["target_exposure"] * snapshot["daily_return"] - snapshot["turnover"] * 0.0005
    )
    assert abs(snapshot["equity"] - expected) <= 0.01
    assert payload["reconciliation"]["passed"] is True


def _write_daily_bundle(tmp_path: Path, *, rows: int) -> Path:
    bundle = tmp_path / "daily"
    bundle.mkdir()
    path = bundle / "klines_1d.csv"
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "timestamp",
                "open_time",
                "symbol",
                "open",
                "high",
                "low",
                "close",
                "volume_contracts",
                "volume_base",
                "volume_quote",
                "confirm",
                "source_record_id",
            ],
        )
        writer.writeheader()
        for day in range(rows):
            ts = start + timedelta(days=day)
            close = 10_000 + day * 10
            writer.writerow(
                {
                    "timestamp": ts.isoformat().replace("+00:00", "Z"),
                    "open_time": int(ts.timestamp() * 1000),
                    "symbol": "BTCUSDT",
                    "open": close - 5,
                    "high": close + 50,
                    "low": close - 50,
                    "close": close,
                    "volume_contracts": 1,
                    "volume_base": 1,
                    "volume_quote": close,
                    "confirm": 1,
                    "source_record_id": f"fixture:{day}",
                }
            )
    return bundle


def _write_ready_gate(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "paper_candidate_ready",
                "paper_candidate_ready": True,
                "selected_candidate": {"strategy_id": "twelve_month_momentum_intended"},
                "ledger_audit": {"complete": True, "lookahead_pass": True},
                "guardrails": {
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "broker_calls_allowed": False,
                    "live_order_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_frozen(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "frozen_rejected_as_high_frequency",
                "guardrails": {"parameter_tuning_allowed": False},
            }
        ),
        encoding="utf-8",
    )
