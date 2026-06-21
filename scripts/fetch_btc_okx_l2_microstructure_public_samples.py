#!/usr/bin/env python3
"""Capture bounded OKX public L2/tick samples for BTC scalping research evidence."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

try:
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
    from quant_crypto.data.okx_swap_public import OkxSwapPublicCollector
    from scripts.fetch_btc_okx_swap_public_data import (
        SYMBOL,
        VENUE_SYMBOL,
        _book_depth_rows,
        _file_facts,
        _int_or_none,
        _iso_ms,
        _okx_request,
        _relpath,
        _trade_rows,
        _utc_z_now,
        _write_csv_atomic,
        _write_json_atomic,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
    from quant_crypto.data.okx_swap_public import OkxSwapPublicCollector
    from scripts.fetch_btc_okx_swap_public_data import (
        SYMBOL,
        VENUE_SYMBOL,
        _book_depth_rows,
        _file_facts,
        _int_or_none,
        _iso_ms,
        _okx_request,
        _relpath,
        _trade_rows,
        _utc_z_now,
        _write_csv_atomic,
        _write_json_atomic,
    )


DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_CAPTURE_REPORT = Path(
    "artifacts/btc_scalping_readiness/latest/btc_okx_l2_microstructure_sample_capture_report.json"
)
TRADE_SAMPLE_FILE = "agg_trades_samples.csv"
BOOK_SAMPLE_FILE = "order_book_depth_samples.csv"


def capture_okx_l2_microstructure_public_samples(
    *,
    repo_root: Path,
    config_path: Path = DEFAULT_CONFIG,
    bundle_dir: Path | None = None,
    capture_report_path: Path = DEFAULT_CAPTURE_REPORT,
    execute_network: bool = False,
    sample_count: int = 5,
    trade_limit: int = 100,
    book_size: int = 50,
    request_sleep_seconds: float = 0.2,
    captured_at: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    captured = captured_at or _utc_z_now()
    effective_sample_count = max(1, int(sample_count))
    effective_trade_limit = min(100, max(1, int(trade_limit)))
    effective_book_size = min(400, max(1, int(book_size)))
    effective_sleep = max(0.0, float(request_sleep_seconds))
    selected_bundle = _resolve(root, bundle_dir) if bundle_dir else selected_btc_perpetual_bundle_dir(root, _resolve(root, config_path))
    blockers: list[str] = []
    if selected_bundle is None:
        blockers.append("btc_okx_selected_bundle_missing")
        selected_bundle = root / "data/external/btc_perpetual/okx_swap/bundles/missing"
    output_root = selected_bundle.parent
    report_path = _resolve(root, capture_report_path)
    planner = OkxSwapPublicCollector(output_root=output_root, dry_run=True, allow_network=False)
    planned_requests = _planned_requests(
        planner=planner,
        sample_count=effective_sample_count,
        trade_limit=effective_trade_limit,
        book_size=effective_book_size,
    )
    base_payload = {
        "schema_version": "btc_okx_l2_microstructure_sample_capture_report_v1",
        "generated_at": captured,
        "selected_bundle_dir": _relpath(selected_bundle, root),
        "requested_sample_count": effective_sample_count,
        "trade_limit": effective_trade_limit,
        "book_size": effective_book_size,
        "public_rest_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "planned_requests": planned_requests,
    }
    if not execute_network:
        payload = {
            **base_payload,
            "status": "dry_run",
            "network_called": False,
            "completed_sample_count": 0,
            "latency_samples": [],
            "files": [],
            "capture_summary": _capture_summary([], [], []),
            "errors": [],
            "blockers": blockers,
        }
        _write_json_atomic(payload, report_path)
        return payload

    if not selected_bundle.exists():
        blockers.append("btc_okx_selected_bundle_dir_missing")

    trade_rows: list[dict[str, Any]] = []
    book_rows: list[dict[str, Any]] = []
    latency_samples: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    completed_sample_count = 0
    collector = OkxSwapPublicCollector(output_root=output_root, dry_run=False, allow_network=True)

    if not blockers:
        for sample_index in range(1, effective_sample_count + 1):
            sample_had_error = False
            sample_captured_at = _utc_z_now()
            try:
                trade_response = _okx_request(
                    collector,
                    "history_trades",
                    {"instId": VENUE_SYMBOL, "limit": str(effective_trade_limit)},
                )
                latency_samples.append(_latency_sample(trade_response, role="agg_trades", sample_index=sample_index))
                trade_rows.extend(
                    _sample_trade_rows(
                        trade_response["payload"].get("data", []),
                        sample_index=sample_index,
                        sample_captured_at=sample_captured_at,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - persisted as evidence.
                sample_had_error = True
                blockers.append("btc_okx_l2_sample_agg_trades_capture_failed")
                errors.append({"role": "agg_trades", "sample_index": str(sample_index), "error": repr(exc)})
            if effective_sleep > 0:
                time.sleep(effective_sleep)
            try:
                book_response = _okx_request(
                    collector,
                    "books",
                    {"instId": VENUE_SYMBOL, "sz": str(effective_book_size)},
                )
                latency_samples.append(_latency_sample(book_response, role="order_book_depth", sample_index=sample_index))
                book_rows.extend(
                    _sample_book_rows(
                        book_response["payload"].get("data", []),
                        sample_index=sample_index,
                        sample_captured_at=sample_captured_at,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - persisted as evidence.
                sample_had_error = True
                blockers.append("btc_okx_l2_sample_order_book_depth_capture_failed")
                errors.append({"role": "order_book_depth", "sample_index": str(sample_index), "error": repr(exc)})
            if not sample_had_error:
                completed_sample_count += 1
            if effective_sleep > 0 and sample_index < effective_sample_count:
                time.sleep(effective_sleep)

    files: list[dict[str, Any]] = []
    if not blockers:
        trade_path = selected_bundle / TRADE_SAMPLE_FILE
        book_path = selected_bundle / BOOK_SAMPLE_FILE
        _write_trade_samples(trade_path, trade_rows)
        _write_book_samples(book_path, book_rows)
        files.extend([_file_facts(trade_path, root), _file_facts(book_path, root)])
        if not trade_rows:
            blockers.append("btc_okx_l2_sample_agg_trades_empty")
        if not book_rows:
            blockers.append("btc_okx_l2_sample_order_book_depth_empty")

    payload = {
        **base_payload,
        "status": "verified" if not blockers else "rejected",
        "network_called": True,
        "completed_sample_count": completed_sample_count,
        "latency_samples": latency_samples,
        "files": files,
        "capture_summary": _capture_summary(trade_rows, book_rows, latency_samples),
        "errors": errors,
        "blockers": _dedupe(blockers),
    }
    _write_json_atomic(payload, report_path)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG))
    parser.add_argument("--bundle-dir", default="")
    parser.add_argument("--capture-report", default=str(DEFAULT_CAPTURE_REPORT))
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--sample-count", type=int, default=5)
    parser.add_argument("--trade-limit", type=int, default=100)
    parser.add_argument("--book-size", type=int, default=50)
    parser.add_argument("--request-sleep-seconds", type=float, default=0.2)
    parser.add_argument("--captured-at", default="")
    args = parser.parse_args()
    payload = capture_okx_l2_microstructure_public_samples(
        repo_root=Path(args.repo_root),
        config_path=Path(args.config_path),
        bundle_dir=Path(args.bundle_dir) if args.bundle_dir else None,
        capture_report_path=Path(args.capture_report),
        execute_network=bool(args.execute_network),
        sample_count=args.sample_count,
        trade_limit=args.trade_limit,
        book_size=args.book_size,
        request_sleep_seconds=args.request_sleep_seconds,
        captured_at=args.captured_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") not in {"verified", "dry_run"}:
        raise SystemExit(2)


def _planned_requests(
    *,
    planner: OkxSwapPublicCollector,
    sample_count: int,
    trade_limit: int,
    book_size: int,
) -> list[dict[str, Any]]:
    planned: list[dict[str, Any]] = []
    for sample_index in range(1, sample_count + 1):
        planned.append(
            _planned_request(
                planner,
                role="agg_trades",
                sample_index=sample_index,
                name="history_trades",
                params={"instId": VENUE_SYMBOL, "limit": str(trade_limit)},
            )
        )
        planned.append(
            _planned_request(
                planner,
                role="order_book_depth",
                sample_index=sample_index,
                name="books",
                params={"instId": VENUE_SYMBOL, "sz": str(book_size)},
            )
        )
    return planned


def _planned_request(
    planner: OkxSwapPublicCollector,
    *,
    role: str,
    sample_index: int,
    name: str,
    params: Mapping[str, Any],
) -> dict[str, Any]:
    response = dict(planner.request_by_name(name, params))
    response["role"] = role
    response["sample_index"] = sample_index
    return response


def _sample_trade_rows(
    rows: object,
    *,
    sample_index: int,
    sample_captured_at: str,
) -> list[dict[str, Any]]:
    sampled: list[dict[str, Any]] = []
    for row in _trade_rows(rows):
        timestamp = _int_or_none(row.get("ts"))
        trade_id = str(row.get("tradeId") or row.get("ts") or "")
        sampled.append(
            {
                "sample_index": sample_index,
                "sample_captured_at": sample_captured_at,
                "timestamp": _iso_ms(timestamp),
                "ts": str(row.get("ts", "")),
                "symbol": SYMBOL,
                "trade_id": str(row.get("tradeId", "")),
                "price": str(row.get("px", "")),
                "size": str(row.get("sz", "")),
                "side": str(row.get("side", "")),
                "source_record_id": f"okx-trade-sample:{VENUE_SYMBOL}:{sample_index}:{trade_id}",
            }
        )
    return sampled


def _sample_book_rows(
    rows: object,
    *,
    sample_index: int,
    sample_captured_at: str,
) -> list[dict[str, Any]]:
    sampled = []
    for row in _book_depth_rows(rows):
        item = dict(row)
        item["sample_index"] = sample_index
        item["sample_captured_at"] = sample_captured_at
        item["source_record_id"] = f"okx-book-sample:{VENUE_SYMBOL}:{sample_index}:{item.get('ts')}:{item.get('side')}:{item.get('level')}"
        sampled.append(item)
    return sampled


def _write_trade_samples(path: Path, rows: list[Mapping[str, Any]]) -> None:
    _write_csv_atomic(
        path,
        [
            "sample_index",
            "sample_captured_at",
            "timestamp",
            "ts",
            "symbol",
            "trade_id",
            "price",
            "size",
            "side",
            "source_record_id",
        ],
        rows,
    )


def _write_book_samples(path: Path, rows: list[Mapping[str, Any]]) -> None:
    _write_csv_atomic(
        path,
        [
            "sample_index",
            "sample_captured_at",
            "timestamp",
            "ts",
            "symbol",
            "side",
            "level",
            "price",
            "size",
            "liquidation_orders",
            "order_count",
            "source_record_id",
        ],
        rows,
    )


def _latency_sample(response: Mapping[str, Any], *, role: str, sample_index: int) -> dict[str, Any]:
    duration = response.get("duration_ms")
    return {
        "sample_index": sample_index,
        "role": role,
        "endpoint": str(response.get("endpoint", "")),
        "url": str(response.get("url", "")),
        "network_called": bool(response.get("network_called", False)),
        "duration_ms": float(duration) if isinstance(duration, (int, float)) else None,
    }


def _capture_summary(
    trade_rows: list[Mapping[str, Any]],
    book_rows: list[Mapping[str, Any]],
    latency_samples: list[Mapping[str, Any]],
) -> dict[str, Any]:
    trade_timestamps = {str(row.get("ts", "")) for row in trade_rows if row.get("ts")}
    book_timestamps = {str(row.get("ts", "")) for row in book_rows if row.get("ts")}
    trade_sample_indices = {str(row.get("sample_index", "")) for row in trade_rows if row.get("sample_index")}
    book_sample_indices = {str(row.get("sample_index", "")) for row in book_rows if row.get("sample_index")}
    latency_durations = [sample.get("duration_ms") for sample in latency_samples if isinstance(sample.get("duration_ms"), (int, float))]
    return {
        "trade_row_count": len(trade_rows),
        "book_level_row_count": len(book_rows),
        "unique_trade_timestamps": len(trade_timestamps),
        "unique_book_timestamps": len(book_timestamps),
        "trade_sample_count_with_rows": len(trade_sample_indices),
        "book_sample_count_with_rows": len(book_sample_indices),
        "latency_sample_count": len(latency_durations),
    }


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
