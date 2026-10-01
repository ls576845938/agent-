from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping

import scripts.fetch_btc_okx_daily_history as daily_capture
from scripts.fetch_btc_okx_daily_history import capture_btc_okx_daily_history


def test_btc_okx_daily_history_dry_run_is_public_daily_only(tmp_path: Path) -> None:
    result = capture_btc_okx_daily_history(
        repo_root=tmp_path,
        execute_network=False,
        captured_at="2026-06-23T00:00:00Z",
    )

    planned = result["planned_requests"]
    assert result["status"] == "dry_run"
    assert result["network_called"] is False
    assert result["public_rest_only"] is True
    assert result["api_key_used"] is False
    assert result["private_endpoint_used"] is False
    assert result["order_endpoint_used"] is False
    assert len(planned) == 1
    assert planned[0]["endpoint"] == "/api/v5/market/history-candles"
    assert planned[0]["params"]["instId"] == "BTC-USDT"
    assert planned[0]["params"]["bar"] == "1Dutc"


def test_btc_okx_daily_history_execute_writes_only_daily_bundle(
    monkeypatch,
    tmp_path: Path,
) -> None:
    end_ms = 1782172800000
    rows = []
    for offset in range(400):
        ts = end_ms - (399 - offset) * daily_capture.DAY_MS
        price = 10000 + offset
        rows.append([str(ts), str(price), str(price + 100), str(price - 100), str(price + 10), "1", "1", "10000", "1"])

    blocks = [rows[-100:], rows[-200:-100], rows[-300:-200], rows[-400:-300]]
    pages = {
        "": blocks[0],
        blocks[0][0][0]: blocks[1],
        blocks[1][0][0]: blocks[2],
        blocks[2][0][0]: blocks[3],
    }

    class FakeCollector:
        def __init__(
            self,
            *,
            output_root: str | Path,
            dry_run: bool,
            allow_network: bool,
            **_kwargs: Any,
        ) -> None:
            self.output_root = Path(output_root)
            self.dry_run = dry_run
            self.allow_network = allow_network

        def request_by_name(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
            assert name == "candles"
            clean = dict(params or {})
            assert clean["instId"] == "BTC-USDT"
            assert clean["bar"] == "1Dutc"
            key = str(clean.get("after", ""))
            return {"payload": {"code": "0", "data": pages.get(key, [])}}

        def bundle_path(self, bundle_id: str, *, create: bool = True) -> Path:
            path = self.output_root / bundle_id
            if create:
                path.mkdir(parents=True, exist_ok=True)
            return path

    monkeypatch.setattr(daily_capture, "OkxSwapPublicCollector", FakeCollector)
    monkeypatch.setattr(daily_capture.time, "time", lambda: end_ms / 1000)

    result = capture_btc_okx_daily_history(
        repo_root=tmp_path,
        bundle_id="daily_fixture",
        execute_network=True,
        history_days=365,
        request_sleep_seconds=0,
        captured_at="2026-06-23T00:00:00Z",
    )

    bundle = tmp_path / "data/external/btc_spot/okx/bundles/daily_fixture"
    daily_path = bundle / "klines_1d.csv"
    rows_written = list(csv.DictReader(daily_path.open("r", encoding="utf-8")))

    assert result["status"] == "verified"
    assert result["network_called"] is True
    assert result["public_rest_only"] is True
    assert result["private_endpoint_used"] is False
    assert result["order_endpoint_used"] is False
    assert result["config_updated"] is False
    assert result["daily_rows"] >= 365
    assert daily_path.exists()
    assert (bundle / "daily_history_manifest.json").exists()
    assert not (bundle / "klines_5m.csv").exists()
    assert {row["symbol"] for row in rows_written} == {"BTCUSDT"}


def test_btc_okx_daily_history_retries_transient_public_request_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    end_ms = 1782172800000
    rows = []
    for offset in range(400):
        ts = end_ms - (399 - offset) * daily_capture.DAY_MS
        price = 10000 + offset
        rows.append([str(ts), str(price), str(price + 100), str(price - 100), str(price + 10), "1", "1", "10000", "1"])

    class FlakyCollector:
        calls = 0

        def __init__(
            self,
            *,
            output_root: str | Path,
            dry_run: bool,
            allow_network: bool,
            **_kwargs: Any,
        ) -> None:
            self.output_root = Path(output_root)
            self.dry_run = dry_run
            self.allow_network = allow_network

        def request_by_name(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
            assert name == "candles"
            FlakyCollector.calls += 1
            if FlakyCollector.calls == 1:
                raise TimeoutError("transient public REST timeout")
            clean = dict(params or {})
            if clean.get("after"):
                return {"payload": {"code": "0", "data": []}}
            return {"payload": {"code": "0", "data": rows}}

        def bundle_path(self, bundle_id: str, *, create: bool = True) -> Path:
            path = self.output_root / bundle_id
            if create:
                path.mkdir(parents=True, exist_ok=True)
            return path

    monkeypatch.setattr(daily_capture, "OkxSwapPublicCollector", FlakyCollector)
    monkeypatch.setattr(daily_capture.time, "time", lambda: end_ms / 1000)

    result = capture_btc_okx_daily_history(
        repo_root=tmp_path,
        bundle_id="daily_fixture",
        execute_network=True,
        history_days=365,
        request_sleep_seconds=0,
        request_retry_count=2,
        request_retry_backoff_seconds=0,
        captured_at="2026-06-23T00:00:00Z",
    )

    assert result["status"] == "verified"
    assert result["request_retry_count"] == 2
    assert result["request_attempt_count"] >= 2
    assert result["request_attempts"][0]["status"] == "error"
    assert result["request_attempts"][0]["error"]
    assert result["request_attempts"][1]["status"] == "success"
    assert result["public_rest_only"] is True
    assert result["private_endpoint_used"] is False
    assert result["order_endpoint_used"] is False
