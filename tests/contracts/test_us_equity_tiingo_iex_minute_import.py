from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.fetch_us_equity_tiingo_iex_minute_bars import import_tiingo_iex_minute_bars


def test_tiingo_iex_minute_import_dry_run_writes_no_market_data(tmp_path: Path) -> None:
    payload = import_tiingo_iex_minute_bars(
        repo_root=tmp_path,
        symbols=["QQQ", "TQQQ"],
        start_date="2026-06-01",
        end_date="2026-06-30",
        execute_network=False,
        generated_at="2026-07-01T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_tiingo_iex_minute_import_report_v1"
    assert payload["status"] == "dry_run"
    assert payload["network_called"] is False
    assert payload["writes_performed"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert not (tmp_path / "data/external/us_equity_intraday/tiingo_iex/interval=1m/kline/TQQQ.parquet").exists()


def test_tiingo_iex_minute_import_writes_raw_parquet_and_masks_token(tmp_path: Path) -> None:
    _write_eod_adjustment_ratio(tmp_path, "TQQQ", [1.0, 1.0])

    def fetcher(symbol: str, start: str, end: str) -> list[dict[str, object]]:
        assert symbol == "TQQQ"
        return _iex_rows("TQQQ", start)

    payload = import_tiingo_iex_minute_bars(
        repo_root=tmp_path,
        symbols=["TQQQ"],
        start_date="2026-06-01",
        end_date="2026-06-03",
        execute_network=True,
        generated_at="2026-06-04T00:00:00Z",
        token="secret-token-that-must-not-leak",
        fetcher=fetcher,
    )

    assert payload["status"] == "pass"
    assert payload["research_ready_status"] == "pass"
    assert payload["network_called"] is True
    assert payload["token_printed"] is False
    assert payload["guardrails"]["token_written_to_artifacts"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert "secret-token-that-must-not-leak" not in json.dumps(payload)

    frame = pd.read_parquet(
        tmp_path / "data/external/us_equity_intraday/tiingo_iex/interval=1m/kline/TQQQ.parquet"
    )
    assert len(frame) == 2
    assert set(frame["source"]) == {"tiingo_iex_intraday_1m"}
    assert set(frame["adjustment_policy"]) == {"raw_intraday_unadjusted_iex_only"}
    assert payload["symbol_reports"]["TQQQ"]["adjustment_ratio_check"]["status"] == "ratio_constant_in_window"


def test_tiingo_iex_minute_import_blocks_research_when_pit_replay_required(tmp_path: Path) -> None:
    _write_eod_adjustment_ratio(tmp_path, "TQQQ", [1.0, 0.5])

    def fetcher(symbol: str, start: str, end: str) -> list[dict[str, object]]:
        return _iex_rows_two_days(symbol)

    payload = import_tiingo_iex_minute_bars(
        repo_root=tmp_path,
        symbols=["TQQQ"],
        start_date="2026-06-01",
        end_date="2026-06-03",
        execute_network=True,
        generated_at="2026-06-04T00:00:00Z",
        token="secret-token-that-must-not-leak",
        fetcher=fetcher,
    )

    assert payload["status"] == "pass"
    assert payload["research_ready_status"] == "blocked"
    assert payload["raw_data_blockers"] == []
    assert "tqqq_minute_pit_adjustment_replay_required" in payload["research_blockers"]
    assert payload["symbol_reports"]["TQQQ"]["adjustment_ratio_check"]["status"] == (
        "ratio_not_constant_requires_pit_factor_replay"
    )
    assert payload["adjustment_controls"]["back_adjusted_output_written"] is False
    assert payload["adjustment_controls"]["back_adjusted_for_signal_use_allowed"] is False


def test_tiingo_iex_minute_import_preserves_existing_kline_when_backfill_is_partial(tmp_path: Path) -> None:
    _write_eod_adjustment_ratio(tmp_path, "TQQQ", [1.0, 1.0])
    existing_path = tmp_path / "data/external/us_equity_intraday/tiingo_iex/interval=1m/kline/TQQQ.parquet"
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-06-30T13:30:00Z"], utc=True),
            "symbol": ["TQQQ"],
            "Open": [111.0],
            "High": [112.0],
            "Low": [110.0],
            "Close": [111.5],
            "Volume": [10_000],
        }
    )
    existing.to_parquet(existing_path, index=False)

    def fetcher(symbol: str, start: str, end: str) -> list[dict[str, object]]:
        if start == "2026-06-01":
            return _iex_rows(symbol, start)
        raise TimeoutError("simulated chunk timeout")

    payload = import_tiingo_iex_minute_bars(
        repo_root=tmp_path,
        symbols=["TQQQ"],
        start_date="2026-06-01",
        end_date="2026-07-31",
        chunk_months=1,
        execute_network=True,
        skip_existing=False,
        min_coverage_ratio=0.90,
        max_new_chunks_per_run=1,
        generated_at="2026-08-01T00:00:00Z",
        token="secret-token-that-must-not-leak",
        fetcher=fetcher,
    )

    retained = pd.read_parquet(existing_path)
    assert payload["status"] == "partial"
    assert payload["symbol_reports"]["TQQQ"]["write_mode"] == "partial_chunks_not_promoted_existing_kline_retained"
    assert payload["symbol_reports"]["TQQQ"]["main_kline_write_suppressed"] is True
    assert payload["attempted_new_chunk_count"] == 1
    assert retained["Close"].tolist() == [111.5]
    assert len(payload["symbol_reports"]["TQQQ"]["chunk_reports"]) == 2
    assert payload["symbol_reports"]["TQQQ"]["chunk_reports"][1]["status"] == "deferred_run_limit"


def _iex_rows(symbol: str, start: str) -> list[dict[str, object]]:
    base = 100.0 if symbol == "TQQQ" else 500.0
    day = pd.Timestamp(start)
    return [
        {
            "date": (day + pd.Timedelta(hours=13, minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "open": base,
            "high": base + 0.5,
            "low": base - 0.5,
            "close": base + 0.1,
            "volume": 10_000.0,
        },
        {
            "date": (day + pd.Timedelta(hours=13, minutes=31)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "open": base + 0.1,
            "high": base + 0.6,
            "low": base - 0.4,
            "close": base + 0.2,
            "volume": 11_000.0,
        },
    ]


def _iex_rows_two_days(symbol: str) -> list[dict[str, object]]:
    base = 100.0 if symbol == "TQQQ" else 500.0
    return [
        {
            "date": "2026-06-01T13:30:00.000Z",
            "open": base,
            "high": base + 0.5,
            "low": base - 0.5,
            "close": base + 0.1,
            "volume": 10_000.0,
        },
        {
            "date": "2026-06-02T13:30:00.000Z",
            "open": base + 1.0,
            "high": base + 1.5,
            "low": base + 0.5,
            "close": base + 1.1,
            "volume": 11_000.0,
        },
    ]


def _write_eod_adjustment_ratio(tmp_path: Path, symbol: str, ratios: list[float]) -> None:
    path = tmp_path / "data/external/us_equity_eod/tiingo/kline" / f"{symbol}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-06-01", "2026-06-02"], utc=True),
            "symbol": [symbol, symbol],
            "Open": [100.0, 101.0],
            "High": [101.0, 102.0],
            "Low": [99.0, 100.0],
            "Close": [100.5, 101.5],
            "Volume": [1_000_000, 1_100_000],
            "AdjClose": [100.5 * ratios[0], 101.5 * ratios[1]],
        }
    )
    frame.to_parquet(path, index=False)
