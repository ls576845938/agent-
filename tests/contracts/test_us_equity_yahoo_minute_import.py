from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.fetch_us_equity_yahoo_minute_bars import import_yahoo_minute_bars


def test_yahoo_minute_import_dry_run_writes_no_market_data(tmp_path: Path) -> None:
    payload = import_yahoo_minute_bars(
        repo_root=tmp_path,
        symbols=["QQQ", "TQQQ"],
        start_date="2026-06-22",
        end_date="2026-06-22",
        execute_network=False,
        generated_at="2026-06-22T20:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_yahoo_minute_import_report_v1"
    assert payload["status"] == "dry_run"
    assert payload["network_called"] is False
    assert payload["writes_performed"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False
    assert not (tmp_path / "data/external/us_equity_intraday/yahoo_chart/interval=1m/kline/TQQQ.parquet").exists()


def test_yahoo_minute_import_writes_raw_1m_without_adjusted_variants(tmp_path: Path) -> None:
    _write_eod_adjustment_ratio(tmp_path, "TQQQ", [0.5, 0.5])

    def fetcher(symbol: str, _start: str, _end: str) -> dict[str, object]:
        return _minute_response(symbol)

    payload = import_yahoo_minute_bars(
        repo_root=tmp_path,
        symbols=["TQQQ"],
        start_date="2026-06-22",
        end_date="2026-06-22",
        execute_network=True,
        generated_at="2026-06-22T13:36:30Z",
        fetcher=fetcher,
    )

    assert payload["status"] == "pass"
    assert payload["blockers"] == []
    assert payload["adjustment_controls"]["raw_intraday_retained"] is True
    assert payload["adjustment_controls"]["front_adjusted_output_written"] is False
    assert payload["adjustment_controls"]["back_adjusted_output_written"] is False
    assert payload["symbol_reports"]["TQQQ"]["dropped_incomplete_1m_bars"] == 1
    assert payload["symbol_reports"]["TQQQ"]["adjustment_ratio_check"]["status"] == "ratio_constant_in_window"

    frame = pd.read_parquet(
        tmp_path / "data/external/us_equity_intraday/yahoo_chart/interval=1m/kline/TQQQ.parquet"
    )
    assert len(frame) == 6
    assert set(frame["interval"]) == {"1m"}
    assert set(frame["adjustment_policy"]) == {"raw_intraday_unadjusted"}
    assert "AdjClose" not in frame.columns
    assert pd.to_datetime(frame["available_time"], utc=True).max() <= pd.Timestamp("2026-06-22T13:36:30Z")


def test_yahoo_minute_import_blocks_when_adjustment_ratio_changes_without_pit_replay(tmp_path: Path) -> None:
    _write_eod_adjustment_ratio(tmp_path, "TQQQ", [0.5, 0.25])

    def fetcher(symbol: str, _start: str, _end: str) -> dict[str, object]:
        return _minute_response_two_days(symbol)

    payload = import_yahoo_minute_bars(
        repo_root=tmp_path,
        symbols=["TQQQ"],
        start_date="2026-06-22",
        end_date="2026-06-23",
        execute_network=True,
        generated_at="2026-06-23T20:00:00Z",
        fetcher=fetcher,
    )

    assert payload["status"] == "partial"
    assert "tqqq_minute_adjustment_ratio_not_constant" in payload["blockers"]
    assert payload["symbol_reports"]["TQQQ"]["adjustment_ratio_check"]["status"] == (
        "ratio_not_constant_requires_pit_factor_replay"
    )


def _minute_response(symbol: str) -> dict[str, object]:
    base = 100.0 if symbol == "TQQQ" else 500.0
    timestamps = [int(pd.Timestamp(f"2026-06-22 13:{minute:02d}:00Z").timestamp()) for minute in range(30, 37)]
    return {
        "chart": {
            "result": [
                {
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": [base + idx * 0.1 for idx in range(7)],
                                "high": [base + idx * 0.1 + 0.05 for idx in range(7)],
                                "low": [base + idx * 0.1 - 0.05 for idx in range(7)],
                                "close": [base + idx * 0.1 + 0.02 for idx in range(7)],
                                "volume": [10_000 + idx for idx in range(7)],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def _minute_response_two_days(symbol: str) -> dict[str, object]:
    base = 100.0 if symbol == "TQQQ" else 500.0
    timestamps = [
        int(pd.Timestamp("2026-06-22 13:30:00Z").timestamp()),
        int(pd.Timestamp("2026-06-23 13:30:00Z").timestamp()),
    ]
    return {
        "chart": {
            "result": [
                {
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": [base, base + 1.0],
                                "high": [base + 0.5, base + 1.5],
                                "low": [base - 0.5, base + 0.5],
                                "close": [base + 0.1, base + 1.1],
                                "volume": [10_000, 11_000],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def _write_eod_adjustment_ratio(tmp_path: Path, symbol: str, ratios: list[float]) -> None:
    path = tmp_path / "data/external/us_equity_eod/yahoo_chart_adjusted/kline" / f"{symbol}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-06-22", "2026-06-23"], utc=True),
            "symbol": [symbol, symbol],
            "Open": [100.0, 101.0],
            "High": [101.0, 102.0],
            "Low": [99.0, 100.0],
            "Close": [100.5, 101.5],
            "Volume": [1_000_000, 1_100_000],
            "AdjustmentRatio": ratios,
        }
    )
    frame.to_parquet(path, index=False)
