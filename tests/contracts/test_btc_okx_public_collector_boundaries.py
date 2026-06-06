from __future__ import annotations

import urllib.request
from typing import Any, Mapping

import pytest

from quant_crypto.data.okx_swap_public import (
    OkxSwapPublicCollector,
    OkxSwapPublicEndpointError,
    PUBLIC_ENDPOINTS,
    build_public_url,
    validate_public_endpoint,
)
from scripts.fetch_btc_okx_swap_public_data import _fetch_paginated_okx_rows, _row_time_ms


def test_okx_public_collector_default_dry_run_does_not_call_network(monkeypatch) -> None:
    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("network should not be called in dry-run")

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)
    result = OkxSwapPublicCollector().request_by_name("candles", {"instId": "BTC-USDT-SWAP", "bar": "1H"})

    assert result["dry_run"] is True
    assert result["network_called"] is False
    assert "/api/v5/market/history-candles" in result["url"]


def test_okx_public_collector_rejects_private_or_order_endpoints() -> None:
    with pytest.raises(OkxSwapPublicEndpointError):
        validate_public_endpoint("/api/v5/trade/order")
    with pytest.raises(OkxSwapPublicEndpointError):
        validate_public_endpoint("/api/v5/account/balance")


def test_okx_public_url_builder_only_allows_public_params() -> None:
    url = build_public_url(PUBLIC_ENDPOINTS["funding_rate_history"], {"instId": "BTC-USDT-SWAP", "limit": "100"})

    assert url.startswith("https://www.okx.com/api/v5/public/funding-rate-history")
    assert "apikey" not in url.lower()
    with pytest.raises(OkxSwapPublicEndpointError):
        build_public_url(PUBLIC_ENDPOINTS["candles"], {"instId": "BTC-USDT-SWAP", "bar": "1H", "apiKey": "secret"})


def test_okx_paginated_rows_walk_backward_with_after_and_dedupe() -> None:
    collector = _FakeOkxCollector(
        {
            "200": [["100", "1"], ["0", "1"], ["100", "duplicate"]],
        }
    )

    rows = _fetch_paginated_okx_rows(
        collector,
        "candles",
        {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "100"},
        timestamp_getter=_row_time_ms,
        target_start_ms=50,
        initial_rows=[["300", "1"], ["200", "1"]],
        sleep_seconds=0,
    )

    assert [row[0] for row in rows] == ["0", "100", "200", "300"]
    assert collector.calls == [
        {
            "name": "candles",
            "params": {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "100", "after": "200"},
        }
    ]


class _FakeOkxCollector:
    def __init__(self, pages: Mapping[str, list[list[str]]]) -> None:
        self.pages = dict(pages)
        self.calls: list[dict[str, Any]] = []

    def request_by_name(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        clean = dict(params or {})
        self.calls.append({"name": name, "params": clean})
        return {"payload": {"code": "0", "data": self.pages.get(str(clean.get("after", "")), [])}}
