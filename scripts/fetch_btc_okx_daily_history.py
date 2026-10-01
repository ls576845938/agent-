#!/usr/bin/env python3
"""Capture long BTC daily candles from OKX public REST for trend v0 research."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from quant_crypto.data.okx_swap_public import OkxSwapPublicCollector
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.okx_swap_public import OkxSwapPublicCollector


SCHEMA_VERSION = "btc_okx_daily_history_capture_report_v1"
DEFAULT_BUNDLE_ID = "btc_okx_spot_btcusdt_daily_5y_v1"
DEFAULT_OUTPUT_ROOT = Path("data/external/btc_spot/okx/bundles")
DEFAULT_CAPTURE_REPORT = Path("artifacts/btc_trend_v0/latest/btc_okx_daily_history_capture_report.json")
SYMBOL = "BTCUSDT"
VENUE_SYMBOL = "BTC-USDT"
DAY_MS = 86_400_000
DEFAULT_REQUEST_RETRY_COUNT = 2
DEFAULT_REQUEST_RETRY_BACKOFF_SECONDS = 2.0


def capture_btc_okx_daily_history(
    *,
    repo_root: Path,
    bundle_id: str = DEFAULT_BUNDLE_ID,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    capture_report: Path = DEFAULT_CAPTURE_REPORT,
    execute_network: bool = False,
    history_days: int = 1825,
    request_sleep_seconds: float = 0.12,
    request_retry_count: int = DEFAULT_REQUEST_RETRY_COUNT,
    request_retry_backoff_seconds: float = DEFAULT_REQUEST_RETRY_BACKOFF_SECONDS,
    captured_at: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    captured = captured_at or _utc_z_now()
    output_abs = _resolve(root, output_root)
    capture_report_abs = _resolve(root, capture_report)
    effective_history_days = max(1, int(history_days))
    effective_sleep = max(0.0, float(request_sleep_seconds))
    effective_retry_count = max(0, int(request_retry_count))
    effective_retry_backoff = max(0.0, float(request_retry_backoff_seconds))
    request_attempts: list[dict[str, Any]] = []

    collector = OkxSwapPublicCollector(
        output_root=output_abs,
        dry_run=not execute_network,
        allow_network=execute_network,
    )
    if not execute_network:
        planned = collector.request_by_name(
            "candles",
            {"instId": VENUE_SYMBOL, "bar": "1Dutc", "limit": "100"},
        )
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "dry_run",
            "generated_at": captured,
            "bundle_id": bundle_id,
            "history_days": effective_history_days,
            "network_called": False,
            "public_rest_only": True,
            "api_key_used": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "planned_requests": [planned],
            "request_retry_count": effective_retry_count,
            "request_retry_backoff_seconds": effective_retry_backoff,
            "blockers": [],
        }
        _write_json_atomic(payload, capture_report_abs)
        return payload

    blockers: list[str] = []
    bundle_dir = collector.bundle_path(bundle_id, create=True)
    target_start_ms = int(time.time() * 1000) - effective_history_days * DAY_MS
    try:
        raw_rows = _fetch_paginated_okx_rows(
            collector,
            "candles",
            {"instId": VENUE_SYMBOL, "bar": "1Dutc", "limit": "100"},
            timestamp_getter=_row_time_ms,
            target_start_ms=target_start_ms,
            sleep_seconds=effective_sleep,
            retry_count=effective_retry_count,
            retry_backoff_seconds=effective_retry_backoff,
            request_attempts=request_attempts,
            max_pages=max(5, int(math.ceil(effective_history_days / 90)) + 10),
        )
        daily_rows = _select_daily_rows(raw_rows, target_start_ms)
        _write_market_candles(bundle_dir / "klines_1d.csv", daily_rows)
        manifest = _daily_manifest(
            bundle_dir=bundle_dir,
            root=root,
            bundle_id=bundle_id,
            rows=daily_rows,
            captured_at=captured,
            requested_history_days=effective_history_days,
        )
        _write_json_atomic(manifest, bundle_dir / "daily_history_manifest.json")
        if len(daily_rows) < 365:
            blockers.append("btc_okx_daily_history_less_than_365_rows")
        if len(daily_rows) < 220:
            blockers.append("btc_okx_daily_history_less_than_ma120_200_minimum")
    except Exception as exc:  # noqa: BLE001 - persisted as evidence.
        daily_rows = []
        manifest = {}
        blockers.append("btc_okx_daily_history_capture_exception")
        error = repr(exc)
    else:
        error = ""

    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "verified" if not blockers else "rejected",
        "generated_at": captured,
        "bundle_id": bundle_id,
        "history_days": effective_history_days,
        "source_provider": "okx_spot",
        "market_type": "spot",
        "symbol": SYMBOL,
        "venue_symbol": VENUE_SYMBOL,
        "bar": "1Dutc",
        "bundle_dir": _relpath(bundle_dir, root),
        "manifest_path": _relpath(bundle_dir / "daily_history_manifest.json", root),
        "klines_1d": _file_facts(bundle_dir / "klines_1d.csv", root) if (bundle_dir / "klines_1d.csv").exists() else {},
        "daily_rows": len(daily_rows),
        "sample_start": _iso_ms(_row_time_ms(daily_rows[0])) if daily_rows else "",
        "sample_end": _iso_ms(_row_time_ms(daily_rows[-1])) if daily_rows else "",
        "network_called": True,
        "public_rest_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "config_updated": False,
        "request_retry_count": effective_retry_count,
        "request_retry_backoff_seconds": effective_retry_backoff,
        "request_attempt_count": len(request_attempts),
        "request_attempts": request_attempts,
        "formal_trend_minimum_ready": len(daily_rows) >= 365,
        "manifest": manifest,
        "error": error,
        "blockers": _dedupe(blockers),
    }
    _write_json_atomic(report, capture_report_abs)
    return report


def _fetch_paginated_okx_rows(
    collector: OkxSwapPublicCollector,
    name: str,
    params: Mapping[str, Any],
    *,
    timestamp_getter: Any,
    target_start_ms: int | None,
    sleep_seconds: float = 0.12,
    retry_count: int = 0,
    retry_backoff_seconds: float = 0.0,
    request_attempts: list[dict[str, Any]] | None = None,
    max_pages: int = 60,
) -> list[Any]:
    rows_by_time: dict[int, Any] = {}
    cursor: int | None = None
    pages = 0
    while pages < max_pages:
        if cursor is not None and target_start_ms is not None and cursor <= target_start_ms:
            break
        request_params = dict(params)
        if cursor is not None:
            request_params["after"] = str(cursor)
        response = _okx_request(
            collector,
            name,
            request_params,
            retry_count=retry_count,
            retry_backoff_seconds=retry_backoff_seconds,
            request_attempts=request_attempts,
        )
        batch = response["payload"].get("data", [])
        added, oldest = _add_rows(rows_by_time, batch, timestamp_getter)
        pages += 1
        if oldest is None or added == 0:
            break
        if cursor is not None and oldest >= cursor:
            break
        cursor = oldest
        if cursor <= 0:
            break
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return [rows_by_time[key] for key in sorted(rows_by_time)]


def _okx_request(
    collector: OkxSwapPublicCollector,
    name: str,
    params: Mapping[str, Any],
    *,
    retry_count: int = 0,
    retry_backoff_seconds: float = 0.0,
    request_attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    max_attempts = max(1, int(retry_count) + 1)
    last_error: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            response = collector.request_by_name(name, params)
            payload = response.get("payload")
            if not isinstance(payload, Mapping) or payload.get("code") != "0":
                raise RuntimeError(f"OKX public request failed for {name}: {payload}")
            _append_request_attempt(
                request_attempts,
                name=name,
                params=params,
                attempt=attempt,
                max_attempts=max_attempts,
                status="success",
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
            return response
        except Exception as exc:  # noqa: BLE001 - persisted as fail-closed public-data evidence.
            last_error = exc
            _append_request_attempt(
                request_attempts,
                name=name,
                params=params,
                attempt=attempt,
                max_attempts=max_attempts,
                status="error",
                duration_ms=(time.perf_counter() - started) * 1000.0,
                error=repr(exc),
            )
            if attempt >= max_attempts:
                break
            if retry_backoff_seconds > 0.0:
                time.sleep(retry_backoff_seconds * attempt)
    assert last_error is not None
    raise last_error


def _append_request_attempt(
    request_attempts: list[dict[str, Any]] | None,
    *,
    name: str,
    params: Mapping[str, Any],
    attempt: int,
    max_attempts: int,
    status: str,
    duration_ms: float,
    error: str = "",
) -> None:
    if request_attempts is None:
        return
    request_attempts.append(
        {
            "name": name,
            "params": {str(key): str(value) for key, value in params.items()},
            "attempt": int(attempt),
            "max_attempts": int(max_attempts),
            "status": status,
            "duration_ms": round(float(duration_ms), 3),
            "error": error[:500],
        }
    )


def _add_rows(rows_by_time: dict[int, Any], batch: object, timestamp_getter: Any) -> tuple[int, int | None]:
    if not isinstance(batch, list):
        return 0, None
    added = 0
    oldest: int | None = None
    for row in batch:
        timestamp = timestamp_getter(row)
        if timestamp is None:
            continue
        oldest = timestamp if oldest is None else min(oldest, timestamp)
        if timestamp not in rows_by_time:
            rows_by_time[timestamp] = row
            added += 1
    return added, oldest


def _select_daily_rows(rows: object, target_start_ms: int) -> list[list[str]]:
    parsed = [list(row) for row in rows if isinstance(row, list) and row and str(row[0]).isdigit()]
    selected = [row for row in parsed if int(row[0]) >= target_start_ms - DAY_MS]
    return sorted(selected, key=lambda row: int(row[0]))


def _write_market_candles(path: Path, rows: list[list[str]]) -> None:
    _write_csv_atomic(
        path,
        [
            "timestamp",
            "open_time",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume_contracts",
            "volume_base",
            "volume_quote",
            "confirm",
            "source_record_id",
        ],
        [
            {
                "timestamp": _iso_ms(int(row[0])),
                "open_time": row[0],
                "symbol": SYMBOL,
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume_contracts": row[5] if len(row) > 5 else "",
                "volume_base": row[6] if len(row) > 6 else "",
                "volume_quote": row[7] if len(row) > 7 else "",
                "confirm": row[8] if len(row) > 8 else "",
                "source_record_id": f"okx:{VENUE_SYMBOL}:1Dutc:{row[0]}",
            }
            for row in rows
        ],
    )


def _daily_manifest(
    *,
    bundle_dir: Path,
    root: Path,
    bundle_id: str,
    rows: list[list[str]],
    captured_at: str,
    requested_history_days: int,
) -> dict[str, Any]:
    path = bundle_dir / "klines_1d.csv"
    return {
        "schema_version": "btc_okx_daily_history_manifest_v1",
        "bundle_id": bundle_id,
        "created_at": captured_at,
        "source_provider": "okx_spot",
        "market_type": "spot",
        "symbol": SYMBOL,
        "venue_symbol": VENUE_SYMBOL,
        "bar": "1Dutc",
        "requested_history_days": requested_history_days,
        "sample_start": _iso_ms(_row_time_ms(rows[0])) if rows else "",
        "sample_end": _iso_ms(_row_time_ms(rows[-1])) if rows else "",
        "row_count": len(rows),
        "files": [_file_facts(path, root)] if path.exists() else [],
        "public_rest_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "license_note": "OKX public REST daily candles captured for local research; no API key, no private endpoint, no order endpoint.",
        "blockers": [] if len(rows) >= 365 else ["btc_okx_daily_history_less_than_365_rows"],
    }


def _write_csv_atomic(path: Path, fieldnames: list[str], rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
        temp_name = handle.name
    Path(temp_name).replace(path)


def _write_json_atomic(payload: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(dict(payload), indent=2, sort_keys=True, default=str)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(encoded + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _file_facts(path: Path, root: Path) -> dict[str, Any]:
    return {"path": _relpath(path, root), "size_bytes": path.stat().st_size, "sha256": _sha256(path)}


def _row_time_ms(row: object) -> int | None:
    if isinstance(row, list) and row:
        return _int_or_none(row[0])
    return None


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso_ms(value: int | None) -> str:
    if value is None:
        return ""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture long BTC daily candles from OKX public REST.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--capture-report", default=str(DEFAULT_CAPTURE_REPORT))
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--history-days", type=int, default=1825)
    parser.add_argument("--request-sleep-seconds", type=float, default=0.12)
    parser.add_argument("--request-retry-count", type=int, default=DEFAULT_REQUEST_RETRY_COUNT)
    parser.add_argument("--request-retry-backoff-seconds", type=float, default=DEFAULT_REQUEST_RETRY_BACKOFF_SECONDS)
    parser.add_argument("--captured-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = capture_btc_okx_daily_history(
        repo_root=Path(args.repo_root),
        bundle_id=args.bundle_id,
        output_root=Path(args.output_root),
        capture_report=Path(args.capture_report),
        execute_network=bool(args.execute_network),
        history_days=args.history_days,
        request_sleep_seconds=args.request_sleep_seconds,
        request_retry_count=args.request_retry_count,
        request_retry_backoff_seconds=args.request_retry_backoff_seconds,
        captured_at=args.captured_at or None,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        print(result["status"])
    if result.get("status") not in {"verified", "dry_run"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
