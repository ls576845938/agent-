#!/usr/bin/env python3
"""Dry-run-first OKX public microstructure capture for BTC scalping evidence."""

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
    from scripts.build_btc_perpetual_data_bundle_manifest import build_btc_perpetual_data_bundle_manifest, write_manifest
    from scripts.fetch_btc_okx_swap_public_data import (
        LICENSE_NOTE,
        SOURCE_PROVIDER,
        SYMBOL,
        VENUE_SYMBOL,
        _book_depth_rows,
        _file_facts,
        _okx_request,
        _relpath,
        _trade_rows,
        _utc_z_now,
        _write_agg_trades,
        _write_json_atomic,
        _write_order_book_depth,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
    from quant_crypto.data.okx_swap_public import OkxSwapPublicCollector
    from scripts.build_btc_perpetual_data_bundle_manifest import build_btc_perpetual_data_bundle_manifest, write_manifest
    from scripts.fetch_btc_okx_swap_public_data import (
        LICENSE_NOTE,
        SOURCE_PROVIDER,
        SYMBOL,
        VENUE_SYMBOL,
        _book_depth_rows,
        _file_facts,
        _okx_request,
        _relpath,
        _trade_rows,
        _utc_z_now,
        _write_agg_trades,
        _write_json_atomic,
        _write_order_book_depth,
    )


DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_CAPTURE_REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_okx_microstructure_capture_report.json")


def capture_okx_microstructure_public_data(
    *,
    repo_root: Path,
    config_path: Path = DEFAULT_CONFIG,
    bundle_dir: Path | None = None,
    capture_report_path: Path = DEFAULT_CAPTURE_REPORT,
    execute_network: bool = False,
    request_sleep_seconds: float = 0.12,
    captured_at: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    captured = captured_at or _utc_z_now()
    selected_bundle = _resolve(root, bundle_dir) if bundle_dir else selected_btc_perpetual_bundle_dir(root, _resolve(root, config_path))
    report_path = _resolve(root, capture_report_path)
    blockers: list[str] = []
    if selected_bundle is None:
        blockers.append("btc_okx_selected_bundle_missing")
        selected_bundle = root / "data/external/btc_perpetual/okx_swap/bundles/missing"
    output_root = selected_bundle.parent
    planner = OkxSwapPublicCollector(
        output_root=output_root,
        dry_run=True,
        allow_network=False,
    )
    collector = OkxSwapPublicCollector(
        output_root=output_root,
        dry_run=not execute_network,
        allow_network=execute_network,
    )
    planned_requests = [
        planner.request_by_name("history_trades", {"instId": VENUE_SYMBOL, "limit": "100"}),
        planner.request_by_name("books", {"instId": VENUE_SYMBOL, "sz": "50"}),
    ]
    if not execute_network:
        payload = {
            "schema_version": "btc_okx_microstructure_capture_report_v1",
            "status": "dry_run",
            "generated_at": captured,
            "selected_bundle_dir": _relpath(selected_bundle, root),
            "network_called": False,
            "public_rest_only": True,
            "api_key_used": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "planned_requests": planned_requests,
            "files": [],
            "blockers": blockers,
        }
        _write_json_atomic(payload, report_path)
        return payload

    if not selected_bundle.exists():
        blockers.append("btc_okx_selected_bundle_dir_missing")
    files: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    latency_samples: list[dict[str, Any]] = []
    if not blockers:
        try:
            trade_response = _okx_request(collector, "history_trades", {"instId": VENUE_SYMBOL, "limit": "100"})
            latency_samples.append(_latency_sample(trade_response))
            _write_agg_trades(selected_bundle / "agg_trades.csv", _trade_rows(trade_response["payload"].get("data", [])))
            files.append(_file_facts(selected_bundle / "agg_trades.csv", root))
            if request_sleep_seconds > 0:
                time.sleep(request_sleep_seconds)
        except Exception as exc:  # noqa: BLE001 - persisted as evidence.
            blockers.append("btc_okx_agg_trades_capture_failed")
            errors.append({"role": "agg_trades", "error": repr(exc)})
        try:
            book_response = _okx_request(collector, "books", {"instId": VENUE_SYMBOL, "sz": "50"})
            latency_samples.append(_latency_sample(book_response))
            _write_order_book_depth(
                selected_bundle / "order_book_depth.csv",
                _book_depth_rows(book_response["payload"].get("data", [])),
            )
            files.append(_file_facts(selected_bundle / "order_book_depth.csv", root))
        except Exception as exc:  # noqa: BLE001 - persisted as evidence.
            blockers.append("btc_okx_order_book_depth_capture_failed")
            errors.append({"role": "order_book_depth", "error": repr(exc)})
    manifest_path = None
    if not blockers:
        manifest = build_btc_perpetual_data_bundle_manifest(
            bundle_dir=selected_bundle,
            bundle_id=selected_bundle.name,
            source_type="production",
            source_provider=SOURCE_PROVIDER,
            exchange=SOURCE_PROVIDER,
            symbol=SYMBOL,
            market_type="usds_m_perpetual",
            promotion_clean_allowed=True,
            license_note=LICENSE_NOTE,
            created_at=_iso_utc(captured),
        )
        manifest_path = _relpath(Path(write_manifest(manifest, selected_bundle)), root)
        blockers.extend(
            str(item)
            for item in manifest.get("blockers", [])
            if str(item)
            not in {
                "btc_liquidation_snapshots_missing_diagnostic_only",
                "btc_open_interest_history_not_verified_diagnostic_partial",
                "diagnostic_only_not_gate_evidence",
            }
        )
    payload = {
        "schema_version": "btc_okx_microstructure_capture_report_v1",
        "status": "verified" if not blockers else "rejected",
        "generated_at": captured,
        "selected_bundle_dir": _relpath(selected_bundle, root),
        "manifest_path": manifest_path,
        "network_called": True,
        "public_rest_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "planned_requests": planned_requests,
        "latency_samples": latency_samples,
        "files": files,
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
    parser.add_argument("--request-sleep-seconds", type=float, default=0.12)
    parser.add_argument("--captured-at", default="")
    args = parser.parse_args()
    payload = capture_okx_microstructure_public_data(
        repo_root=Path(args.repo_root),
        config_path=Path(args.config_path),
        bundle_dir=Path(args.bundle_dir) if args.bundle_dir else None,
        capture_report_path=Path(args.capture_report),
        execute_network=bool(args.execute_network),
        request_sleep_seconds=args.request_sleep_seconds,
        captured_at=args.captured_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") not in {"verified", "dry_run"}:
        raise SystemExit(2)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _iso_utc(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return datetime.now(timezone.utc).isoformat()


def _latency_sample(response: Mapping[str, Any]) -> dict[str, Any]:
    duration = response.get("duration_ms")
    return {
        "endpoint": str(response.get("endpoint", "")),
        "url": str(response.get("url", "")),
        "network_called": bool(response.get("network_called", False)),
        "duration_ms": float(duration) if isinstance(duration, (int, float)) else None,
    }


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
