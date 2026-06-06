#!/usr/bin/env python3
"""Import Binance Vision public USD-M BTCUSDT archive files into a local bundle."""

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
SYMBOL = "BTCUSDT"


def import_archives(
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
    files: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    endpoint_urls: list[str] = []
    mark_1h_by_time: dict[int, str] = {}
    for data_type, output_prefix, intervals in (
        ("klines", "klines", ("1h", "4h", "1d")),
        ("markPriceKlines", "mark_price_klines", ("1h",)),
        ("premiumIndexKlines", "premium_index_klines", ("1h",)),
    ):
        for interval in intervals:
            rows, urls, errs = _download_kline_rows(
                data_type=data_type,
                interval=interval,
                start=start,
                end=end,
                raw_dir=raw_dir,
                sleep_seconds=sleep_seconds,
            )
            endpoint_urls.extend(urls)
            errors.extend(errs)
            output = bundle_dir / f"{output_prefix}_{interval}.csv"
            _write_kline_csv(output, f"{output_prefix}_{interval}", rows)
            files.append({"path": output.name, "role": f"{output_prefix}_{interval}", "record_count": len(rows)})
            if data_type == "markPriceKlines" and interval == "1h":
                mark_1h_by_time = {int(row["open_time"]): row["close"] for row in rows}
    funding_rows, funding_urls, funding_errors = _download_funding_rows(start=start, end=end, raw_dir=raw_dir, sleep_seconds=sleep_seconds)
    endpoint_urls.extend(funding_urls)
    errors.extend(funding_errors)
    funding_output = bundle_dir / "funding_rate.csv"
    _write_funding_csv(funding_output, funding_rows, mark_1h_by_time)
    files.append({"path": funding_output.name, "role": "funding_rate", "record_count": len(funding_rows)})
    audit = {
        "bundle_id": bundle_id,
        "bundle_path": str(bundle_dir),
        "landing_mode": "local_archive_import",
        "public_archive_import_executed": True,
        "public_rest_fetch_executed": False,
        "api_key_used": False,
        "private_endpoint_used": False,
        "source_base": BASE,
        "sample_start": _iso(start),
        "sample_end": _iso(end),
        "files": files,
        "endpoints_used": sorted(set(endpoint_urls)),
        "errors": errors,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "blockers": _archive_blockers(files, errors),
    }
    (bundle_dir / "local_archive_import_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--sample-start", required=True)
    parser.add_argument("--sample-end", required=True)
    parser.add_argument("--bundle-root", default=str(DEFAULT_BUNDLE_ROOT))
    parser.add_argument("--sleep-seconds", type=float, default=0.02)
    args = parser.parse_args()
    payload = import_archives(
        bundle_id=args.bundle_id,
        start=_parse_dt(args.sample_start),
        end=_parse_dt(args.sample_end),
        bundle_root=Path(args.bundle_root),
        sleep_seconds=args.sleep_seconds,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


def _download_kline_rows(
    *,
    data_type: str,
    interval: str,
    start: datetime,
    end: datetime,
    raw_dir: Path,
    sleep_seconds: float,
) -> tuple[list[dict[str, str]], list[str], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    urls: list[str] = []
    errors: list[dict[str, str]] = []
    for year, month in _months(start, end):
        url = f"{BASE}/monthly/{data_type}/{SYMBOL}/{interval}/{SYMBOL}-{interval}-{year:04d}-{month:02d}.zip"
        try:
            rows.extend(_read_archive_csv(url, raw_dir))
            urls.append(url)
            time.sleep(sleep_seconds)
        except HTTPError as exc:
            errors.append({"url": url, "error": f"HTTP {exc.code}"})
    current_month = datetime(end.year, end.month, 1, tzinfo=timezone.utc)
    if start <= end and end >= current_month:
        day = current_month
        while day <= end:
            if day >= start:
                url = f"{BASE}/daily/{data_type}/{SYMBOL}/{interval}/{SYMBOL}-{interval}-{day:%Y-%m-%d}.zip"
                try:
                    rows.extend(_read_archive_csv(url, raw_dir))
                    urls.append(url)
                    time.sleep(sleep_seconds)
                except HTTPError as exc:
                    errors.append({"url": url, "error": f"HTTP {exc.code}"})
            day += timedelta(days=1)
    filtered = [row for row in rows if start.timestamp() * 1000 <= int(row["open_time"]) <= end.timestamp() * 1000]
    filtered.sort(key=lambda row: int(row["open_time"]))
    deduped = {int(row["open_time"]): row for row in filtered}
    return [deduped[key] for key in sorted(deduped)], urls, errors


def _download_funding_rows(
    *,
    start: datetime,
    end: datetime,
    raw_dir: Path,
    sleep_seconds: float,
) -> tuple[list[dict[str, str]], list[str], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    urls: list[str] = []
    errors: list[dict[str, str]] = []
    for year, month in _months(start, end):
        url = f"{BASE}/monthly/fundingRate/{SYMBOL}/{SYMBOL}-fundingRate-{year:04d}-{month:02d}.zip"
        try:
            rows.extend(_read_archive_csv(url, raw_dir))
            urls.append(url)
            time.sleep(sleep_seconds)
        except HTTPError as exc:
            errors.append({"url": url, "error": f"HTTP {exc.code}"})
    filtered = [row for row in rows if start.timestamp() * 1000 <= int(row["calc_time"]) <= end.timestamp() * 1000]
    filtered.sort(key=lambda row: int(row["calc_time"]))
    deduped = {int(row["calc_time"]): row for row in filtered}
    return [deduped[key] for key in sorted(deduped)], urls, errors


def _read_archive_csv(url: str, raw_dir: Path) -> list[dict[str, str]]:
    target = raw_dir / url.rsplit("/", 1)[-1]
    if not target.exists():
        with urlopen(url, timeout=30) as response:
            target.write_bytes(response.read())
    with zipfile.ZipFile(target) as archive:
        name = archive.namelist()[0]
        data = archive.read(name).decode("utf-8")
    return list(csv.DictReader(io.StringIO(data)))


def _write_kline_csv(path: Path, role: str, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "timestamp",
                "open_time_ms",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time_ms",
                "source_record_id",
            ],
        )
        writer.writeheader()
        for row in rows:
            open_time = int(row["open_time"])
            writer.writerow(
                {
                    "timestamp": _iso_from_ms(open_time),
                    "open_time_ms": open_time,
                    "open": row.get("open", ""),
                    "high": row.get("high", ""),
                    "low": row.get("low", ""),
                    "close": row.get("close", ""),
                    "volume": row.get("volume", ""),
                    "close_time_ms": row.get("close_time", ""),
                    "source_record_id": f"{role}:{open_time}",
                }
            )


def _write_funding_csv(path: Path, rows: list[dict[str, str]], mark_by_time: dict[int, str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp", "fundingTime", "symbol", "fundingRate", "markPrice", "source_record_id"],
        )
        writer.writeheader()
        for row in rows:
            funding_time = int(row["calc_time"])
            writer.writerow(
                {
                    "timestamp": _iso_from_ms(funding_time),
                    "fundingTime": funding_time,
                    "symbol": SYMBOL,
                    "fundingRate": row.get("last_funding_rate", ""),
                    "markPrice": mark_by_time.get(funding_time, ""),
                    "source_record_id": f"funding_rate_archive:{funding_time}",
                }
            )


def _months(start: datetime, end: datetime) -> list[tuple[int, int]]:
    out = []
    cursor = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
    while cursor <= end:
        out.append((cursor.year, cursor.month))
        if cursor.month == 12:
            cursor = datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            cursor = datetime(cursor.year, cursor.month + 1, 1, tzinfo=timezone.utc)
    if out and out[-1] == (end.year, end.month):
        # Current month is imported from daily archives where available.
        return out[:-1]
    return out


def _archive_blockers(files: list[dict[str, Any]], errors: list[dict[str, str]]) -> list[str]:
    blockers = []
    roles = {str(item["role"]) for item in files if int(item.get("record_count", 0) or 0) > 0}
    for role in (
        "klines_1h",
        "klines_4h",
        "klines_1d",
        "mark_price_klines_1h",
        "premium_index_klines_1h",
        "funding_rate",
    ):
        if role not in roles:
            blockers.append(f"btc_archive_{role}_missing")
    blockers.append("btc_archive_funding_info_missing_requires_public_rest_or_manual_file")
    blockers.append("btc_archive_exchange_info_missing_requires_public_rest_or_manual_file")
    if errors:
        blockers.append("btc_archive_partial_download_errors")
    return blockers


def _safe_bundle_dir(bundle_root: Path, bundle_id: str) -> Path:
    if not bundle_id or "/" in bundle_id or ".." in bundle_id:
        raise ValueError("bundle_id must be a simple path segment")
    expected = DEFAULT_BUNDLE_ROOT.resolve()
    actual_root = bundle_root.resolve()
    if actual_root != expected:
        raise ValueError(f"bundle root must be {expected}")
    path = bundle_root / bundle_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
