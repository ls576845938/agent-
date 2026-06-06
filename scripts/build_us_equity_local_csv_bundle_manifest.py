#!/usr/bin/env python3
"""Build or validate a US equity local CSV provider bundle manifest."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.data.lineage.local_csv_provider import (  # noqa: E402
    REQUIRED_LOCAL_CSV_FILES,
    count_csv_records,
    file_sha256,
)


DEFAULT_BUNDLE_ROOT = Path("data/external/us_equity_lineage/bundles")
DEFAULT_FILENAMES = {
    "universe_membership_events": "universe_membership_events.csv",
    "delisted_symbols": "delisted_symbols.csv",
    "corporate_actions": "corporate_actions.csv",
    "symbol_mapping": "symbol_mapping.csv",
    "adjustment_replay": "adjustment_replay.csv",
}


def build_local_csv_bundle_manifest(
    *,
    bundle_root: Path,
    bundle_id: str,
    source_provider: str,
    source_type: str,
    created_at: str | None = None,
    as_of_date: str = "",
    sample_start: str = "",
    sample_end: str = "",
    universe_name: str = "",
    price_data_reference: str = "",
    license_note: str = "",
    promotion_clean_allowed: bool = False,
) -> dict[str, Any]:
    generated = created_at or datetime.now(timezone.utc).isoformat()
    blockers: list[str] = []
    if not bundle_id:
        blockers.append("bundle_id_missing")
    if source_provider not in {"local_csv", "crsp", "sharadar", "polygon", "norgate", "other"}:
        blockers.append("source_provider_missing")
    if source_type not in {"fixture", "sample", "production"}:
        blockers.append("source_type_missing_or_invalid")
    if source_type == "fixture":
        blockers.append("fixture_source_not_promotion_ready")
    elif source_type == "sample":
        blockers.append("sample_source_not_promotion_ready")
    elif source_type == "production" and not promotion_clean_allowed:
        blockers.append("promotion_clean_not_allowed")
    if not sample_start:
        blockers.append("sample_start_missing")
    if not sample_end:
        blockers.append("sample_end_missing")
    if not license_note:
        blockers.append("license_note_missing")

    files: dict[str, dict[str, Any]] = {}
    for key in REQUIRED_LOCAL_CSV_FILES:
        filename = DEFAULT_FILENAMES[key]
        path = bundle_root / filename
        if not path.exists():
            blockers.append(f"local_csv_{key}_file_missing")
            files[key] = {"path": filename, "sha256": "", "record_count": 0}
            continue
        files[key] = {
            "path": filename,
            "sha256": file_sha256(path),
            "record_count": count_csv_records(path),
        }

    return {
        "schema_version": "us_equity_local_csv_provider_bundle_manifest_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=REPO_ROOT),
        "branch": _git(["branch", "--show-current"], cwd=REPO_ROOT),
        "bundle_id": bundle_id,
        "source_provider": source_provider,
        "source_type": source_type,
        "created_at": generated,
        "as_of_date": as_of_date,
        "sample_start": sample_start,
        "sample_end": sample_end,
        "universe_name": universe_name,
        "price_data_reference": price_data_reference,
        "license_note": license_note,
        "promotion_clean_allowed": promotion_clean_allowed,
        "files": files,
        "blockers": _dedupe(blockers),
    }


def write_local_csv_bundle_manifest(payload: Mapping[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--source-provider", default="local_csv")
    parser.add_argument("--source-type", default="sample")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--sample-start", default="")
    parser.add_argument("--sample-end", default="")
    parser.add_argument("--universe-name", default="")
    parser.add_argument("--price-data-reference", default="")
    parser.add_argument("--license-note", default="")
    parser.add_argument("--promotion-clean-allowed", action="store_true")
    parser.add_argument("--output", default="")
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()

    bundle_root = Path(args.bundle_root)
    payload = build_local_csv_bundle_manifest(
        bundle_root=bundle_root,
        bundle_id=args.bundle_id,
        source_provider=args.source_provider,
        source_type=args.source_type,
        created_at=args.generated_at or None,
        as_of_date=args.as_of_date,
        sample_start=args.sample_start,
        sample_end=args.sample_end,
        universe_name=args.universe_name,
        price_data_reference=args.price_data_reference,
        license_note=args.license_note,
        promotion_clean_allowed=bool(args.promotion_clean_allowed),
    )
    output = Path(args.output) if args.output else bundle_root / "provider_bundle_manifest.json"
    print(write_local_csv_bundle_manifest(payload, output))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
