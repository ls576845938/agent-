from __future__ import annotations

import csv
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.build_btc_intraday_trend_v1_report import (
    COST_BPS_GRID,
    FAMILIES,
    INTERVALS,
    build_btc_intraday_trend_v1_report,
)


def test_intraday_trend_v1_blocks_when_primary_history_is_insufficient(tmp_path: Path) -> None:
    db_path = _write_intraday_sqlite(tmp_path, rows_by_interval={"4h": 20, "1h": 20, "15m": 20, "5m": 20})

    payload = build_btc_intraday_trend_v1_report(
        repo_root=tmp_path,
        db_path=db_path,
        output=tmp_path / "report.json",
        grid_output=tmp_path / "grid.csv",
        ledger_output=tmp_path / "ledger.csv",
        markdown_output=tmp_path / "report.md",
        generated_at="2026-06-24T00:00:00Z",
    )

    assert payload["status"] == "blocked_insufficient_primary_history"
    assert payload["overall_ranking"] == []
    assert payload["grid_output"]["row_count"] == 0
    assert payload["position_ledger"]["complete"] is False
    assert "btc_intraday_trend_v1_4h_rows_below_minimum" in payload["blockers"]
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["old_5m_hft_candidate_reused"] is False


def test_intraday_trend_v1_runs_all_intervals_families_and_cost_pressure(tmp_path: Path) -> None:
    db_path = _write_intraday_sqlite(
        tmp_path,
        rows_by_interval={"4h": 700, "1h": 700, "15m": 700, "5m": 700},
    )

    payload = build_btc_intraday_trend_v1_report(
        repo_root=tmp_path,
        db_path=db_path,
        output=tmp_path / "report.json",
        grid_output=tmp_path / "grid.csv",
        ledger_output=tmp_path / "ledger.csv",
        markdown_output=tmp_path / "report.md",
        min_bars_by_interval={"4h": 100, "1h": 100, "15m": 100, "5m": 100},
        generated_at="2026-06-24T00:00:00Z",
    )

    assert payload["status"] == "research_only_intraday_trend_v1_complete"
    assert payload["tested_intervals"] == INTERVALS
    assert payload["primary_intervals"] == ["4h", "1h"]
    assert payload["exploratory_intervals"] == ["15m", "5m"]
    assert payload["families"] == FAMILIES
    assert {row["interval"] for row in payload["selected_candidates"]} == set(INTERVALS)
    assert payload["guardrails"]["branch_separate_from_daily_trend_mainline"] is True
    assert payload["guardrails"]["true_hft_claimed"] is False
    assert payload["guardrails"]["paper_runner_allowed"] is False
    assert payload["guardrails"]["private_endpoint_used"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False

    family_pairs = {(row["interval"], row["family_id"]) for row in payload["family_summaries"]}
    for interval in INTERVALS:
        for family in FAMILIES:
            if interval == "4h" and family == "it05_dual_timeframe_trend_filter":
                continue
            assert (interval, family) in family_pairs
    assert ("1h", "it05_dual_timeframe_trend_filter") in family_pairs
    assert ("15m", "it05_dual_timeframe_trend_filter") in family_pairs
    assert ("5m", "it05_dual_timeframe_trend_filter") in family_pairs

    stress_pairs = {(row["interval"], float(row["cost_bps"])) for row in payload["cost_stress"]}
    assert stress_pairs == {(interval, cost_bps) for interval in INTERVALS for cost_bps in COST_BPS_GRID}
    shock_types = {float(row["cost_bps"]): row["shock_type"] for row in payload["cost_stress"]}
    assert shock_types[5.0] == "base_cost"
    assert shock_types[10.0] == "base_cost"
    assert shock_types[25.0] == "base_cost"
    assert shock_types[50.0] == "higher_slippage_shock"
    assert shock_types[100.0] == "higher_slippage_shock"

    grid_rows = list(csv.DictReader((tmp_path / "grid.csv").open(encoding="utf-8")))
    assert len(grid_rows) == payload["grid_output"]["row_count"]
    assert {row["interval"] for row in grid_rows} == set(INTERVALS)
    assert {row["family_id"] for row in grid_rows} == set(FAMILIES)


def test_intraday_trend_v1_ledger_is_t_plus_one_and_excludes_frozen_hft_candidate(tmp_path: Path) -> None:
    db_path = _write_intraday_sqlite(
        tmp_path,
        rows_by_interval={"4h": 700, "1h": 700, "15m": 700, "5m": 700},
    )

    payload = build_btc_intraday_trend_v1_report(
        repo_root=tmp_path,
        db_path=db_path,
        output=tmp_path / "report.json",
        grid_output=tmp_path / "grid.csv",
        ledger_output=tmp_path / "ledger.csv",
        markdown_output=tmp_path / "report.md",
        min_bars_by_interval={"4h": 100, "1h": 100, "15m": 100, "5m": 100},
        generated_at="2026-06-24T00:00:00Z",
    )

    ledger_rows = list(csv.DictReader((tmp_path / "ledger.csv").open(encoding="utf-8")))
    assert len(ledger_rows) == payload["position_ledger"]["row_count"]
    assert payload["position_ledger"]["complete"] is True
    assert ledger_rows

    changed_rows = [row for row in ledger_rows if float(row["turnover"]) > 0.0 and row["signal_timestamp"]]
    assert changed_rows
    for row in changed_rows[:100]:
        assert row["reason"] == "exposure_changed_from_prior_effective_signal"
        assert _parse_ts(row["signal_timestamp"]) < _parse_ts(row["effective_timestamp"])

    serialized = json.dumps(payload["selected_candidates"], ensure_ascii=False)
    serialized += (tmp_path / "grid.csv").read_text(encoding="utf-8")
    serialized += (tmp_path / "ledger.csv").read_text(encoding="utf-8")
    assert "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1" not in serialized


def _write_intraday_sqlite(tmp_path: Path, *, rows_by_interval: dict[str, int]) -> Path:
    db_path = tmp_path / "market_data.sqlite"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            create table market_klines (
                exchange text,
                symbol text,
                interval text,
                open_time_ms integer,
                open_time text,
                close_time_ms integer,
                close_time text,
                open real,
                high real,
                low real,
                close real,
                volume real,
                quote_volume real,
                trade_count integer,
                taker_buy_base_volume real,
                taker_buy_quote_volume real,
                source text,
                ingested_at text,
                updated_at text
            )
            """
        )
        for interval, rows in rows_by_interval.items():
            _insert_interval(con, interval=interval, rows=rows)
    return db_path


def _insert_interval(con: sqlite3.Connection, *, interval: str, rows: int) -> None:
    step_minutes = {"4h": 240, "1h": 60, "15m": 15, "5m": 5}[interval]
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    batch = []
    for i in range(rows):
        ts = start + timedelta(minutes=step_minutes * i)
        close = 40_000.0 + i * 8.0 + 1_000.0 * math.sin(i / 35.0) - 600.0 * math.sin(i / 9.0)
        open_ = close * (1.0 + 0.0004 * math.sin(i / 7.0))
        high = max(open_, close) * 1.002
        low = min(open_, close) * 0.998
        volume = 100.0 + 20.0 * math.sin(i / 11.0) + (i % 17)
        close_ts = ts + timedelta(minutes=step_minutes)
        batch.append(
            (
                "binance_spot",
                "BTCUSDT",
                interval,
                int(ts.timestamp() * 1000),
                ts.isoformat().replace("+00:00", "Z"),
                int(close_ts.timestamp() * 1000),
                close_ts.isoformat().replace("+00:00", "Z"),
                open_,
                high,
                low,
                close,
                volume,
                volume * close,
                100 + (i % 50),
                volume * 0.48,
                volume * close * 0.48,
                "fixture",
                "2026-06-24T00:00:00Z",
                "2026-06-24T00:00:00Z",
            )
        )
    con.executemany(
        """
        insert into market_klines (
            exchange, symbol, interval, open_time_ms, open_time, close_time_ms, close_time,
            open, high, low, close, volume, quote_volume, trade_count,
            taker_buy_base_volume, taker_buy_quote_volume, source, ingested_at, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        batch,
    )


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
