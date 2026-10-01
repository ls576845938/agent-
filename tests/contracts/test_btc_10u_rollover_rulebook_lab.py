from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from quant_crypto.research import ten_u_rollover_rulebook_lab as lab


def test_10u_rulebook_grid_translates_declared_guide_rules() -> None:
    scenarios = lab._scenario_grid()
    assert {scenario.base_leverage for scenario in scenarios} == {10.0, 15.0, 20.0}
    assert {scenario.daily_flat_enabled for scenario in scenarios} == {True, False}
    assert {scenario.add_enabled for scenario in scenarios} == {True, False}
    assert {scenario.signal_mode for scenario in scenarios} == {"monthly_only", "monthly_plus_donchian"}
    assert all(scenario.emergency_kill_enabled for scenario in scenarios)
    assert lab.INITIAL_SLEEVE_COUNT == 10
    assert lab.STOP_LOSS_PCT == 0.03
    assert lab.EMERGENCY_5M_ADVERSE_PCT == 0.05
    assert lab.ADD_ALLOCATION_MULTIPLIERS == (1.0, 0.8, 0.6)
    assert lab.PROFIT_EXTRACT_MULTIPLE == 3.0
    assert lab.CONSECUTIVE_LOSS_PAUSE_TRIGGER == 3
    assert lab.GLOBAL_PAUSE_DAYS == 7


def test_10u_rulebook_lab_outputs_research_only_artifacts_and_rule_fields(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    monkeypatch.setattr(lab, "_frozen_v3_direction", _always_long_direction)

    report = lab.build_btc_10u_rollover_rulebook_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 3, tzinfo=timezone.utc),
        initial_capital=1000.0,
    )

    assert report["schema_version"] == "btc_10u_rollover_rulebook_lab_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_10u_rollover_rulebook_lab_research_only_no_paper_no_live"
    assert report["research_design"]["initial_sleeve_count"] == 10
    assert report["research_design"]["base_leverage_grid"] == [10.0, 15.0, 20.0]
    assert report["research_design"]["stop_loss_pct"] == 0.03
    assert report["research_design"]["emergency_5m_adverse_pct"] == 0.05
    assert report["research_design"]["add_allocation_multipliers"] == [1.0, 0.8, 0.6]
    assert report["research_design"]["same_bar_profit_allowed"] is False
    assert report["research_design"]["signal_mode_grid"] == ["monthly_only", "monthly_plus_donchian"]
    assert report["summary"]["candidate_count"] == 24
    assert report["summary"]["extreme_leverage_candidate_count"] >= 1
    assert report["summary"]["monthly_trend_up_ratio"] > 0.0
    assert report["summary"]["monthly_only_signal_ratio"] > 0.0
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["broker_access_allowed"] is False

    rows = report["grid_rows_sample"]
    assert rows
    assert any(float(row["base_leverage"]) == 20.0 for row in rows)
    assert any(row["signal_mode"] == "monthly_only" for row in rows)
    assert any(row["research_decision"] == "extreme_leverage_rulebook_research_only_not_paper_eligible" for row in rows)
    assert all(row["paper_queue_write_allowed"] is False for row in rows)
    assert all(row["paper_candidate_created"] is False for row in rows)
    assert all(row["live_unlock_allowed"] is False for row in rows)
    assert {"entry_count", "stop_loss_count", "emergency_5m_kill_count", "daily_flat_count", "cooldown_count"} <= set(rows[0])

    event_types = {event["event_type"] for event in report["event_sample"]}
    assert "entry_count" in event_types
    assert "emergency_5m_kill_count" in event_types or "stop_loss_count" in event_types

    for name in [
        "btc_10u_rollover_rulebook_lab_report.json",
        "btc_10u_rollover_rulebook_lab_grid.csv",
        "btc_10u_rollover_rulebook_lab_events.csv",
        "btc_10u_rollover_rulebook_lab_summary_cn.md",
        "paper_live_safety_status.json",
    ]:
        assert (tmp_path / "out" / name).exists()
    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["paper_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False


def test_10u_rulebook_falls_back_to_1h_emergency_proxy_without_unlocking(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db, include_5m=False)
    _write_derivatives(derivatives)
    monkeypatch.setattr(lab, "_frozen_v3_direction", _always_long_direction)

    report = lab.build_btc_10u_rollover_rulebook_lab(
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


def _always_long_direction(market, *, initial_capital: float, base_cost_bps: float) -> pd.Series:
    return pd.Series(1.0, index=market["bars_4h"].index, dtype=float)


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
    for i in range(210 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        if i == 150 * 24 + 5:
            low = price * 0.92
            close = price * 0.98
        else:
            price *= 1.0007
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
    if include_5m:
        price_5m = 100.0
        for i in range(210 * 24 * 12):
            open_time = start + timedelta(minutes=5 * i)
            close_time = open_time + timedelta(minutes=5) - timedelta(milliseconds=1)
            price_5m *= 1.000058
            low = price_5m * 0.999
            if i == (150 * 24 + 5) * 12:
                low = price_5m * 0.93
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
                    low,
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
    for i in range(210 * 24):
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
