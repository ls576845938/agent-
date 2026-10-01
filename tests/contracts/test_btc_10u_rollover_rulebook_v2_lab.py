from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from quant_crypto.research import ten_u_rollover_rulebook_v2_lab as lab


def test_10u_v2_grid_declares_small_modification_space() -> None:
    scenarios = lab._scenario_grid()
    assert {scenario.base_leverage for scenario in scenarios} == {10.0, 15.0, 20.0}
    assert {scenario.add_trigger_mode for scenario in scenarios} == {"pct_8", "pct_12", "pct_16", "atr_1"}
    assert {scenario.exit_mode for scenario in scenarios} == {"no_daily_flat", "trend_failure", "max_hold_24h"}
    assert len(scenarios) == 36
    assert lab.MAX_HOLD_HOURS == 24
    assert lab.MONTHLY_RISK_OFF_DRAWDOWN_PCT == 0.20


def test_10u_v2_outputs_research_only_donchian_entry_and_risk_switch(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    monkeypatch.setattr(lab, "_donchian_direction_4h", _long_then_short_direction)

    report = lab.build_btc_10u_rollover_rulebook_v2_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 3, tzinfo=timezone.utc),
        initial_capital=1000.0,
    )

    assert report["schema_version"] == "btc_10u_rollover_rulebook_v2_lab_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_10u_rollover_rulebook_v2_lab_research_only_no_paper_no_live"
    design = report["research_design"]
    assert design["candidate_count"] == 36
    assert design["entry_signal"] == "existing Donchian long/short trend direction, shifted before 1h execution"
    assert design["monthly_risk_switch"]["role"] == "big risk switch only, not an entry signal"
    assert design["add_trigger_modes"] == ["pct_8", "pct_12", "pct_16", "atr_1"]
    assert design["exit_modes"] == ["no_daily_flat", "trend_failure", "max_hold_24h"]
    assert design["same_bar_profit_allowed"] is False
    assert report["summary"]["trade_signal_nonzero_ratio"] > 0.0
    assert report["summary"]["monthly_risk_on_ratio"] > 0.0
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["broker_access_allowed"] is False

    rows = report["grid_rows_sample"]
    assert rows
    assert any(row["entry_signal"] == "shifted_frozen_donchian_long_short" for row in rows)
    assert any(row["monthly_risk_switch_only"] is True for row in rows)
    assert any(float(row["base_leverage"]) == 20.0 for row in rows)
    assert any(row["research_decision"] == "extreme_leverage_v2_research_only_not_paper_eligible" for row in rows)
    assert all(row["paper_queue_write_allowed"] is False for row in rows)
    assert all(row["paper_candidate_created"] is False for row in rows)
    assert all(row["live_unlock_allowed"] is False for row in rows)
    assert {"long_entry_count", "short_entry_count", "add_count", "trend_failure_exit_count", "max_hold_exit_count"} <= set(rows[0])

    event_types = {event["event_type"] for event in report["event_sample"]}
    assert "entry_count" in event_types
    assert any(event.get("side") in {"long", "short"} for event in report["event_sample"])

    for name in [
        "btc_10u_rollover_rulebook_v2_lab_report.json",
        "btc_10u_rollover_rulebook_v2_lab_grid.csv",
        "btc_10u_rollover_rulebook_v2_lab_events.csv",
        "btc_10u_rollover_rulebook_v2_lab_summary_cn.md",
        "paper_live_safety_status.json",
    ]:
        assert (tmp_path / "out" / name).exists()
    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["paper_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False


def test_10u_v2_missing_5m_is_proxy_warning_not_promotion(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db, include_5m=False)
    _write_derivatives(derivatives)
    monkeypatch.setattr(lab, "_donchian_direction_4h", _long_then_short_direction)

    report = lab.build_btc_10u_rollover_rulebook_v2_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 3, tzinfo=timezone.utc),
        initial_capital=1000.0,
    )

    assert report["status"] == "complete_research_only"
    assert "5m_emergency_kill_used_1h_proxy_due_to_missing_5m_data" in report["warnings"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def _long_then_short_direction(*, bars_1h, bars_4h, derivatives_4h, initial_capital: float, base_cost_bps: float) -> pd.Series:
    index = bars_4h.index
    split = len(index) // 2
    values = [1.0 if i < split else -1.0 for i in range(len(index))]
    return pd.Series(values, index=index, dtype=float)


def _write_market_db(path: Path, *, include_5m: bool = True) -> None:
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
    total_hours = 240 * 24
    for i in range(total_hours):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        drift = 1.0009 if i < total_hours // 2 else 0.9991
        price *= drift
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
                price * 0.998,
                price,
                100.0,
            )
        )
    if include_5m:
        price_5m = 100.0
        total_5m = total_hours * 12
        for i in range(total_5m):
            open_time = start + timedelta(minutes=5 * i)
            close_time = open_time + timedelta(minutes=5) - timedelta(milliseconds=1)
            drift = 1.000075 if i < total_5m // 2 else 0.999925
            price_5m *= drift
            rows.append(
                (
                    "binance_spot",
                    "BTCUSDT",
                    "5m",
                    int(open_time.timestamp() * 1000),
                    open_time.isoformat(),
                    int(close_time.timestamp() * 1000),
                    close_time.isoformat(),
                    price_5m * 0.9995,
                    price_5m * 1.001,
                    price_5m * 0.999,
                    price_5m,
                    20.0,
                )
            )
    conn.executemany("insert into market_klines values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _write_derivatives(path: Path) -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(240 * 24):
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
