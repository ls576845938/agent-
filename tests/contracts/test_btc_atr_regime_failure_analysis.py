from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.atr_regime_failure_analysis import (
    build_btc_atr_regime_failure_analysis,
    build_market_regime_frame,
)
from quant_crypto.research.simple_trend_rule_lab import aggregate_ohlcv, load_market_1h


def test_atr_regime_failure_report_is_research_only_and_segments_market(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)

    report = build_btc_atr_regime_failure_analysis(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 29, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_atr_regime_failure_analysis_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_atr_regime_failure_analysis_research_only_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert {row["segment_id"] for row in report["calendar_segment_review"]} >= {
        "2024_trend_segment",
        "2025_drawdown_segment",
        "2026_recent_segment",
    }
    assert report["regime_review"]
    assert report["segment_regime_matrix"]
    assert "should_be_flat_regimes" in report["failure_summary"]
    assert "operator_summary_zh" in report["failure_summary"]
    assert (tmp_path / "out" / "btc_atr_regime_failure_analysis_report.json").exists()
    markdown = (tmp_path / "out" / "btc_atr_regime_failure_analysis_summary_cn.md").read_text(encoding="utf-8")
    assert "应该空仓" in markdown


def test_market_regime_frame_uses_shifted_volatility_cap(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    _write_market_db(db)
    source_1h = load_market_1h(db)
    bars_4h = aggregate_ohlcv(source_1h, interval_hours=4)

    frame = build_market_regime_frame(bars_4h)

    assert set(frame["regime_label"].dropna().unique()) <= {
        "bull_trend",
        "bear_or_drawdown",
        "high_volatility_risk",
        "sideways_chop",
    }
    assert frame["vol_cap_85_shifted"].iloc[:60].isna().any()
    assert frame.index.equals(bars_4h.index)


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
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    total_hours = 850 * 24
    for i in range(total_hours):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        if i < 365 * 24:
            drift = 1.00045 + 0.00015 * ((i % 48) / 48.0)
        elif i < 730 * 24:
            drift = 0.99982 - 0.00012 * ((i % 36) / 36.0)
        else:
            drift = 1.00005 + (0.0006 if i % 96 < 12 else -0.00015)
        price = max(10.0, price * drift)
        rows.append(
            (
                "binance_spot",
                "BTCUSDT",
                "1h",
                int(open_time.timestamp() * 1000),
                open_time.isoformat(),
                int(close_time.timestamp() * 1000),
                close_time.isoformat(),
                price * 0.995,
                price * 1.012,
                price * 0.988,
                price,
                100.0 + (i % 24) * 2.0,
            )
        )
    conn.executemany("insert into market_klines values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _write_derivatives(path: Path) -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(850 * 24):
        event_time = start + timedelta(hours=i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "open_interest_usd": 1_000_000.0 + i * 50.0,
                "funding_rate": 0.00008 + (i % 72) * 0.000001,
                "long_short_ratio": 1.0 + (i % 96) / 400.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
