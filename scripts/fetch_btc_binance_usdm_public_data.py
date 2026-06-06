#!/usr/bin/env python3
"""Dry-run-first Binance USD-M public market data fetcher.

The script only supports public market-data endpoints. It writes standardized
CSV/JSON files under one selected BTC perpetual bundle directory when both CLI
and config explicitly allow network execution.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError

import yaml

try:
    from quant_crypto.data.binance_usdm_public import (
        BinanceUsdmPublicCollector,
        PUBLIC_ENDPOINTS,
        assert_no_binance_credentials_in_env,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.binance_usdm_public import (
        BinanceUsdmPublicCollector,
        PUBLIC_ENDPOINTS,
        assert_no_binance_credentials_in_env,
    )


DEFAULT_BUNDLE_ROOT = Path("data/external/btc_perpetual/binance_usdm/bundles")
DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_SYMBOL = "BTCUSDT"
KLINE_LIMIT = 1500
FUNDING_LIMIT = 1000
OI_LIMIT = 500
INTERVAL_MS = {
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


def build_fetch_plan(
    *,
    bundle_id: str,
    symbol: str,
    interval: str,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> list[dict[str, object]]:
    window = {}
    if start_time_ms is not None and end_time_ms is not None:
        window = {"startTime": start_time_ms, "endTime": end_time_ms}
    common = {"symbol": symbol, "interval": interval, **window}
    return [
        {"name": "klines", "params": common},
        {"name": "mark_price_klines", "params": common},
        {"name": "premium_index_klines", "params": common},
        {"name": "funding_rate", "params": {"symbol": symbol, **window}},
        {"name": "funding_info", "params": {}},
        {"name": "exchange_info", "params": {"symbol": symbol}},
        {"name": "open_interest", "params": {"symbol": symbol}},
        {"name": "open_interest_hist", "params": {"symbol": symbol, "period": interval, **window}},
    ]


def fetch_bundle(
    *,
    bundle_id: str,
    symbol: str,
    start_time_ms: int,
    end_time_ms: int,
    bundle_root: Path,
    config_path: Path,
    execute_network: bool,
    sleep_seconds: float = 0.1,
) -> dict[str, Any]:
    config = _provider_config(config_path)
    if execute_network:
        _validate_network_config(config)
        _validate_bundle_root(bundle_root)
        assert_no_binance_credentials_in_env()
    collector = BinanceUsdmPublicCollector(
        output_root=bundle_root,
        dry_run=not execute_network,
        allow_network=execute_network,
    )
    bundle_dir = collector.bundle_path(bundle_id, create=execute_network)
    if not execute_network:
        plan = build_fetch_plan(
            bundle_id=bundle_id,
            symbol=symbol,
            interval="1h",
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )
        return {
            "bundle_id": bundle_id,
            "bundle_path": str(bundle_dir),
            "dry_run": True,
            "network_called": False,
            "public_rest_fetch_executed": False,
            "requests": [collector.request_by_name(str(item["name"]), item["params"]) for item in plan],
            "files": [],
            "errors": [],
        }
    files: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for interval in ("1h", "4h", "1d"):
        role = f"klines_{interval}"
        files.append(
            _fetch_kline_csv(
                collector=collector,
                bundle_id=bundle_id,
                role=role,
                endpoint_name="klines",
                output_name=f"klines_{interval}.csv",
                symbol=symbol,
                interval=interval,
                start_time_ms=start_time_ms,
                end_time_ms=end_time_ms,
                sleep_seconds=sleep_seconds,
            )
        )
    for endpoint_name, output_name in (
        ("mark_price_klines", "mark_price_klines_1h.csv"),
        ("premium_index_klines", "premium_index_klines_1h.csv"),
    ):
        files.append(
            _fetch_kline_csv(
                collector=collector,
                bundle_id=bundle_id,
                role=output_name.removesuffix(".csv"),
                endpoint_name=endpoint_name,
                output_name=output_name,
                symbol=symbol,
                interval="1h",
                start_time_ms=start_time_ms,
                end_time_ms=end_time_ms,
                sleep_seconds=sleep_seconds,
            )
        )
    files.append(
        _fetch_funding_rate_csv(
            collector=collector,
            bundle_id=bundle_id,
            symbol=symbol,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            sleep_seconds=sleep_seconds,
        )
    )
    for endpoint_name, output_name, params in (
        ("funding_info", "funding_info.json", {}),
        ("exchange_info", "exchange_info.json", {"symbol": symbol}),
        ("open_interest", "open_interest_current.json", {"symbol": symbol}),
    ):
        try:
            result = collector.request_by_name(endpoint_name, params)
            payload = result.get("payload")
            path = collector.bundle_file_path(bundle_id, output_name, create_parent=True)
            _write_json_payload(path, endpoint_name, payload, url=str(result.get("url", "")))
            files.append({"path": str(path), "role": output_name.removesuffix(".json"), "record_count": _json_count(payload)})
            time.sleep(sleep_seconds)
        except (HTTPError, URLError, ValueError, TimeoutError) as exc:
            errors.append(_fetch_error(output_name.removesuffix(".json"), exc))
    try:
        files.append(
            _fetch_open_interest_hist_csv(
                collector=collector,
                bundle_id=bundle_id,
                symbol=symbol,
                start_time_ms=start_time_ms,
                end_time_ms=end_time_ms,
                sleep_seconds=sleep_seconds,
            )
        )
    except (HTTPError, URLError, ValueError, TimeoutError) as exc:
        error = _fetch_error("open_interest_hist_1h", exc)
        error["diagnostic_only"] = True
        errors.append(error)
    audit = {
        "bundle_id": bundle_id,
        "bundle_path": str(bundle_dir),
        "dry_run": False,
        "network_called": True,
        "public_rest_fetch_executed": True,
        "endpoints_used": sorted(
            {
                "/fapi/v1/klines",
                "/fapi/v1/markPriceKlines",
                "/fapi/v1/premiumIndexKlines",
                "/fapi/v1/fundingRate",
                "/fapi/v1/fundingInfo",
                "/fapi/v1/exchangeInfo",
                "/fapi/v1/openInterest",
                "/futures/data/openInterestHist",
            }
        ),
        "api_key_used": False,
        "private_endpoint_used": False,
        "files": files,
        "errors": errors,
        "blockers": _fetch_blockers(errors),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (bundle_dir / "public_rest_fetch_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--bundle-root", default=str(DEFAULT_BUNDLE_ROOT))
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG))
    parser.add_argument("--start-time-ms", type=int, required=True)
    parser.add_argument("--end-time-ms", type=int, required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--execute", action="store_true", help="Execute public network calls when --allow-network is also set")
    parser.add_argument("--sleep-seconds", type=float, default=0.1)
    args = parser.parse_args()
    result = fetch_bundle(
        bundle_id=args.bundle_id,
        symbol=args.symbol,
        start_time_ms=args.start_time_ms,
        end_time_ms=args.end_time_ms,
        bundle_root=Path(args.bundle_root),
        config_path=Path(args.config_path),
        execute_network=bool(args.allow_network and args.execute),
        sleep_seconds=args.sleep_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def _fetch_kline_csv(
    *,
    collector: BinanceUsdmPublicCollector,
    bundle_id: str,
    role: str,
    endpoint_name: str,
    output_name: str,
    symbol: str,
    interval: str,
    start_time_ms: int,
    end_time_ms: int,
    sleep_seconds: float,
) -> dict[str, Any]:
    rows: list[list[Any]] = []
    cursor = start_time_ms
    step = INTERVAL_MS[interval]
    while cursor <= end_time_ms:
        result = collector.request_by_name(
            endpoint_name,
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_time_ms,
                "limit": KLINE_LIMIT,
            },
        )
        payload = result.get("payload") or []
        if not payload:
            break
        rows.extend(payload)
        last_open = int(payload[-1][0])
        next_cursor = last_open + step
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(payload) < KLINE_LIMIT:
            break
        time.sleep(sleep_seconds)
    path = collector.bundle_file_path(bundle_id, output_name, create_parent=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "timestamp",
                "open_time_ms",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time_ms",
                "source_record_id",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "timestamp": _iso_from_ms(int(row[0])),
                    "open_time_ms": row[0],
                    "open": row[1] if len(row) > 1 else "",
                    "high": row[2] if len(row) > 2 else "",
                    "low": row[3] if len(row) > 3 else "",
                    "close": row[4] if len(row) > 4 else "",
                    "volume": row[5] if len(row) > 5 else "",
                    "close_time_ms": row[6] if len(row) > 6 else "",
                    "source_record_id": f"{role}:{row[0]}",
                }
            )
    return {"path": str(path), "role": role, "record_count": len(rows)}


def _fetch_funding_rate_csv(
    *,
    collector: BinanceUsdmPublicCollector,
    bundle_id: str,
    symbol: str,
    start_time_ms: int,
    end_time_ms: int,
    sleep_seconds: float,
) -> dict[str, Any]:
    rows: list[Mapping[str, Any]] = []
    cursor = start_time_ms
    while cursor <= end_time_ms:
        result = collector.request_by_name(
            "funding_rate",
            {
                "symbol": symbol,
                "startTime": cursor,
                "endTime": end_time_ms,
                "limit": FUNDING_LIMIT,
            },
        )
        payload = result.get("payload") or []
        if not payload:
            break
        rows.extend(payload)
        last_time = int(payload[-1]["fundingTime"])
        next_cursor = last_time + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(payload) < FUNDING_LIMIT:
            break
        time.sleep(sleep_seconds)
    path = collector.bundle_file_path(bundle_id, "funding_rate.csv", create_parent=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp", "fundingTime", "symbol", "fundingRate", "markPrice", "source_record_id"],
        )
        writer.writeheader()
        for row in rows:
            funding_time = int(row["fundingTime"])
            writer.writerow(
                {
                    "timestamp": _iso_from_ms(funding_time),
                    "fundingTime": funding_time,
                    "symbol": row.get("symbol", symbol),
                    "fundingRate": row.get("fundingRate", ""),
                    "markPrice": row.get("markPrice", ""),
                    "source_record_id": f"funding_rate:{funding_time}",
                }
            )
    return {"path": str(path), "role": "funding_rate", "record_count": len(rows)}


def _fetch_open_interest_hist_csv(
    *,
    collector: BinanceUsdmPublicCollector,
    bundle_id: str,
    symbol: str,
    start_time_ms: int,
    end_time_ms: int,
    sleep_seconds: float,
) -> dict[str, Any]:
    rows: list[Mapping[str, Any]] = []
    cursor = start_time_ms
    while cursor <= end_time_ms:
        result = collector.request_by_name(
            "open_interest_hist",
            {
                "symbol": symbol,
                "period": "1h",
                "startTime": cursor,
                "endTime": end_time_ms,
                "limit": OI_LIMIT,
            },
        )
        payload = result.get("payload") or []
        if not payload:
            break
        rows.extend(payload)
        last_time = int(payload[-1]["timestamp"])
        next_cursor = last_time + INTERVAL_MS["1h"]
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(payload) < OI_LIMIT:
            break
        time.sleep(sleep_seconds)
    path = collector.bundle_file_path(bundle_id, "open_interest_hist_1h.csv", create_parent=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp", "timestamp_ms", "sumOpenInterest", "sumOpenInterestValue", "source_record_id"],
        )
        writer.writeheader()
        for row in rows:
            timestamp = int(row["timestamp"])
            writer.writerow(
                {
                    "timestamp": _iso_from_ms(timestamp),
                    "timestamp_ms": timestamp,
                    "sumOpenInterest": row.get("sumOpenInterest", ""),
                    "sumOpenInterestValue": row.get("sumOpenInterestValue", ""),
                    "source_record_id": f"open_interest_hist:{timestamp}",
                }
            )
    return {"path": str(path), "role": "open_interest_hist_1h", "record_count": len(rows), "diagnostic_only": True}


def _write_json_payload(path: Path, endpoint_name: str, payload: Any, *, url: str = "") -> None:
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    wrapped = {
        "fetched_at": fetched_at,
        "captured_at": fetched_at,
        "source_method": "public_rest_response",
        "source_endpoint": PUBLIC_ENDPOINTS[endpoint_name],
        "source_url_or_doc": url,
        "api_key_used": False,
        "private_endpoint_used": False,
        "auth_headers_present": False,
        "rows": payload if isinstance(payload, list) else [payload],
        "payload": payload,
    }
    if endpoint_name == "funding_info":
        wrapped["endpoint_response_available"] = True
        wrapped["raw_response"] = payload
    if endpoint_name == "exchange_info":
        wrapped["raw_symbol_info"] = payload
        wrapped["historical_rule_lineage_available"] = False
    path.write_text(json.dumps(wrapped, indent=2, sort_keys=True), encoding="utf-8")


def _json_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    return 1 if payload else 0


def _fetch_error(role: str, exc: BaseException) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": role, "error": str(exc)}
    if isinstance(exc, HTTPError):
        payload["http_status"] = exc.code
    return payload


def _fetch_blockers(errors: list[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for error in errors:
        if error.get("http_status") == 451:
            blockers.append("btc_binance_public_rest_http_451_geoblocked")
        role = error.get("role")
        if role:
            blockers.append(f"btc_public_rest_{role}_fetch_failed")
    return _dedupe(blockers)


def _provider_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    providers = payload.get("providers", {})
    if not isinstance(providers, Mapping):
        return {}
    provider = providers.get("binance_usdm", {})
    return dict(provider) if isinstance(provider, Mapping) else {}


def _validate_network_config(config: Mapping[str, Any]) -> None:
    if config.get("allow_public_rest_fetch") is not True:
        raise SystemExit("allow_public_rest_fetch=false in config; refusing REST fetch")
    if config.get("allow_network") is not True:
        raise SystemExit("allow_network=false in config; refusing REST fetch")
    if config.get("allow_private_endpoints") is True:
        raise SystemExit("allow_private_endpoints=true is forbidden")
    if config.get("allow_order_endpoints") is True:
        raise SystemExit("allow_order_endpoints=true is forbidden")


def _validate_bundle_root(bundle_root: Path) -> None:
    expected = DEFAULT_BUNDLE_ROOT.resolve()
    actual = bundle_root.resolve()
    if actual != expected:
        raise SystemExit(f"bundle root must be {expected}")


def _iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


if __name__ == "__main__":
    main()
