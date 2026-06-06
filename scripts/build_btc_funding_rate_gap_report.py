#!/usr/bin/env python3
"""Build a BTC funding-rate coverage gap report for the selected bundle."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from quant_crypto.data.funding_rate_coverage import funding_rate_coverage_status
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.funding_rate_coverage import funding_rate_coverage_status


DEFAULT_BUNDLE_ID = "btc_usdm_binance_btcusdt_20240101_20260512_v1"
DEFAULT_BUNDLE_ROOT = Path("data/external/btc_perpetual/binance_usdm/bundles")
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_data_status/latest")


def build_btc_funding_rate_gap_report(
    *,
    bundle_id: str = DEFAULT_BUNDLE_ID,
    bundle_root: Path = DEFAULT_BUNDLE_ROOT,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    bundle_dir = root / bundle_root / bundle_id if not bundle_root.is_absolute() else bundle_root / bundle_id
    manifest_path = bundle_dir / "btc_perpetual_bundle_manifest.json"
    manifest = _read_json(manifest_path)
    sample_start = str(manifest.get("sample_start") or "2024-01-01T00:00:00Z")
    sample_end = str(manifest.get("sample_end") or "2026-05-12T00:00:00Z")
    funding_path = bundle_dir / "funding_rate.csv"
    status = funding_rate_coverage_status(funding_path, sample_start=sample_start, sample_end=sample_end)
    return {
        "schema_version": "btc_funding_rate_gap_report_v1",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "bundle_id": bundle_id,
        "symbol": "BTCUSDT",
        "sample_start": sample_start,
        "sample_end": sample_end,
        "funding_rate_path": _relpath(funding_path, root),
        **status,
    }


def write_btc_funding_rate_gap_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_funding_rate_gap_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--bundle-root", default=str(DEFAULT_BUNDLE_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    args = parser.parse_args()
    payload = build_btc_funding_rate_gap_report(bundle_id=args.bundle_id, bundle_root=Path(args.bundle_root))
    print(write_btc_funding_rate_gap_report(payload, Path(args.output_root)))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
