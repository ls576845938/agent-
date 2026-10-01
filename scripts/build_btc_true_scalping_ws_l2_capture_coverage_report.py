#!/usr/bin/env python3
"""Aggregate public WS L2 capture coverage for BTC scalping research readiness."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_CAPTURE_ROOT = Path("artifacts/btc_scalping_readiness")
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_scalping_readiness/latest")
REPORT_SCHEMA_VERSION = "btc_true_scalping_ws_l2_capture_coverage_report_v1"
MIN_RESEARCH_CAPTURE_SECONDS = 3600.0
MIN_EVENT_LEDGER_HISTORY_DAYS = 30.0


def build_btc_true_scalping_ws_l2_capture_coverage_report(
    *,
    repo_root: Path | None = None,
    capture_root: Path | None = None,
    output_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    capture_base = _resolve(root, capture_root or DEFAULT_CAPTURE_ROOT)
    output_dir = _resolve(root, output_root or DEFAULT_OUTPUT_ROOT)
    sessions = _sessions(root=root, capture_base=capture_base)
    totals = _coverage_totals(sessions)
    validation = _validation(sessions=sessions, totals=totals)
    blockers = _blockers(validation=validation, totals=totals)
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "venue_symbol": "BTC-USDT-SWAP",
        "scope": "research_only_ws_l2_capture_coverage_no_candidate_no_paper_no_live",
        "status": _status(validation=validation),
        "decision": "continue_accumulating_public_ws_l2_history_before_true_scalping",
        "next_required_action": "run_segmented_public_ws_l2_capture_until_minimum_research_seconds_and_history_days_are_met",
        "thresholds": {
            "minimum_research_capture_seconds": MIN_RESEARCH_CAPTURE_SECONDS,
            "minimum_event_ledger_history_days": MIN_EVENT_LEDGER_HISTORY_DAYS,
            "required_channels": ["trades", "books"],
        },
        "capture_root": _relpath(capture_base, root),
        "sessions": sessions,
        "coverage_totals": totals,
        "validation": validation,
        "blockers": blockers,
        "coverage_contract_satisfied": bool(validation["coverage_contract_satisfied"]),
        "contract_satisfied": False,
        "event_ledger_feature_validation_allowed": False,
        "execution_latency_model_ready": False,
        "queue_model_ready": False,
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
    (output_dir / "btc_true_scalping_ws_l2_capture_coverage_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--capture-root", default=str(DEFAULT_CAPTURE_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_true_scalping_ws_l2_capture_coverage_report(
        repo_root=Path(args.repo_root),
        capture_root=Path(args.capture_root),
        output_root=Path(args.output_root),
        generated_at=args.generated_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") not in {
        "ws_l2_capture_coverage_accumulating_research_only_history_insufficient",
        "ws_l2_capture_coverage_thresholds_met_research_only_execution_queue_locked",
        "ws_l2_capture_coverage_missing_or_invalid_research_only",
    }:
        raise SystemExit(2)


def _sessions(*, root: Path, capture_base: Path) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for capture_report_path in sorted(capture_base.glob("*/btc_okx_public_ws_l2_raw_capture_report.json")):
        session_dir = capture_report_path.parent
        capture = _read_json(capture_report_path)
        manifest = _mapping(capture.get("manifest"))
        selected_bundle_dir = str(capture.get("selected_bundle_dir", "") or "")
        replay = _read_json(session_dir / "btc_true_scalping_ws_order_book_replay_report.json")
        resync = _read_json(session_dir / "btc_true_scalping_ws_reconnect_resync_policy_report.json")
        latency_queue = _read_json(session_dir / "btc_true_scalping_ws_latency_queue_diagnostics_report.json")
        channel_counts = _mapping(capture.get("channel_counts") or manifest.get("channel_counts"))
        duration = _float(manifest.get("capture_duration_seconds")) or 0.0
        session = {
            "session_id": session_dir.name,
            "capture_report": _relpath(capture_report_path, root),
            "selected_bundle_dir": selected_bundle_dir,
            "status": str(capture.get("status", "missing") or "missing"),
            "public_ws_only": bool(capture.get("public_ws_only", False) or manifest.get("public_ws_only", False)),
            "private_endpoint_used": bool(capture.get("private_endpoint_used", True) or manifest.get("private_endpoint_used", True)),
            "order_endpoint_used": bool(capture.get("order_endpoint_used", True) or manifest.get("order_endpoint_used", True)),
            "broker_calls_used": bool(capture.get("broker_calls_used", True) or manifest.get("broker_calls_used", True)),
            "capture_start": str(manifest.get("capture_start", "") or ""),
            "capture_end": str(manifest.get("capture_end", "") or ""),
            "capture_duration_seconds": duration,
            "event_ledger_history_days": duration / 86_400.0,
            "message_count": int(capture.get("message_count", manifest.get("message_count", 0)) or 0),
            "data_message_count": int(capture.get("data_message_count", manifest.get("data_message_count", 0)) or 0),
            "trade_message_count": int(channel_counts.get("trades", 0) or 0),
            "book_message_count": int(channel_counts.get("books", 0) or 0),
            "connection_count": int(capture.get("connection_count", manifest.get("connection_count", 0)) or 0),
            "forced_reconnect_count": int(capture.get("forced_reconnect_count", manifest.get("forced_reconnect_count", 0)) or 0),
            "replay_sequence_ready": bool(replay.get("replay_sequence_ready", False)),
            "replay_report": _relpath(session_dir / "btc_true_scalping_ws_order_book_replay_report.json", root)
            if (session_dir / "btc_true_scalping_ws_order_book_replay_report.json").exists()
            else None,
            "resync_policy_ready": bool(resync.get("resync_policy_ready", False)),
            "actual_reconnect_or_gap_exercised": bool(
                _mapping(resync.get("validation")).get("actual_reconnect_or_gap_exercised", False)
            ),
            "resync_report": _relpath(session_dir / "btc_true_scalping_ws_reconnect_resync_policy_report.json", root)
            if (session_dir / "btc_true_scalping_ws_reconnect_resync_policy_report.json").exists()
            else None,
            "proxy_diagnostics_ready": bool(latency_queue.get("proxy_diagnostics_ready", False)),
            "latency_queue_report": _relpath(
                session_dir / "btc_true_scalping_ws_latency_queue_diagnostics_report.json", root
            )
            if (session_dir / "btc_true_scalping_ws_latency_queue_diagnostics_report.json").exists()
            else None,
        }
        sessions.append(session)
    return sessions


def _coverage_totals(sessions: list[Mapping[str, Any]]) -> dict[str, Any]:
    valid_sessions = [
        session
        for session in sessions
        if session.get("status") == "verified_preflight"
        and session.get("public_ws_only") is True
        and session.get("private_endpoint_used") is False
        and session.get("order_endpoint_used") is False
        and session.get("broker_calls_used") is False
    ]
    total_duration = sum(float(session.get("capture_duration_seconds", 0.0) or 0.0) for session in valid_sessions)
    starts = [_datetime_or_none(session.get("capture_start")) for session in valid_sessions]
    ends = [_datetime_or_none(session.get("capture_end")) for session in valid_sessions]
    clean_starts = [value for value in starts if value is not None]
    clean_ends = [value for value in ends if value is not None]
    span_days = 0.0
    if clean_starts and clean_ends:
        span_days = max(0.0, (max(clean_ends) - min(clean_starts)).total_seconds() / 86_400.0)
    return {
        "session_count": len(sessions),
        "verified_public_session_count": len(valid_sessions),
        "total_capture_duration_seconds": total_duration,
        "total_event_ledger_history_days": total_duration / 86_400.0,
        "calendar_span_days": span_days,
        "remaining_research_capture_seconds": max(0.0, MIN_RESEARCH_CAPTURE_SECONDS - total_duration),
        "remaining_event_ledger_history_days": max(0.0, MIN_EVENT_LEDGER_HISTORY_DAYS - (total_duration / 86_400.0)),
        "remaining_calendar_span_days": max(0.0, MIN_EVENT_LEDGER_HISTORY_DAYS - span_days),
        "total_message_count": sum(int(session.get("message_count", 0) or 0) for session in valid_sessions),
        "total_data_message_count": sum(int(session.get("data_message_count", 0) or 0) for session in valid_sessions),
        "total_trade_message_count": sum(int(session.get("trade_message_count", 0) or 0) for session in valid_sessions),
        "total_book_message_count": sum(int(session.get("book_message_count", 0) or 0) for session in valid_sessions),
        "total_forced_reconnect_count": sum(int(session.get("forced_reconnect_count", 0) or 0) for session in valid_sessions),
        "replay_sequence_ready_session_count": sum(1 for session in valid_sessions if session.get("replay_sequence_ready") is True),
        "resync_policy_ready_session_count": sum(1 for session in valid_sessions if session.get("resync_policy_ready") is True),
        "actual_reconnect_or_gap_exercised_session_count": sum(
            1 for session in valid_sessions if session.get("actual_reconnect_or_gap_exercised") is True
        ),
        "proxy_diagnostics_ready_session_count": sum(
            1 for session in valid_sessions if session.get("proxy_diagnostics_ready") is True
        ),
    }


def _validation(*, sessions: list[Mapping[str, Any]], totals: Mapping[str, Any]) -> dict[str, Any]:
    verified_count = int(totals.get("verified_public_session_count", 0) or 0)
    duration_ok = float(totals.get("total_capture_duration_seconds", 0.0) or 0.0) >= MIN_RESEARCH_CAPTURE_SECONDS
    history_ok = float(totals.get("total_event_ledger_history_days", 0.0) or 0.0) >= MIN_EVENT_LEDGER_HISTORY_DAYS
    calendar_ok = float(totals.get("calendar_span_days", 0.0) or 0.0) >= MIN_EVENT_LEDGER_HISTORY_DAYS
    all_replay_ready = verified_count > 0 and int(totals.get("replay_sequence_ready_session_count", 0) or 0) == verified_count
    all_proxy_ready = verified_count > 0 and int(totals.get("proxy_diagnostics_ready_session_count", 0) or 0) == verified_count
    return {
        "capture_reports_present": bool(sessions),
        "verified_public_sessions_present": verified_count > 0,
        "public_source_boundary_satisfied": verified_count == len(sessions) and verified_count > 0,
        "required_channels_observed": int(totals.get("total_trade_message_count", 0) or 0) > 0
        and int(totals.get("total_book_message_count", 0) or 0) > 0,
        "all_verified_sessions_have_replay_sequence_ready": all_replay_ready,
        "all_verified_sessions_have_proxy_diagnostics_ready": all_proxy_ready,
        "resync_policy_exercised": int(totals.get("actual_reconnect_or_gap_exercised_session_count", 0) or 0) > 0,
        "minimum_research_capture_seconds_satisfied": duration_ok,
        "minimum_event_ledger_history_days_satisfied": history_ok,
        "minimum_calendar_span_days_satisfied": calendar_ok,
        "execution_latency_model_ready": False,
        "queue_model_ready": False,
        "coverage_contract_satisfied": duration_ok and history_ok and calendar_ok and all_replay_ready and all_proxy_ready,
    }


def _blockers(*, validation: Mapping[str, Any], totals: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not bool(validation.get("capture_reports_present", False)):
        blockers.append("btc_ws_l2_capture_coverage_reports_missing")
    if not bool(validation.get("verified_public_sessions_present", False)):
        blockers.append("btc_ws_l2_capture_coverage_verified_public_sessions_missing")
    if not bool(validation.get("public_source_boundary_satisfied", False)):
        blockers.append("btc_ws_l2_capture_coverage_public_source_boundary_not_satisfied")
    if not bool(validation.get("required_channels_observed", False)):
        blockers.append("btc_ws_l2_capture_coverage_required_trades_books_channels_missing")
    if not bool(validation.get("all_verified_sessions_have_replay_sequence_ready", False)):
        blockers.append("btc_ws_l2_capture_coverage_replay_sequence_not_ready_for_all_sessions")
    if not bool(validation.get("all_verified_sessions_have_proxy_diagnostics_ready", False)):
        blockers.append("btc_ws_l2_capture_coverage_latency_queue_proxy_not_ready_for_all_sessions")
    if not bool(validation.get("resync_policy_exercised", False)):
        blockers.append("btc_ws_l2_capture_coverage_resync_policy_not_exercised")
    if not bool(validation.get("minimum_research_capture_seconds_satisfied", False)):
        blockers.append(
            "btc_ws_l2_capture_coverage_research_seconds_short_"
            f"{float(totals.get('remaining_research_capture_seconds', 0.0) or 0.0):.3f}"
        )
    if not bool(validation.get("minimum_event_ledger_history_days_satisfied", False)):
        blockers.append(
            "btc_ws_l2_capture_coverage_event_history_days_short_"
            f"{float(totals.get('remaining_event_ledger_history_days', 0.0) or 0.0):.6f}"
        )
    if not bool(validation.get("minimum_calendar_span_days_satisfied", False)):
        blockers.append(
            "btc_ws_l2_capture_coverage_calendar_span_days_short_"
            f"{float(totals.get('remaining_calendar_span_days', 0.0) or 0.0):.6f}"
        )
    if not bool(validation.get("execution_latency_model_ready", False)):
        blockers.append("btc_execution_latency_model_missing_public_ws_coverage_is_not_order_latency")
    if not bool(validation.get("queue_model_ready", False)):
        blockers.append("btc_queue_model_missing_public_l2_coverage_is_not_exchange_queue_position")
    return _dedupe(blockers)


def _status(*, validation: Mapping[str, Any]) -> str:
    if not bool(validation.get("capture_reports_present", False)) or not bool(
        validation.get("verified_public_sessions_present", False)
    ):
        return "ws_l2_capture_coverage_missing_or_invalid_research_only"
    if bool(validation.get("coverage_contract_satisfied", False)):
        return "ws_l2_capture_coverage_thresholds_met_research_only_execution_queue_locked"
    return "ws_l2_capture_coverage_accumulating_research_only_history_insufficient"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()
    except Exception:  # noqa: BLE001 - metadata only.
        return "unknown"


def _datetime_or_none(value: object) -> datetime | None:
    text = str(value or "")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
