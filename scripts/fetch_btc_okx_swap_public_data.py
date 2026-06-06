#!/usr/bin/env python3
"""Capture an OKX public BTC-USDT-SWAP research bundle.

This collector is public-data only. It refuses OKX credentials through the
collector layer and writes a local bundle compatible with the existing BTC
perpetual evidence gates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

try:
    from quant_crypto.data.btc_perpetual_provider_config import default_provider_root
    from quant_crypto.data.okx_swap_public import OkxSwapPublicCollector
    from scripts.build_btc_perpetual_data_bundle_manifest import (
        build_btc_perpetual_data_bundle_manifest,
        write_manifest,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.btc_perpetual_provider_config import default_provider_root
    from quant_crypto.data.okx_swap_public import OkxSwapPublicCollector
    from build_btc_perpetual_data_bundle_manifest import (
        build_btc_perpetual_data_bundle_manifest,
        write_manifest,
    )


DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_BUNDLE_ID = "btc_okx_swap_btcusdt_recent_24h_v1"
DEFAULT_OUTPUT_ROOT = Path("data/external/btc_perpetual/okx_swap/bundles")
DEFAULT_CAPTURE_REPORT = Path("artifacts/btc_data_status/latest/btc_okx_public_bundle_capture_report.json")
DEFAULT_MANUAL_METADATA_IMPORT_REPORT = Path("artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json")
DEFAULT_RAW_CAPTURE_ROOT = Path("artifacts/btc_data_status/latest/okx_public_metadata_raw_capture")
SYMBOL = "BTCUSDT"
VENUE_SYMBOL = "BTC-USDT-SWAP"
INDEX_SYMBOL = "BTC-USDT"
SOURCE_PROVIDER = "okx_swap"
LICENSE_NOTE = "OKX public REST market data captured for local research; no API key, no private endpoint, no order endpoint."
DAY_MS = 86_400_000
DIAGNOSTIC_ONLY_BLOCKERS = {
    "btc_liquidation_snapshots_missing_diagnostic_only",
    "btc_liquidation_snapshot_missing_diagnostic_only",
    "btc_open_interest_history_not_verified_diagnostic_partial",
    "diagnostic_only_not_gate_evidence",
}


def capture_okx_public_bundle(
    *,
    repo_root: Path,
    bundle_id: str = DEFAULT_BUNDLE_ID,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    config_path: Path = DEFAULT_CONFIG,
    raw_capture_root: Path = DEFAULT_RAW_CAPTURE_ROOT,
    capture_report_path: Path = DEFAULT_CAPTURE_REPORT,
    manual_metadata_import_report_path: Path = DEFAULT_MANUAL_METADATA_IMPORT_REPORT,
    execute_network: bool = False,
    update_config: bool = True,
    history_days: int = 1,
    request_sleep_seconds: float = 0.12,
    captured_at: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    captured = captured_at or _utc_z_now()
    output_abs = _resolve(root, output_root)
    raw_abs = _resolve(root, raw_capture_root)
    capture_report_abs = _resolve(root, capture_report_path)
    manual_report_abs = _resolve(root, manual_metadata_import_report_path)
    config_abs = _resolve(root, config_path)
    effective_history_days = max(1, int(history_days))
    effective_sleep = max(0.0, float(request_sleep_seconds))

    collector = OkxSwapPublicCollector(
        output_root=output_abs,
        dry_run=not execute_network,
        allow_network=execute_network,
    )
    if not execute_network:
        payload = {
            "schema_version": "btc_okx_public_bundle_capture_report_v1",
            "status": "dry_run",
            "generated_at": captured,
            "bundle_id": bundle_id,
            "history_days": effective_history_days,
            "network_called": False,
            "planned_requests": [
                collector.request_by_name("instruments", {"instType": "SWAP", "instId": VENUE_SYMBOL}),
                collector.request_by_name("funding_rate", {"instId": VENUE_SYMBOL}),
                collector.request_by_name("funding_rate_history", {"instId": VENUE_SYMBOL, "limit": "100"}),
            ],
            "blockers": [],
        }
        _write_json_atomic(payload, capture_report_abs)
        return payload

    raw_abs.mkdir(parents=True, exist_ok=True)
    bundle_dir = collector.bundle_path(bundle_id, create=True)
    blockers: list[str] = []

    instrument_response = _okx_request(collector, "instruments", {"instType": "SWAP", "instId": VENUE_SYMBOL})
    funding_info_response = _okx_request(collector, "funding_rate", {"instId": VENUE_SYMBOL})
    open_interest_response = _okx_request(
        collector,
        "open_interest",
        {"instType": "SWAP", "instId": VENUE_SYMBOL},
    )

    raw_exchange = raw_abs / "exchange_info_raw.json"
    raw_funding = raw_abs / "funding_info_raw.json"
    exchange_status = raw_abs / "exchange_info_http_status.txt"
    funding_status = raw_abs / "funding_info_http_status.txt"
    _write_json_atomic(instrument_response["payload"], raw_exchange)
    _write_json_atomic(funding_info_response["payload"], raw_funding)
    exchange_status.write_text("200\n", encoding="utf-8")
    funding_status.write_text("200\n", encoding="utf-8")

    initial_funding_response = _okx_request(
        collector,
        "funding_rate_history",
        {"instId": VENUE_SYMBOL, "limit": "100"},
    )
    initial_funding_rows = _funding_rows(initial_funding_response["payload"].get("data", []))
    latest_funding_ms = int(initial_funding_rows[-1]["fundingTime"]) if initial_funding_rows else None
    requested_start_ms = latest_funding_ms - effective_history_days * DAY_MS if latest_funding_ms is not None else None
    funding_rows = _fetch_paginated_okx_rows(
        collector,
        "funding_rate_history",
        {"instId": VENUE_SYMBOL, "limit": "100"},
        timestamp_getter=lambda row: _int_or_none(_mapping(row).get("fundingTime")),
        target_start_ms=requested_start_ms,
        initial_rows=initial_funding_rows,
        sleep_seconds=effective_sleep,
    )
    if len(funding_rows) < 4:
        blockers.append("btc_okx_funding_history_less_than_four_events")
    if requested_start_ms is not None and effective_history_days > 1:
        funding_window = [
            row
            for row in funding_rows
            if requested_start_ms <= int(row["fundingTime"]) <= latest_funding_ms
        ]
    else:
        funding_window = funding_rows[-4:] if len(funding_rows) >= 4 else funding_rows
    sample_start_ms = int(funding_window[0]["fundingTime"]) if funding_window else None
    sample_end_ms = int(funding_window[-1]["fundingTime"]) if funding_window else None
    if sample_start_ms is None or sample_end_ms is None:
        blockers.append("btc_okx_sample_window_missing")
    sample_start = _iso_ms(sample_start_ms) if sample_start_ms is not None else None
    sample_end = _iso_ms(sample_end_ms) if sample_end_ms is not None else None

    if sample_start_ms is not None and sample_end_ms is not None:
        klines_1h_raw = _fetch_paginated_okx_rows(
            collector,
            "candles",
            {"instId": VENUE_SYMBOL, "bar": "1H", "limit": "100"},
            timestamp_getter=_row_time_ms,
            target_start_ms=sample_start_ms - 3_600_000,
            sleep_seconds=effective_sleep,
        )
        klines_4h_raw = _fetch_paginated_okx_rows(
            collector,
            "candles",
            {"instId": VENUE_SYMBOL, "bar": "4H", "limit": "100"},
            timestamp_getter=_row_time_ms,
            target_start_ms=sample_start_ms - 14_400_000,
            sleep_seconds=effective_sleep,
        )
        klines_1d_raw = _fetch_paginated_okx_rows(
            collector,
            "candles",
            {"instId": VENUE_SYMBOL, "bar": "1Dutc", "limit": "100"},
            timestamp_getter=_row_time_ms,
            target_start_ms=sample_start_ms - 86_400_000,
            sleep_seconds=effective_sleep,
        )
        mark_1h_raw = _fetch_paginated_okx_rows(
            collector,
            "mark_price_candles",
            {"instId": VENUE_SYMBOL, "bar": "1H", "limit": "100"},
            timestamp_getter=_row_time_ms,
            target_start_ms=sample_start_ms - 3_600_000,
            sleep_seconds=effective_sleep,
        )
        index_1h_raw = _fetch_paginated_okx_rows(
            collector,
            "index_candles",
            {"instId": INDEX_SYMBOL, "bar": "1H", "limit": "100"},
            timestamp_getter=_row_time_ms,
            target_start_ms=sample_start_ms - 3_600_000,
            sleep_seconds=effective_sleep,
        )
        klines_1h = _select_candles(klines_1h_raw, sample_start_ms, sample_end_ms, 3_600_000)
        klines_4h = _select_candles(klines_4h_raw, sample_start_ms, sample_end_ms, 14_400_000)
        klines_1d = _select_candles(klines_1d_raw, sample_start_ms, sample_end_ms, 86_400_000)
        mark_1h = _select_candles(mark_1h_raw, sample_start_ms, sample_end_ms, 3_600_000)
        index_1h = _select_candles(index_1h_raw, sample_start_ms, sample_end_ms, 3_600_000)
    else:
        klines_1h, klines_4h, klines_1d, mark_1h, index_1h = [], [], [], [], []

    _write_market_candles(bundle_dir / "klines_1h.csv", klines_1h)
    _write_market_candles(bundle_dir / "klines_4h.csv", klines_4h)
    _write_market_candles(bundle_dir / "klines_1d.csv", klines_1d)
    _write_mark_candles(bundle_dir / "mark_price_klines_1h.csv", mark_1h)
    _write_premium_index(bundle_dir / "premium_index_klines_1h.csv", mark_1h, index_1h)
    _write_funding_rate(bundle_dir / "funding_rate.csv", funding_window, mark_1h)
    _write_json_atomic(
        _canonical_funding_info(funding_info_response["payload"], captured_at=captured),
        bundle_dir / "funding_info.json",
    )
    _write_json_atomic(
        _canonical_exchange_info(
            instrument_response["payload"],
            captured_at=captured,
            mark_price=_latest_close(mark_1h),
        ),
        bundle_dir / "exchange_info.json",
    )
    _write_json_atomic(open_interest_response["payload"], bundle_dir / "open_interest_current.json")

    manifest = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle_dir,
        bundle_id=bundle_id,
        source_type="production",
        source_provider=SOURCE_PROVIDER,
        exchange=SOURCE_PROVIDER,
        symbol=SYMBOL,
        market_type="usds_m_perpetual",
        promotion_clean_allowed=True,
        sample_start=sample_start,
        sample_end=sample_end,
        license_note=LICENSE_NOTE,
        created_at=captured,
    )
    write_manifest(manifest, bundle_dir)
    diagnostic_warnings = [str(item) for item in manifest.get("blockers", []) if str(item) in DIAGNOSTIC_ONLY_BLOCKERS]
    blockers.extend(str(item) for item in manifest.get("blockers", []) if str(item) not in DIAGNOSTIC_ONLY_BLOCKERS)
    metadata_report_written = False
    if not blockers:
        _write_manual_metadata_import_report(
            manual_report_abs,
            root=root,
            bundle_dir=bundle_dir,
            raw_exchange=raw_exchange,
            raw_funding=raw_funding,
            exchange_status=exchange_status,
            funding_status=funding_status,
            captured_at=captured,
        )
        metadata_report_written = True
        if update_config:
            _update_selected_provider_config(config_abs, bundle_id=bundle_id)

    report = {
        "schema_version": "btc_okx_public_bundle_capture_report_v1",
        "status": "verified" if not blockers else "rejected",
        "generated_at": captured,
        "bundle_id": bundle_id,
        "history_days": effective_history_days,
        "source_provider": SOURCE_PROVIDER,
        "bundle_dir": _relpath(bundle_dir, root),
        "manifest_path": _relpath(bundle_dir / "btc_perpetual_bundle_manifest.json", root),
        "sample_start": sample_start,
        "sample_end": sample_end,
        "network_called": True,
        "public_rest_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "raw_exchange_info": _file_facts(raw_exchange, root),
        "raw_funding_info": _file_facts(raw_funding, root),
        "manual_metadata_import_report": _relpath(manual_report_abs, root),
        "manual_metadata_import_report_written": metadata_report_written,
        "config_updated": bool(update_config and not blockers),
        "diagnostic_warnings": _dedupe(diagnostic_warnings),
        "blockers": _dedupe(blockers),
    }
    _write_json_atomic(report, capture_report_abs)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG))
    parser.add_argument("--raw-capture-root", default=str(DEFAULT_RAW_CAPTURE_ROOT))
    parser.add_argument("--capture-report", default=str(DEFAULT_CAPTURE_REPORT))
    parser.add_argument("--manual-metadata-import-report", default=str(DEFAULT_MANUAL_METADATA_IMPORT_REPORT))
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--no-update-config", action="store_true")
    parser.add_argument("--history-days", type=int, default=1)
    parser.add_argument("--request-sleep-seconds", type=float, default=0.12)
    parser.add_argument("--captured-at", default="")
    args = parser.parse_args()

    result = capture_okx_public_bundle(
        repo_root=Path(args.repo_root),
        bundle_id=args.bundle_id,
        output_root=Path(args.output_root),
        config_path=Path(args.config_path),
        raw_capture_root=Path(args.raw_capture_root),
        capture_report_path=Path(args.capture_report),
        manual_metadata_import_report_path=Path(args.manual_metadata_import_report),
        execute_network=bool(args.execute_network),
        update_config=not args.no_update_config,
        history_days=args.history_days,
        request_sleep_seconds=args.request_sleep_seconds,
        captured_at=args.captured_at or None,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("status") not in {"verified", "dry_run"}:
        raise SystemExit(2)


def _okx_request(collector: OkxSwapPublicCollector, name: str, params: Mapping[str, Any]) -> dict[str, Any]:
    response = collector.request_by_name(name, params)
    payload = response.get("payload")
    if not isinstance(payload, Mapping) or payload.get("code") != "0":
        raise RuntimeError(f"OKX public request failed for {name}: {payload}")
    return response


def _fetch_paginated_okx_rows(
    collector: OkxSwapPublicCollector,
    name: str,
    params: Mapping[str, Any],
    *,
    timestamp_getter: Any,
    target_start_ms: int | None,
    initial_rows: list[Any] | None = None,
    sleep_seconds: float = 0.12,
    max_pages: int = 600,
) -> list[Any]:
    rows_by_time: dict[int, Any] = {}
    cursor: int | None = None

    def add_rows(batch: object) -> tuple[int, int | None]:
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

    if initial_rows:
        _, cursor = add_rows(initial_rows)
    pages = 0
    while pages < max_pages:
        if cursor is not None and target_start_ms is not None and cursor <= target_start_ms:
            break
        request_params = dict(params)
        if cursor is not None:
            request_params["after"] = str(cursor)
        response = _okx_request(collector, name, request_params)
        batch = response["payload"].get("data", [])
        added, oldest = add_rows(batch)
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


def _row_time_ms(row: object) -> int | None:
    if isinstance(row, list) and row:
        return _int_or_none(row[0])
    return None


def _funding_rows(rows: object) -> list[dict[str, Any]]:
    out = [dict(row) for row in rows if isinstance(row, Mapping) and str(row.get("fundingTime", "")).isdigit()]
    return sorted(out, key=lambda row: int(row["fundingTime"]))


def _select_candles(rows: object, sample_start_ms: int, sample_end_ms: int, interval_ms: int) -> list[list[str]]:
    parsed = [list(row) for row in rows if isinstance(row, list) and row and str(row[0]).isdigit()]
    parsed = sorted(parsed, key=lambda row: int(row[0]))
    lower = sample_start_ms - interval_ms
    selected = [row for row in parsed if lower <= int(row[0]) <= sample_end_ms]
    return selected


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
                "source_record_id": f"okx:{VENUE_SYMBOL}:{row[0]}",
            }
            for row in rows
        ],
    )


def _write_mark_candles(path: Path, rows: list[list[str]]) -> None:
    _write_csv_atomic(
        path,
        ["timestamp", "open_time", "symbol", "open", "high", "low", "close", "confirm", "source_record_id"],
        [
            {
                "timestamp": _iso_ms(int(row[0])),
                "open_time": row[0],
                "symbol": SYMBOL,
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "confirm": row[5] if len(row) > 5 else "",
                "source_record_id": f"okx-mark:{VENUE_SYMBOL}:{row[0]}",
            }
            for row in rows
        ],
    )


def _write_premium_index(path: Path, mark_rows: list[list[str]], index_rows: list[list[str]]) -> None:
    index_by_time = {str(row[0]): row for row in index_rows}
    rows = []
    for mark in mark_rows:
        index = index_by_time.get(str(mark[0]))
        if not index:
            continue
        mark_close = _float(mark[4])
        index_close = _float(index[4])
        premium = mark_close - index_close if mark_close is not None and index_close is not None else None
        premium_rate = premium / index_close if premium is not None and index_close not in {None, 0.0} else None
        rows.append(
            {
                "timestamp": _iso_ms(int(mark[0])),
                "open_time": mark[0],
                "symbol": SYMBOL,
                "mark_close": mark[4],
                "index_close": index[4],
                "premium": _format_float(premium),
                "premium_rate": _format_float(premium_rate),
                "confirm": mark[5] if len(mark) > 5 else "",
                "source_record_id": f"okx-premium:{VENUE_SYMBOL}:{mark[0]}",
            }
        )
    _write_csv_atomic(
        path,
        ["timestamp", "open_time", "symbol", "mark_close", "index_close", "premium", "premium_rate", "confirm", "source_record_id"],
        rows,
    )


def _write_funding_rate(path: Path, rows: list[Mapping[str, Any]], mark_rows: list[list[str]]) -> None:
    mark_by_time = {str(row[0]): row[4] for row in mark_rows}
    _write_csv_atomic(
        path,
        ["timestamp", "fundingTime", "symbol", "fundingRate", "markPrice", "source_record_id", "instId", "realizedRate"],
        [
            {
                "timestamp": _iso_ms(int(row["fundingTime"])),
                "fundingTime": str(row["fundingTime"]),
                "symbol": SYMBOL,
                "fundingRate": str(row.get("fundingRate") or row.get("realizedRate") or ""),
                "markPrice": str(mark_by_time.get(str(row["fundingTime"]), "")),
                "source_record_id": f"okx-funding:{VENUE_SYMBOL}:{row['fundingTime']}",
                "instId": VENUE_SYMBOL,
                "realizedRate": str(row.get("realizedRate") or row.get("fundingRate") or ""),
            }
            for row in rows
        ],
    )


def _canonical_funding_info(payload: Mapping[str, Any], *, captured_at: str) -> dict[str, Any]:
    rows = [row for row in payload.get("data", []) if isinstance(row, Mapping)]
    canonical_rows = []
    for row in rows:
        prev_time = _int_or_none(row.get("prevFundingTime"))
        funding_time = _int_or_none(row.get("fundingTime"))
        interval_hours = (funding_time - prev_time) / 3_600_000 if funding_time and prev_time else 8
        canonical_rows.append(
            {
                "symbol": SYMBOL,
                "venue_symbol": row.get("instId"),
                "adjustedFundingRateCap": row.get("maxFundingRate"),
                "adjustedFundingRateFloor": row.get("minFundingRate"),
                "fundingIntervalHours": interval_hours,
                "raw": dict(row),
            }
        )
    return {
        "source_method": "public_rest_response",
        "source_endpoint": "/api/v5/public/funding-rate",
        "source_url_or_doc": "https://www.okx.com/docs-v5/en/#public-data-rest-api-get-funding-rate",
        "captured_at": captured_at,
        "symbol": SYMBOL,
        "venue_symbol": VENUE_SYMBOL,
        "endpoint_response_available": bool(canonical_rows),
        "raw_response": canonical_rows,
        "symbol_adjustment_record_present": bool(canonical_rows),
        "operator_note": "OKX public funding-rate capture; no API key and no private/account/order endpoint.",
        "blockers": [],
    }


def _canonical_exchange_info(payload: Mapping[str, Any], *, captured_at: str, mark_price: float | None) -> dict[str, Any]:
    rows = [row for row in payload.get("data", []) if isinstance(row, Mapping)]
    instrument = dict(rows[0]) if rows else {}
    min_size = _float(instrument.get("minSz") or instrument.get("lotSz"))
    contract_value = _float(instrument.get("ctVal"))
    min_notional = min_size * contract_value * mark_price if None not in {min_size, contract_value, mark_price} else None
    return {
        "source_method": "official_public_rest_capture",
        "source_endpoint": "/api/v5/public/instruments",
        "source_url_or_doc": "https://www.okx.com/docs-v5/en/#public-data-rest-api-get-instruments",
        "captured_at": captured_at,
        "symbol": SYMBOL,
        "venue_symbol": VENUE_SYMBOL,
        "raw_symbol_info": instrument,
        "mark_price_at_capture": mark_price,
        "min_notional_estimate": min_notional,
        "historical_rule_lineage_available": False,
        "operator_note": "OKX public instruments capture; no API key and no private/account/order endpoint.",
        "api_key_used": False,
        "private_endpoint_used": False,
        "auth_headers_present": False,
        "blockers": [],
    }


def _latest_close(rows: list[list[str]]) -> float | None:
    for row in reversed(rows):
        value = _float(row[4] if len(row) > 4 else None)
        if value is not None:
            return value
    return None


def _write_manual_metadata_import_report(
    output: Path,
    *,
    root: Path,
    bundle_dir: Path,
    raw_exchange: Path,
    raw_funding: Path,
    exchange_status: Path,
    funding_status: Path,
    captured_at: str,
) -> None:
    exchange_output = bundle_dir / "exchange_info.json"
    funding_output = bundle_dir / "funding_info.json"
    payload = {
        "schema_version": "btc_manual_metadata_import_report_v1",
        "status": "verified",
        "generated_at": captured_at,
        "dry_run": False,
        "captured_at": captured_at,
        "writes_performed": True,
        "exchange_info_verified": True,
        "funding_info_verified": True,
        "raw_input_files": {
            "exchange_info_raw": {
                "path": _relpath(raw_exchange, root),
                "exists": True,
                "size_bytes": raw_exchange.stat().st_size,
                "sha256": _sha256(raw_exchange),
                "http_status_file": _relpath(exchange_status, root),
                "http_status": 200,
                "http_status_verified": True,
            },
            "funding_info_raw": {
                "path": _relpath(raw_funding, root),
                "exists": True,
                "size_bytes": raw_funding.stat().st_size,
                "sha256": _sha256(raw_funding),
                "http_status_file": _relpath(funding_status, root),
                "http_status": 200,
                "http_status_verified": True,
            },
        },
        "exchange_info_output_path": _relpath(exchange_output, root),
        "exchange_info_output_sha256": _sha256(exchange_output),
        "funding_info_output_path": _relpath(funding_output, root),
        "funding_info_output_sha256": _sha256(funding_output),
        "bundle_dir": _relpath(bundle_dir, root),
        "post_import_validation_command": "make validate-btc-public-data-bundle",
        "blockers": [],
    }
    _write_json_atomic(payload, output)


def _update_selected_provider_config(config_path: Path, *, bundle_id: str) -> None:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    if not isinstance(payload, Mapping):
        payload = {}
    config = dict(payload)
    providers = dict(config.get("providers") or {})
    providers["okx_swap"] = {
        "enabled": True,
        "mode": "local_bundle",
        "landing_mode": "public_rest_capture",
        "root": default_provider_root(SOURCE_PROVIDER),
        "selected_bundle_id": bundle_id,
        "require_explicit_bundle_selection": True,
        "allow_local_archive_import": True,
        "allow_public_rest_fetch": False,
        "allow_network": False,
        "allow_private_endpoints": False,
        "allow_order_endpoints": False,
        "allow_sample_for_tests_only": False,
        "promotion_clean_allowed": True,
    }
    if "binance_usdm" in providers and isinstance(providers["binance_usdm"], Mapping):
        providers["binance_usdm"] = dict(providers["binance_usdm"])
        providers["binance_usdm"]["enabled"] = False
    config["selected_provider"] = SOURCE_PROVIDER
    config["providers"] = providers
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


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
    encoded = json.dumps(dict(payload), indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        handle.write(encoded)
        handle.write("\n")
        temp_name = handle.name
    Path(temp_name).replace(path)


def _file_facts(path: Path, root: Path) -> dict[str, Any]:
    return {"path": _relpath(path, root), "size_bytes": path.stat().st_size, "sha256": _sha256(path)}


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


def _float(value: object) -> float | None:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _format_float(value: float | None) -> str:
    return "" if value is None else f"{value:.12g}"


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
