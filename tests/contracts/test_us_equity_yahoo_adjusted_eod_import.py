from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.fetch_us_equity_yahoo_adjusted_eod import import_yahoo_adjusted_eod


def test_yahoo_adjusted_eod_import_dry_run_writes_no_market_data(tmp_path: Path) -> None:
    payload = import_yahoo_adjusted_eod(
        repo_root=tmp_path,
        symbols=["TQQQ"],
        start_date="2026-06-20",
        end_date="2026-06-25",
        execute_network=False,
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_yahoo_adjusted_eod_import_report_v1"
    assert payload["status"] == "dry_run"
    assert payload["network_called"] is False
    assert payload["writes_performed"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False
    assert not (tmp_path / "data/external/us_equity_eod/yahoo_chart_adjusted/kline/TQQQ.parquet").exists()


def test_yahoo_adjusted_eod_import_writes_adjusted_parquet(tmp_path: Path) -> None:
    def fetcher(_symbol: str, _start: str, _end: str) -> dict[str, object]:
        return _yahoo_response()

    payload = import_yahoo_adjusted_eod(
        repo_root=tmp_path,
        symbols=["TQQQ"],
        start_date="2026-06-20",
        end_date="2026-06-25",
        execute_network=True,
        generated_at="2026-06-25T00:00:00Z",
        fetcher=fetcher,
    )

    assert payload["status"] == "pass"
    assert payload["network_called"] is True
    assert payload["blockers"] == []
    assert payload["guardrails"]["api_key_used_for_market_data"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False

    frame = pd.read_parquet(tmp_path / "data/external/us_equity_eod/yahoo_chart_adjusted/kline/TQQQ.parquet")
    assert list(frame["symbol"].unique()) == ["TQQQ"]
    assert {"datetime", "Open", "High", "Low", "Close", "RawClose", "AdjustmentRatio", "source"} <= set(
        frame.columns
    )
    assert frame["Close"].iloc[0] == 50.0
    assert frame["RawClose"].iloc[0] == 100.0
    assert frame["AdjustmentRatio"].iloc[0] == 0.5
    assert frame["Open"].iloc[0] == 45.0
    assert frame["source"].iloc[0] == "yahoo_chart_adjusted"


def test_yahoo_adjusted_eod_import_blocks_bad_adjusted_ohlc(tmp_path: Path) -> None:
    def fetcher(_symbol: str, _start: str, _end: str) -> dict[str, object]:
        payload = _yahoo_response()
        payload["chart"]["result"][0]["indicators"]["adjclose"][0]["adjclose"][-1] = -1.0  # type: ignore[index]
        return payload

    payload = import_yahoo_adjusted_eod(
        repo_root=tmp_path,
        symbols=["TQQQ"],
        start_date="2026-06-20",
        end_date="2026-06-25",
        execute_network=True,
        generated_at="2026-06-25T00:00:00Z",
        fetcher=fetcher,
    )

    assert payload["status"] == "pass"
    assert payload["available_symbols"] == ["TQQQ"]
    assert payload["symbol_reports"]["TQQQ"]["rows"] == 2


def _yahoo_response() -> dict[str, object]:
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [1782086400, 1782172800, 1782259200],
                    "indicators": {
                        "quote": [
                            {
                                "open": [90.0, 101.0, 102.0],
                                "high": [110.0, 103.0, 104.0],
                                "low": [80.0, 100.0, 101.0],
                                "close": [100.0, 102.0, 104.0],
                                "volume": [1_000_000, 1_100_000, 1_200_000],
                            }
                        ],
                        "adjclose": [{"adjclose": [50.0, 51.0, 52.0]}],
                    },
                }
            ],
            "error": None,
        }
    }
