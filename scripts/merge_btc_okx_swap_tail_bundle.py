#!/usr/bin/env python3
"""Merge a short OKX BTC-USDT-SWAP tail bundle into the selected local bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts.build_btc_perpetual_data_bundle_manifest import build_btc_perpetual_data_bundle_manifest, write_manifest
    from scripts.fetch_btc_okx_swap_public_data import (
        DEFAULT_MANUAL_METADATA_IMPORT_REPORT,
        DEFAULT_OUTPUT_ROOT,
        DEFAULT_RAW_CAPTURE_ROOT,
        LICENSE_NOTE,
        SOURCE_PROVIDER,
        SYMBOL,
        _write_manual_metadata_import_report,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from build_btc_perpetual_data_bundle_manifest import build_btc_perpetual_data_bundle_manifest, write_manifest
    from fetch_btc_okx_swap_public_data import (
        DEFAULT_MANUAL_METADATA_IMPORT_REPORT,
        DEFAULT_OUTPUT_ROOT,
        DEFAULT_RAW_CAPTURE_ROOT,
        LICENSE_NOTE,
        SOURCE_PROVIDER,
        SYMBOL,
        _write_manual_metadata_import_report,
    )


DEFAULT_TARGET_BUNDLE_ID = "btc_okx_swap_btcusdt_daily_roll_90d_v1"
DEFAULT_TAIL_BUNDLE_ID = "btc_okx_swap_btcusdt_tail_10d_v1"
DEFAULT_REPORT = Path("artifacts/btc_data_status/latest/btc_okx_tail_bundle_merge_report.json")
CSV_INTERVAL_MS = {
    "klines_5m.csv": 300_000,
    "klines_15m.csv": 900_000,
    "klines_1h.csv": 3_600_000,
    "klines_4h.csv": 14_400_000,
    "klines_1d.csv": 86_400_000,
    "mark_price_klines_1h.csv": 3_600_000,
    "premium_index_klines_1h.csv": 3_600_000,
}
CSV_FILES = [
    "klines_5m.csv",
    "klines_15m.csv",
    "klines_1h.csv",
    "klines_4h.csv",
    "klines_1d.csv",
    "mark_price_klines_1h.csv",
    "premium_index_klines_1h.csv",
    "funding_rate.csv",
    "agg_trades.csv",
    "order_book_depth.csv",
]
JSON_REPLACE_FILES = ["funding_info.json", "exchange_info.json", "open_interest_current.json"]
PIT_FIELDS = ["event_time", "available_time", "ingested_at", "processed_at"]


def merge_okx_tail_bundle(
    *,
    repo_root: Path,
    target_bundle_id: str = DEFAULT_TARGET_BUNDLE_ID,
    tail_bundle_id: str = DEFAULT_TAIL_BUNDLE_ID,
    bundle_root: Path = DEFAULT_OUTPUT_ROOT,
    raw_capture_root: Path = DEFAULT_RAW_CAPTURE_ROOT,
    manual_metadata_import_report: Path = DEFAULT_MANUAL_METADATA_IMPORT_REPORT,
    output_report: Path = DEFAULT_REPORT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    bundle_root_abs = _resolve(root, bundle_root)
    target = _safe_bundle_dir(bundle_root_abs, target_bundle_id)
    tail = _safe_bundle_dir(bundle_root_abs, tail_bundle_id)
    generated = generated_at or _utc_z_now()
    blockers: list[str] = []
    if not target.exists():
        blockers.append("btc_okx_tail_merge_target_bundle_missing")
    if not tail.exists():
        blockers.append("btc_okx_tail_merge_tail_bundle_missing")
    merged_files: list[dict[str, Any]] = []
    replaced_json: list[str] = []
    if not blockers:
        for filename in CSV_FILES:
            target_path = target / filename
            tail_path = tail / filename
            if not target_path.exists() and not tail_path.exists():
                continue
            facts = _merge_csv_file(target_path=target_path, tail_path=tail_path, filename=filename)
            merged_files.append(facts)
        for filename in JSON_REPLACE_FILES:
            source = tail / filename
            dest = target / filename
            if source.exists():
                payload = _with_json_pit_fields(_read_json(source), generated)
                _write_json_atomic(payload, dest)
                replaced_json.append(filename)
        manifest = build_btc_perpetual_data_bundle_manifest(
            bundle_dir=target,
            bundle_id=target_bundle_id,
            source_type="production",
            source_provider=SOURCE_PROVIDER,
            exchange=SOURCE_PROVIDER,
            symbol=SYMBOL,
            market_type="usds_m_perpetual",
            promotion_clean_allowed=True,
            license_note=LICENSE_NOTE,
            created_at=generated,
        )
        write_manifest(manifest, target)
        hard_manifest_blockers = [
            str(item)
            for item in manifest.get("blockers", [])
            if str(item)
            not in {
                "btc_liquidation_snapshots_missing_diagnostic_only",
                "btc_liquidation_snapshot_missing_diagnostic_only",
                "btc_open_interest_history_not_verified_diagnostic_partial",
                "diagnostic_only_not_gate_evidence",
            }
        ]
        blockers.extend(hard_manifest_blockers)
        raw_abs = _resolve(root, raw_capture_root)
        raw_exchange = raw_abs / "exchange_info_raw.json"
        raw_funding = raw_abs / "funding_info_raw.json"
        exchange_status = raw_abs / "exchange_info_http_status.txt"
        funding_status = raw_abs / "funding_info_http_status.txt"
        raw_files_present = all(path.exists() for path in [raw_exchange, raw_funding, exchange_status, funding_status])
        if raw_files_present and not blockers:
            _write_manual_metadata_import_report(
                _resolve(root, manual_metadata_import_report),
                root=root,
                bundle_dir=target,
                raw_exchange=raw_exchange,
                raw_funding=raw_funding,
                exchange_status=exchange_status,
                funding_status=funding_status,
                captured_at=generated,
            )
        else:
            blockers.append("btc_okx_tail_merge_raw_metadata_capture_missing")
    else:
        manifest = {}
        raw_files_present = False

    report = {
        "schema_version": "btc_okx_tail_bundle_merge_report_v1",
        "status": "verified" if not blockers else "rejected",
        "generated_at": generated,
        "target_bundle_id": target_bundle_id,
        "tail_bundle_id": tail_bundle_id,
        "target_bundle_dir": _relpath(target, root),
        "tail_bundle_dir": _relpath(tail, root),
        "merged_files": merged_files,
        "replaced_json_files": replaced_json,
        "manifest_path": _relpath(target / "btc_perpetual_bundle_manifest.json", root),
        "manifest_sample_start": manifest.get("sample_start"),
        "manifest_sample_end": manifest.get("sample_end"),
        "raw_metadata_files_present": raw_files_present,
        "manual_metadata_import_report": _relpath(_resolve(root, manual_metadata_import_report), root),
        "public_rest_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "blockers": _dedupe(blockers),
    }
    _write_json_atomic(report, _resolve(root, output_report))
    return report


def _merge_csv_file(*, target_path: Path, tail_path: Path, filename: str) -> dict[str, Any]:
    target_rows = _read_csv_rows(target_path)
    tail_rows = _read_csv_rows(tail_path)
    by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in [*target_rows, *tail_rows]:
        normalized = _normalize_csv_row(row, filename)
        key = _row_merge_key(normalized, filename)
        if key:
            by_key[key] = normalized
    fieldnames = _fieldnames_for(filename, target_rows, tail_rows)
    rows = [by_key[key] for key in sorted(by_key)]
    _write_csv_atomic(target_path, fieldnames, rows)
    return {
        "path": target_path.name,
        "target_before_rows": len(target_rows),
        "tail_rows": len(tail_rows),
        "merged_rows": len(rows),
        "sample_start": rows[0].get("timestamp") if rows else "",
        "sample_end": rows[-1].get("timestamp") if rows else "",
        "sha256": _sha256(target_path),
    }


def _normalize_csv_row(row: Mapping[str, Any], filename: str) -> dict[str, Any]:
    out = dict(row)
    event_ms = _row_event_ms(out, filename)
    interval_ms = CSV_INTERVAL_MS.get(filename, 0)
    available_ms = event_ms + interval_ms if event_ms is not None and interval_ms else event_ms
    timestamp = _iso_ms(event_ms)
    if timestamp and not out.get("timestamp"):
        out["timestamp"] = timestamp
    pit = _pit_times(event_ms, available_ms=available_ms)
    for field, value in pit.items():
        out[field] = value
    return out


def _row_event_ms(row: Mapping[str, Any], filename: str) -> int | None:
    if filename == "funding_rate.csv":
        return _parse_time_ms(row.get("fundingTime") or row.get("timestamp"))
    if filename in {"agg_trades.csv", "order_book_depth.csv"}:
        return _parse_time_ms(row.get("ts") or row.get("timestamp"))
    return _parse_time_ms(row.get("open_time") or row.get("timestamp"))


def _row_merge_key(row: Mapping[str, Any], filename: str) -> tuple[Any, ...]:
    event_ms = _row_event_ms(row, filename)
    if event_ms is None:
        return ()
    if filename == "order_book_depth.csv":
        return (event_ms, str(row.get("side", "")), str(row.get("level", "")), str(row.get("price", "")))
    if filename == "agg_trades.csv":
        return (event_ms, str(row.get("trade_id") or row.get("source_record_id") or row.get("price", "")), str(row.get("side", "")))
    return (event_ms,)


def _fieldnames_for(filename: str, target_rows: list[dict[str, Any]], tail_rows: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for field in ["timestamp", *PIT_FIELDS]:
        _append_once(seen, field)
    for row in [*(target_rows[:1]), *(tail_rows[:1])]:
        for field in row:
            _append_once(seen, field)
    for fallback in {
        "klines_5m.csv": ["open_time", "symbol", "open", "high", "low", "close", "volume_contracts", "volume_base", "volume_quote", "confirm", "source_record_id"],
        "klines_15m.csv": ["open_time", "symbol", "open", "high", "low", "close", "volume_contracts", "volume_base", "volume_quote", "confirm", "source_record_id"],
        "klines_1h.csv": ["open_time", "symbol", "open", "high", "low", "close", "volume_contracts", "volume_base", "volume_quote", "confirm", "source_record_id"],
        "klines_4h.csv": ["open_time", "symbol", "open", "high", "low", "close", "volume_contracts", "volume_base", "volume_quote", "confirm", "source_record_id"],
        "klines_1d.csv": ["open_time", "symbol", "open", "high", "low", "close", "volume_contracts", "volume_base", "volume_quote", "confirm", "source_record_id"],
        "mark_price_klines_1h.csv": ["open_time", "symbol", "open", "high", "low", "close", "confirm", "source_record_id"],
        "premium_index_klines_1h.csv": ["open_time", "symbol", "mark_close", "index_close", "premium", "premium_rate", "confirm", "source_record_id"],
        "funding_rate.csv": ["fundingTime", "symbol", "fundingRate", "markPrice", "source_record_id", "instId", "realizedRate"],
        "agg_trades.csv": ["ts", "symbol", "trade_id", "price", "size", "side", "source_record_id"],
        "order_book_depth.csv": ["ts", "symbol", "side", "level", "price", "size", "liquidation_orders", "order_count", "source_record_id"],
    }.get(filename, []):
        _append_once(seen, fallback)
    return seen


def _with_json_pit_fields(payload: Mapping[str, Any], generated_at: str) -> dict[str, Any]:
    out = dict(payload)
    captured = str(out.get("captured_at") or generated_at)
    for field in PIT_FIELDS:
        out.setdefault(field, captured)
    return out


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_csv_atomic(path: Path, fieldnames: list[str], rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
        temp_name = handle.name
    Path(temp_name).replace(path)


def _write_json_atomic(payload: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        json.dump(dict(payload), handle, indent=2, sort_keys=True)
        temp_name = handle.name
    Path(temp_name).replace(path)


def _safe_bundle_dir(bundle_root: Path, bundle_id: str) -> Path:
    if not bundle_id or "/" in bundle_id or ".." in bundle_id:
        raise ValueError("bundle_id must be a simple path segment")
    path = bundle_root / bundle_id
    root = bundle_root.resolve()
    resolved = path.resolve()
    if root not in (resolved, *resolved.parents):
        raise ValueError("bundle path escapes bundle root")
    return path


def _pit_times(event_ms: int | None, *, available_ms: int | None) -> dict[str, str]:
    event = _iso_ms(event_ms)
    available = _iso_ms(available_ms if available_ms is not None else event_ms)
    return {
        "event_time": event,
        "available_time": available,
        "ingested_at": available,
        "processed_at": available,
    }


def _parse_time_ms(value: object) -> int | None:
    if value in {None, ""}:
        return None
    text = str(value).strip()
    if text.isdigit():
        number = int(text)
        if number > 10_000_000_000_000:
            return number // 1000
        if number > 10_000_000_000:
            return number
        return number * 1000
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def _iso_ms(value: int | None) -> str:
    if value is None:
        return ""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _append_once(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--target-bundle-id", default=DEFAULT_TARGET_BUNDLE_ID)
    parser.add_argument("--tail-bundle-id", default=DEFAULT_TAIL_BUNDLE_ID)
    parser.add_argument("--bundle-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--raw-capture-root", default=str(DEFAULT_RAW_CAPTURE_ROOT))
    parser.add_argument("--manual-metadata-import-report", default=str(DEFAULT_MANUAL_METADATA_IMPORT_REPORT))
    parser.add_argument("--output-report", default=str(DEFAULT_REPORT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = merge_okx_tail_bundle(
        repo_root=Path(args.repo_root),
        target_bundle_id=args.target_bundle_id,
        tail_bundle_id=args.tail_bundle_id,
        bundle_root=Path(args.bundle_root),
        raw_capture_root=Path(args.raw_capture_root),
        manual_metadata_import_report=Path(args.manual_metadata_import_report),
        output_report=Path(args.output_report),
        generated_at=args.generated_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") != "verified":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
