from __future__ import annotations

import urllib.request

import pytest

from quant_crypto.data.binance_usdm_public import (
    BinanceUsdmPublicCollector,
    BinanceUsdmPublicEndpointError,
    PUBLIC_ENDPOINTS,
    build_public_url,
    classify_open_interest_coverage,
    validate_public_endpoint,
)


def test_public_collector_default_dry_run_does_not_call_network(monkeypatch) -> None:
    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("network should not be called in dry-run")

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)
    result = BinanceUsdmPublicCollector().request_by_name("klines", {"symbol": "BTCUSDT", "interval": "1h"})

    assert result["dry_run"] is True
    assert result["network_called"] is False
    assert "/fapi/v1/klines" in result["url"]


def test_public_collector_rejects_private_or_order_endpoints() -> None:
    with pytest.raises(BinanceUsdmPublicEndpointError):
        validate_public_endpoint("/fapi/v1/order")
    with pytest.raises(BinanceUsdmPublicEndpointError):
        validate_public_endpoint("/fapi/v2/account")


def test_public_url_builder_only_allows_allowlisted_endpoints() -> None:
    url = build_public_url(PUBLIC_ENDPOINTS["funding_rate"], {"symbol": "BTCUSDT"})

    assert url.startswith("https://fapi.binance.com/fapi/v1/fundingRate")
    assert "apikey" not in url.lower()


def test_public_collector_rejects_api_key_and_unknown_params() -> None:
    with pytest.raises(BinanceUsdmPublicEndpointError):
        build_public_url(PUBLIC_ENDPOINTS["klines"], {"symbol": "BTCUSDT", "interval": "1h", "apiKey": "secret"})
    with pytest.raises(BinanceUsdmPublicEndpointError):
        build_public_url(PUBLIC_ENDPOINTS["klines"], {"symbol": "BTCUSDT", "interval": "1h", "recvWindow": 5000})
    with pytest.raises(BinanceUsdmPublicEndpointError):
        build_public_url(PUBLIC_ENDPOINTS["exchange_info"], {"symbol": "BTCUSDT", "startTime": 1})


def test_public_collector_rejects_binance_credentials_in_environment(monkeypatch) -> None:
    monkeypatch.setenv("BINANCE_API_KEY", "not-used")
    collector = BinanceUsdmPublicCollector(dry_run=False, allow_network=True)

    with pytest.raises(BinanceUsdmPublicEndpointError):
        collector.request_by_name("exchange_info", {"symbol": "BTCUSDT"})


def test_public_collector_rejects_non_binance_base_url() -> None:
    with pytest.raises(BinanceUsdmPublicEndpointError):
        build_public_url(PUBLIC_ENDPOINTS["klines"], {"symbol": "BTCUSDT", "interval": "1h"}, base_url="https://example.com")


def test_dry_run_bundle_path_does_not_create_directory(tmp_path) -> None:
    collector = BinanceUsdmPublicCollector(output_root=tmp_path)
    path = collector.bundle_path("dryrun_bundle", create=False)

    assert path == tmp_path / "dryrun_bundle"
    assert not path.exists()


def test_output_paths_stay_under_bundle_dir(tmp_path) -> None:
    collector = BinanceUsdmPublicCollector(output_root=tmp_path)

    with pytest.raises(ValueError):
        collector.bundle_file_path("bundle1", "../escape.csv")
    assert collector.bundle_file_path("bundle1", "klines_1h.csv", create_parent=True).is_file() is False


def test_open_interest_latest_month_is_marked_partial() -> None:
    coverage = classify_open_interest_coverage(
        sample_start_ms=1_700_000_000_000,
        sample_end_ms=1_800_000_000_000,
        oi_start_ms=1_797_000_000_000,
        oi_end_ms=1_800_000_000_000,
    )

    assert coverage == "latest_month_only"
