#!/usr/bin/env python3
"""Try to repair missing BTCUSDT fundingRate coverage from public Binance Vision archives."""

from __future__ import annotations

import argparse
import csv
import io
import json
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


BASE = "https://data.binance.vision/data/futures/um"
DEFAULT_BUNDLE_ROOT = Path("data/external/btc_perpetual/binance_usdm/bundles")
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_data_status/latest")
SYMBOL = "BTCUSDT"


def repair_funding_rate_coverage(
    *,
    bundle_id: str,
    start: datetime,
    end: datetime,
    bundle_root: Path = DEFAULT_BUNDLE_ROOT,
    sleep_seconds: float = 0.02,
) -> dict[str, Any]:
    bundle_dir = _safe_bundle_dir(bundle_root, bundle_id)
    raw_dir = bundle_dir / "raw_archives"
    raw_dir.mkdir(parents=True, exist_ok=True)
    funding_path = bundle_dir / "funding_rate.csv"
    existing = _read_existing_funding(funding_path)
    mark_by_time = _read_mark_prices(bundle_dir / "mark_price_klines_1h.csv")
    downloaded, endpoints, errors, attempted = _download_missing_rows(
        start=start,
        end=end,
        raw_dir=raw_dir,
        sleep_seconds=sleep_seconds,
    )
    before_count = len(existing)
    combined = {int(row["fundingTime"]): row for row in existing}
    for row in downloaded:
        funding_time = int(row["calc_time"])
        combined[funding_time] = {
            "timestamp": _iso_from_ms(funding_time),
            "fundingTime": str(funding_time),
            "symbol": SYMBOL,
            "fundingRate": row.get("last_funding_rate", ""),
            "markPrice": row.get("markPrice") or mark_by_time.get(funding_time, ""),
            "source_record_id": f"funding_rate_archive_repair:{funding_time}",
        }
    repaired = [combined[key] for key in sorted(combined)]
    if len(repaired) > before_count:
        _write_funding_csv(funding_path, repaired)
    coverage_start = repaired[0]["timestamp"] if repaired else None
    coverage_end = repaired[-1]["timestamp"] if repaired else None
    full_coverage = _coverage_aligned(repaired, start, end)
    blockers: list[str] = []
    if len(repaired) == before_count:
        blockers.append("btc_funding_rate_no_archive_rows_added")
    if not full_coverage:
        blockers.append("btc_funding_rate_sample_range_not_aligned_after_repair")
    if errors:
        blockers.append("btc_funding_rate_archive_repair_errors")
    audit = {
        "bundle_id": bundle_id,
        "bundle_path": str(bundle_dir),
        "repair_mode": "binance_vision_public_archive",
        "api_key_used": False,
        "private_endpoint_used": False,
        "previous_record_count": before_count,
        "new_record_count": len(repaired),
        "records_added": len(repaired) - before_count,
        "requested_start": _iso(start),
        "requested_end": _iso(end),
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "full_sample_coverage": bool(full_coverage),
        "endpoints_used": sorted(set(endpoints)),
        "errors": errors,
        "attempted_sources": attempted,
        "rows_added": len(repaired) - before_count,
        "repair_success": bool(len(repaired) > before_count and full_coverage),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "blockers": blockers,
    }
    (bundle_dir / "funding_rate_repair_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    _write_archive_repair_report(audit, DEFAULT_OUTPUT_ROOT)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--repair-start", required=True)
    parser.add_argument("--repair-end", required=True)
    parser.add_argument("--bundle-root", default=str(DEFAULT_BUNDLE_ROOT))
    parser.add_argument("--sleep-seconds", type=float, default=0.02)
    args = parser.parse_args()
    payload = repair_funding_rate_coverage(
        bundle_id=args.bundle_id,
        start=_parse_dt(args.repair_start),
        end=_parse_dt(args.repair_end),
        bundle_root=Path(args.bundle_root),
        sleep_seconds=args.sleep_seconds,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


def _download_missing_rows(
    *,
    start: datetime,
    end: datetime,
    raw_dir: Path,
    sleep_seconds: float,
) -> tuple[list[dict[str, str]], list[str], list[dict[str, str]], list[dict[str, Any]]]:
    rows: list[dict[str, str]] = []
    endpoints: list[str] = []
    errors: list[dict[str, str]] = []
    attempted: list[dict[str, Any]] = []
    monthly_url = f"{BASE}/monthly/fundingRate/{SYMBOL}/{SYMBOL}-fundingRate-{start.year:04d}-{start.month:02d}.zip"
    try:
        downloaded = _read_archive_csv(monthly_url, raw_dir)
        rows.extend(downloaded)
        endpoints.append(monthly_url)
        attempted.append(_attempt("monthly", monthly_url, f"{start.year:04d}-{start.month:02d}", 200, len(downloaded), None))
        time.sleep(sleep_seconds)
    except (HTTPError, URLError) as exc:
        error = _error(monthly_url, exc)
        errors.append(error)
        attempted.append(_attempt("monthly", monthly_url, f"{start.year:04d}-{start.month:02d}", _status_code(exc), 0, error))
    day = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    while day <= end:
        url = f"{BASE}/daily/fundingRate/{SYMBOL}/{SYMBOL}-fundingRate-{day:%Y-%m-%d}.zip"
        try:
            downloaded = _read_archive_csv(url, raw_dir)
            rows.extend(downloaded)
            endpoints.append(url)
            attempted.append(_attempt("daily", url, day.strftime("%Y-%m-%d"), 200, len(downloaded), None))
            time.sleep(sleep_seconds)
        except (HTTPError, URLError) as exc:
            error = _error(url, exc)
            errors.append(error)
            attempted.append(_attempt("daily", url, day.strftime("%Y-%m-%d"), _status_code(exc), 0, error))
        day += timedelta(days=1)
    filtered = [row for row in rows if start.timestamp() * 1000 <= int(row["calc_time"]) <= end.timestamp() * 1000]
    deduped = {int(row["calc_time"]): row for row in filtered}
    return [deduped[key] for key in sorted(deduped)], endpoints, errors, attempted


def _read_archive_csv(url: str, raw_dir: Path) -> list[dict[str, str]]:
    target = raw_dir / url.rsplit("/", 1)[-1]
    if not target.exists():
        with urlopen(url, timeout=30) as response:
            target.write_bytes(response.read())
    with zipfile.ZipFile(target) as archive:
        data = archive.read(archive.namelist()[0]).decode("utf-8")
    return list(csv.DictReader(io.StringIO(data)))


def _read_existing_funding(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_mark_prices(path: Path) -> dict[int, str]:
    if not path.exists():
        return {}
    out: dict[int, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                out[int(row.get("open_time_ms", ""))] = row.get("close", "")
            except ValueError:
                continue
    return out


def _write_funding_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp", "fundingTime", "symbol", "fundingRate", "markPrice", "source_record_id"],
        )
        writer.writeheader()
        writer.writerows(rows)


def _coverage_aligned(rows: list[dict[str, str]], start: datetime, end: datetime) -> bool:
    if not rows:
        return False
    first = _parse_ms(rows[0].get("fundingTime"))
    last = _parse_ms(rows[-1].get("fundingTime"))
    if first is None or last is None:
        return False
    return first <= start and last.timestamp() * 1000 + 8 * 3600 * 1000 >= end.timestamp() * 1000


def _safe_bundle_dir(bundle_root: Path, bundle_id: str) -> Path:
    if not bundle_id or "/" in bundle_id or ".." in bundle_id:
        raise ValueError("bundle_id must be a simple path segment")
    expected = DEFAULT_BUNDLE_ROOT.resolve()
    if bundle_root.resolve() != expected:
        raise ValueError(f"bundle root must be {expected}")
    path = bundle_root / bundle_id
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _error(url: str, exc: BaseException) -> dict[str, str]:
    payload = {"url": url, "error": str(exc)}
    if isinstance(exc, HTTPError):
        payload["http_status"] = str(exc.code)
    return payload


def _status_code(exc: BaseException) -> int | None:
    if isinstance(exc, HTTPError):
        return int(exc.code)
    return None


def _error_type(exc: BaseException) -> str:
    if isinstance(exc, HTTPError):
        if exc.code == 404:
            return "not_found"
        if exc.code == 451:
            return "http_451"
        return "unknown_http_error"
    if isinstance(exc, URLError):
        return "network_blocked"
    return "unknown"


def _attempt(
    mode: str,
    url: str,
    date_or_month: str,
    status_code: int | None,
    rows: int,
    error: dict[str, str] | None,
) -> dict[str, Any]:
    error_type = "none"
    if error:
        if str(error.get("http_status")) == "404":
            error_type = "not_found"
        elif str(error.get("http_status")) == "451":
            error_type = "http_451"
        else:
            error_type = "network_blocked" if "urlopen" in str(error.get("error", "")).lower() else "unknown"
    return {
        "mode": mode,
        "url": url,
        "status_code": status_code,
        "role": "funding_rate",
        "date_or_month": date_or_month,
        "rows": rows,
        "error_type": error_type,
    }


def _write_archive_repair_report(audit: dict[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "btc_funding_rate_archive_repair_report_v1",
        "generated_at": audit["generated_at"],
        "bundle_id": audit["bundle_id"],
        "repair_mode": audit["repair_mode"],
        "attempted_sources": audit.get("attempted_sources", []),
        "rows_added": audit.get("records_added", 0),
        "repair_success": bool(audit.get("repair_success", False)),
        "blockers": audit.get("blockers", []),
    }
    output = output_root / "btc_funding_rate_archive_repair_report.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _parse_ms(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)) / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
