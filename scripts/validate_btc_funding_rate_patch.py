#!/usr/bin/env python3
"""Validate a manual offline BTC funding-rate patch before merge."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

import jsonschema


DEFAULT_BUNDLE_ID = "btc_usdm_binance_btcusdt_20240101_20260512_v1"
DEFAULT_BUNDLE_ROOT = Path("data/external/btc_perpetual/binance_usdm/bundles")
DEFAULT_PATCH_ID = "funding_rate_patch_20260501_20260512"
REQUIRED_COLUMNS = ["timestamp", "fundingTime", "symbol", "fundingRate", "markPrice", "source_record_id"]
SCHEMA_PATH = Path("schemas/btc_funding_rate_patch_metadata.schema.json")
EXPECTED_START_MS = 1777593600000
EXPECTED_END_MS = 1778544000000
EXPECTED_ROW_COUNT = 34
EXPECTED_INTERVAL_MS = 8 * 60 * 60 * 1000
EXPECTED_TIME_TOLERANCE_MS = 5 * 60 * 1000
EXPECTED_REQUESTED_START = "2026-05-01T00:00:00Z"
EXPECTED_REQUESTED_END = "2026-05-12T00:00:00Z"


def validate_btc_funding_rate_patch(
    *,
    bundle_id: str = DEFAULT_BUNDLE_ID,
    patch_id: str = DEFAULT_PATCH_ID,
    bundle_root: Path = DEFAULT_BUNDLE_ROOT,
) -> dict[str, Any]:
    bundle_dir = _safe_bundle_dir(bundle_root, bundle_id)
    patch_dir = bundle_dir / "patches"
    csv_path = patch_dir / f"{patch_id}.csv"
    metadata_path = patch_dir / f"{patch_id}.metadata.json"
    metadata = _read_json(metadata_path)
    blockers: list[str] = []
    if not csv_path.exists():
        blockers.append("btc_funding_rate_patch_csv_missing")
    if not metadata_path.exists():
        blockers.append("btc_funding_rate_patch_metadata_missing")
    rows, csv_blockers = _read_patch_csv(csv_path)
    blockers.extend(csv_blockers)
    blockers.extend(_validate_metadata(metadata, csv_path, rows, patch_id=patch_id, bundle_id=bundle_id))
    expected_times = _expected_funding_times_from_gap_report() or _default_expected_funding_times()
    times = [row["funding_time"] for row in rows]
    if rows:
        if times != sorted(times):
            blockers.append("btc_funding_rate_patch_non_monotonic")
        if len(times) != len(set(times)):
            blockers.append("btc_funding_rate_patch_duplicate_funding_time")
        if not _times_match_expected_with_tolerance(times, expected_times):
            blockers.append("btc_funding_rate_patch_expected_times_mismatch")
        if _ms_abs_delta(min(times), expected_times[0]) > EXPECTED_TIME_TOLERANCE_MS:
            blockers.append("btc_funding_rate_patch_expected_start_mismatch")
        if _ms_abs_delta(max(times), expected_times[-1]) > EXPECTED_TIME_TOLERANCE_MS:
            blockers.append("btc_funding_rate_patch_expected_end_mismatch")
        if len(rows) != len(expected_times):
            blockers.append("btc_funding_rate_patch_record_count_not_expected")
        for left, right in zip(times, times[1:]):
            if abs(int((right - left).total_seconds() * 1000) - EXPECTED_INTERVAL_MS) > EXPECTED_TIME_TOLERANCE_MS:
                blockers.append("btc_funding_rate_patch_interval_not_8h")
                break
    validation_status = "missing" if not csv_path.exists() or not metadata_path.exists() else "fail"
    valid = not blockers
    if valid:
        validation_status = "pass"
    return {
        "schema_version": "btc_funding_rate_patch_validation_report_v1",
        "bundle_id": bundle_id,
        "patch_id": patch_id,
        "patch_csv_path": str(csv_path),
        "metadata_path": str(metadata_path),
        "patch_present": csv_path.exists() and metadata_path.exists(),
        "record_count": len(rows),
        "sha256": _sha256(csv_path) if csv_path.exists() else None,
        "expected_row_count": len(expected_times),
        "first_funding_time": _iso(min(times)) if times else None,
        "last_funding_time": _iso(max(times)) if times else None,
        "expected_first_funding_time": _iso(expected_times[0]),
        "expected_last_funding_time": _iso(expected_times[-1]),
        "duplicate_funding_time_count": len(times) - len(set(times)),
        "monotonic_time_pass": bool(times == sorted(times)),
        "expected_times_match": bool(_times_match_expected_with_tolerance(times, expected_times)) if rows else False,
        "source_method": metadata.get("source_method"),
        "sha256_match": bool(csv_path.exists() and metadata.get("csv_sha256") == _sha256(csv_path)),
        "record_count_match": int(metadata.get("record_count", -1) or -1) == len(rows) if metadata else False,
        "validation_status": validation_status,
        "validation_pass": valid,
        "blockers": _dedupe(blockers),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--bundle-root", default=str(DEFAULT_BUNDLE_ROOT))
    parser.add_argument("--patch-id", default=DEFAULT_PATCH_ID)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    payload = validate_btc_funding_rate_patch(bundle_id=args.bundle_id, patch_id=args.patch_id, bundle_root=Path(args.bundle_root))
    output = Path(args.output) if args.output else Path(args.bundle_root) / args.bundle_id / "funding_rate_patch_validation_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


def _read_patch_csv(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    blockers: list[str] = []
    if not path.exists():
        return [], blockers
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != REQUIRED_COLUMNS:
            blockers.append("btc_funding_rate_patch_columns_invalid")
            return [], blockers
        rows: list[dict[str, Any]] = []
        for row in reader:
            row_blockers = _validate_row(row)
            blockers.extend(row_blockers)
            funding_time = _parse_ms(row.get("fundingTime"))
            if funding_time:
                rows.append({"funding_time": funding_time, "raw": dict(row)})
    if not rows:
        blockers.append("btc_funding_rate_patch_empty")
    return rows, blockers


def _validate_row(row: Mapping[str, str]) -> list[str]:
    blockers: list[str] = []
    funding_time = _parse_ms(row.get("fundingTime"))
    timestamp = _parse_time(row.get("timestamp"))
    if row.get("symbol") != "BTCUSDT":
        blockers.append("btc_funding_rate_patch_symbol_not_btcusdt")
    if funding_time is None:
        blockers.append("btc_funding_rate_patch_funding_time_invalid")
    if timestamp is None or "Z" not in str(row.get("timestamp", "")):
        blockers.append("btc_funding_rate_patch_timestamp_not_utc")
    if funding_time and timestamp and abs((funding_time - timestamp).total_seconds()) > 300:
        blockers.append("btc_funding_rate_patch_timestamp_funding_time_mismatch")
    try:
        value = Decimal(str(row.get("fundingRate", "")))
        if not value.is_finite():
            blockers.append("btc_funding_rate_patch_funding_rate_not_finite")
    except InvalidOperation:
        blockers.append("btc_funding_rate_patch_funding_rate_not_numeric")
    mark_price = str(row.get("markPrice", "")).strip()
    if mark_price:
        try:
            value = Decimal(mark_price)
            if not value.is_finite():
                blockers.append("btc_funding_rate_patch_mark_price_not_finite")
        except InvalidOperation:
            blockers.append("btc_funding_rate_patch_mark_price_not_numeric")
    if not row.get("source_record_id"):
        blockers.append("btc_funding_rate_patch_source_record_id_missing")
    return blockers


def _validate_metadata(metadata: Mapping[str, Any], csv_path: Path, rows: list[dict[str, Any]], *, patch_id: str, bundle_id: str) -> list[str]:
    blockers: list[str] = []
    required = {
        "schema_version": "btc_funding_rate_patch_metadata_v1",
        "patch_id": patch_id,
        "csv_filename": f"{patch_id}.csv",
        "source_base_url": "https://fapi.binance.com",
        "source_endpoint": "/fapi/v1/fundingRate",
        "symbol": "BTCUSDT",
        "api_key_used": False,
        "private_endpoint_used": False,
        "auth_headers_present": False,
        "target_bundle_id": bundle_id,
        "target_file": "funding_rate.csv",
        "merge_key": "fundingTime",
        "merge_policy": "fail_on_duplicate_fundingTime",
    }
    if not metadata:
        return ["btc_funding_rate_patch_metadata_invalid"]
    blockers.extend(_validate_metadata_schema(metadata))
    if metadata.get("source_method") != "manual_offline_public_rest_capture":
        blockers.append("btc_funding_rate_patch_metadata_source_method_invalid")
    for key, expected in required.items():
        if metadata.get(key) != expected:
            blockers.append(f"btc_funding_rate_patch_metadata_{key}_invalid")
    expected_values = {
        "requested_start": EXPECTED_REQUESTED_START,
        "requested_end": EXPECTED_REQUESTED_END,
        "startTime": EXPECTED_START_MS,
        "endTime": EXPECTED_END_MS,
        "expected_row_count": EXPECTED_ROW_COUNT,
        "expected_first_fundingTime": EXPECTED_START_MS,
        "expected_last_fundingTime": EXPECTED_END_MS,
        "funding_interval_hours": 8,
    }
    for key, expected in expected_values.items():
        if metadata.get(key) != expected:
            blockers.append(f"btc_funding_rate_patch_metadata_{key}_invalid")
    if metadata.get("csv_sha256") != (_sha256(csv_path) if csv_path.exists() else None):
        blockers.append("btc_funding_rate_patch_sha256_mismatch")
    if metadata.get("sha256"):
        blockers.append("btc_funding_rate_patch_metadata_legacy_sha256_key_invalid")
    if int(metadata.get("record_count", -1) or -1) != len(rows):
        blockers.append("btc_funding_rate_patch_record_count_mismatch")
    if not metadata.get("captured_at"):
        blockers.append("btc_funding_rate_patch_captured_at_missing")
    if not metadata.get("operator_note"):
        blockers.append("btc_funding_rate_patch_operator_note_missing")
    if metadata.get("blockers"):
        blockers.append("btc_funding_rate_patch_metadata_has_blockers")
    return blockers


def _validate_metadata_schema(metadata: Mapping[str, Any]) -> list[str]:
    if not SCHEMA_PATH.exists():
        return ["btc_funding_rate_patch_metadata_schema_missing"]
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(dict(metadata), schema)
    except jsonschema.ValidationError as exc:
        path = ".".join(str(value) for value in exc.absolute_path) or "root"
        return [f"btc_funding_rate_patch_metadata_schema_invalid:{path}"]
    return []


def _safe_bundle_dir(bundle_root: Path, bundle_id: str) -> Path:
    if not bundle_id or "/" in bundle_id or ".." in bundle_id:
        raise ValueError("bundle_id must be a simple path segment")
    path = bundle_root / bundle_id
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _expected_funding_times_from_gap_report() -> list[datetime]:
    path = Path("artifacts/btc_data_status/latest/btc_funding_rate_gap_report.json")
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    values = payload.get("expected_missing_funding_time_ms")
    if not isinstance(values, list) or not values:
        return []
    out: list[datetime] = []
    for value in values:
        parsed = _parse_ms(value)
        if parsed is None:
            return []
        out.append(parsed)
    return out


def _default_expected_funding_times() -> list[datetime]:
    out: list[datetime] = []
    for value in range(EXPECTED_START_MS, EXPECTED_END_MS + 1, EXPECTED_INTERVAL_MS):
        parsed = _parse_ms(value)
        if parsed is not None:
            out.append(parsed)
    return out


def _times_match_expected_with_tolerance(times: list[datetime], expected_times: list[datetime]) -> bool:
    if len(times) != len(expected_times):
        return False
    ordered = sorted(times)
    for actual, expected in zip(ordered, expected_times):
        if _ms_abs_delta(actual, expected) > EXPECTED_TIME_TOLERANCE_MS:
            return False
    return True


def _ms_abs_delta(left: datetime, right: datetime) -> int:
    return abs(int((left - right).total_seconds() * 1000))


def _parse_ms(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)) / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _parse_time(value: object) -> datetime | None:
    if value in {None, ""}:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


if __name__ == "__main__":
    main()
