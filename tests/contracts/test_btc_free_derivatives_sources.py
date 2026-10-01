from __future__ import annotations

import urllib.request
from datetime import datetime, timezone

import pytest

from quant_crypto.data.binance_usdm_public import PUBLIC_ENDPOINTS as BINANCE_ENDPOINTS, build_public_url
from quant_crypto.data.free_derivatives_sources import (
    FreeDerivativesSourceError,
    build_btc_free_derivatives_source_plan,
    build_btc_free_derivatives_source_report,
)
from quant_crypto.data.okx_swap_public import PUBLIC_ENDPOINTS as OKX_ENDPOINTS
from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from scripts.build_btc_free_derivatives_source_report import build_btc_free_derivatives_source_report_file


TS = datetime(2026, 6, 27, 0, 0, tzinfo=timezone.utc)


def test_binance_free_derivatives_endpoints_are_allowlisted_public_only() -> None:
    url = build_public_url(
        BINANCE_ENDPOINTS["global_long_short_ratio"],
        {"symbol": "BTCUSDT", "period": "1h"},
    )

    assert url.startswith("https://fapi.binance.com/futures/data/globalLongShortAccountRatio")
    assert "apikey" not in url.lower()
    assert BINANCE_ENDPOINTS["force_orders"] == "/fapi/v1/allForceOrders"


def test_free_derivatives_plan_covers_required_roles_without_network(monkeypatch) -> None:
    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("network should not be called by source plan")

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)
    plans = build_btc_free_derivatives_source_plan()
    roles = {plan.role for plan in plans}
    providers = {plan.provider for plan in plans}

    assert {"open_interest", "funding_rate", "liquidation", "long_short_ratio"} <= roles
    assert {"binance_usdm", "okx_swap", "bybit", "coingecko"} <= providers
    assert any(plan.endpoint == OKX_ENDPOINTS["liquidation_orders"] for plan in plans)
    assert any(plan.provider == "bybit" and plan.network_supported is False for plan in plans)


def test_free_derivatives_report_is_planned_and_does_not_unlock_strategy() -> None:
    payload = build_btc_free_derivatives_source_report(generated_at_utc=TS)

    assert payload["status"] == "planned"
    assert payload["network_called"] is False
    assert payload["api_key_used"] is False
    assert payload["private_endpoint_used"] is False
    assert payload["order_endpoint_used"] is False
    assert payload["strategy_gate_unlocked"] is False
    assert payload["coverage"]["free_sources_sufficient_for_v1_diagnostic"] is True
    assert validate_btc_artifact_schema(payload) == []


def test_free_derivatives_network_fetch_refuses_vendor_credentials(monkeypatch) -> None:
    monkeypatch.setenv("COINGLASS_API_KEY", "should-not-be-used")

    with pytest.raises(FreeDerivativesSourceError):
        build_btc_free_derivatives_source_report(generated_at_utc=TS, execute_network=True)


def test_free_derivatives_report_script_writes_planned_artifact(tmp_path) -> None:
    output = tmp_path / "free_sources.json"
    payload = build_btc_free_derivatives_source_report_file(output=output, generated_at_utc=TS)

    assert output.exists()
    assert payload["status"] == "planned"
