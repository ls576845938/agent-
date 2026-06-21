#!/usr/bin/env python3
"""Run one isolated OKX public WS L2 capture segment and rebuild research evidence."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts.build_btc_true_scalping_ws_l2_capture_coverage_report import (
        build_btc_true_scalping_ws_l2_capture_coverage_report,
    )
    from scripts.build_btc_true_scalping_ws_l2_raw_capture_quality_report import (
        build_btc_true_scalping_ws_l2_raw_capture_quality_report,
    )
    from scripts.build_btc_true_scalping_ws_latency_queue_diagnostics_report import (
        build_btc_true_scalping_ws_latency_queue_diagnostics_report,
    )
    from scripts.build_btc_true_scalping_ws_order_book_replay_report import (
        build_btc_true_scalping_ws_order_book_replay_report,
    )
    from scripts.build_btc_true_scalping_ws_reconnect_resync_policy_report import (
        build_btc_true_scalping_ws_reconnect_resync_policy_report,
    )
    from scripts.fetch_btc_okx_public_ws_l2_raw_capture import capture_okx_public_ws_l2_raw_data
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.build_btc_true_scalping_ws_l2_capture_coverage_report import (
        build_btc_true_scalping_ws_l2_capture_coverage_report,
    )
    from scripts.build_btc_true_scalping_ws_l2_raw_capture_quality_report import (
        build_btc_true_scalping_ws_l2_raw_capture_quality_report,
    )
    from scripts.build_btc_true_scalping_ws_latency_queue_diagnostics_report import (
        build_btc_true_scalping_ws_latency_queue_diagnostics_report,
    )
    from scripts.build_btc_true_scalping_ws_order_book_replay_report import (
        build_btc_true_scalping_ws_order_book_replay_report,
    )
    from scripts.build_btc_true_scalping_ws_reconnect_resync_policy_report import (
        build_btc_true_scalping_ws_reconnect_resync_policy_report,
    )
    from scripts.fetch_btc_okx_public_ws_l2_raw_capture import capture_okx_public_ws_l2_raw_data


DEFAULT_CAPTURE_ROOT = Path("artifacts/btc_scalping_readiness")
DEFAULT_BUNDLE_ROOT = Path("data/external/btc_perpetual/okx_swap/bundles")
DEFAULT_BASE_BUNDLE_ID = "btc_okx_swap_btcusdt_history_365d_v1"
REPORT_SCHEMA_VERSION = "btc_okx_public_ws_l2_segment_capture_run_report_v1"


def run_btc_okx_public_ws_l2_segment_capture(
    *,
    repo_root: Path | None = None,
    segment_id: str | None = None,
    bundle_root: Path | None = None,
    capture_root: Path | None = None,
    execute_network: bool = False,
    duration_seconds: float = 10.0,
    max_messages: int = 2_000,
    channels: list[str] | None = None,
    recv_timeout_seconds: float = 5.0,
    forced_reconnect_after_messages: int = 0,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_now()
    segment = _segment_id(segment_id=segment_id, generated_at=generated)
    capture_base = _resolve(root, capture_root or DEFAULT_CAPTURE_ROOT)
    bundle_base = _resolve(root, bundle_root or DEFAULT_BUNDLE_ROOT)
    output_dir = capture_base / segment
    bundle_dir = bundle_base / f"{DEFAULT_BASE_BUNDLE_ID}_{segment}"
    capture_report = output_dir / "btc_okx_public_ws_l2_raw_capture_report.json"
    replay_report = output_dir / "btc_true_scalping_ws_order_book_replay_report.json"
    runner_report = output_dir / "btc_okx_public_ws_l2_segment_capture_run_report.json"
    effective_channels = channels or ["trades", "books"]
    bundle_dir.mkdir(parents=True, exist_ok=True)

    capture = capture_okx_public_ws_l2_raw_data(
        repo_root=root,
        bundle_dir=bundle_dir,
        capture_report_path=capture_report,
        execute_network=execute_network,
        duration_seconds=duration_seconds,
        max_messages=max_messages,
        channels=effective_channels,
        recv_timeout_seconds=recv_timeout_seconds,
        forced_reconnect_after_messages=forced_reconnect_after_messages,
        captured_at=generated,
    )

    built_reports: dict[str, Any] = {}
    post_capture_reports_built = False
    if execute_network and capture.get("status") in {"verified_preflight", "partial"}:
        quality = build_btc_true_scalping_ws_l2_raw_capture_quality_report(
            repo_root=root,
            ws_capture_report_path=capture_report,
            output_root=output_dir,
            generated_at=generated,
        )
        replay = build_btc_true_scalping_ws_order_book_replay_report(
            repo_root=root,
            ws_capture_report_path=capture_report,
            output_root=output_dir,
            generated_at=generated,
        )
        resync = build_btc_true_scalping_ws_reconnect_resync_policy_report(
            repo_root=root,
            replay_report_path=replay_report,
            output_root=output_dir,
            generated_at=generated,
        )
        latency_queue = build_btc_true_scalping_ws_latency_queue_diagnostics_report(
            repo_root=root,
            ws_capture_report_path=capture_report,
            replay_report_path=replay_report,
            output_root=output_dir,
            generated_at=generated,
        )
        coverage = build_btc_true_scalping_ws_l2_capture_coverage_report(
            repo_root=root,
            capture_root=capture_base,
            output_root=capture_base / "latest",
            generated_at=generated,
        )
        built_reports = {
            "raw_capture_quality_status": quality.get("status"),
            "order_book_replay_status": replay.get("status"),
            "reconnect_resync_policy_status": resync.get("status"),
            "latency_queue_diagnostics_status": latency_queue.get("status"),
            "coverage_status": coverage.get("status"),
        }
        post_capture_reports_built = True

    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "btc",
        "symbol": "BTCUSDT",
        "venue_symbol": "BTC-USDT-SWAP",
        "scope": "research_only_public_ws_l2_segment_capture_no_candidate_no_paper_no_live",
        "segment_id": segment,
        "status": _status(execute_network=execute_network, capture=capture, reports_built=post_capture_reports_built),
        "decision": "continue_accumulating_public_ws_l2_history_before_true_scalping",
        "next_required_action": "repeat_public_ws_l2_segment_capture_until_coverage_report_thresholds_are_met",
        "capture_root": _relpath(capture_base, root),
        "output_root": _relpath(output_dir, root),
        "selected_bundle_dir": _relpath(bundle_dir, root),
        "requested": {
            "execute_network": execute_network,
            "duration_seconds": max(0.1, float(duration_seconds)),
            "max_messages": max(1, int(max_messages)),
            "channels": effective_channels,
            "recv_timeout_seconds": max(0.1, float(recv_timeout_seconds)),
            "forced_reconnect_after_messages": max(0, int(forced_reconnect_after_messages)),
        },
        "source_reports": {
            "ws_capture_report": _relpath(capture_report, root),
            "raw_capture_quality_report": _relpath(
                output_dir / "btc_true_scalping_ws_l2_raw_capture_quality_report.json",
                root,
            )
            if post_capture_reports_built
            else None,
            "order_book_replay_report": _relpath(replay_report, root) if post_capture_reports_built else None,
            "reconnect_resync_policy_report": _relpath(
                output_dir / "btc_true_scalping_ws_reconnect_resync_policy_report.json",
                root,
            )
            if post_capture_reports_built
            else None,
            "latency_queue_diagnostics_report": _relpath(
                output_dir / "btc_true_scalping_ws_latency_queue_diagnostics_report.json",
                root,
            )
            if post_capture_reports_built
            else None,
            "coverage_report": _relpath(
                capture_base / "latest/btc_true_scalping_ws_l2_capture_coverage_report.json",
                root,
            )
            if post_capture_reports_built
            else None,
        },
        "capture_status": capture.get("status"),
        "capture_network_called": bool(capture.get("network_called", False)),
        "post_capture_reports_built": post_capture_reports_built,
        "built_report_statuses": built_reports,
        "blockers": _blockers(capture=capture, reports_built=post_capture_reports_built, execute_network=execute_network),
        "contract_satisfied": False,
        "event_ledger_feature_validation_allowed": False,
        "true_scalping_allowed": False,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "guardrails": {
            "research_only": True,
            "production_ready": False,
            "paper_or_live_usable": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "broker_calls_allowed": False,
            "real_orders_created": False,
            "future_label_used_for_signal": False,
            "lookahead_used_for_signal": False,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(payload, runner_report)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--segment-id", default="")
    parser.add_argument("--bundle-root", default=str(DEFAULT_BUNDLE_ROOT))
    parser.add_argument("--capture-root", default=str(DEFAULT_CAPTURE_ROOT))
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--duration-seconds", type=float, default=10.0)
    parser.add_argument("--max-messages", type=int, default=2_000)
    parser.add_argument("--channels", default="trades,books")
    parser.add_argument("--recv-timeout-seconds", type=float, default=5.0)
    parser.add_argument("--forced-reconnect-after-messages", type=int, default=0)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = run_btc_okx_public_ws_l2_segment_capture(
        repo_root=Path(args.repo_root),
        segment_id=args.segment_id or None,
        bundle_root=Path(args.bundle_root),
        capture_root=Path(args.capture_root),
        execute_network=bool(args.execute_network),
        duration_seconds=args.duration_seconds,
        max_messages=args.max_messages,
        channels=_split_channels(args.channels),
        recv_timeout_seconds=args.recv_timeout_seconds,
        forced_reconnect_after_messages=args.forced_reconnect_after_messages,
        generated_at=args.generated_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") not in {
        "dry_run_public_ws_l2_segment_capture_planned",
        "public_ws_l2_segment_capture_verified_research_only",
        "public_ws_l2_segment_capture_partial_research_only",
        "public_ws_l2_segment_capture_failed_or_rejected_research_only",
    }:
        raise SystemExit(2)


def _status(*, execute_network: bool, capture: Mapping[str, Any], reports_built: bool) -> str:
    if not execute_network:
        return "dry_run_public_ws_l2_segment_capture_planned"
    if capture.get("status") == "verified_preflight" and reports_built:
        return "public_ws_l2_segment_capture_verified_research_only"
    if capture.get("status") == "partial":
        return "public_ws_l2_segment_capture_partial_research_only"
    return "public_ws_l2_segment_capture_failed_or_rejected_research_only"


def _blockers(*, capture: Mapping[str, Any], reports_built: bool, execute_network: bool) -> list[str]:
    blockers = [str(item) for item in capture.get("blockers", []) if str(item)]
    if not execute_network:
        blockers.append("btc_ws_l2_segment_capture_dry_run_no_network_executed")
    elif not reports_built:
        blockers.append("btc_ws_l2_segment_capture_post_capture_reports_not_built")
    blockers.append("btc_true_scalping_locked_until_coverage_execution_latency_and_queue_models_are_ready")
    return _dedupe(blockers)


def _segment_id(*, segment_id: str | None, generated_at: str) -> str:
    value = segment_id or f"ws_l2_segment_{generated_at}"
    clean = (
        value.strip()
        .replace(":", "")
        .replace("-", "")
        .replace("+", "")
        .replace(".", "")
        .replace("T", "t")
    )
    clean = clean.replace("Z", "z")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", clean):
        raise ValueError("segment_id must be a simple path segment")
    return clean


def _split_channels(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json_atomic(payload: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        json.dump(dict(payload), handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_name = handle.name
    Path(temp_name).replace(path)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
