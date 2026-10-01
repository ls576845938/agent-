#!/usr/bin/env python3
"""Fetch only public BTCUSDT fundingRate data into a patch file."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


BASE_URL = "https://fapi.binance.com"
ENDPOINT = "/fapi/v1/fundingRate"
DEFAULT_BUNDLE_ID = "btc_usdm_binance_btcusdt_20240101_20260512_v1"
DEFAULT_BUNDLE_ROOT = Path("data/external/btc_perpetual/binance_usdm/bundles")
DEFAULT_PATCH_ID = "funding_rate_patch_20260501_20260512"
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_data_status/latest")


def fetch_btc_funding_rate_patch(
    *,
    bundle_id: str = DEFAULT_BUNDLE_ID,
    patch_id: str = DEFAULT_PATCH_ID,
    bundle_root: Path = DEFAULT_BUNDLE_ROOT,
    start: str = "2026-05-01T00:00:00Z",
    end: str = "2026-05-12T00:00:00Z",
    allow_network: bool = False,
    execute: bool = False,
) -> dict[str, object]:
    bundle_dir = _safe_bundle_dir(bundle_root, bundle_id)
    patch_dir = bundle_dir / "patches"
    patch_dir.mkdir(parents=True, exist_ok=True)
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end)
    blockers: list[str] = []
    requests: list[dict[str, object]] = []
    rows: list[dict[str, str]] = []
    attempted = bool(allow_network and execute)
    if not allow_network:
        blockers.append("btc_public_rest_allow_network_missing")
    if not execute:
        blockers.append("btc_public_rest_execute_missing")
    if attempted:
        current = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        while current <= end_ms:
            params = {"symbol": "BTCUSDT", "startTime": current, "endTime": end_ms, "limit": 1000}
            url = f"{BASE_URL}{ENDPOINT}?{urlencode(params)}"
            try:
                with urlopen(url, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                batch = _normalize_rows(payload)
                requests.append({"url": url, "params": params, "captured_at": _now(), "http_status": 200, "row_count": len(batch)})
                rows.extend(batch)
                if not batch:
                    break
                next_time = max(int(row["fundingTime"]) for row in batch) + 1
                if next_time <= current:
                    blockers.append("btc_public_rest_pagination_not_advancing")
                    break
                current = next_time
            except HTTPError as exc:
                requests.append({"url": url, "params": params, "captured_at": _now(), "http_status": exc.code, "row_count": 0})
                blockers.append("btc_public_rest_http_451_geoblocked" if exc.code == 451 else f"btc_public_rest_http_{exc.code}")
                break
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                requests.append({"url": url, "params": params, "captured_at": _now(), "http_status": None, "row_count": 0, "error": str(exc)})
                blockers.append("btc_public_rest_funding_rate_fetch_failed")
                break
    rows = _dedupe_rows(rows, start_dt=start_dt, end_dt=end_dt)
    if attempted and not rows and "btc_public_rest_funding_rate_fetch_failed" not in blockers:
        blockers.append("btc_public_rest_no_rows_added")
    patch_csv = patch_dir / f"{patch_id}.csv"
    metadata_path = patch_dir / f"{patch_id}.metadata.json"
    if rows:
        _write_patch_csv(patch_csv, rows)
        metadata = _metadata(
            bundle_id=bundle_id,
            patch_id=patch_id,
            patch_csv=patch_csv,
            start_dt=start_dt,
            end_dt=end_dt,
            requests=requests,
            record_count=len(rows),
            blockers=[],
        )
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    report = {
        "schema_version": "btc_funding_rate_public_rest_fetch_report_v1",
        "generated_at": _now(),
        "bundle_id": bundle_id,
        "patch_id": patch_id,
        "public_rest_fetch_attempted": attempted,
        "endpoint": ENDPOINT,
        "api_key_used": False,
        "private_endpoint_used": False,
        "rows_added": len(rows),
        "patch_csv": str(patch_csv) if rows else None,
        "metadata_path": str(metadata_path) if rows else None,
        "requests": requests,
        "blockers": _dedupe(blockers),
    }
    DEFAULT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    (DEFAULT_OUTPUT_ROOT / "btc_funding_rate_public_rest_fetch_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--bundle-root", default=str(DEFAULT_BUNDLE_ROOT))
    parser.add_argument("--patch-id", default=DEFAULT_PATCH_ID)
    parser.add_argument("--start", default="2026-05-01T00:00:00Z")
    parser.add_argument("--end", default="2026-05-12T00:00:00Z")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    print(json.dumps(fetch_btc_funding_rate_patch(bundle_id=args.bundle_id, patch_id=args.patch_id, bundle_root=Path(args.bundle_root), start=args.start, end=args.end, allow_network=args.allow_network, execute=args.execute), indent=2, sort_keys=True))


def _normalize_rows(payload: object) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not isinstance(payload, list):
        return rows
    for item in payload:
        if not isinstance(item, dict):
            continue
        funding_time = int(item["fundingTime"])
        rows.append(
            {
                "timestamp": datetime.fromtimestamp(funding_time / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                "fundingTime": str(funding_time),
                "symbol": "BTCUSDT",
                "fundingRate": str(item.get("fundingRate", "")),
                "markPrice": str(item.get("markPrice", "")),
                "source_record_id": f"funding_rate_public_rest:{funding_time}",
            }
        )
    return rows


def _dedupe_rows(rows: list[dict[str, str]], *, start_dt: datetime, end_dt: datetime) -> list[dict[str, str]]:
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    deduped = {
        int(row["fundingTime"]): row
        for row in rows
        if start_ms <= int(row["fundingTime"]) <= end_ms
    }
    return [deduped[key] for key in sorted(deduped)]


def _write_patch_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "fundingTime", "symbol", "fundingRate", "markPrice", "source_record_id"])
        writer.writeheader()
        writer.writerows(rows)


def _metadata(
    *,
    bundle_id: str,
    patch_id: str,
    patch_csv: Path,
    start_dt: datetime,
    end_dt: datetime,
    requests: list[dict[str, object]],
    record_count: int,
    blockers: list[str],
) -> dict[str, object]:
    return {
        "schema_version": "btc_funding_rate_patch_metadata_v1",
        "patch_id": patch_id,
        "csv_filename": patch_csv.name,
        "csv_sha256": _sha256(patch_csv),
        "source_method": "manual_offline_public_rest_capture",
        "source_base_url": BASE_URL,
        "source_endpoint": ENDPOINT,
        "symbol": "BTCUSDT",
        "requested_start": _iso(start_dt),
        "requested_end": _iso(end_dt),
        "startTime": int(start_dt.timestamp() * 1000),
        "endTime": int(end_dt.timestamp() * 1000),
        "captured_at": _now(),
        "operator_note": "Manual public REST capture of /fapi/v1/fundingRate from an accessible environment; no API key, no private endpoint.",
        "api_key_used": False,
        "private_endpoint_used": False,
        "auth_headers_present": False,
        "record_count": record_count,
        "expected_row_count": 34,
        "expected_first_fundingTime": 1777593600000,
        "expected_last_fundingTime": 1778544000000,
        "funding_interval_hours": 8,
        "target_bundle_id": bundle_id,
        "target_file": "funding_rate.csv",
        "merge_key": "fundingTime",
        "merge_policy": "fail_on_duplicate_fundingTime",
        "operator": "codex_public_rest_fetch",
        "created_at": _now(),
        "requests": requests,
        "blockers": blockers,
    }


def _safe_bundle_dir(bundle_root: Path, bundle_id: str) -> Path:
    if not bundle_id or "/" in bundle_id or ".." in bundle_id:
        raise ValueError("bundle_id must be a simple path segment")
    path = bundle_root / bundle_id
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


if __name__ == "__main__":
    main()
