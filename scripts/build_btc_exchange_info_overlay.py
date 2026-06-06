#!/usr/bin/env python3
"""Validate or wrap BTC exchangeInfo metadata for the local bundle."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from quant_crypto.data.binance_usdm_metadata import evaluate_exchange_info
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.binance_usdm_metadata import evaluate_exchange_info


DEFAULT_BUNDLE_DIR = Path(
    "data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1"
)


def build_exchange_info_overlay(
    *,
    source_payload: Mapping[str, Any],
    source_method: str,
    source_url_or_doc: str,
    operator_note: str,
    captured_at: str | None = None,
    api_key_used: bool = False,
    private_endpoint_used: bool = False,
    auth_headers_present: bool = False,
) -> dict[str, Any]:
    if source_method not in {"public_rest_response", "manual_offline_capture", "official_public_rest_capture"}:
        raise ValueError("source_method must be public_rest_response, manual_offline_capture, or official_public_rest_capture")
    return {
        "source_method": source_method,
        "source_endpoint": "/fapi/v1/exchangeInfo",
        "source_url_or_doc": source_url_or_doc,
        "captured_at": captured_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "symbol": "BTCUSDT",
        "raw_symbol_info": source_payload,
        "historical_rule_lineage_available": False,
        "operator_note": operator_note,
        "api_key_used": bool(api_key_used),
        "private_endpoint_used": bool(private_endpoint_used),
        "auth_headers_present": bool(auth_headers_present),
        "blockers": [],
    }


def write_exchange_info_overlay(payload: Mapping[str, Any], bundle_dir: Path) -> str:
    output = bundle_dir / "exchange_info.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR))
    parser.add_argument("--input-json", default="")
    parser.add_argument("--source-method", default="manual_offline_capture")
    parser.add_argument("--source-url-or-doc", default="")
    parser.add_argument("--operator-note", default="")
    parser.add_argument("--captured-at", default="")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    bundle_dir = Path(args.bundle_dir)
    output = bundle_dir / "exchange_info.json"
    if args.validate_only:
        print(json.dumps(evaluate_exchange_info(output), indent=2, sort_keys=True))
        return
    if not args.input_json:
        raise SystemExit("exchange_info input is required; refusing to invent exchange rules")
    if not _is_utc_capture_timestamp(args.captured_at):
        raise SystemExit("captured_at is required as UTC ISO-8601 with Z for exchangeInfo raw input")
    try:
        raw = _read_strict_json(Path(args.input_json))
    except (json.JSONDecodeError, ValueError) as exc:
        raise SystemExit("input exchangeInfo JSON is invalid or non-standard") from exc
    if isinstance(raw, Mapping) and raw.get("symbol") == "BTCUSDT":
        source_payload = raw
    else:
        source_payload = _extract_btcusdt_symbol_info(raw)
        if not source_payload:
            raise SystemExit("input exchangeInfo does not contain BTCUSDT symbol info")
    payload = build_exchange_info_overlay(
        source_payload=source_payload,
        source_method=args.source_method,
        source_url_or_doc=args.source_url_or_doc,
        operator_note=args.operator_note,
        captured_at=args.captured_at or None,
    )
    temp_validation_path = _write_temp_overlay_for_validation(payload, bundle_dir)
    try:
        status = evaluate_exchange_info(temp_validation_path)
    finally:
        temp_validation_path.unlink(missing_ok=True)
    if not status.get("exchange_info_verified"):
        raise SystemExit("input exchangeInfo does not satisfy BTCUSDT current-rule contract")
    print(write_exchange_info_overlay(payload, bundle_dir))


def _extract_btcusdt_symbol_info(payload: Any) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        if payload.get("symbol") == "BTCUSDT":
            return dict(payload)
        for key in ("symbols", "rows", "data"):
            found = _extract_btcusdt_symbol_info(payload.get(key))
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _extract_btcusdt_symbol_info(item)
            if found:
                return found
    return {}


def _read_strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant is not allowed: {value}")


def _is_utc_capture_timestamp(value: str) -> bool:
    raw = value.strip()
    if not raw or not raw.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _write_temp_overlay_for_validation(payload: Mapping[str, Any], bundle_dir: Path) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    path = bundle_dir / ".exchange_info.validation.tmp.json"
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return path


if __name__ == "__main__":
    main()
