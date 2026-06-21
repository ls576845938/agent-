#!/usr/bin/env python3
"""Capture timestamp-aligned OKX public trades/books for BTC L2 research preflight."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
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
        _okx_request,
        _relpath,
        _trade_rows,
        _utc_z_now,
        _write_csv_atomic,
        _write_json_atomic,
    )


DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_CAPTURE_REPORT = Path(
    "artifacts/btc_scalping_readiness/latest/btc_okx_timestamp_aligned_l2_capture_report.json"
)
AGG_TRADES_ALIGNED_FILE = "agg_trades_aligned.csv"
ORDER_BOOK_DEPTH_ALIGNED_FILE = "order_book_depth_aligned.csv"
ALIGNMENT_MANIFEST_FILE = "l2_alignment_manifest.json"
REPORT_SCHEMA_VERSION = "btc_okx_timestamp_aligned_l2_capture_report_v1"


def capture_okx_timestamp_aligned_l2_public_data(
    *,
    repo_root: Path,
    config_path: Path = DEFAULT_CONFIG,
    bundle_dir: Path | None = None,
    capture_report_path: Path = DEFAULT_CAPTURE_REPORT,
    execute_network: bool = False,
    sample_count: int = 6,
    trade_limit: int = 100,
    book_size: int = 50,
    request_sleep_seconds: float = 0.25,
    captured_at: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    captured = captured_at or _utc_z_now()
    selected_bundle = _resolve(root, bundle_dir) if bundle_dir else selected_btc_perpetual_bundle_dir(root, _resolve(root, config_path))
    report_path = _resolve(root, capture_report_path)
    effective_sample_count = max(1, int(sample_count))
    effective_trade_limit = min(100, max(1, int(trade_limit)))
    effective_book_size = min(400, max(1, int(book_size)))
    effective_sleep = max(0.0, float(request_sleep_seconds))
    blockers: list[str] = []
    if selected_bundle is None:
        blockers.append("btc_okx_selected_bundle_missing")
        selected_bundle = root / "data/external/btc_perpetual/okx_swap/bundles/missing"
    output_root = selected_bundle.parent
    planner = OkxSwapPublicCollector(output_root=output_root, dry_run=True, allow_network=False)
    planned_requests = _planned_requests(
        planner=planner,
        sample_count=effective_sample_count,
        trade_limit=effective_trade_limit,
        book_size=effective_book_size,
    )
    base_payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "dry_run",
        "generated_at": captured,
        "selected_bundle_dir": _relpath(selected_bundle, root),
        "sample_count": effective_sample_count,
        "trade_limit": effective_trade_limit,
        "book_size": effective_book_size,
        "network_called": False,
        "public_rest_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "planned_requests": planned_requests,
    }
    if not execute_network:
        payload = {
            **base_payload,
            "completed_sample_count": 0,
            "files": [],
            "capture_summary": _capture_summary([], [], []),
            "latency_samples": [],
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
    capture_started_at = _utc_z_now()
    capture_started_monotonic_ns = time.monotonic_ns()

    if not blockers:
        for sample_index in range(1, effective_sample_count + 1):
            sample_had_error = False
            try:
                trade_context = _request_context(
                    collector=collector,
                    role="agg_trades_aligned",
                    name="history_trades",
                    sample_index=sample_index,
                    params={"instId": VENUE_SYMBOL, "limit": str(effective_trade_limit)},
                )
                latency_samples.append(trade_context["latency_sample"])
                trade_rows.extend(
                    _aligned_trade_rows(
                        trade_context["response"]["payload"].get("data", []),
                        sample_index=sample_index,
                        local_receive_ts=trade_context["local_receive_ts"],
                        monotonic_ns=trade_context["monotonic_ns"],
                    )
                )
            except Exception as exc:  # noqa: BLE001 - persisted as evidence.
                sample_had_error = True
                blockers.append("btc_okx_aligned_l2_agg_trades_capture_failed")
                errors.append({"role": "agg_trades_aligned", "sample_index": str(sample_index), "error": repr(exc)})
            if effective_sleep > 0:
                time.sleep(effective_sleep)
            try:
                book_context = _request_context(
                    collector=collector,
                    role="order_book_depth_aligned",
                    name="books",
                    sample_index=sample_index,
                    params={"instId": VENUE_SYMBOL, "sz": str(effective_book_size)},
                )
                latency_samples.append(book_context["latency_sample"])
                book_rows.extend(
                    _aligned_book_rows(
                        book_context["response"]["payload"].get("data", []),
                        sample_index=sample_index,
                        local_receive_ts=book_context["local_receive_ts"],
                        monotonic_ns=book_context["monotonic_ns"],
                    )
                )
            except Exception as exc:  # noqa: BLE001 - persisted as evidence.
                sample_had_error = True
                blockers.append("btc_okx_aligned_l2_order_book_depth_capture_failed")
                errors.append({"role": "order_book_depth_aligned", "sample_index": str(sample_index), "error": repr(exc)})
            if not sample_had_error:
                completed_sample_count += 1
            if effective_sleep > 0 and sample_index < effective_sample_count:
                time.sleep(effective_sleep)

    capture_ended_monotonic_ns = time.monotonic_ns()
    capture_ended_at = _utc_z_now()
    files: list[dict[str, Any]] = []
    manifest: dict[str, Any] | None = None
    if not blockers:
        trade_path = selected_bundle / AGG_TRADES_ALIGNED_FILE
        book_path = selected_bundle / ORDER_BOOK_DEPTH_ALIGNED_FILE
        manifest_path = selected_bundle / ALIGNMENT_MANIFEST_FILE
        _write_aligned_trades(trade_path, trade_rows)
        _write_aligned_books(book_path, book_rows)
        manifest = _alignment_manifest(
            capture_started_at=capture_started_at,
            capture_ended_at=capture_ended_at,
            capture_started_monotonic_ns=capture_started_monotonic_ns,
            capture_ended_monotonic_ns=capture_ended_monotonic_ns,
            sample_count=effective_sample_count,
            completed_sample_count=completed_sample_count,
            trade_rows=trade_rows,
            book_rows=book_rows,
            latency_samples=latency_samples,
            errors=errors,
        )
        _write_json_atomic(manifest, manifest_path)
        files.extend([_file_facts(trade_path, root), _file_facts(book_path, root), _file_facts(manifest_path, root)])
        if not trade_rows:
            blockers.append("btc_okx_aligned_l2_agg_trades_empty")
        if not book_rows:
            blockers.append("btc_okx_aligned_l2_order_book_depth_empty")

    payload = {
        **base_payload,
        "status": "verified_preflight" if not blockers else "rejected",
        "network_called": True,
        "completed_sample_count": completed_sample_count,
        "files": files,
        "capture_summary": _capture_summary(trade_rows, book_rows, latency_samples),
        "latency_samples": latency_samples,
        "alignment_manifest": manifest,
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
    parser.add_argument("--sample-count", type=int, default=6)
    parser.add_argument("--trade-limit", type=int, default=100)
    parser.add_argument("--book-size", type=int, default=50)
    parser.add_argument("--request-sleep-seconds", type=float, default=0.25)
    parser.add_argument("--captured-at", default="")
    args = parser.parse_args()
    payload = capture_okx_timestamp_aligned_l2_public_data(
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
    if payload.get("status") not in {"verified_preflight", "dry_run"}:
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
            {
                **planner.request_by_name("history_trades", {"instId": VENUE_SYMBOL, "limit": str(trade_limit)}),
                "role": "agg_trades_aligned",
                "sample_index": sample_index,
            }
        )
        planned.append(
            {
                **planner.request_by_name("books", {"instId": VENUE_SYMBOL, "sz": str(book_size)}),
                "role": "order_book_depth_aligned",
                "sample_index": sample_index,
            }
        )
    return planned


def _request_context(
    *,
    collector: OkxSwapPublicCollector,
    role: str,
    name: str,
    sample_index: int,
    params: Mapping[str, Any],
) -> dict[str, Any]:
    request_started_monotonic_ns = time.monotonic_ns()
    response = _okx_request(collector, name, params)
    monotonic_ns = time.monotonic_ns()
    local_receive_ts = _utc_z_now()
    duration = response.get("duration_ms")
    latency_sample = {
        "sample_index": sample_index,
        "role": role,
        "endpoint": str(response.get("endpoint", "")),
        "url": str(response.get("url", "")),
        "network_called": bool(response.get("network_called", False)),
        "duration_ms": float(duration) if isinstance(duration, (int, float)) else None,
        "request_started_monotonic_ns": request_started_monotonic_ns,
        "local_receive_ts": local_receive_ts,
        "monotonic_ns": monotonic_ns,
    }
    return {
        "response": response,
        "local_receive_ts": local_receive_ts,
        "monotonic_ns": monotonic_ns,
        "latency_sample": latency_sample,
    }


def _aligned_trade_rows(
    rows: object,
    *,
    sample_index: int,
    local_receive_ts: str,
    monotonic_ns: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in _trade_rows(rows):
        exchange_ts_ms = _int_or_none(row.get("ts"))
        trade_id = str(row.get("tradeId") or row.get("ts") or "")
        out.append(
            {
                "capture_sequence": sample_index,
                "exchange_ts": _iso_ms(exchange_ts_ms),
                "exchange_ts_ms": str(row.get("ts", "")),
                "local_receive_ts": local_receive_ts,
                "monotonic_ns": monotonic_ns,
                "venue_symbol": VENUE_SYMBOL,
                "symbol": SYMBOL,
                "trade_id": str(row.get("tradeId", "")),
                "price": str(row.get("px", "")),
                "size": str(row.get("sz", "")),
                "side": str(row.get("side", "")),
                "source_record_id": f"okx-aligned-trade:{VENUE_SYMBOL}:{sample_index}:{trade_id}",
            }
        )
    return out


def _aligned_book_rows(
    rows: object,
    *,
    sample_index: int,
    local_receive_ts: str,
    monotonic_ns: int,
) -> list[dict[str, Any]]:
    raw_rows = _book_depth_rows(rows)
    by_ts: dict[str, list[dict[str, Any]]] = {}
    for row in raw_rows:
        by_ts.setdefault(str(row.get("ts", "")), []).append(dict(row))
    out: list[dict[str, Any]] = []
    for ts, snapshot in sorted(by_ts.items()):
        best_bid = _best_price(snapshot, side="bid", fn=max)
        best_ask = _best_price(snapshot, side="ask", fn=min)
        spread_bps = _spread_bps(best_bid, best_ask)
        bid_depth_notional = _depth_notional(snapshot, side="bid")
        ask_depth_notional = _depth_notional(snapshot, side="ask")
        for row in snapshot:
            level = str(row.get("level", ""))
            side = str(row.get("side", ""))
            out.append(
                {
                    "capture_sequence": sample_index,
                    "exchange_ts": str(row.get("timestamp", "")),
                    "exchange_ts_ms": str(row.get("ts", "")),
                    "local_receive_ts": local_receive_ts,
                    "monotonic_ns": monotonic_ns,
                    "venue_symbol": VENUE_SYMBOL,
                    "symbol": SYMBOL,
                    "side": side,
                    "level": level,
                    "price": str(row.get("price", "")),
                    "size": str(row.get("size", "")),
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread_bps": spread_bps,
                    "bid_depth_notional": bid_depth_notional,
                    "ask_depth_notional": ask_depth_notional,
                    "liquidation_orders": str(row.get("liquidation_orders", "")),
                    "order_count": str(row.get("order_count", "")),
                    "source_record_id": f"okx-aligned-book:{VENUE_SYMBOL}:{sample_index}:{ts}:{side}:{level}",
                }
            )
    return out


def _write_aligned_trades(path: Path, rows: list[Mapping[str, Any]]) -> None:
    _write_csv_atomic(
        path,
        [
            "capture_sequence",
            "exchange_ts",
            "exchange_ts_ms",
            "local_receive_ts",
            "monotonic_ns",
            "venue_symbol",
            "symbol",
            "trade_id",
            "price",
            "size",
            "side",
            "source_record_id",
        ],
        rows,
    )


def _write_aligned_books(path: Path, rows: list[Mapping[str, Any]]) -> None:
    _write_csv_atomic(
        path,
        [
            "capture_sequence",
            "exchange_ts",
            "exchange_ts_ms",
            "local_receive_ts",
            "monotonic_ns",
            "venue_symbol",
            "symbol",
            "side",
            "level",
            "price",
            "size",
            "best_bid",
            "best_ask",
            "spread_bps",
            "bid_depth_notional",
            "ask_depth_notional",
            "liquidation_orders",
            "order_count",
            "source_record_id",
        ],
        rows,
    )


def _alignment_manifest(
    *,
    capture_started_at: str,
    capture_ended_at: str,
    capture_started_monotonic_ns: int,
    capture_ended_monotonic_ns: int,
    sample_count: int,
    completed_sample_count: int,
    trade_rows: list[Mapping[str, Any]],
    book_rows: list[Mapping[str, Any]],
    latency_samples: list[Mapping[str, Any]],
    errors: list[Mapping[str, str]],
) -> dict[str, Any]:
    trade_sequences = {int(row.get("capture_sequence", 0) or 0) for row in trade_rows}
    book_sequences = {int(row.get("capture_sequence", 0) or 0) for row in book_rows}
    exchange_times = [
        int(value)
        for value in [*[_int_or_none(row.get("exchange_ts_ms")) for row in trade_rows], *[_int_or_none(row.get("exchange_ts_ms")) for row in book_rows]]
        if value is not None
    ]
    duration_seconds = max(0.0, (capture_ended_monotonic_ns - capture_started_monotonic_ns) / 1_000_000_000.0)
    return {
        "schema_version": "btc_okx_l2_alignment_manifest_v1",
        "data_version": f"okx_public_l2_aligned_preflight_{capture_started_at.replace(':', '').replace('-', '')}",
        "capture_start": capture_started_at,
        "capture_end": capture_ended_at,
        "capture_duration_seconds": duration_seconds,
        "capture_started_monotonic_ns": capture_started_monotonic_ns,
        "capture_ended_monotonic_ns": capture_ended_monotonic_ns,
        "venue": "okx",
        "venue_symbol": VENUE_SYMBOL,
        "symbol": SYMBOL,
        "public_channels": ["GET /api/v5/market/history-trades", "GET /api/v5/market/books"],
        "public_rest_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "broker_calls_used": False,
        "clock_source": "system_utc_and_python_monotonic_ns",
        "required_time_bases": ["exchange_ts", "local_receive_ts", "monotonic_ns"],
        "checksum_or_sequence_policy": "rest_snapshot_no_exchange_sequence_checksum_available_capture_sequence_recorded",
        "requested_sample_count": sample_count,
        "completed_sample_count": completed_sample_count,
        "trade_row_count": len(trade_rows),
        "book_level_row_count": len(book_rows),
        "capture_sequences_with_trades": sorted(trade_sequences),
        "capture_sequences_with_books": sorted(book_sequences),
        "same_capture_sequence_count": len(trade_sequences & book_sequences),
        "exchange_start_ms": min(exchange_times) if exchange_times else None,
        "exchange_end_ms": max(exchange_times) if exchange_times else None,
        "gap_count": max(0, sample_count - completed_sample_count),
        "latency_sample_count": len(latency_samples),
        "error_count": len(errors),
    }


def _capture_summary(
    trade_rows: list[Mapping[str, Any]],
    book_rows: list[Mapping[str, Any]],
    latency_samples: list[Mapping[str, Any]],
) -> dict[str, Any]:
    trade_sequences = {int(row.get("capture_sequence", 0) or 0) for row in trade_rows}
    book_sequences = {int(row.get("capture_sequence", 0) or 0) for row in book_rows}
    return {
        "trade_row_count": len(trade_rows),
        "book_level_row_count": len(book_rows),
        "capture_sequences_with_trades": len(trade_sequences),
        "capture_sequences_with_books": len(book_sequences),
        "same_capture_sequence_count": len(trade_sequences & book_sequences),
        "latency_sample_count": len(latency_samples),
    }


def _best_price(rows: list[Mapping[str, Any]], *, side: str, fn: Any) -> float | None:
    prices = [_float(row.get("price")) for row in rows if str(row.get("side", "")) == side]
    clean = [price for price in prices if price is not None]
    return fn(clean) if clean else None


def _depth_notional(rows: list[Mapping[str, Any]], *, side: str) -> float:
    return sum(
        (price or 0.0) * (size or 0.0)
        for price, size in (
            (_float(row.get("price")), _float(row.get("size")))
            for row in rows
            if str(row.get("side", "")) == side
        )
    )


def _spread_bps(best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None:
        return None
    midpoint = (best_bid + best_ask) / 2.0
    if midpoint <= 0 or best_ask <= best_bid:
        return None
    return (best_ask - best_bid) / midpoint * 10_000.0


def _float(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _iso_ms(value: int | None) -> str:
    if value is None:
        return ""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


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
