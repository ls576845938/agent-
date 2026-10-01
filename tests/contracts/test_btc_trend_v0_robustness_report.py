from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from scripts.build_btc_trend_v0_robustness_report import (
    COST_BPS_GRID,
    DELAY_DAYS_GRID,
    MA_FAST_GRID,
    MA_SLOW_GRID,
    MOMENTUM_WINDOW_GRID,
    TARGET_VOL_GRID,
    VOL_WINDOW_GRID,
    build_btc_trend_v0_robustness_report,
)


def test_btc_trend_v0_robustness_short_history_is_insufficient(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=400)

    payload = build_btc_trend_v0_robustness_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        output=tmp_path / "robustness.json",
        ledger_output=tmp_path / "ledger.csv",
        markdown_output=tmp_path / "robustness.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "insufficient_history"
    assert payload["candidate_ranking"] == []
    assert payload["position_ledger"]["complete"] is False
    assert "btc_trend_v0_robustness_requires_at_least_1095_daily_rows" in payload["blockers"]
    assert (tmp_path / "ledger.csv").read_text(encoding="utf-8").startswith("timestamp,strategy_id,close")


def test_btc_trend_v0_robustness_writes_shifted_position_ledger(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=1200)

    payload = build_btc_trend_v0_robustness_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        output=tmp_path / "robustness.json",
        ledger_output=tmp_path / "ledger.csv",
        markdown_output=tmp_path / "robustness.md",
        initial_capital=10_000.0,
        generated_at="2026-06-23T00:00:00Z",
    )

    rows = list(csv.DictReader((tmp_path / "ledger.csv").open("r", encoding="utf-8")))
    assert payload["status"] == "research_only"
    assert payload["position_ledger"]["complete"] is True
    assert payload["paper_candidate_ready"] is False
    assert payload["promotion_allowed"] is False
    assert rows
    assert {row["strategy_id"] for row in rows} == set(payload["formal_strategy_ids"])
    assert all(row["reason"] for row in rows)
    changed = [row for row in rows if float(row["turnover"]) > 0.0]
    assert changed
    assert all(row["reason"] == "exposure_changed_from_prior_effective_signal" for row in changed)

    positive = [row for row in rows if float(row["exposure"]) > 0.0]
    assert positive
    for row in positive:
        signal_ts = pd.Timestamp(row["signal_timestamp"])
        effective_ts = pd.Timestamp(row["effective_timestamp"])
        assert signal_ts < effective_ts

    default_by_id = {row["strategy_id"]: row for row in payload["default_performance"]}
    ledger_final = max(
        (row for row in rows if row["strategy_id"] == "ma120_200_trend_intended"),
        key=lambda row: row["timestamp"],
    )
    assert float(ledger_final["equity"]) == default_by_id["ma120_200_trend_intended"]["metrics"]["final_equity"]


def test_btc_trend_v0_robustness_fixed_grids_and_cost_stress(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=1200)

    payload = build_btc_trend_v0_robustness_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        output=tmp_path / "robustness.json",
        ledger_output=tmp_path / "ledger.csv",
        markdown_output=tmp_path / "robustness.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    params = payload["parameters"]
    assert params["cost_bps_grid"] == COST_BPS_GRID
    assert params["delay_days_grid"] == DELAY_DAYS_GRID
    assert params["ma_fast_grid"] == MA_FAST_GRID
    assert params["ma_slow_grid"] == MA_SLOW_GRID
    assert params["momentum_window_grid"] == MOMENTUM_WINDOW_GRID
    assert params["vol_window_grid"] == VOL_WINDOW_GRID
    assert params["target_vol_grid"] == TARGET_VOL_GRID

    summary = payload["parameter_matrix_summary"]
    assert summary["ma120_200_trend_intended"]["row_count"] == 9
    assert summary["ma120_200_trend_intended"]["default_present"] is True
    assert summary["ma120_200_trend_vol_target_intended"]["row_count"] == 81
    assert summary["ma120_200_trend_vol_target_intended"]["default_present"] is True
    assert summary["twelve_month_momentum_intended"]["row_count"] == 3
    assert summary["twelve_month_momentum_intended"]["default_present"] is True

    ma_costs = [
        row
        for row in payload["cost_stress"]
        if row["strategy_id"] == "ma120_200_trend_intended"
    ]
    assert [row["cost_bps"] for row in ma_costs] == COST_BPS_GRID
    returns_by_cost = {row["cost_bps"]: row["metrics"]["total_return_pct"] for row in ma_costs}
    assert returns_by_cost[0.0] >= returns_by_cost[5.0] >= returns_by_cost[10.0] >= returns_by_cost[25.0]


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
            cycle = (day % 360) - 180
            close = 20_000 + day * 18 + cycle * 8
            writer.writerow(
                {
                    "timestamp": ts.isoformat().replace("+00:00", "Z"),
                    "open_time": int(ts.timestamp() * 1000),
                    "symbol": "BTCUSDT",
                    "open": close - 30,
                    "high": close + 120,
                    "low": close - 120,
                    "close": close,
                    "volume_contracts": 1,
                    "volume_base": 1,
                    "volume_quote": close,
                    "confirm": 1,
                    "source_record_id": f"fixture:{day}",
                }
            )
    return bundle
