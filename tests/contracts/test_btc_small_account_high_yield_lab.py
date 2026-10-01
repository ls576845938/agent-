from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.short_interval_data_refresh import build_btc_short_interval_data_refresh
from quant_crypto.research.small_account_high_yield_lab import build_btc_small_account_high_yield_lab


def test_small_account_high_yield_lab_is_research_only_and_uses_short_interval_gate(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    source_top5 = tmp_path / "top5.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    _write_top5(source_top5)
    refresh_report = build_btc_short_interval_data_refresh(
        market_db_path=db,
        output_dir=tmp_path / "refresh",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        execute_network=False,
    )
    assert refresh_report["status"] == "complete_research_only"

    report = build_btc_small_account_high_yield_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        source_top5_report_path=source_top5,
        data_refresh_report_path=tmp_path / "refresh" / "btc_short_interval_data_refresh_report.json",
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        top_n=1,
    )

    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_small_account_high_yield_lab_research_only_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["validation_design"]["max_leverage"] == 3.0
    assert report["validation_design"]["funding_oi_long_short_usage"] == "risk_filter_only_never_standalone_direction"
    assert report["input"]["intraday_15m_enabled"] is True
    assert {row["bucket"] for row in report["candidate_rows"]} >= {"donchian_leverage_overlay", "intraday_15m"}
    assert all(float(row["max_leverage"]) <= 3.0 for row in report["candidate_rows"])
    assert all(row["paper_queue_write_allowed"] is False for row in report["candidate_rows"])
    assert all(row["paper_candidate_created"] is False for row in report["candidate_rows"])
    assert all(row["live_unlock_allowed"] is False for row in report["candidate_rows"])
    assert all("simulated_liquidation_count" in row for row in report["candidate_rows"])
    assert all(row["forward_30d_status"] == "pending_future_data" for row in report["candidate_rows"])
    assert all(row["forward_60d_status"] == "pending_future_data" for row in report["candidate_rows"])
    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    markdown = (tmp_path / "out" / "btc_small_account_high_yield_lab_summary_cn.md").read_text(encoding="utf-8")
    assert "BTC 小资金高收益研究实验室" in markdown
    assert "不写 paper 队列" in markdown


def test_high_yield_lab_blocks_intraday_bucket_when_short_interval_data_not_ready(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    source_top5 = tmp_path / "top5.json"
    _write_market_db(db, include_1m=False)
    _write_derivatives(derivatives)
    _write_top5(source_top5)
    missing_refresh = tmp_path / "missing_refresh.json"

    report = build_btc_small_account_high_yield_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        source_top5_report_path=source_top5,
        data_refresh_report_path=missing_refresh,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        top_n=1,
    )

    assert report["status"] == "complete_research_only"
    assert "btc_high_yield_short_interval_data_not_ready" in report["intraday_blockers"]
    assert {row["bucket"] for row in report["candidate_rows"]} == {"donchian_leverage_overlay"}
    assert report["gate"]["live_order_allowed"] is False


def _write_market_db(path: Path, *, include_1m: bool = True) -> None:
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
    if include_1m:
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
                        "variant_id": "formal_donchian_w120_d50_200_atr20_cd0_fail0_risknone",
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
        price * 1.0015,
        price * 0.9985,
        price,
        volume,
    )

