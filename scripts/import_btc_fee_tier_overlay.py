#!/usr/bin/env python3
"""Import a manually captured BTC USD-M fee-tier overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import jsonschema


DEFAULT_OVERLAY_OUTPUT = Path("artifacts/btc_cost_model/latest/btc_fee_tier_overlay.json")
DEFAULT_REPORT_OUTPUT = Path("artifacts/btc_cost_model/latest/btc_fee_tier_overlay_import_report.json")
FEE_TIER_SCHEMA = Path("schemas/btc_fee_tier_overlay.schema.json")
POST_IMPORT_VALIDATION_COMMAND = "make validate-btc-evidence"
ALLOWED_FEE_TIER_SOURCES = {
    "manual_public_binance_usdm_fee_schedule",
    "manual_public_okx_swap_fee_schedule",
}
UTC_SECOND_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def import_btc_fee_tier_overlay(
    *,
    maker_fee_bps: object,
    taker_fee_bps: object,
    source: str,
    source_url_or_doc: str,
    captured_at: str,
    overlay_output: Path = DEFAULT_OVERLAY_OUTPUT,
    dry_run: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated = generated_at or _utc_z_now()
    blockers: list[str] = []
    maker = _parse_non_negative_float(maker_fee_bps)
    taker = _parse_non_negative_float(taker_fee_bps)
    source_text = source.strip() if isinstance(source, str) else ""
    source_url_text = source_url_or_doc.strip() if isinstance(source_url_or_doc, str) else ""
    captured = captured_at.strip() if isinstance(captured_at, str) else ""

    if maker is None:
        blockers.append("btc_maker_fee_bps_missing_or_invalid")
    if taker is None:
        blockers.append("btc_taker_fee_bps_missing_or_invalid")
    if not source_text:
        blockers.append("btc_fee_tier_source_missing")
    elif source_text not in ALLOWED_FEE_TIER_SOURCES:
        blockers.append("btc_fee_tier_source_not_canonical")
    if not source_url_text:
        blockers.append("btc_fee_tier_source_url_or_doc_missing")
    if not captured:
        blockers.append("btc_fee_tier_captured_at_missing")
    elif not UTC_SECOND_TIMESTAMP_RE.match(captured):
        blockers.append("btc_fee_tier_captured_at_not_utc")
    elif _captured_at_is_after_generated_at(captured, generated):
        blockers.append("btc_fee_tier_captured_at_in_future")

    overlay = (
        {
            "schema_version": "btc_fee_tier_overlay_v1",
            "symbol": "BTCUSDT",
            "market_type": "usds_m_perpetual",
            "maker_fee_bps": maker,
            "taker_fee_bps": taker,
            "source": source_text,
            "source_url_or_doc": source_url_text,
            "captured_at": captured,
            "api_key_used": False,
            "private_endpoint_used": False,
            "auth_headers_used": False,
        }
        if maker is not None and taker is not None
        else None
    )
    if overlay is not None and not _schema_valid(overlay, FEE_TIER_SCHEMA):
        blockers.append("btc_fee_tier_overlay_schema_invalid")
    overlay_hash = _stable_json_sha256(overlay) if overlay is not None else None

    if blockers:
        captured_for_report = captured if UTC_SECOND_TIMESTAMP_RE.match(captured) else None
        return _report(
            status="rejected",
            generated_at=generated,
            dry_run=dry_run,
            captured_at=captured_for_report,
            overlay_output=overlay_output,
            maker_fee_bps=maker,
            taker_fee_bps=taker,
            source=source_text or None,
            source_url_or_doc=source_url_text or None,
            overlay_payload_sha256=overlay_hash,
            writes_performed=False,
            blockers=_dedupe(blockers),
        )

    assert overlay is not None
    if not dry_run:
        _write_json_atomic(overlay, overlay_output)
    return _report(
        status="verified",
        generated_at=generated,
        dry_run=dry_run,
        captured_at=captured,
        overlay_output=overlay_output,
        maker_fee_bps=maker,
        taker_fee_bps=taker,
        source=source_text,
        source_url_or_doc=source_url_text,
        overlay_payload_sha256=overlay_hash,
        writes_performed=not dry_run,
        blockers=[],
    )


def write_fee_tier_overlay_import_report(payload: Mapping[str, Any], output: Path) -> str:
    _write_json_atomic(payload, output)
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--maker-fee-bps", required=True)
    parser.add_argument("--taker-fee-bps", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-url-or-doc", required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--overlay-output", default=str(DEFAULT_OVERLAY_OUTPUT))
    parser.add_argument("--report-output", default=str(DEFAULT_REPORT_OUTPUT))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = import_btc_fee_tier_overlay(
        maker_fee_bps=args.maker_fee_bps,
        taker_fee_bps=args.taker_fee_bps,
        source=args.source,
        source_url_or_doc=args.source_url_or_doc,
        captured_at=args.captured_at,
        overlay_output=Path(args.overlay_output),
        dry_run=bool(args.dry_run),
    )
    write_fee_tier_overlay_import_report(result, Path(args.report_output))
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("status") != "verified":
        raise SystemExit(1)


def _report(
    *,
    status: str,
    generated_at: str,
    dry_run: bool,
    captured_at: str | None,
    overlay_output: Path,
    maker_fee_bps: float | None,
    taker_fee_bps: float | None,
    source: str | None,
    source_url_or_doc: str | None,
    overlay_payload_sha256: str | None,
    writes_performed: bool,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "btc_fee_tier_overlay_import_report_v1",
        "status": status,
        "generated_at": generated_at,
        "dry_run": bool(dry_run),
        "captured_at": captured_at,
        "writes_performed": bool(writes_performed),
        "fee_tier_verified": status == "verified",
        "overlay_output": str(overlay_output),
        "maker_fee_bps": maker_fee_bps,
        "taker_fee_bps": taker_fee_bps,
        "source": source,
        "source_url_or_doc": source_url_or_doc,
        "overlay_payload_sha256": overlay_payload_sha256,
        "post_import_validation_command": POST_IMPORT_VALIDATION_COMMAND,
        "blockers": blockers,
    }


def _parse_non_negative_float(value: object) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _schema_valid(payload: Mapping[str, Any], schema_path: Path) -> bool:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(dict(payload), schema)
    except jsonschema.ValidationError:
        return False
    return True


def _captured_at_is_after_generated_at(captured_at: str, generated_at: str) -> bool:
    captured = _parse_utc_z_timestamp(captured_at)
    generated = _parse_utc_z_timestamp(generated_at)
    if captured is None or generated is None:
        return True
    return captured > generated


def _parse_utc_z_timestamp(value: str) -> datetime | None:
    raw = value.strip()
    if not UTC_SECOND_TIMESTAMP_RE.match(raw):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json_atomic(payload: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        json.dump(dict(payload), handle, indent=2, sort_keys=True)
        handle.write("\n")
    temp_path.replace(output)


def _stable_json_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


if __name__ == "__main__":
    main()
