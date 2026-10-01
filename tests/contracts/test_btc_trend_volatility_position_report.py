from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from scripts.build_btc_trend_all_strategy_backtest_report import _candidate_specs
from scripts.build_btc_trend_volatility_position_report import (
    TARGET_VOLS,
    VOL_WINDOWS,
    build_btc_trend_volatility_position_report,
)


def test_volatility_position_blocks_without_top_validation_report(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=700)

    payload = build_btc_trend_volatility_position_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        top_validation_report=tmp_path / "missing.json",
        output=tmp_path / "report.json",
        grid_output=tmp_path / "grid.csv",
        ledger_output=tmp_path / "ledger.csv",
        markdown_output=tmp_path / "report.md",
        minimum_daily_rows=600,
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "volatility_position_blocked"
    assert "btc_trend_top_strategy_validation_report_missing_or_unexpected_status" in payload["blockers"]
    assert payload["grid_output"]["row_count"] == 0
    assert payload["position_ledger"]["complete"] is False
    assert (tmp_path / "grid.csv").read_text(encoding="utf-8").startswith("family_id,base_candidate_id")


def test_volatility_position_builds_grid_and_t_plus_1_ledger(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=900)
    top_report = tmp_path / "top.json"
    _write_top_validation_report(top_report, ["t01_twelve_month_momentum", "t06_atr_channel_breakout"])

    payload = build_btc_trend_volatility_position_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        top_validation_report=top_report,
        output=tmp_path / "report.json",
        grid_output=tmp_path / "grid.csv",
        ledger_output=tmp_path / "ledger.csv",
        markdown_output=tmp_path / "report.md",
        minimum_daily_rows=600,
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "volatility_position_research_only"
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["this_report_does_not_unlock_live_trading"] is True
    assert payload["parameters"]["vol_windows"] == VOL_WINDOWS
    assert payload["parameters"]["target_vols"] == TARGET_VOLS
    assert payload["grid_output"]["row_count"] == 2 * len(VOL_WINDOWS) * len(TARGET_VOLS)
    assert payload["position_ledger"]["complete"] is True
    assert len(payload["family_summaries"]) == 2

    ledger_rows = list(csv.DictReader((tmp_path / "ledger.csv").open("r", encoding="utf-8")))
    assert ledger_rows
    changed = [row for row in ledger_rows if float(row["turnover"]) > 0.0 and row["signal_timestamp"]]
    assert changed
    for row in changed:
        assert pd.Timestamp(row["signal_timestamp"]) < pd.Timestamp(row["effective_timestamp"])
        assert row["reason"] == "volatility_target_exposure_changed"
        assert 0.0 <= float(row["exposure"]) <= 1.0


def test_volatility_position_reports_risk_differences_against_baseline(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=900)
    top_report = tmp_path / "top.json"
    _write_top_validation_report(top_report, ["t01_twelve_month_momentum"])

    payload = build_btc_trend_volatility_position_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        top_validation_report=top_report,
        output=tmp_path / "report.json",
        grid_output=tmp_path / "grid.csv",
        ledger_output=tmp_path / "ledger.csv",
        markdown_output=tmp_path / "report.md",
        minimum_daily_rows=600,
        generated_at="2026-06-23T00:00:00Z",
    )

    summary = payload["family_summaries"][0]
    selected = summary["selected_variant"]
    assert "volatility_reduction_vs_baseline_pct" in selected
    assert "drawdown_reduction_vs_baseline_pct" in selected
    assert "sharpe_diff_vs_baseline" in selected
    assert summary["variant_count"] == len(VOL_WINDOWS) * len(TARGET_VOLS)
    assert (tmp_path / "report.md").read_text(encoding="utf-8").startswith("# BTC 趋势波动率仓位报告")


def _write_top_validation_report(path: Path, families: list[str]) -> None:
    specs = _candidate_specs()
    rows = []
    for family_id in families:
        spec = next(item for item in specs if item.family_id == family_id)
        rows.append(
            {
                "family_id": spec.family_id,
                "candidate_id": spec.candidate_id,
                "validation_status": "research_validation_passed",
            }
        )
    path.write_text(
        json.dumps(
            {
                "status": "top_strategy_validation_research_only",
                "candidate_summaries": rows,
                "guardrails": {"live_order_allowed": False},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


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
            high_vol_cycle = ((day % 90) - 45) * (70 if day > rows // 2 else 20)
            trend = day * 12
            close = max(1000.0, 20_000 + trend + high_vol_cycle)
            writer.writerow(
                {
                    "timestamp": ts.isoformat().replace("+00:00", "Z"),
                    "open_time": int(ts.timestamp() * 1000),
                    "symbol": "BTCUSDT",
                    "open": close - 30,
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
