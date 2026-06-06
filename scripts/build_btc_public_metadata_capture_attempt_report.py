#!/usr/bin/env python3
"""Attempt BTC public metadata capture and write a fail-closed audit report."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError

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


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_data_status/latest")
DEFAULT_RAW_CAPTURE_ROOT = Path("artifacts/btc_data_status/latest/public_metadata_raw_capture")
ENDPOINTS = {
    "exchange_info": {"params": {"symbol": "BTCUSDT"}, "required_for": "exchange_info_verification"},
    "funding_info": {"params": {}, "required_for": "funding_info_endpoint_verification"},
}


RequestFn = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def build_btc_public_metadata_capture_attempt_report(
    *,
    execute_network: bool,
    generated_at: str | None = None,
    request_fn: RequestFn | None = None,
    raw_capture_root: Path | None = None,
) -> dict[str, Any]:
    generated = generated_at or _utc_z_now()
    blockers: list[str] = []
    endpoint_results: dict[str, dict[str, Any]] = {}
    collector = BinanceUsdmPublicCollector(dry_run=not execute_network, allow_network=execute_network)
    if execute_network:
        assert_no_binance_credentials_in_env()
    request = request_fn or collector.request_by_name
    for name, spec in ENDPOINTS.items():
        result = _attempt_endpoint(
            name=name,
            params=spec["params"],
            required_for=str(spec["required_for"]),
            execute_network=execute_network,
            request_fn=request,
        )
        endpoint_results[name] = result
        blockers.extend(result["blockers"])
    capture_complete = all(result["capture_status"] == "captured" for result in endpoint_results.values())
    raw_capture_artifacts = _write_raw_capture_artifacts(
        endpoint_results=endpoint_results,
        raw_capture_root=raw_capture_root,
        captured_at=generated,
    )
    endpoint_results = _strip_internal_endpoint_fields(endpoint_results)
    if not execute_network:
        blockers.append("btc_public_metadata_capture_not_executed")
    blockers.extend(raw_capture_artifacts["blockers"])
    status = "capture_complete" if capture_complete else "capture_incomplete"
    next_required_action = (
        "run_manual_metadata_import"
        if capture_complete and raw_capture_artifacts["writes_performed"]
        else "wrap_and_validate_metadata"
        if capture_complete
        else "manual_capture_from_allowed_network"
    )
    return {
        "schema_version": "btc_public_metadata_capture_attempt_report_v1",
        "generated_at": generated,
        "status": status,
        "network_called": bool(execute_network),
        "symbol": "BTCUSDT",
        "allowed_endpoints": {
            name: f"GET {PUBLIC_ENDPOINTS[name]}" for name in ENDPOINTS
        },
        "safety": {
            "api_key_required": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "writes_bundle_files": False,
            "strategy_retest_allowed": False,
            "paper_or_live_unlock_allowed": False,
        },
        "endpoint_results": endpoint_results,
        "raw_capture_artifacts": raw_capture_artifacts,
        "next_required_action": next_required_action,
        "blockers": _dedupe(blockers),
    }


def write_btc_public_metadata_capture_attempt_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_public_metadata_capture_attempt_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--raw-capture-root", default="")
    args = parser.parse_args()
    payload = build_btc_public_metadata_capture_attempt_report(
        execute_network=bool(args.execute_network),
        generated_at=args.generated_at or None,
        raw_capture_root=Path(args.raw_capture_root) if args.raw_capture_root else None,
    )
    print(write_btc_public_metadata_capture_attempt_report(payload, Path(args.output_root)))


def _attempt_endpoint(
    *,
    name: str,
    params: Mapping[str, Any],
    required_for: str,
    execute_network: bool,
    request_fn: RequestFn,
) -> dict[str, Any]:
    url = ""
    blockers: list[str] = []
    try:
        response = request_fn(name, params)
        url = str(response.get("url", ""))
        payload = response.get("payload")
        network_called = bool(response.get("network_called", execute_network))
        captured = bool(network_called and "payload" in response)
        if not captured:
            blockers.append(f"btc_public_metadata_{name}_capture_not_executed")
        return {
            "required_for": required_for,
            "capture_status": "captured" if captured else "not_executed",
            "endpoint": f"GET {PUBLIC_ENDPOINTS[name]}",
            "url": url,
            "network_called": network_called,
            "http_status": 200 if captured else None,
            "record_count": _json_count(payload) if captured else 0,
            "response_error_excerpt": "",
            "blockers": blockers,
            "_raw_payload": payload if captured else None,
        }
    except HTTPError as exc:
        excerpt = _http_error_excerpt(exc)
        if exc.code == 451:
            blockers.append("btc_binance_public_rest_http_451_geoblocked")
        blockers.append(f"btc_public_metadata_{name}_capture_failed")
        return {
            "required_for": required_for,
            "capture_status": "failed",
            "endpoint": f"GET {PUBLIC_ENDPOINTS[name]}",
            "url": getattr(exc, "url", url) or "",
            "network_called": bool(execute_network),
            "http_status": int(exc.code),
            "record_count": 0,
            "response_error_excerpt": excerpt,
            "blockers": _dedupe(blockers),
            "_raw_payload": None,
        }
    except (URLError, TimeoutError, ValueError) as exc:
        blockers.append(f"btc_public_metadata_{name}_capture_failed")
        return {
            "required_for": required_for,
            "capture_status": "failed",
            "endpoint": f"GET {PUBLIC_ENDPOINTS[name]}",
            "url": url,
            "network_called": bool(execute_network),
            "http_status": None,
            "record_count": 0,
            "response_error_excerpt": str(exc)[:500],
            "blockers": blockers,
            "_raw_payload": None,
        }


def _write_raw_capture_artifacts(
    *,
    endpoint_results: Mapping[str, Mapping[str, Any]],
    raw_capture_root: Path | None,
    captured_at: str,
) -> dict[str, Any]:
    if raw_capture_root is None:
        return _raw_capture_artifact_status(enabled=False)
    raw_capture_root.mkdir(parents=True, exist_ok=True)
    paths = {
        "exchange_info_raw": raw_capture_root / "exchange_info_raw.json",
        "exchange_info_http_status": raw_capture_root / "exchange_info_http_status.txt",
        "funding_info_raw": raw_capture_root / "funding_info_raw.json",
        "funding_info_http_status": raw_capture_root / "funding_info_http_status.txt",
    }
    blockers: list[str] = []
    writes: list[str] = []
    for endpoint_name, raw_key, status_key in (
        ("exchange_info", "exchange_info_raw", "exchange_info_http_status"),
        ("funding_info", "funding_info_raw", "funding_info_http_status"),
    ):
        result = endpoint_results.get(endpoint_name, {})
        payload = result.get("_raw_payload")
        if result.get("capture_status") != "captured" or "_raw_payload" not in result:
            blockers.append(f"btc_public_metadata_{endpoint_name}_raw_capture_missing")
            continue
        paths[raw_key].write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        paths[status_key].write_text(f"{int(result.get('http_status') or 0)}\n", encoding="utf-8")
        writes.extend([str(paths[raw_key]), str(paths[status_key])])
    writes_performed = not blockers and len(writes) == 4
    dry_run_command = ""
    apply_command = ""
    if writes_performed:
        base = (
            f"EXCHANGE_INFO_RAW={paths['exchange_info_raw']} "
            f"FUNDING_INFO_RAW={paths['funding_info_raw']} "
            f"EXCHANGE_INFO_HTTP_STATUS={paths['exchange_info_http_status']} "
            f"FUNDING_INFO_HTTP_STATUS={paths['funding_info_http_status']} "
            f"BTC_MANUAL_METADATA_CAPTURED_AT={captured_at}"
        )
        dry_run_command = f"make dry-run-btc-manual-metadata-import {base}"
        apply_command = f"make apply-btc-manual-metadata-import {base}"
    return _raw_capture_artifact_status(
        enabled=True,
        output_root=str(raw_capture_root),
        writes_performed=writes_performed,
        exchange_info_raw=str(paths["exchange_info_raw"]) if paths["exchange_info_raw"].exists() else None,
        exchange_info_http_status=str(paths["exchange_info_http_status"])
        if paths["exchange_info_http_status"].exists()
        else None,
        funding_info_raw=str(paths["funding_info_raw"]) if paths["funding_info_raw"].exists() else None,
        funding_info_http_status=str(paths["funding_info_http_status"])
        if paths["funding_info_http_status"].exists()
        else None,
        dry_run_import_command=dry_run_command,
        apply_import_command=apply_command,
        blockers=blockers,
    )


def _raw_capture_artifact_status(
    *,
    enabled: bool,
    output_root: str | None = None,
    writes_performed: bool = False,
    exchange_info_raw: str | None = None,
    exchange_info_http_status: str | None = None,
    funding_info_raw: str | None = None,
    funding_info_http_status: str | None = None,
    dry_run_import_command: str = "",
    apply_import_command: str = "",
    blockers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "output_root": output_root,
        "writes_performed": bool(writes_performed),
        "exchange_info_raw": exchange_info_raw,
        "exchange_info_http_status": exchange_info_http_status,
        "funding_info_raw": funding_info_raw,
        "funding_info_http_status": funding_info_http_status,
        "dry_run_import_command": dry_run_import_command,
        "apply_import_command": apply_import_command,
        "blockers": blockers or [],
    }


def _strip_internal_endpoint_fields(endpoint_results: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    stripped: dict[str, dict[str, Any]] = {}
    for name, result in endpoint_results.items():
        stripped[name] = {key: value for key, value in result.items() if not str(key).startswith("_")}
    return stripped


def _http_error_excerpt(exc: HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")[:500]
    except Exception:
        return str(exc)[:500]


def _json_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    return 1 if payload is not None else 0


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
