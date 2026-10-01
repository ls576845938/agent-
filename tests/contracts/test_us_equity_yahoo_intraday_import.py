from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.fetch_us_equity_yahoo_intraday_bars import import_yahoo_intraday_bars


def test_yahoo_intraday_import_dry_run_writes_no_market_data(tmp_path: Path) -> None:
    payload = import_yahoo_intraday_bars(
        repo_root=tmp_path,
        symbols=["QQQ", "TQQQ"],
        start_date="2026-06-20",
        end_date="2026-06-25",
        execute_network=False,
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_yahoo_intraday_import_report_v1"
    assert payload["status"] == "dry_run"
    assert payload["network_called"] is False
    assert payload["writes_performed"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False
    assert not (tmp_path / "data/external/us_equity_intraday/yahoo_chart/interval=1h/kline/TQQQ.parquet").exists()


def test_yahoo_intraday_import_writes_1h_and_derived_4h_parquet(tmp_path: Path) -> None:
    def fetcher(symbol: str, _start: str, _end: str, interval: str) -> dict[str, object]:
        assert interval == "1h"
        return _yahoo_intraday_response(symbol)

    payload = import_yahoo_intraday_bars(
        repo_root=tmp_path,
        symbols=["TQQQ", "QQQ"],
        start_date="2026-06-22",
        end_date="2026-06-22",
        execute_network=True,
        generated_at="2026-06-22T22:00:00Z",
        fetcher=fetcher,
    )

    assert payload["status"] == "pass"
    assert payload["network_called"] is True
    assert payload["blockers"] == []
    assert payload["available_symbols"] == ["TQQQ", "QQQ"]
    assert payload["guardrails"]["private_endpoint_used"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False

    one_hour = pd.read_parquet(
        tmp_path / "data/external/us_equity_intraday/yahoo_chart/interval=1h/kline/TQQQ.parquet"
    )
    four_hour = pd.read_parquet(
        tmp_path / "data/external/us_equity_intraday/yahoo_chart/interval=4h/kline/TQQQ.parquet"
    )

    assert len(one_hour) == 7
    assert len(four_hour) == 2
    assert set(one_hour["interval"]) == {"1h"}
    assert set(four_hour["interval"]) == {"4h"}
    assert one_hour["source"].iloc[0] == "yahoo_chart_intraday_1h"
    assert four_hour["source"].iloc[0] == "yahoo_chart_intraday_1h_derived_4h"
    assert four_hour["Open"].iloc[0] == one_hour["Open"].iloc[0]
    assert four_hour["Close"].iloc[0] == one_hour["Close"].iloc[3]
    assert four_hour["High"].iloc[0] == one_hour["High"].iloc[:4].max()
    assert four_hour["Low"].iloc[0] == one_hour["Low"].iloc[:4].min()
    assert four_hour["Volume"].iloc[0] == one_hour["Volume"].iloc[:4].sum()
    assert pd.to_datetime(four_hour["available_time"], utc=True).iloc[0] > pd.to_datetime(
        four_hour["datetime"], utc=True
    ).iloc[0]


def test_yahoo_intraday_import_blocks_stale_or_missing_required_symbol(tmp_path: Path) -> None:
    def fetcher(symbol: str, _start: str, _end: str, _interval: str) -> dict[str, object]:
        if symbol == "QQQ":
            return {"chart": {"result": [], "error": None}}
        return _yahoo_intraday_response(symbol)

    payload = import_yahoo_intraday_bars(
        repo_root=tmp_path,
        symbols=["TQQQ", "QQQ"],
        start_date="2026-06-22",
        end_date="2026-06-22",
        execute_network=True,
        generated_at="2026-07-10T00:00:00Z",
        fetcher=fetcher,
    )

    assert payload["status"] == "partial"
    assert "yahoo_tqqq_intraday_stale" in payload["blockers"]
    assert "yahoo_qqq_intraday_empty_response" in payload["blockers"]
    assert "yahoo_intraday_required_symbols_missing" in payload["blockers"]


def test_yahoo_intraday_import_drops_incomplete_current_bar(tmp_path: Path) -> None:
    def fetcher(symbol: str, _start: str, _end: str, _interval: str) -> dict[str, object]:
        return _yahoo_intraday_response(symbol)

    payload = import_yahoo_intraday_bars(
        repo_root=tmp_path,
        symbols=["TQQQ"],
        start_date="2026-06-22",
        end_date="2026-06-22",
        execute_network=True,
        generated_at="2026-06-22T18:45:00Z",
        fetcher=fetcher,
    )

    assert payload["status"] == "pass"
    assert payload["symbol_reports"]["TQQQ"]["dropped_incomplete_1h_bars"] == 2
    one_hour = pd.read_parquet(
        tmp_path / "data/external/us_equity_intraday/yahoo_chart/interval=1h/kline/TQQQ.parquet"
    )
    assert len(one_hour) == 5
    assert pd.to_datetime(one_hour["bar_end_utc"], utc=True).max() <= pd.Timestamp("2026-06-22T18:45:00Z")


def _yahoo_intraday_response(symbol: str) -> dict[str, object]:
    timestamps = [
        int(pd.Timestamp(f"2026-06-22 {hour}:30:00Z").timestamp())
        for hour in (13, 14, 15, 16, 17, 18, 19)
    ]
    base = 100.0 if symbol == "TQQQ" else 500.0
    return {
        "chart": {
            "result": [
                {
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": [base + idx for idx in range(7)],
                                "high": [base + idx + 1.0 for idx in range(7)],
                                "low": [base + idx - 1.0 for idx in range(7)],
                                "close": [base + idx + 0.5 for idx in range(7)],
                                "volume": [1_000_000 + idx for idx in range(7)],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }
