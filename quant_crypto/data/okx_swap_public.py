from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


BASE_URL = "https://www.okx.com"
ALLOWED_BASE_URLS = {BASE_URL}
PUBLIC_ENDPOINTS = {
    "instruments": "/api/v5/public/instruments",
    "funding_rate": "/api/v5/public/funding-rate",
    "funding_rate_history": "/api/v5/public/funding-rate-history",
    "candles": "/api/v5/market/history-candles",
    "mark_price_candles": "/api/v5/market/history-mark-price-candles",
    "index_candles": "/api/v5/market/history-index-candles",
    "open_interest": "/api/v5/public/open-interest",
}
FORBIDDEN_ENDPOINT_TOKENS = (
    "account",
    "asset",
    "balance",
    "broker",
    "leverage",
    "margin",
    "order",
    "position",
    "private",
    "trade",
    "transfer",
    "withdrawal",
)
FORBIDDEN_PARAM_TOKENS = {
    "apikey",
    "api_key",
    "sign",
    "signature",
    "secret",
    "passphrase",
    "timestamp",
}
FORBIDDEN_ENV_VARS = {
    "OKX_API_KEY",
    "OKX_API_SECRET",
    "OKX_SECRET_KEY",
    "OKX_PASSPHRASE",
    "OKX_PROJECT_ID",
}
PUBLIC_ENDPOINT_PARAM_ALLOWLIST: dict[str, set[str]] = {
    "/api/v5/public/instruments": {"instType", "instFamily", "instId"},
    "/api/v5/public/funding-rate": {"instId"},
    "/api/v5/public/funding-rate-history": {"instId", "before", "after", "limit"},
    "/api/v5/market/history-candles": {"instId", "bar", "before", "after", "limit"},
    "/api/v5/market/history-mark-price-candles": {"instId", "bar", "before", "after", "limit"},
    "/api/v5/market/history-index-candles": {"instId", "bar", "before", "after", "limit"},
    "/api/v5/public/open-interest": {"instType", "instId", "instFamily"},
}


class OkxSwapPublicEndpointError(ValueError):
    pass


@dataclass(frozen=True)
class OkxSwapRequest:
    endpoint: str
    params: dict[str, Any]
    url: str
    dry_run: bool


def validate_public_endpoint(endpoint: str) -> str:
    normalized = endpoint.strip()
    lowered = normalized.lower()
    if normalized not in PUBLIC_ENDPOINTS.values():
        raise OkxSwapPublicEndpointError(f"Endpoint is not in the public allowlist: {endpoint}")
    if any(token in lowered for token in FORBIDDEN_ENDPOINT_TOKENS):
        raise OkxSwapPublicEndpointError(f"Forbidden endpoint token in endpoint: {endpoint}")
    return normalized


def validate_public_params(endpoint: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    safe_endpoint = validate_public_endpoint(endpoint)
    allowed = PUBLIC_ENDPOINT_PARAM_ALLOWLIST[safe_endpoint]
    clean_params = {key: value for key, value in dict(params or {}).items() if value is not None}
    for key in clean_params:
        lowered = str(key).lower()
        if lowered in FORBIDDEN_PARAM_TOKENS:
            raise OkxSwapPublicEndpointError(f"Forbidden auth/private param for public collector: {key}")
        if key not in allowed:
            raise OkxSwapPublicEndpointError(f"Param is not allowed for {safe_endpoint}: {key}")
    return clean_params


def assert_no_okx_credentials_in_env(env: Mapping[str, str] | None = None) -> None:
    source = env if env is not None else os.environ
    present = sorted(name for name in FORBIDDEN_ENV_VARS if source.get(name))
    if present:
        raise OkxSwapPublicEndpointError(
            "Public market-data fetch refuses OKX credential environment variables: " + ", ".join(present)
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


class OkxSwapPublicCollector:
    """Dry-run first collector for OKX public BTC-USDT-SWAP market data."""

    def __init__(
        self,
        *,
        output_root: str | Path = "data/external/btc_perpetual/okx_swap/bundles",
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
            assert_no_okx_credentials_in_env()
        url = build_public_url(
            endpoint,
            params,
            base_url=self.base_url,
            allow_test_base_url=self.allow_test_base_url,
        )
        planned = OkxSwapRequest(endpoint=endpoint, params=dict(params or {}), url=url, dry_run=self.dry_run)
        if self.dry_run or not self.allow_network:
            return {
                "dry_run": True,
                "network_called": False,
                "endpoint": planned.endpoint,
                "params": planned.params,
                "url": planned.url,
            }
        request = urllib.request.Request(url, headers={"User-Agent": "QuantStationVNEXT-public-data/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
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
            raise OkxSwapPublicEndpointError(f"Unknown public endpoint name: {name}")
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


def _validate_base_url(base_url: str, *, allow_test_base_url: bool) -> None:
    normalized = base_url.rstrip("/")
    if normalized in ALLOWED_BASE_URLS:
        return
    if allow_test_base_url and normalized.startswith(("http://127.0.0.1", "http://localhost")):
        return
    raise OkxSwapPublicEndpointError(f"Base URL is not an allowed OKX public host: {base_url}")
