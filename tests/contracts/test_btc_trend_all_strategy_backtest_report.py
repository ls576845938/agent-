from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from scripts.build_btc_trend_all_strategy_backtest_report import (
    BLOCKED_FAMILIES,
    BTC_FAMILIES,
    COST_BPS_GRID,
    DELAY_DAYS_GRID,
    build_btc_trend_all_strategy_backtest_report,
)


def test_all_strategy_backtest_short_history_blocks_ranking(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=400)

    payload = build_btc_trend_all_strategy_backtest_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        output=tmp_path / "report.json",
        grid_output=tmp_path / "grid.csv",
        ledger_output=tmp_path / "ledger.csv",
        markdown_output=tmp_path / "report.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "insufficient_history"
    assert payload["overall_ranking"] == []
    assert payload["grid_output"]["row_count"] == 0
    assert payload["position_ledger"]["complete"] is False
    assert "btc_trend_all_strategy_validation_requires_at_least_1095_daily_rows" in payload["blockers"]
    assert (tmp_path / "grid.csv").read_text(encoding="utf-8").startswith("candidate_id,family_id")


def test_all_strategy_backtest_runs_all_btc_families_and_writes_t_plus_1_ledger(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=1700)

    payload = build_btc_trend_all_strategy_backtest_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        output=tmp_path / "report.json",
        grid_output=tmp_path / "grid.csv",
        ledger_output=tmp_path / "ledger.csv",
        markdown_output=tmp_path / "report.md",
        initial_capital=10_000.0,
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "research_only_all_backtest_complete"
    assert payload["decision"] == "btc_spot_daily_candidate_sweep_complete_manual_review_required"
    assert payload["btc_families"] == BTC_FAMILIES
    assert payload["guardrails"]["private_endpoint_used"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["guardrails"]["live_order_allowed"] is False

    family_ids = {row["family_id"] for row in payload["family_summaries"]}
    assert family_ids == set(BTC_FAMILIES)
    assert all(row["candidate_count"] > 0 for row in payload["family_summaries"])
    assert payload["grid_output"]["row_count"] > len(BTC_FAMILIES)
    assert payload["position_ledger"]["complete"] is True

    blocked_ids = {row["family_id"] for row in payload["blocked_families"]}
    assert "m01_multi_asset_tsmom" in blocked_ids
    assert set(row["family_id"] for row in BLOCKED_FAMILIES).issubset(blocked_ids)

    ledger_rows = list(csv.DictReader((tmp_path / "ledger.csv").open("r", encoding="utf-8")))
    assert len(ledger_rows) == payload["position_ledger"]["row_count"]
    changed = [row for row in ledger_rows if float(row["turnover"]) > 0.0 and row["signal_timestamp"]]
    assert changed
    for row in changed:
        assert pd.Timestamp(row["signal_timestamp"]) < pd.Timestamp(row["effective_timestamp"])
        assert row["reason"] == "exposure_changed_from_prior_effective_signal"


def test_all_strategy_cost_delay_and_blocked_grids_are_fixed(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=1700)

    payload = build_btc_trend_all_strategy_backtest_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        output=tmp_path / "report.json",
        grid_output=tmp_path / "grid.csv",
        ledger_output=tmp_path / "ledger.csv",
        markdown_output=tmp_path / "report.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["parameters"]["cost_bps_grid"] == COST_BPS_GRID
    assert payload["parameters"]["delay_days_grid"] == DELAY_DAYS_GRID

    tested_families = {row["family_id"] for row in payload["family_summaries"]}
    cost_keys = {(row["family_id"], row["cost_bps"]) for row in payload["cost_stress"]}
    delay_keys = {(row["family_id"], row["delay_days"]) for row in payload["delay_stress"]}
    for family_id in tested_families:
        assert {(family_id, cost) for cost in COST_BPS_GRID}.issubset(cost_keys)
        assert {(family_id, delay) for delay in DELAY_DAYS_GRID}.issubset(delay_keys)

    for blocked in payload["blocked_families"]:
        assert blocked["status"].startswith("blocked")
        assert blocked["reason"]
        assert blocked["required_data"]


def _write_daily_bundle(tmp_path: Path, *, rows: int) -> Path:
    bundle = tmp_path / f"daily_{rows}"
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
            regime = (day // 280) % 4
            base = 20_000 + day * 10
            cycle = ((day % 180) - 90) * 30
            shock = -4500 if regime == 1 else 3500 if regime == 2 else 0
            close = max(1000.0, base + cycle + shock)
            writer.writerow(
                {
                    "timestamp": ts.isoformat().replace("+00:00", "Z"),
                    "open_time": int(ts.timestamp() * 1000),
                    "symbol": "BTCUSDT",
                    "open": close - 40,
                    "high": close + 150,
                    "low": max(1.0, close - 150),
                    "close": close,
                    "volume_contracts": 1,
                    "volume_base": 1,
                    "volume_quote": close,
                    "confirm": 1,
                    "source_record_id": f"fixture:{day}",
                }
            )
    return bundle
