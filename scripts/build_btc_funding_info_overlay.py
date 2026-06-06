#!/usr/bin/env python3
"""Build or validate a clearly labeled BTC fundingInfo metadata overlay."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from quant_crypto.data.binance_usdm_metadata import (
        build_funding_info_endpoint_overlay,
        build_inferred_funding_info_overlay,
        evaluate_funding_info,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.binance_usdm_metadata import (
        build_funding_info_endpoint_overlay,
        build_inferred_funding_info_overlay,
        evaluate_funding_info,
    )


DEFAULT_BUNDLE_DIR = Path(
    "data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1"
)


def write_funding_info_overlay(payload: Mapping[str, Any], bundle_dir: Path) -> str:
    output = bundle_dir / "funding_info.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def read_bundle_manifest(bundle_dir: Path) -> dict[str, Any]:
    path = bundle_dir / "btc_perpetual_bundle_manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR))
    parser.add_argument("--input-json", default="")
    parser.add_argument("--source-method", default="inferred_from_funding_rate_spacing")
    parser.add_argument("--source-url-or-doc", default="")
    parser.add_argument("--captured-at", default="")
    parser.add_argument("--operator-note", default="")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    bundle_dir = Path(args.bundle_dir)
    manifest = read_bundle_manifest(bundle_dir)
    if args.validate_only:
        payload = evaluate_funding_info(bundle_dir, manifest)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if args.input_json:
        if not _is_utc_capture_timestamp(args.captured_at):
            raise SystemExit("captured_at is required as UTC ISO-8601 with Z for fundingInfo raw input")
        try:
            raw = _read_strict_json(Path(args.input_json))
        except (json.JSONDecodeError, ValueError) as exc:
            raise SystemExit("input fundingInfo JSON is invalid or non-standard") from exc
        payload = build_funding_info_endpoint_overlay(
            bundle_dir=bundle_dir,
            raw_response=raw,
            source_method=args.source_method,
            source_url_or_doc=args.source_url_or_doc,
            captured_at=args.captured_at or None,
            operator_note=args.operator_note,
        )
        if payload.get("blockers"):
            raise SystemExit("input fundingInfo overlay has provenance or interval blockers")
    else:
        payload = build_inferred_funding_info_overlay(
            bundle_dir=bundle_dir,
            operator_note=args.operator_note
            or "Inferred from local funding_rate.csv fundingTime spacing; fundingInfo endpoint response unavailable.",
        )
    print(write_funding_info_overlay(payload, bundle_dir))


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


if __name__ == "__main__":
    main()
