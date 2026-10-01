from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from quant_crypto.data.binance_usdm_public import (
    BinanceUsdmPublicCollector,
    PUBLIC_ENDPOINTS as BINANCE_ENDPOINTS,
)
from quant_crypto.data.okx_swap_public import (
    OkxSwapPublicCollector,
    PUBLIC_ENDPOINTS as OKX_ENDPOINTS,
)
from quant_crypto.monitoring.artifact_schema import apply_btc_artifact_schema, stable_payload_hash


BTC_FREE_DERIVATIVES_SOURCES_VERSION = "btc_free_derivatives_sources_v1"
BYBIT_BASE_URL = "https://api.bybit.com"
COINGECKO_BASE_URL = "https://api.coingecko.com"
FORBIDDEN_VENDOR_ENV_VARS = {
    "COINGLASS_API_KEY",
    "BYBIT_API_KEY",
    "BYBIT_API_SECRET",
    "COINGECKO_API_KEY",
    "COINGECKO_DEMO_API_KEY",
}
BYBIT_PUBLIC_ENDPOINTS = {
    "open_interest": "/v5/market/open-interest",
    "funding_history": "/v5/market/funding/history",
}
OKX_RUBIK_PUBLIC_ENDPOINTS = {
    "open_interest_volume": "/api/v5/rubik/stat/contracts/open-interest-volume",
    "long_short_account_ratio": "/api/v5/rubik/stat/contracts/long-short-account-ratio",
}
COINGECKO_PUBLIC_ENDPOINTS = {
    "derivatives": "/api/v3/derivatives",
    "derivative_exchanges": "/api/v3/derivatives/exchanges",
}
BYBIT_PUBLIC_WS_SUBSCRIPTIONS = {
    "all_liquidation": "allLiquidation.BTCUSDT",
}
HOUR_MS = 60 * 60 * 1000


class FreeDerivativesSourceError(ValueError):
    pass


@dataclass(frozen=True)
class PublicRequestPlan:
    provider: str
    role: str
    endpoint: str
    params: dict[str, Any]
    url: str
    network_supported: bool = True
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "role": self.role,
            "endpoint": self.endpoint,
            "params": dict(self.params),
            "url": self.url,
            "network_supported": self.network_supported,
            "notes": self.notes,
        }


def build_btc_free_derivatives_source_plan(
    *,
    symbol: str = "BTCUSDT",
    okx_inst_id: str = "BTC-USDT-SWAP",
    period: str = "1h",
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> list[PublicRequestPlan]:
    window = _window_params(start_time_ms=start_time_ms, end_time_ms=end_time_ms)
    binance = BinanceUsdmPublicCollector()
    okx = OkxSwapPublicCollector()
    plans: list[PublicRequestPlan] = [
        _binance_plan(binance, "funding_rate", "funding_rate", {"symbol": symbol, **window}),
        _binance_plan(binance, "open_interest", "open_interest", {"symbol": symbol}),
        _binance_plan(binance, "open_interest_hist", "open_interest", {"symbol": symbol, "period": period, **window}),
        _binance_plan(binance, "global_long_short_ratio", "long_short_ratio", {"symbol": symbol, "period": period, **window}),
        _binance_plan(binance, "top_long_short_account_ratio", "long_short_ratio", {"symbol": symbol, "period": period, **window}),
        _binance_plan(binance, "taker_long_short_ratio", "taker_flow", {"symbol": symbol, "period": period, **window}),
        _binance_plan(binance, "force_orders", "liquidation", {"symbol": symbol, **window}),
        _okx_plan(okx, "funding_rate_history", "funding_rate", {"instId": okx_inst_id, "limit": "100"}),
        _okx_plan(okx, "open_interest", "open_interest", {"instType": "SWAP", "instId": okx_inst_id}),
        _okx_plan(okx, "liquidation_orders", "liquidation", {"instType": "SWAP", "mgnMode": "cross", "instId": okx_inst_id}),
        _bybit_plan(
            "open_interest",
            "open_interest",
            {"category": "linear", "symbol": symbol, "intervalTime": "1h", **_bybit_window(window)},
        ),
        _bybit_plan("funding_history", "funding_rate", {"category": "linear", "symbol": symbol, **_bybit_window(window)}),
        PublicRequestPlan(
            provider="bybit",
            role="liquidation",
            endpoint="wss://stream.bybit.com/v5/public/linear",
            params={"topic": BYBIT_PUBLIC_WS_SUBSCRIPTIONS["all_liquidation"]},
            url="wss://stream.bybit.com/v5/public/linear",
            network_supported=False,
            notes="public websocket subscription plan only; capture runner not enabled by default",
        ),
        _coingecko_plan("derivatives", "cross_vendor_derivatives"),
        _coingecko_plan("derivative_exchanges", "cross_vendor_derivatives_exchanges"),
    ]
    return plans


def build_btc_free_derivatives_source_report(
    *,
    generated_at_utc: datetime,
    symbol: str = "BTCUSDT",
    execute_network: bool = False,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> dict[str, Any]:
    plans = build_btc_free_derivatives_source_plan(
        symbol=symbol,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
    )
    responses: list[dict[str, Any]] = []
    blockers: list[str] = []
    if execute_network:
        _assert_no_vendor_credentials()
        for plan in plans:
            if not plan.network_supported:
                continue
            try:
                responses.append(_fetch_public_json(plan))
                time.sleep(0.1)
            except Exception as exc:  # noqa: BLE001 - report fail-closed by source.
                blockers.append(f"btc_free_derivatives_source_fetch_failed:{plan.provider}:{plan.role}:{type(exc).__name__}")
    coverage = _coverage(plans)
    payload = {
        "free_derivatives_sources_version": BTC_FREE_DERIVATIVES_SOURCES_VERSION,
        "status": "verified" if execute_network and not blockers else ("planned" if not execute_network else "blocked"),
        "symbol": symbol,
        "execute_network": execute_network,
        "network_called": execute_network,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "public_market_data_only": True,
        "source_plan": [plan.to_dict() for plan in plans],
        "coverage": coverage,
        "response_summaries": responses,
        "strategy_gate_unlocked": False,
        "blockers": blockers,
    }
    return apply_btc_artifact_schema(
        payload,
        decision="free_derivatives_sources_planned" if not execute_network else ("free_derivatives_sources_verified" if not blockers else "free_derivatives_sources_blocked"),
        generated_at_utc=generated_at_utc,
        as_of_utc=generated_at_utc,
        blockers=blockers,
        warnings=[],
        input_hashes={"source_plan": stable_payload_hash({"plans": [plan.to_dict() for plan in plans]})},
    )


def normalize_binance_derivatives_sentiment_rows(
    *,
    open_interest_hist: list[Mapping[str, Any]],
    long_short_ratio: list[Mapping[str, Any]],
    funding_rates: list[Mapping[str, Any]],
    force_orders: list[Mapping[str, Any]],
    start_hour_ms: int,
    end_hour_ms: int,
    generated_at_utc: datetime,
    symbol: str = "BTCUSDT",
) -> list[dict[str, Any]]:
    oi_by_hour = {_hour_ms(_int(item.get("timestamp"))): item for item in open_interest_hist if item.get("timestamp") is not None}
    ls_by_hour = {_hour_ms(_int(item.get("timestamp"))): item for item in long_short_ratio if item.get("timestamp") is not None}
    funding = sorted(
        [(int(item.get("fundingTime")), item) for item in funding_rates if item.get("fundingTime") is not None],
        key=lambda item: item[0],
    )
    liquidations_by_hour = _aggregate_force_orders_by_hour(force_orders)
    rows: list[dict[str, Any]] = []
    for hour in range(_hour_ms(start_hour_ms), _hour_ms(end_hour_ms) + 1, HOUR_MS):
        event_time = datetime.fromtimestamp(hour / 1000, tz=timezone.utc)
        available_time = event_time + timedelta(minutes=5)
        funding_item = _latest_at_or_before(funding, hour)
        liquidation = liquidations_by_hour.get(hour, {"long_liquidation_usd": 0.0, "short_liquidation_usd": 0.0})
        oi_item = oi_by_hour.get(hour, {})
        ls_item = ls_by_hour.get(hour, {})
        component_payload = {
            "open_interest": oi_item,
            "long_short_ratio": ls_item,
            "funding_rate": funding_item,
            "liquidation": liquidation,
        }
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": available_time.isoformat(),
                "ingested_at": generated_at_utc.isoformat(),
                "processed_at": generated_at_utc.isoformat(),
                "venue": "binance_usdm",
                "symbol": symbol,
                "source_provider": "binance_usdm_free_public",
                "is_final": True,
                "open_interest_usd": _optional_float(
                    oi_item.get("sumOpenInterestValue")
                    or oi_item.get("sumOpenInterest")
                    or oi_item.get("openInterest")
                ),
                "funding_rate": _optional_float(_mapping(funding_item).get("fundingRate")),
                "long_liquidation_usd": float(liquidation.get("long_liquidation_usd", 0.0)),
                "short_liquidation_usd": float(liquidation.get("short_liquidation_usd", 0.0)),
                "long_short_ratio": _optional_float(ls_item.get("longShortRatio")),
                "source_raw_payload_hash": stable_payload_hash(component_payload),
            }
        )
    return rows


def fetch_binance_free_derivatives_payloads(
    *,
    symbol: str,
    start_hour_ms: int,
    end_hour_ms: int,
    sleep_seconds: float = 0.1,
) -> dict[str, Any]:
    from quant_crypto.data.binance_usdm_public import assert_no_binance_credentials_in_env, build_public_url

    assert_no_binance_credentials_in_env()
    _assert_no_vendor_credentials()
    open_interest_hist = _fetch_binance_windowed_series(
        endpoint=BINANCE_ENDPOINTS["open_interest_hist"],
        base_params={"symbol": symbol, "period": "1h", "limit": 500},
        start_ms=start_hour_ms,
        end_ms=end_hour_ms,
        max_window_hours=499,
        sleep_seconds=sleep_seconds,
        build_url=build_public_url,
    )
    long_short_ratio = _fetch_binance_windowed_series(
        endpoint=BINANCE_ENDPOINTS["global_long_short_ratio"],
        base_params={"symbol": symbol, "period": "1h", "limit": 500},
        start_ms=start_hour_ms,
        end_ms=end_hour_ms,
        max_window_hours=499,
        sleep_seconds=sleep_seconds,
        build_url=build_public_url,
    )
    funding_rates = _fetch_binance_windowed_series(
        endpoint=BINANCE_ENDPOINTS["funding_rate"],
        base_params={"symbol": symbol, "limit": 1000},
        start_ms=start_hour_ms,
        end_ms=end_hour_ms,
        max_window_hours=24 * 365,
        sleep_seconds=sleep_seconds,
        build_url=build_public_url,
    )
    force_orders = _fetch_binance_windowed_series(
        endpoint=BINANCE_ENDPOINTS["force_orders"],
        base_params={"symbol": symbol, "limit": 1000},
        start_ms=start_hour_ms,
        end_ms=end_hour_ms,
        max_window_hours=24,
        sleep_seconds=sleep_seconds,
        build_url=build_public_url,
        tolerate_http_errors=True,
    )
    return {
        "open_interest_hist": open_interest_hist,
        "long_short_ratio": long_short_ratio,
        "funding_rates": funding_rates,
        "force_orders": force_orders,
    }


def normalize_okx_derivatives_sentiment_rows(
    *,
    open_interest_volume: list[Mapping[str, Any]],
    long_short_ratio: list[Mapping[str, Any]],
    funding_rates: list[Mapping[str, Any]],
    liquidation_orders: list[Mapping[str, Any]],
    start_hour_ms: int,
    end_hour_ms: int,
    generated_at_utc: datetime,
    symbol: str = "BTCUSDT",
) -> list[dict[str, Any]]:
    oi_by_hour = {_hour_ms(_int(item[0])): item for item in open_interest_volume if _sequence_len(item) >= 2}
    ls_by_hour = {_hour_ms(_int(item[0])): item for item in long_short_ratio if _sequence_len(item) >= 2}
    funding = sorted(
        [(int(item.get("fundingTime")), item) for item in funding_rates if item.get("fundingTime") is not None],
        key=lambda item: item[0],
    )
    liquidations_by_hour = _aggregate_okx_liquidation_orders_by_hour(liquidation_orders)
    rows: list[dict[str, Any]] = []
    for hour in range(_hour_ms(start_hour_ms), _hour_ms(end_hour_ms) + 1, HOUR_MS):
        event_time = datetime.fromtimestamp(hour / 1000, tz=timezone.utc)
        available_time = event_time + timedelta(minutes=5)
        oi_item = oi_by_hour.get(hour, [])
        ls_item = ls_by_hour.get(hour, [])
        funding_item = _latest_at_or_before(funding, hour)
        liquidation = liquidations_by_hour.get(hour, {"long_liquidation_usd": 0.0, "short_liquidation_usd": 0.0})
        component_payload = {
            "open_interest_volume": oi_item,
            "long_short_ratio": ls_item,
            "funding_rate": funding_item,
            "liquidation": liquidation,
        }
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": available_time.isoformat(),
                "ingested_at": generated_at_utc.isoformat(),
                "processed_at": generated_at_utc.isoformat(),
                "venue": "okx_swap",
                "symbol": symbol,
                "source_provider": "okx_free_public",
                "is_final": True,
                "open_interest_usd": _optional_float(oi_item[1]) if _sequence_len(oi_item) >= 2 else None,
                "funding_rate": _optional_float(_mapping(funding_item).get("fundingRate")),
                "long_liquidation_usd": float(liquidation.get("long_liquidation_usd", 0.0)),
                "short_liquidation_usd": float(liquidation.get("short_liquidation_usd", 0.0)),
                "long_short_ratio": _optional_float(ls_item[1]) if _sequence_len(ls_item) >= 2 else None,
                "source_raw_payload_hash": stable_payload_hash(component_payload),
            }
        )
    return rows


def fetch_okx_free_derivatives_payloads(
    *,
    start_hour_ms: int,
    end_hour_ms: int,
    inst_id: str = "BTC-USDT-SWAP",
    ccy: str = "BTC",
    symbol: str = "BTCUSDT",
    sleep_seconds: float = 0.1,
) -> dict[str, Any]:
    from quant_crypto.data.okx_swap_public import assert_no_okx_credentials_in_env, build_public_url

    del symbol
    assert_no_okx_credentials_in_env()
    _assert_no_vendor_credentials()
    open_interest_volume = _fetch_okx_rubik_window(
        endpoint=OKX_RUBIK_PUBLIC_ENDPOINTS["open_interest_volume"],
        base_params={"ccy": ccy, "period": "1H"},
        start_ms=start_hour_ms - HOUR_MS,
        end_ms=end_hour_ms,
        max_window_hours=336,
        sleep_seconds=sleep_seconds,
    )
    long_short_ratio = _fetch_okx_rubik_window(
        endpoint=OKX_RUBIK_PUBLIC_ENDPOINTS["long_short_account_ratio"],
        base_params={"ccy": ccy, "period": "1H"},
        start_ms=start_hour_ms - HOUR_MS,
        end_ms=end_hour_ms,
        max_window_hours=336,
        sleep_seconds=sleep_seconds,
    )
    funding_rates = _fetch_okx_paginated_records(
        build_url=build_public_url,
        endpoint=OKX_ENDPOINTS["funding_rate_history"],
        base_params={"instId": inst_id, "limit": "100"},
        start_ms=start_hour_ms - 8 * HOUR_MS,
        end_ms=end_hour_ms,
        timestamp_field="fundingTime",
        sleep_seconds=sleep_seconds,
    )
    liquidation_orders = _fetch_okx_liquidation_orders(
        build_url=build_public_url,
        inst_id=inst_id,
        start_ms=start_hour_ms,
        end_ms=end_hour_ms,
        sleep_seconds=sleep_seconds,
    )
    return {
        "open_interest_volume": open_interest_volume,
        "long_short_ratio": long_short_ratio,
        "funding_rates": funding_rates,
        "liquidation_orders": liquidation_orders,
    }


def _binance_plan(collector: BinanceUsdmPublicCollector, name: str, role: str, params: Mapping[str, Any]) -> PublicRequestPlan:
    request = collector.request_by_name(name, params)
    return PublicRequestPlan(
        provider="binance_usdm",
        role=role,
        endpoint=BINANCE_ENDPOINTS[name],
        params=dict(params),
        url=str(request["url"]),
    )


def _okx_plan(collector: OkxSwapPublicCollector, name: str, role: str, params: Mapping[str, Any]) -> PublicRequestPlan:
    request = collector.request_by_name(name, params)
    return PublicRequestPlan(
        provider="okx_swap",
        role=role,
        endpoint=OKX_ENDPOINTS[name],
        params=dict(params),
        url=str(request["url"]),
    )


def _bybit_plan(name: str, role: str, params: Mapping[str, Any]) -> PublicRequestPlan:
    if name not in BYBIT_PUBLIC_ENDPOINTS:
        raise FreeDerivativesSourceError(f"Unknown Bybit public endpoint: {name}")
    endpoint = BYBIT_PUBLIC_ENDPOINTS[name]
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
    return PublicRequestPlan(
        provider="bybit",
        role=role,
        endpoint=endpoint,
        params=dict(params),
        url=f"{BYBIT_BASE_URL}{endpoint}" + (f"?{query}" if query else ""),
    )


def _coingecko_plan(name: str, role: str) -> PublicRequestPlan:
    if name not in COINGECKO_PUBLIC_ENDPOINTS:
        raise FreeDerivativesSourceError(f"Unknown CoinGecko public endpoint: {name}")
    endpoint = COINGECKO_PUBLIC_ENDPOINTS[name]
    return PublicRequestPlan(
        provider="coingecko",
        role=role,
        endpoint=endpoint,
        params={},
        url=f"{COINGECKO_BASE_URL}{endpoint}",
    )


def _fetch_public_json(plan: PublicRequestPlan) -> dict[str, Any]:
    request = urllib.request.Request(plan.url, headers={"User-Agent": "QuantStationVNEXT-free-derivatives/1.0"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8")
    payload = json.loads(raw)
    return {
        "provider": plan.provider,
        "role": plan.role,
        "endpoint": plan.endpoint,
        "http_status": 200,
        "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "payload_hash": stable_payload_hash({"payload": payload}),
        "record_count": _payload_count(payload),
    }


def _coverage(plans: list[PublicRequestPlan]) -> dict[str, Any]:
    by_role: dict[str, list[str]] = {}
    for plan in plans:
        by_role.setdefault(plan.role, []).append(plan.provider)
    return {
        "roles": {role: sorted(set(providers)) for role, providers in sorted(by_role.items())},
        "required_derivatives_sentiment_roles": {
            "open_interest": "open_interest" in by_role,
            "funding_rate": "funding_rate" in by_role,
            "liquidation": "liquidation" in by_role,
            "long_short_ratio": "long_short_ratio" in by_role,
        },
        "free_sources_sufficient_for_v1_diagnostic": all(
            role in by_role for role in ("open_interest", "funding_rate", "liquidation", "long_short_ratio")
        ),
    }


def _payload_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, Mapping):
        data = payload.get("data") or payload.get("result") or payload.get("tickers")
        if isinstance(data, list):
            return len(data)
        if isinstance(data, Mapping):
            nested = data.get("list")
            if isinstance(nested, list):
                return len(nested)
        return 1
    return 0


def _window_params(*, start_time_ms: int | None, end_time_ms: int | None) -> dict[str, int]:
    if start_time_ms is None or end_time_ms is None:
        return {}
    return {"startTime": start_time_ms, "endTime": end_time_ms}


def _bybit_window(window: Mapping[str, Any]) -> dict[str, Any]:
    return {"startTime": window.get("startTime"), "endTime": window.get("endTime")}


def _assert_no_vendor_credentials(env: Mapping[str, str] | None = None) -> None:
    source = env if env is not None else os.environ
    present = sorted(name for name in FORBIDDEN_VENDOR_ENV_VARS if source.get(name))
    if present:
        raise FreeDerivativesSourceError("Free public derivatives fetch refuses credential environment variables: " + ", ".join(present))


def _fetch_binance_windowed_series(
    *,
    endpoint: str,
    base_params: Mapping[str, Any],
    start_ms: int,
    end_ms: int,
    max_window_hours: int,
    sleep_seconds: float,
    build_url: Any,
    tolerate_http_errors: bool = False,
) -> list[Mapping[str, Any]]:
    from urllib.error import HTTPError, URLError

    rows: list[Mapping[str, Any]] = []
    cursor = _hour_ms(start_ms)
    while cursor <= end_ms:
        window_end = min(cursor + max_window_hours * HOUR_MS, end_ms)
        params = dict(base_params)
        params.update({"startTime": cursor, "endTime": window_end})
        url = build_url(endpoint, params)
        try:
            payload = _fetch_json_url(url)
        except (HTTPError, URLError, TimeoutError):
            if tolerate_http_errors:
                cursor = window_end + HOUR_MS
                continue
            raise
        if isinstance(payload, list):
            rows.extend(item for item in payload if isinstance(item, Mapping))
        elif isinstance(payload, Mapping):
            data = payload.get("data")
            if isinstance(data, list):
                rows.extend(item for item in data if isinstance(item, Mapping))
        time.sleep(sleep_seconds)
        cursor = window_end + HOUR_MS
    return _dedupe_by_timestamp(rows)


def _fetch_okx_rubik_window(
    *,
    endpoint: str,
    base_params: Mapping[str, Any],
    start_ms: int,
    end_ms: int,
    max_window_hours: int,
    sleep_seconds: float,
) -> list[Mapping[str, Any] | list[Any]]:
    rows: list[Mapping[str, Any] | list[Any]] = []
    cursor = _hour_ms(start_ms)
    while cursor <= end_ms:
        window_end = min(cursor + max_window_hours * HOUR_MS, end_ms)
        params = dict(base_params)
        params.update({"begin": cursor, "end": window_end})
        query = urllib.parse.urlencode(params)
        payload = _fetch_json_url(f"https://www.okx.com{endpoint}?{query}")
        if isinstance(payload, Mapping) and str(payload.get("code")) != "0":
            raise FreeDerivativesSourceError(f"OKX rubik public fetch failed: {endpoint}:{payload.get('code')}:{payload.get('msg')}")
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if isinstance(data, list):
            rows.extend(item for item in data if isinstance(item, (Mapping, list)))
        time.sleep(sleep_seconds)
        cursor = window_end + HOUR_MS
    return _dedupe_okx_array_rows(rows)


def _fetch_okx_paginated_records(
    *,
    build_url: Any,
    endpoint: str,
    base_params: Mapping[str, Any],
    start_ms: int,
    end_ms: int,
    timestamp_field: str,
    sleep_seconds: float,
) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    before: str | None = None
    for _ in range(20):
        params = dict(base_params)
        if before:
            params["before"] = before
        payload = _fetch_json_url(build_url(endpoint, params))
        if isinstance(payload, Mapping) and str(payload.get("code")) != "0":
            raise FreeDerivativesSourceError(f"OKX public fetch failed: {endpoint}:{payload.get('code')}:{payload.get('msg')}")
        data = payload.get("data") if isinstance(payload, Mapping) else None
        page = [item for item in data if isinstance(item, Mapping)] if isinstance(data, list) else []
        if not page:
            break
        rows.extend(item for item in page if start_ms <= _int(item.get(timestamp_field)) <= end_ms)
        oldest = min(_int(item.get(timestamp_field)) for item in page if item.get(timestamp_field) is not None)
        if oldest <= start_ms:
            break
        before = str(oldest)
        time.sleep(sleep_seconds)
    return _dedupe_by_timestamp(rows)


def _fetch_okx_liquidation_orders(
    *,
    build_url: Any,
    inst_id: str,
    start_ms: int,
    end_ms: int,
    sleep_seconds: float,
) -> list[Mapping[str, Any]]:
    del sleep_seconds
    underlying = inst_id.removesuffix("-SWAP")
    payload = _fetch_json_url(
        build_url(
            OKX_ENDPOINTS["liquidation_orders"],
            {
                "instType": "SWAP",
                "uly": underlying,
                "state": "filled",
                "limit": "100",
            },
        )
    )
    if isinstance(payload, Mapping) and str(payload.get("code")) != "0":
        raise FreeDerivativesSourceError(f"OKX liquidation public fetch failed:{payload.get('code')}:{payload.get('msg')}")
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, list):
        return []
    rows: list[Mapping[str, Any]] = []
    for item in data:
        if not isinstance(item, Mapping):
            continue
        details = item.get("details")
        if not isinstance(details, list):
            continue
        for detail in details:
            if not isinstance(detail, Mapping):
                continue
            ts = detail.get("ts") or detail.get("time")
            if ts is None or not (start_ms <= _int(ts) <= end_ms):
                continue
            enriched = dict(detail)
            enriched["instId"] = item.get("instId")
            rows.append(enriched)
    return _dedupe_by_timestamp(rows)


def _fetch_json_url(url: str) -> Any:
    from urllib.error import HTTPError, URLError

    request = urllib.request.Request(url, headers={"User-Agent": "QuantStationVNEXT-free-derivatives/1.0"})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if 400 <= exc.code < 500:
                raise
            last_error = exc
        except (TimeoutError, URLError) as exc:
            last_error = exc
        time.sleep(0.5 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise FreeDerivativesSourceError("public json fetch failed without an exception")


def _dedupe_by_timestamp(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    keyed: dict[int, Mapping[str, Any]] = {}
    passthrough: list[Mapping[str, Any]] = []
    for row in rows:
        ts = row.get("timestamp") or row.get("fundingTime") or row.get("time")
        if ts is None:
            passthrough.append(row)
            continue
        keyed[int(ts)] = row
    return [*passthrough, *[keyed[key] for key in sorted(keyed)]]


def _dedupe_okx_array_rows(rows: list[Mapping[str, Any] | list[Any]]) -> list[Mapping[str, Any] | list[Any]]:
    keyed: dict[int, Mapping[str, Any] | list[Any]] = {}
    passthrough: list[Mapping[str, Any] | list[Any]] = []
    for row in rows:
        ts: Any = None
        if isinstance(row, Mapping):
            ts = row.get("ts") or row.get("timestamp")
        elif isinstance(row, list) and row:
            ts = row[0]
        if ts is None:
            passthrough.append(row)
            continue
        keyed[int(ts)] = row
    return [*passthrough, *[keyed[key] for key in sorted(keyed)]]


def _aggregate_force_orders_by_hour(rows: list[Mapping[str, Any]]) -> dict[int, dict[str, float]]:
    result: dict[int, dict[str, float]] = {}
    for row in rows:
        order = _mapping(row.get("order")) or row
        event_time = order.get("time") or row.get("time")
        if event_time is None:
            continue
        hour = _hour_ms(int(event_time))
        bucket = result.setdefault(hour, {"long_liquidation_usd": 0.0, "short_liquidation_usd": 0.0})
        notional = _optional_float(order.get("ap") or order.get("averagePrice") or order.get("price")) or 0.0
        notional *= _optional_float(order.get("origQty") or order.get("executedQty") or order.get("q")) or 0.0
        side = str(order.get("side") or "").upper()
        if side == "SELL":
            bucket["long_liquidation_usd"] += notional
        elif side == "BUY":
            bucket["short_liquidation_usd"] += notional
    return result


def _aggregate_okx_liquidation_orders_by_hour(rows: list[Mapping[str, Any]]) -> dict[int, dict[str, float]]:
    result: dict[int, dict[str, float]] = {}
    for row in rows:
        event_time = row.get("ts") or row.get("time")
        if event_time is None:
            continue
        hour = _hour_ms(_int(event_time))
        bucket = result.setdefault(hour, {"long_liquidation_usd": 0.0, "short_liquidation_usd": 0.0})
        notional = (_optional_float(row.get("bkPx")) or 0.0) * (_optional_float(row.get("sz")) or 0.0)
        pos_side = str(row.get("posSide") or "").lower()
        side = str(row.get("side") or "").lower()
        if pos_side == "long" or side == "sell":
            bucket["long_liquidation_usd"] += notional
        elif pos_side == "short" or side == "buy":
            bucket["short_liquidation_usd"] += notional
    return result


def _latest_at_or_before(items: list[tuple[int, Mapping[str, Any]]], timestamp_ms: int) -> Mapping[str, Any]:
    latest: Mapping[str, Any] = {}
    for ts, item in items:
        if ts > timestamp_ms:
            break
        latest = item
    return latest


def _hour_ms(value: int) -> int:
    return int(value // HOUR_MS * HOUR_MS)


def _int(value: Any) -> int:
    return int(float(value))


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence_len(value: object) -> int:
    return len(value) if isinstance(value, list) else 0
