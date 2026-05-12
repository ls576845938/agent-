from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backend.app.services.us_quant import USQuantService
from quant_us.core.calendar import USEquityCalendar
from quant_us.data.minute_quality_gate import _expected_regular_timestamps


def _write_minute_partition(
    data_root: Path,
    *,
    root_subdir: str,
    symbol: str,
    bar_size: str,
    trading_day: str,
    timestamps: list[datetime],
) -> None:
    path = (
        data_root
        / root_subdir
        / "vendor=yfinance"
        / "asset_class=equity"
        / f"bar_size={bar_size}"
        / f"symbol={symbol}"
        / f"date={trading_day}.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "symbol": [symbol] * len(timestamps),
            "open": [100.0] * len(timestamps),
            "high": [101.0] * len(timestamps),
            "low": [99.0] * len(timestamps),
            "close": [100.5] * len(timestamps),
            "volume": [1_000] * len(timestamps),
        }
    ).to_parquet(path, index=False)


def test_us_quant_data_quality_report_supports_symbols_bar_sizes_and_lookback(tmp_path: Path) -> None:
    calendar = USEquityCalendar.with_holidays()
    trading_day = datetime(2026, 5, 8, tzinfo=timezone.utc).date()
    full_1m = _expected_regular_timestamps(trading_day, 1, calendar)
    full_5m = _expected_regular_timestamps(trading_day, 5, calendar)
    _write_minute_partition(
        tmp_path,
        root_subdir="raw",
        symbol="AAPL",
        bar_size="1m",
        trading_day=trading_day.isoformat(),
        timestamps=full_1m[1:],
    )
    _write_minute_partition(
        tmp_path,
        root_subdir="cleaned",
        symbol="AAPL",
        bar_size="1m",
        trading_day=trading_day.isoformat(),
        timestamps=full_1m,
    )
    _write_minute_partition(
        tmp_path,
        root_subdir="raw",
        symbol="AAPL",
        bar_size="5m",
        trading_day=trading_day.isoformat(),
        timestamps=full_5m,
    )
    _write_minute_partition(
        tmp_path,
        root_subdir="cleaned",
        symbol="AAPL",
        bar_size="5m",
        trading_day=trading_day.isoformat(),
        timestamps=full_5m,
    )

    payload = USQuantService().data_quality_report(
        {
            "data_root": str(tmp_path),
            "symbols": ["AAPL"],
            "bar_sizes": ["1m", "5m"],
            "lookback_trading_days": 1,
            "as_of": "2026-05-08T21:00:00Z",
        }
    )

    assert payload["status"] == "WARN"
    assert payload["lookback_trading_days"] == 1
    assert payload["bar_sizes"] == ["1m", "5m"]
    assert payload["evaluated_symbols"] == ["AAPL"]
    dataset_statuses = payload["dataset_statuses"]
    assert dataset_statuses["raw"]["status"] == "WARN"
    assert dataset_statuses["cleaned"]["status"] == "PASS"
    assert payload["evidence_summary"]["strict_gate"] is True
    assert payload["evidence_summary"]["download_performed"] is False
    assert payload["evidence_summary"]["bar_size_summary"]["1m"]["status"] == "WARN"
    assert payload["evidence_summary"]["bar_size_summary"]["5m"]["status"] == "PASS"
    assert payload["remediation_summary"]["action_count"] >= 1
    assert payload["remediation_summary"]["actions"][0]["category"] == "coverage"


def test_us_quant_data_quality_report_rejects_invalid_bar_size_without_fallback() -> None:
    try:
        USQuantService().data_quality_report({"bar_sizes": ["2m"]})
    except ValueError as exc:
        assert "Unsupported minute bar sizes" in str(exc)
    else:
        raise AssertionError("expected invalid minute bar size to raise ValueError")
