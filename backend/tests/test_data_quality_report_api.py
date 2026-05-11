from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from quant_us.core.calendar import USEquityCalendar
from quant_us.data.minute_quality_gate import _expected_regular_timestamps


TESTCLIENT_AVAILABLE = bool(importlib.util.find_spec("fastapi")) and bool(importlib.util.find_spec("httpx"))


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


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are not installed in the current environment")
def test_us_data_quality_report_api_returns_strict_evidence_summary(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from backend.app.api.app_factory import create_app

    calendar = USEquityCalendar.with_holidays()
    trading_day = datetime(2026, 5, 8, tzinfo=timezone.utc).date()
    full_1m = _expected_regular_timestamps(trading_day, 1, calendar)
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

    client = TestClient(create_app())
    response = client.post(
        "/api/us/data/quality-report",
        json={
            "data_root": str(tmp_path),
            "symbols": ["AAPL"],
            "bar_sizes": ["1m"],
            "lookback_trading_days": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "WARN"
    assert payload["evidence_summary"]["strict_gate"] is True
    assert payload["evidence_summary"]["download_performed"] is False
    assert payload["evidence_summary"]["bar_size_summary"]["1m"]["status"] == "WARN"
    assert payload["remediation_summary"]["action_count"] >= 1
    assert payload["remediation_summary"]["actions"][0]["category"] == "coverage"


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI TestClient dependencies are not installed in the current environment")
def test_us_data_quality_report_api_rejects_invalid_bar_size(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from backend.app.api.app_factory import create_app

    client = TestClient(create_app())
    response = client.post(
        "/api/us/data/quality-report",
        json={
            "data_root": str(tmp_path),
            "symbols": ["AAPL"],
            "bar_sizes": ["2m"],
        },
    )

    assert response.status_code == 400
    assert "Unsupported minute bar sizes" in response.json()["detail"]
