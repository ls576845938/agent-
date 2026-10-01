from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from quant_crypto.research import high_octane_10u_discipline_overlay_lab as lab


SCENARIO_ID = "ho_step0p35_core5x6_reserve5x2_attack10x2_cap2_max10_delaylate_none"


def test_high_octane_10u_overlay_builds_research_only_packet(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    watchlist = tmp_path / "watchlist.csv"
    _write_market_db(db)
    _write_derivatives(derivatives)
    _write_watchlist(watchlist)
    monkeypatch.setattr(lab, "_frozen_v3_direction", _always_long_direction)

    report = lab.build_btc_high_octane_10u_discipline_overlay_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        high_octane_watchlist_path=watchlist,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 3, tzinfo=timezone.utc),
        initial_capital=1000.0,
        top_n=1,
    )

    assert report["schema_version"] == "btc_high_octane_10u_discipline_overlay_lab_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_high_octane_10u_discipline_overlay_lab_research_only_no_paper_no_live"
    design = report["research_design"]
    assert design["candidate_count"] == 1
    assert design["cooldown_bars_4h"] == 12
    assert design["global_pause_bars_4h"] == 42
    assert "10 isolated sleeve accounts" in design["overlay_disciplines"]
    assert "20pct leverage derisk after loss" in design["overlay_disciplines"]
    assert design["same_bar_profit_allowed"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["broker_access_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False

    rows = report["grid_rows_sample"]
    assert len(rows) == 1
    row = rows[0]
    assert row["scenario_id"] == SCENARIO_ID
    assert row["overlay"] == "10u_discipline_cooldown_derisk_pause_extract_safe_account"
    assert row["max_template_leverage"] <= 10.0
    assert row["paper_queue_write_allowed"] is False
    assert row["paper_candidate_created"] is False
    assert row["live_unlock_allowed"] is False
    assert {
        "cooldown_count",
        "leverage_derisk_count",
        "global_pause_count",
        "extract_count",
        "weekly_safe_transfer_count",
        "safe_cash",
        "strategic_reserve",
        "min_remaining_capital_pct_after_10pct_spike",
        "annual_return_delta_vs_source_pct",
    } <= set(row)

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["paper_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False

    for name in [
        "btc_high_octane_10u_discipline_overlay_lab_report.json",
        "btc_high_octane_10u_discipline_overlay_lab_grid.csv",
        "btc_high_octane_10u_discipline_overlay_lab_events.csv",
        "btc_high_octane_10u_discipline_overlay_lab_summary_cn.md",
        "paper_live_safety_status.json",
    ]:
        assert (tmp_path / "out" / name).exists()


def test_high_octane_10u_overlay_blocks_missing_source_without_unlocking(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)

    report = lab.build_btc_high_octane_10u_discipline_overlay_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        high_octane_watchlist_path=tmp_path / "missing.csv",
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 3, tzinfo=timezone.utc),
        initial_capital=1000.0,
        top_n=1,
    )

    assert report["status"] == "blocked"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert any("missing_high_octane_watchlist" in blocker for blocker in report["blockers"])


def _always_long_direction(market, *, initial_capital: float, base_cost_bps: float) -> pd.Series:
    return pd.Series(1.0, index=market["bars_4h"].index, dtype=float)


def _write_watchlist(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "scenario_id",
                "annual_return_pct",
                "total_return_pct",
                "max_drawdown_abs_pct",
                "min_remaining_capital_pct_after_10pct_spike",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "scenario_id": SCENARIO_ID,
                "annual_return_pct": "500.0",
                "total_return_pct": "5000.0",
                "max_drawdown_abs_pct": "35.0",
                "min_remaining_capital_pct_after_10pct_spike": "45.0",
            }
        )


def _write_market_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        create table market_klines (
            exchange text not null,
            symbol text not null,
            interval text not null,
            open_time_ms integer not null,
            open_time text not null,
            close_time_ms integer not null,
            close_time text not null,
            open real not null,
            high real not null,
            low real not null,
            close real not null,
            volume real not null
        )
        """
    )
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    for i in range(220 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        price *= 1.00085
        if i in {900, 1300, 1800}:
            low = price * 0.96
            close = price * 0.985
        else:
            low = price * 0.998
            close = price
        rows.append(
            (
                "binance_spot",
                "BTCUSDT",
                "1h",
                int(open_time.timestamp() * 1000),
                open_time.isoformat(),
                int(close_time.timestamp() * 1000),
                close_time.isoformat(),
                price * 0.999,
                price * 1.002,
                low,
                close,
                100.0,
            )
        )
    conn.executemany("insert into market_klines values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _write_derivatives(path: Path) -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(220 * 24):
        event_time = start + timedelta(hours=i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "open_interest_usd": 1_000_000.0,
                "funding_rate": 0.00001,
                "long_short_ratio": 1.0,
                "top_trader_long_short_ratio": 1.0,
                "taker_buy_sell_ratio": 1.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
