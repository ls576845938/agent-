from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from scripts.build_btc_trend_priority_strategy_backtest_report import (
    COST_BPS_GRID,
    DELAY_DAYS_GRID,
    EWMAC_PAIRS,
    FIRST_PRIORITY_FAMILIES,
    MA_FAST_WINDOWS,
    MA_SLOW_WINDOWS,
    MOMENTUM_WINDOWS,
    TARGET_VOLS,
    VOL_WINDOWS,
    build_btc_trend_priority_strategy_backtest_report,
)


def test_priority_backtest_short_history_blocks_ranking(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=400)

    payload = build_btc_trend_priority_strategy_backtest_report(
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
    assert "btc_trend_priority_validation_requires_at_least_1095_daily_rows" in payload["blockers"]
    assert (tmp_path / "grid.csv").read_text(encoding="utf-8").startswith("candidate_id,family_id")


def test_priority_backtest_runs_first_priority_grid_and_writes_t_plus_1_ledger(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=1700)

    payload = build_btc_trend_priority_strategy_backtest_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        output=tmp_path / "report.json",
        grid_output=tmp_path / "grid.csv",
        ledger_output=tmp_path / "ledger.csv",
        markdown_output=tmp_path / "report.md",
        initial_capital=10_000.0,
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "research_only_backtest_complete"
    assert payload["first_priority_families"] == FIRST_PRIORITY_FAMILIES
    assert payload["guardrails"]["private_endpoint_used"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["optimization_objective"]["name"] == "cost_adjusted_return_risk_score"
    assert "Sharpe-only" in " ".join(payload["optimization_objective"]["notes"])

    family_ids = {row["family_id"] for row in payload["family_summaries"]}
    assert family_ids == set(FIRST_PRIORITY_FAMILIES)
    assert all(row["candidate_count"] > 0 for row in payload["family_summaries"])
    assert payload["walk_forward"]["summary"]["all_first_priority_families_have_walk_forward"] is True
    assert payload["position_ledger"]["complete"] is True

    grid_rows = list(csv.DictReader((tmp_path / "grid.csv").open("r", encoding="utf-8")))
    assert len(grid_rows) == payload["grid_output"]["row_count"]
    assert {row["family_id"] for row in grid_rows} == set(FIRST_PRIORITY_FAMILIES)

    ledger_rows = list(csv.DictReader((tmp_path / "ledger.csv").open("r", encoding="utf-8")))
    assert ledger_rows
    changed = [row for row in ledger_rows if float(row["turnover"]) > 0.0 and row["signal_timestamp"]]
    assert changed
    for row in changed:
        assert pd.Timestamp(row["signal_timestamp"]) < pd.Timestamp(row["effective_timestamp"])
        assert row["reason"] == "exposure_changed_from_prior_effective_signal"


def test_priority_backtest_parameter_and_stress_grids_are_fixed(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=1700)

    payload = build_btc_trend_priority_strategy_backtest_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        output=tmp_path / "report.json",
        grid_output=tmp_path / "grid.csv",
        ledger_output=tmp_path / "ledger.csv",
        markdown_output=tmp_path / "report.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    params = payload["parameters"]
    assert params["cost_bps_grid"] == COST_BPS_GRID
    assert params["delay_days_grid"] == DELAY_DAYS_GRID
    assert params["momentum_windows"] == MOMENTUM_WINDOWS
    assert params["ma_fast_windows"] == MA_FAST_WINDOWS
    assert params["ma_slow_windows"] == MA_SLOW_WINDOWS
    assert params["ewmac_pairs"] == [list(pair) for pair in EWMAC_PAIRS]
    assert params["vol_windows"] == VOL_WINDOWS
    assert params["target_vols"] == TARGET_VOLS

    cost_keys = {(row["family_id"], row["cost_bps"]) for row in payload["cost_stress"]}
    delay_keys = {(row["family_id"], row["delay_days"]) for row in payload["delay_stress"]}
    for family_id in FIRST_PRIORITY_FAMILIES:
        assert {(family_id, cost) for cost in COST_BPS_GRID}.issubset(cost_keys)
        assert {(family_id, delay) for delay in DELAY_DAYS_GRID}.issubset(delay_keys)

    default_params = {
        summary["family_id"]: summary["default_candidate"]["params"]
        for summary in payload["family_summaries"]
    }
    assert default_params["t01_twelve_month_momentum"] == {"momentum_window": 365, "position_mode": "binary"}
    assert default_params["t02_long_ma_trend"] == {"ma_fast": 120, "ma_slow": 200, "position_mode": "binary"}
    assert default_params["t03_ewmac_forecast"]["ewmac_fast"] == 16
    assert default_params["t03_ewmac_forecast"]["ewmac_slow"] == 64


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
            trend = day * 18
            cycle = ((day % 240) - 120) * 12
            close = 20_000 + trend + cycle
            writer.writerow(
                {
                    "timestamp": ts.isoformat().replace("+00:00", "Z"),
                    "open_time": int(ts.timestamp() * 1000),
                    "symbol": "BTCUSDT",
                    "open": close - 30,
                    "high": close + 120,
                    "low": max(1.0, close - 120),
                    "close": close,
                    "volume_contracts": 1,
                    "volume_base": 1,
                    "volume_quote": close,
                    "confirm": 1,
                    "source_record_id": f"fixture:{day}",
                }
            )
    return bundle
