from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import quant_crypto.research.short_interval_data_refresh as refresh
from quant_crypto.research.short_interval_data_refresh import build_btc_short_interval_data_refresh, load_market_klines_frame


def test_short_interval_refresh_resamples_complete_1m_to_5m_15m_without_network(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    _write_schema(db)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _insert_1h_rows(db, start=start, hours=48)
    _insert_1m_rows(db, start=start, minutes=48 * 60)

    report = build_btc_short_interval_data_refresh(
        market_db_path=db,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        execute_network=False,
    )

    assert report["status"] == "complete_research_only"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["network"]["network_called"] is False
    coverage = {row["interval"]: row for row in report["coverage"]}
    assert coverage["1m"]["last_open_time_ms"] == report["target"]["target_last_open_time_ms_by_interval"]["1m"]
    assert coverage["5m"]["last_open_time_ms"] == report["target"]["target_last_open_time_ms_by_interval"]["5m"]
    assert coverage["15m"]["last_open_time_ms"] == report["target"]["target_last_open_time_ms_by_interval"]["15m"]
    assert coverage["5m"]["gap_count"] == 0
    assert coverage["15m"]["gap_count"] == 0
    frame_5m = load_market_klines_frame(db, interval="5m")
    first_5m = frame_5m.iloc[0]
    one_minute = load_market_klines_frame(db, interval="1m").iloc[:5]
    assert first_5m["open"] == one_minute["open"].iloc[0]
    assert first_5m["high"] == one_minute["high"].max()
    assert first_5m["low"] == one_minute["low"].min()
    assert first_5m["close"] == one_minute["close"].iloc[-1]
    assert first_5m["volume"] == one_minute["volume"].sum()
    assert (tmp_path / "out" / "btc_short_interval_data_refresh_report.json").exists()
    assert "BTC 短周期数据刷新报告" in (tmp_path / "out" / "btc_short_interval_data_refresh_summary_cn.md").read_text(encoding="utf-8")


def test_short_interval_refresh_blocks_when_1m_is_stale_and_network_disabled(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    _write_schema(db)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _insert_1h_rows(db, start=start, hours=48)
    _insert_1m_rows(db, start=start, minutes=24 * 60)

    report = build_btc_short_interval_data_refresh(
        market_db_path=db,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        execute_network=False,
    )

    assert report["status"] == "blocked_data_refresh_required"
    assert "btc_1m_refresh_required_execute_network_false" in report["blockers"]
    assert "btc_1m_coverage_stale_vs_latest_1h" in report["blockers"]
    assert report["gate"]["paper_candidate_created"] is False


def test_market_1h_refresh_blocks_when_network_disabled_and_data_stale(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    _write_schema(db)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _insert_1h_rows(db, start=start, hours=24)

    report = refresh.build_btc_market_1h_data_refresh(
        market_db_path=db,
        output_dir=tmp_path / "out_1h",
        generated_at_utc=datetime(2026, 1, 3, 5, 30, tzinfo=timezone.utc),
        execute_network=False,
    )

    assert report["status"] == "blocked_data_refresh_required"
    assert "btc_1h_refresh_required_execute_network_false" in report["blockers"]
    assert "btc_1h_coverage_stale_vs_latest_completed_hour" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_market_1h_refresh_fetches_only_through_latest_completed_hour(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    _write_schema(db)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _insert_1h_rows(db, start=start, hours=48)
    calls = []

    def fake_fetch(**kwargs):
        calls.append(kwargs)
        assert kwargs["interval"] == "1h"
        assert kwargs["start_time_ms"] == int(datetime(2026, 1, 3, 0, tzinfo=timezone.utc).timestamp() * 1000)
        assert kwargs["end_time_ms"] == int(datetime(2026, 1, 3, 4, tzinfo=timezone.utc).timestamp() * 1000)
        rows = []
        for i in range(5):
            open_time = datetime(2026, 1, 3, i, tzinfo=timezone.utc)
            close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
            rows.append(_kline_row("1h", open_time, close_time, 110.0 + i, volume=200.0 + i))
        return rows

    monkeypatch.setattr(refresh, "fetch_binance_spot_klines", fake_fetch)

    report = refresh.build_btc_market_1h_data_refresh(
        market_db_path=db,
        output_dir=tmp_path / "out_1h",
        generated_at_utc=datetime(2026, 1, 3, 5, 30, tzinfo=timezone.utc),
        execute_network=True,
    )

    assert len(calls) == 1
    assert report["status"] == "complete_research_only"
    assert report["network"]["rows_written"] == 5
    assert report["target"]["target_last_1h_close_time"] == "2026-01-03T04:59:59.999000+00:00"
    coverage = report["coverage"][0]
    assert coverage["last_close_time"] == "2026-01-03T04:59:59.999000+00:00"
    assert coverage["gap_count"] == 0
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert (tmp_path / "out_1h" / "btc_market_1h_data_refresh_report.json").exists()
    assert (tmp_path / "out_1h" / "btc_market_1h_data_refresh_summary_cn.md").exists()


def _write_schema(path: Path) -> None:
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
    conn.commit()
    conn.close()


def _insert_1h_rows(path: Path, *, start: datetime, hours: int) -> None:
    rows = []
    price = 100.0
    for i in range(hours):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        price *= 1.0005
        rows.append(_row("1h", open_time, close_time, price, volume=100.0 + i))
    _insert(path, rows)


def _insert_1m_rows(path: Path, *, start: datetime, minutes: int) -> None:
    rows = []
    price = 100.0
    for i in range(minutes):
        open_time = start + timedelta(minutes=i)
        close_time = open_time + timedelta(minutes=1) - timedelta(milliseconds=1)
        price *= 1.00001
        rows.append(_row("1m", open_time, close_time, price, volume=1.0 + (i % 7)))
    _insert(path, rows)


def _row(interval: str, open_time: datetime, close_time: datetime, price: float, *, volume: float) -> tuple:
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


def _kline_row(interval: str, open_time: datetime, close_time: datetime, price: float, *, volume: float) -> refresh.KlineRow:
    return refresh.KlineRow(
        exchange="binance_spot",
        symbol="BTCUSDT",
        interval=interval,
        open_time_ms=int(open_time.timestamp() * 1000),
        open_time=open_time.isoformat(),
        close_time_ms=int(close_time.timestamp() * 1000),
        close_time=close_time.isoformat(),
        open=price * 0.999,
        high=price * 1.001,
        low=price * 0.998,
        close=price,
        volume=volume,
    )


def _insert(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    conn.executemany("insert into market_klines values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
