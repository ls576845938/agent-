from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.short_interval_data_refresh import build_btc_short_interval_data_refresh
from quant_crypto.research.small_account_high_yield_lab import build_btc_small_account_high_yield_lab
from quant_crypto.research.small_account_high_yield_near_miss_review import (
    V2_DRAWDOWN_GATES,
    V2_LIQUIDATION_BUFFERS_BPS,
    V2_MAX_LEVERAGES,
    V2_VOL_TARGETS,
    build_btc_small_account_high_yield_near_miss_review,
)


def test_near_miss_review_builds_top10_attribution_and_v2_grid(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    top5 = tmp_path / "top5.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    _write_top5(top5)
    refresh = build_btc_short_interval_data_refresh(
        market_db_path=db,
        output_dir=tmp_path / "refresh",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        execute_network=False,
    )
    assert refresh["status"] == "complete_research_only"
    high_yield = build_btc_small_account_high_yield_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        source_top5_report_path=top5,
        data_refresh_report_path=tmp_path / "refresh" / "btc_short_interval_data_refresh_report.json",
        output_dir=tmp_path / "hy",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        top_n=1,
    )
    assert high_yield["status"] == "complete_research_only"

    report = build_btc_small_account_high_yield_near_miss_review(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        source_high_yield_report_path=tmp_path / "hy" / "btc_small_account_high_yield_lab_report.json",
        source_top5_report_path=top5,
        output_dir=tmp_path / "near",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_small_account_high_yield_near_miss_research_only_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["validation_design"]["v2_candidate_count"] == 270
    assert len(report["v2_narrow_grid_rows"]) == 270
    assert report["validation_design"]["trendless_filter"]["uses_shift_1"] is True

    top10 = report["top10_near_miss_review"]
    assert top10
    required = {
        "gap_to_60_pct",
        "cost_drag_annual_pct",
        "drawdown_gate_drag_annual_pct",
        "consecutive_loss_derisk_drag_annual_pct",
        "liquidation_buffer_derisk_drag_annual_pct",
        "trendless_or_low_exposure_gap_pct",
    }
    assert required <= set(top10[0])

    v2 = report["v2_narrow_grid_rows"]
    assert {float(row["vol_target_pct"]) for row in v2} == set(V2_VOL_TARGETS)
    assert {float(row["max_leverage"]) for row in v2} == set(V2_MAX_LEVERAGES)
    assert {float(row["drawdown_gate_pct"]) for row in v2} == set(V2_DRAWDOWN_GATES)
    assert {float(row["min_liquidation_buffer_bps_policy"]) for row in v2} == set(V2_LIQUIDATION_BUFFERS_BPS)
    assert {row["trendless_filter"] for row in v2} == {"off", "on"}
    assert all(float(row["max_leverage"]) <= 3.0 for row in v2)
    assert all(row["paper_queue_write_allowed"] is False for row in v2)
    assert all(row["paper_candidate_created"] is False for row in v2)
    assert all(row["live_unlock_allowed"] is False for row in v2)
    assert sum(1 for row in v2 if row["trendless_filter"] == "on") == 135

    comparison = report["vol_target_120_vs_fixed_3x"]
    assert comparison["same_window_same_signal"] is True
    assert "high_volatility_loss_comparison" in comparison
    assert "vol_target_120" in comparison["high_volatility_loss_comparison"]
    assert "fixed_3x" in comparison["high_volatility_loss_comparison"]

    intraday = report["intraday_contribution"]
    assert intraday["intraday_15m_evaluated"] is True
    assert intraday["intraday_15m_not_mixed_into_v2_grid"] is True
    assert intraday["paper_queue_write_allowed"] is False
    assert intraday["live_unlock_allowed"] is False

    safety = json.loads((tmp_path / "near" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert (tmp_path / "near" / "btc_small_account_high_yield_near_miss_top10_review.csv").exists()
    assert (tmp_path / "near" / "btc_small_account_high_yield_near_miss_v2_grid.csv").exists()
    markdown = (tmp_path / "near" / "btc_small_account_high_yield_near_miss_review_summary_cn.md").read_text(encoding="utf-8")
    assert "BTC 高收益 Near-Miss 复核包" in markdown
    assert "不写 paper 队列" in markdown


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
    for i in range(260 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        if i < 90 * 24:
            drift = 1.00055
        elif i < 150 * 24:
            drift = 0.9994
        else:
            drift = 1.00035 + (0.0004 if i % 48 < 6 else -0.00003)
        price = max(30.0, price * drift)
        rows.append(_row("1h", open_time, close_time, price, 100.0 + (i % 24)))
    minute_start = start + timedelta(days=254)
    minute_price = price * 0.95
    for i in range(6 * 24 * 60):
        open_time = minute_start + timedelta(minutes=i)
        close_time = open_time + timedelta(minutes=1) - timedelta(milliseconds=1)
        minute_price *= 1.0 + (0.00006 if i % 240 < 80 else -0.000025)
        rows.append(_row("1m", open_time, close_time, minute_price, 2.0 + (i % 5)))
    conn.executemany("insert into market_klines values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _write_derivatives(path: Path) -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(260 * 24):
        event_time = start + timedelta(hours=i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "open_interest_usd": 1_000_000.0 + i * 100.0 + (i % 48) * 20.0,
                "funding_rate": 0.00003 + ((i % 96) - 48) * 0.0000005,
                "long_short_ratio": 1.0 + ((i % 144) - 72) / 900.0,
                "top_trader_long_short_ratio": 1.0,
                "taker_buy_sell_ratio": 1.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")


def _write_top5(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "btc_long_short_top5_review_v1",
                "candidate_rows": [
                    {
                        "variant_id": "formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone",
                        "review_decision": "trend_following_concentration_expected_requires_forward_confirmation",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _row(interval: str, open_time: datetime, close_time: datetime, price: float, volume: float) -> tuple:
    return (
        "binance_spot",
        "BTCUSDT",
        interval,
        int(open_time.timestamp() * 1000),
        open_time.isoformat(),
        int(close_time.timestamp() * 1000),
        close_time.isoformat(),
        price * 0.999,
        price * 1.001,
        price * 0.998,
        price,
        volume,
    )
