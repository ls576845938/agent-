from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


BASE_URL = "https://fapi.binance.com"
ALLOWED_BASE_URLS = {BASE_URL}
PUBLIC_ENDPOINTS = {
    "klines": "/fapi/v1/klines",
    "mark_price_klines": "/fapi/v1/markPriceKlines",
    "premium_index_klines": "/fapi/v1/premiumIndexKlines",
    "funding_rate": "/fapi/v1/fundingRate",
    "funding_info": "/fapi/v1/fundingInfo",
    "premium_index": "/fapi/v1/premiumIndex",
    "exchange_info": "/fapi/v1/exchangeInfo",
    "open_interest": "/fapi/v1/openInterest",
    "open_interest_hist": "/futures/data/openInterestHist",
}
FORBIDDEN_ENDPOINT_TOKENS = (
    "account",
    "position",
    "order",
    "listenkey",
    "userdata",
    "userdatastream",
    "leverage",
    "margin",
    "transfer",
    "broker",
    "private",
    "income",
    "balance",
)
FORBIDDEN_PARAM_TOKENS = {
    "apikey",
    "api_key",
    "signature",
    "timestamp",
    "recvwindow",
    "secret",
    "listenkey",
}
FORBIDDEN_ENV_VARS = {
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_SECRET_KEY",
    "BINANCE_USDM_API_KEY",
    "BINANCE_USDM_API_SECRET",
    "BINANCE_FUTURES_API_KEY",
    "BINANCE_FUTURES_API_SECRET",
}
PUBLIC_ENDPOINT_PARAM_ALLOWLIST: dict[str, set[str]] = {
    "/fapi/v1/klines": {"symbol", "interval", "startTime", "endTime", "limit"},
    "/fapi/v1/markPriceKlines": {"symbol", "interval", "startTime", "endTime", "limit"},
    "/fapi/v1/premiumIndexKlines": {"symbol", "interval", "startTime", "endTime", "limit"},
    "/fapi/v1/fundingRate": {"symbol", "startTime", "endTime", "limit"},
    "/fapi/v1/fundingInfo": {"symbol"},
    "/fapi/v1/premiumIndex": {"symbol"},
    "/fapi/v1/exchangeInfo": {"symbol"},
    "/fapi/v1/openInterest": {"symbol"},
    "/futures/data/openInterestHist": {"symbol", "period", "startTime", "endTime", "limit"},
}
WINDOWED_ENDPOINTS = {
    "/fapi/v1/klines",
    "/fapi/v1/markPriceKlines",
    "/fapi/v1/premiumIndexKlines",
    "/fapi/v1/fundingRate",
    "/futures/data/openInterestHist",
}


class BinanceUsdmPublicEndpointError(ValueError):
    pass


@dataclass(frozen=True)
class BinanceUsdmRequest:
    endpoint: str
    params: dict[str, Any]
    url: str
    dry_run: bool


def validate_public_endpoint(endpoint: str) -> str:
    normalized = endpoint.strip()
    lowered = normalized.lower()
    if normalized not in PUBLIC_ENDPOINTS.values():
        raise BinanceUsdmPublicEndpointError(f"Endpoint is not in the public allowlist: {endpoint}")
    if any(token in lowered for token in FORBIDDEN_ENDPOINT_TOKENS):
        raise BinanceUsdmPublicEndpointError(f"Forbidden endpoint token in endpoint: {endpoint}")
    return normalized


def validate_public_params(endpoint: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    safe_endpoint = validate_public_endpoint(endpoint)
    allowed = PUBLIC_ENDPOINT_PARAM_ALLOWLIST[safe_endpoint]
    clean_params = {key: value for key, value in dict(params or {}).items() if value is not None}
    for key in clean_params:
        lowered = str(key).lower()
        if lowered in FORBIDDEN_PARAM_TOKENS:
            raise BinanceUsdmPublicEndpointError(f"Forbidden auth/private param for public collector: {key}")
        if key not in allowed:
            raise BinanceUsdmPublicEndpointError(f"Param is not allowed for {safe_endpoint}: {key}")
    if safe_endpoint in WINDOWED_ENDPOINTS and ("startTime" in clean_params) != ("endTime" in clean_params):
        raise BinanceUsdmPublicEndpointError(f"Explicit startTime/endTime window must be paired for {safe_endpoint}")
    return clean_params


def assert_no_binance_credentials_in_env(env: Mapping[str, str] | None = None) -> None:
    source = env if env is not None else os.environ
    present = sorted(name for name in FORBIDDEN_ENV_VARS if source.get(name))
    if present:
        raise BinanceUsdmPublicEndpointError(
            "Public market-data fetch refuses Binance credential environment variables: "
            + ", ".join(present)
        )


def build_public_url(
    endpoint: str,
    params: Mapping[str, Any] | None = None,
    *,
    base_url: str = BASE_URL,
    allow_test_base_url: bool = False,
) -> str:
    safe_endpoint = validate_public_endpoint(endpoint)
    _validate_base_url(base_url, allow_test_base_url=allow_test_base_url)
    clean_params = validate_public_params(safe_endpoint, params)
    query = urllib.parse.urlencode(clean_params)
    return f"{base_url.rstrip('/')}{safe_endpoint}" + (f"?{query}" if query else "")


class BinanceUsdmPublicCollector:
    """Dry-run first collector for Binance USD-M public market-data endpoints."""

    def __init__(
        self,
        *,
        output_root: str | Path = "data/external/btc_perpetual/binance_usdm/bundles",
        base_url: str = BASE_URL,
        dry_run: bool = True,
        allow_network: bool = False,
        allow_test_base_url: bool = False,
    ) -> None:
        self.output_root = Path(output_root)
        self.base_url = base_url
        self.dry_run = bool(dry_run)
        self.allow_network = bool(allow_network)
        self.allow_test_base_url = bool(allow_test_base_url)

    def request(self, endpoint: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if self.allow_network and not self.dry_run:
            assert_no_binance_credentials_in_env()
        url = build_public_url(
            endpoint,
            params,
            base_url=self.base_url,
            allow_test_base_url=self.allow_test_base_url,
        )
        planned = BinanceUsdmRequest(endpoint=endpoint, params=dict(params or {}), url=url, dry_run=self.dry_run)
        if self.dry_run or not self.allow_network:
            return {
                "dry_run": True,
                "network_called": False,
                "endpoint": planned.endpoint,
                "params": planned.params,
                "url": planned.url,
            }
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read().decode("utf-8")
        return {
            "dry_run": False,
            "network_called": True,
            "endpoint": planned.endpoint,
            "params": planned.params,
            "url": planned.url,
            "payload": json.loads(raw),
        }

    def request_by_name(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if name not in PUBLIC_ENDPOINTS:
            raise BinanceUsdmPublicEndpointError(f"Unknown public endpoint name: {name}")
        return self.request(PUBLIC_ENDPOINTS[name], params)

    def bundle_path(self, bundle_id: str, *, create: bool = True) -> Path:
        if not bundle_id or "/" in bundle_id or ".." in bundle_id:
            raise ValueError("bundle_id must be a simple path segment")
        path = self.output_root / bundle_id
        resolved_root = self.output_root.resolve()
        resolved_path = path.resolve()
        if resolved_root not in (resolved_path, *resolved_path.parents):
            raise ValueError("bundle path escapes output root")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def bundle_file_path(self, bundle_id: str, relative_path: str, *, create_parent: bool = False) -> Path:
        if relative_path.startswith("/") or ".." in Path(relative_path).parts:
            raise ValueError("relative_path must stay under bundle dir")
        bundle = self.bundle_path(bundle_id, create=create_parent)
        path = bundle / relative_path
        if bundle.resolve() not in (path.resolve(), *path.resolve().parents):
            raise ValueError("output path escapes selected bundle dir")
        if create_parent:
            path.parent.mkdir(parents=True, exist_ok=True)
        return path


def classify_open_interest_coverage(
    *,
    sample_start_ms: int | None,
    sample_end_ms: int | None,
    oi_start_ms: int | None,
    oi_end_ms: int | None,
) -> str:
    if oi_start_ms is None or oi_end_ms is None:
        return "missing"
    if sample_start_ms is None or sample_end_ms is None:
        return "partial_local_archive"
    if oi_start_ms <= sample_start_ms and oi_end_ms >= sample_end_ms:
        return "full_local_archive"
    days = max((oi_end_ms - oi_start_ms) / 86_400_000, 0)
    if days <= 35:
        return "latest_month_only"
    return "partial_local_archive"


def _validate_base_url(base_url: str, *, allow_test_base_url: bool) -> None:
    normalized = base_url.rstrip("/")
    if normalized in ALLOWED_BASE_URLS:
        return
    if allow_test_base_url and normalized.startswith(("http://127.0.0.1", "http://localhost")):
        return
    raise BinanceUsdmPublicEndpointError(f"Base URL is not an allowed Binance USD-M public host: {base_url}")
