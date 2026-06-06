#!/usr/bin/env python3
"""Atomically merge a validated manual BTC funding-rate patch."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from validate_btc_funding_rate_patch import (
        DEFAULT_BUNDLE_ID,
        DEFAULT_BUNDLE_ROOT,
        DEFAULT_PATCH_ID,
        REQUIRED_COLUMNS,
        validate_btc_funding_rate_patch,
    )
except ModuleNotFoundError:  # pragma: no cover - imported as scripts.*
    from scripts.validate_btc_funding_rate_patch import (
        DEFAULT_BUNDLE_ID,
        DEFAULT_BUNDLE_ROOT,
        DEFAULT_PATCH_ID,
        REQUIRED_COLUMNS,
        validate_btc_funding_rate_patch,
    )


def merge_btc_funding_rate_patch(
    *,
    bundle_id: str = DEFAULT_BUNDLE_ID,
    patch_id: str = DEFAULT_PATCH_ID,
    bundle_root: Path = DEFAULT_BUNDLE_ROOT,
    dry_run: bool = False,
) -> dict[str, Any]:
    bundle_dir = bundle_root / bundle_id
    funding_path = bundle_dir / "funding_rate.csv"
    patch_path = bundle_dir / "patches" / f"{patch_id}.csv"
    validation = validate_btc_funding_rate_patch(bundle_id=bundle_id, patch_id=patch_id, bundle_root=bundle_root)
    blockers = list(validation["blockers"])
    existing = _read_rows(funding_path)
    patch_rows = _read_rows(patch_path)
    existing_time_values = [row.get("fundingTime", "") for row in existing]
    patch_time_values = [row.get("fundingTime", "") for row in patch_rows]
    if len(existing_time_values) != len(set(existing_time_values)):
        blockers.append("btc_funding_rate_existing_duplicate_funding_time")
    if existing_time_values != sorted(existing_time_values, key=lambda value: int(value or 0)):
        blockers.append("btc_funding_rate_existing_non_monotonic")
    if len(patch_time_values) != len(set(patch_time_values)):
        blockers.append("btc_funding_rate_patch_duplicate_funding_time")
    existing_times = set(existing_time_values)
    patch_times = [row["fundingTime"] for row in patch_rows]
    overlaps = sorted(existing_times.intersection(patch_times))
    if overlaps:
        blockers.append("btc_funding_rate_patch_overlaps_existing_funding_time")
    merged_by_time = {row["fundingTime"]: row for row in existing}
    for row in patch_rows:
        merged_by_time[row["fundingTime"]] = row
    merged = [merged_by_time[key] for key in sorted(merged_by_time, key=lambda value: int(value))]
    if len(merged) != len(existing) + len(patch_rows) and not overlaps:
        blockers.append("btc_funding_rate_merge_count_mismatch")
    if len({row["fundingTime"] for row in merged}) != len(merged):
        blockers.append("btc_funding_rate_merged_duplicate_funding_time")
    if [row["fundingTime"] for row in merged] != sorted((row["fundingTime"] for row in merged), key=lambda value: int(value)):
        blockers.append("btc_funding_rate_merged_non_monotonic")
    merge_ready = bool(validation["validation_pass"] and not overlaps and not blockers)
    backup_path = funding_path.with_suffix(".csv.bak")
    post_write_verified = False
    if merge_ready and not dry_run:
        shutil.copy2(funding_path, backup_path)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=funding_path.parent, prefix=".funding_rate.", suffix=".tmp", delete=False) as handle:
                temp_path = Path(handle.name)
                writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
                writer.writeheader()
                writer.writerows(merged)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, funding_path)
            _fsync_dir(funding_path.parent)
            post_write_rows = _read_rows(funding_path)
            post_write_verified = (
                len(post_write_rows) == len(merged)
                and [row["fundingTime"] for row in post_write_rows] == [row["fundingTime"] for row in merged]
                and len({row["fundingTime"] for row in post_write_rows}) == len(post_write_rows)
            )
            if not post_write_verified:
                blockers.append("btc_funding_rate_post_merge_verification_failed")
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()
    report = {
        "schema_version": "btc_funding_rate_patch_merge_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bundle_id": bundle_id,
        "patch_id": patch_id,
        "dry_run": dry_run,
        "records_before": len(existing),
        "patch_record_count": len(patch_rows),
        "records_after": len(merged) if merge_ready else len(existing),
        "rows_added": len(patch_rows) if merge_ready else 0,
        "overlap_count": len(overlaps),
        "merge_ready": merge_ready,
        "merge_success": merge_ready and not dry_run and post_write_verified,
        "backup_path": str(backup_path) if merge_ready and not dry_run else None,
        "post_write_verified": post_write_verified,
        "blockers": _dedupe(blockers),
    }
    output = bundle_dir / "funding_rate_patch_merge_report.json"
    _atomic_write_json(output, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--bundle-root", default=str(DEFAULT_BUNDLE_ROOT))
    parser.add_argument("--patch-id", default=DEFAULT_PATCH_ID)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(merge_btc_funding_rate_patch(bundle_id=args.bundle_id, patch_id=args.patch_id, bundle_root=Path(args.bundle_root), dry_run=args.dry_run), indent=2, sort_keys=True))


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


if __name__ == "__main__":
    main()
