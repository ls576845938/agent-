from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.build_us_equity_tiingo_iex_minute_pit_adjustment_replay import (
    build_tiingo_iex_minute_pit_adjustment_replay,
)


def test_pit_adjustment_replay_builds_forward_factor_without_future_backfill(tmp_path: Path) -> None:
    _write_raw_minute(tmp_path, "TQQQ")
    _write_tiingo_eod(tmp_path, "TQQQ")

    payload = build_tiingo_iex_minute_pit_adjustment_replay(
        repo_root=tmp_path,
        symbols=["TQQQ"],
        generated_at="2026-06-03T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_tiingo_iex_minute_pit_adjustment_replay_report_v1"
    assert payload["status"] == "pass"
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["adjustment_method"]["future_factor_backfill_allowed"] is False

    adjusted = pd.read_parquet(
        tmp_path / "data/external/us_equity_intraday/tiingo_iex/interval=1m_pit_adjusted/kline/TQQQ.parquet"
    )
    before = adjusted.loc[adjusted["datetime"] == pd.Timestamp("2026-06-01T13:29:00Z")]
    after = adjusted.loc[adjusted["datetime"] == pd.Timestamp("2026-06-01T13:30:00Z")]
    assert float(before["pit_factor"].iloc[0]) == 1.0
    assert float(after["pit_factor"].iloc[0]) == 2.0
    assert float(after["PitClose"].iloc[0]) == 202.0

    events = pd.read_parquet(
        tmp_path / "data/external/us_equity_corporate_actions/tiingo_pit_factor_replay/TQQQ_factor_events.parquet"
    )
    assert len(events) == 1
    assert events["event_types"].iloc[0] == "split"
    assert bool(events["future_factor_backfill_allowed"].iloc[0]) is False
    assert payload["symbol_reports"]["TQQQ"]["no_lookahead_violations"] == 0


def test_pit_adjustment_replay_blocks_missing_inputs(tmp_path: Path) -> None:
    payload = build_tiingo_iex_minute_pit_adjustment_replay(
        repo_root=tmp_path,
        symbols=["QQQ"],
        generated_at="2026-06-03T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    assert "qqq_raw_minute_missing" in payload["blockers"]


def _write_raw_minute(tmp_path: Path, symbol: str) -> None:
    path = tmp_path / "data/external/us_equity_intraday/tiingo_iex/interval=1m/kline" / f"{symbol}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                ["2026-06-01T13:29:00Z", "2026-06-01T13:30:00Z", "2026-06-02T13:30:00Z"],
                utc=True,
            ),
            "symbol": [symbol, symbol, symbol],
            "Open": [200.0, 100.0, 102.0],
            "High": [201.0, 102.0, 103.0],
            "Low": [199.0, 99.0, 101.0],
            "Close": [200.5, 101.0, 102.5],
            "Volume": [10_000, 12_000, 13_000],
        }
    )
    frame.to_parquet(path, index=False)


def _write_tiingo_eod(tmp_path: Path, symbol: str) -> None:
    path = tmp_path / "data/external/us_equity_eod/tiingo/kline" / f"{symbol}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-05-29", "2026-06-01", "2026-06-02"], utc=True),
            "symbol": [symbol, symbol, symbol],
            "RawClose": [200.0, 101.0, 102.5],
            "DivCash": [0.0, 0.0, 0.0],
            "SplitFactor": [1.0, 2.0, 1.0],
        }
    )
    frame.to_parquet(path, index=False)
