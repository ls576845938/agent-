#!/usr/bin/env python3
"""Document BTC OKX public WS reconnect/resync policy for research-only L2 replay."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_scalping_readiness/latest")
DEFAULT_REPLAY_REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_ws_order_book_replay_report.json")
REPORT_SCHEMA_VERSION = "btc_true_scalping_ws_reconnect_resync_policy_report_v1"


def build_btc_true_scalping_ws_reconnect_resync_policy_report(
    *,
    repo_root: Path | None = None,
    replay_report_path: Path | None = None,
    output_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    replay_file = _resolve(root, replay_report_path or DEFAULT_REPLAY_REPORT)
    replay = _read_json(replay_file)
    replay_summary = _mapping(replay.get("replay_summary"))
    replay_validation = _mapping(replay.get("validation"))
    policy = _policy()
    validation = _validation(replay=replay, replay_summary=replay_summary, replay_validation=replay_validation)
    blockers = _blockers(replay=replay, validation=validation)
    policy_ready = bool(validation["resync_policy_ready"])
    actual_exercised = bool(validation["actual_reconnect_or_gap_exercised"])
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "venue_symbol": "BTC-USDT-SWAP",
        "scope": "research_only_ws_reconnect_resync_policy_no_candidate_no_paper_no_live",
        "status": _status(policy_ready=policy_ready, actual_exercised=actual_exercised),
        "decision": "extend_public_ws_l2_capture_with_resync_policy_then_measure_latency_and_queue",
        "next_required_action": "run_long_public_ws_capture_with_forced_disconnect_resync_test_before_event_ledger_features",
        "source_reports": {
            "ws_order_book_replay_report": _relpath(replay_file, root) if replay_file.exists() else None,
        },
        "source_replay_summary": {
            "status": str(replay.get("status", "missing") or "missing"),
            "replay_sequence_ready": bool(replay.get("replay_sequence_ready", False)),
            "snapshot_count": int(replay_summary.get("snapshot_count", 0) or 0),
            "applied_update_count": int(replay_summary.get("applied_update_count", 0) or 0),
            "sequence_gap_count": int(replay_summary.get("sequence_gap_count", 0) or 0),
            "crossed_book_count": int(replay_summary.get("crossed_book_count", 0) or 0),
            "seq_id_observed_count": int(replay_summary.get("seq_id_observed_count", 0) or 0),
            "prev_seq_id_observed_count": int(replay_summary.get("prev_seq_id_observed_count", 0) or 0),
            "connection_count": int(replay_summary.get("connection_count", 0) or 0),
            "forced_reconnect_count": int(replay_summary.get("forced_reconnect_count", 0) or 0),
            "transport_gap_count": int(replay_summary.get("transport_gap_count", 0) or 0),
        },
        "resync_policy": policy,
        "validation": validation,
        "blockers": blockers,
        "resync_policy_ready": policy_ready,
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
    output_dir = _resolve(root, output_root or DEFAULT_OUTPUT_ROOT)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "btc_true_scalping_ws_reconnect_resync_policy_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--replay-report-path", default=str(DEFAULT_REPLAY_REPORT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_true_scalping_ws_reconnect_resync_policy_report(
        repo_root=Path(args.repo_root),
        replay_report_path=Path(args.replay_report_path),
        output_root=Path(args.output_root),
        generated_at=args.generated_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") not in {
        "ws_reconnect_resync_policy_exercised_research_only_history_latency_queue_insufficient",
        "ws_reconnect_resync_policy_documented_research_only_not_exercised_history_latency_queue_insufficient",
        "ws_reconnect_resync_policy_missing_or_replay_not_ready_research_only",
    }:
        raise SystemExit(2)


def _status(*, policy_ready: bool, actual_exercised: bool) -> str:
    if policy_ready and actual_exercised:
        return "ws_reconnect_resync_policy_exercised_research_only_history_latency_queue_insufficient"
    if policy_ready:
        return "ws_reconnect_resync_policy_documented_research_only_not_exercised_history_latency_queue_insufficient"
    return "ws_reconnect_resync_policy_missing_or_replay_not_ready_research_only"


def _policy() -> dict[str, Any]:
    return {
        "policy_id": "btc_okx_public_ws_l2_reconnect_resync_policy_v1",
        "integrity_source": "seqId_prevSeqId_continuity",
        "local_book_state_machine": [
            {"state": "waiting_for_snapshot", "feature_emission_allowed": False},
            {"state": "active_segment", "feature_emission_allowed": True},
            {"state": "quarantined_segment", "feature_emission_allowed": False},
        ],
        "valid_segment_requires": [
            "snapshot_before_updates",
            "prevSeqId_equals_last_seqId_for_every_update",
            "best_bid_less_than_best_ask",
            "local_receive_ts_and_monotonic_ns_present",
        ],
        "failure_actions": [
            {
                "trigger": "update_before_snapshot",
                "action": "discard_local_book_wait_for_next_snapshot",
                "ledger_effect": "mark_segment_invalid_no_features_emitted",
            },
            {
                "trigger": "prev_seq_id_mismatch",
                "action": "quarantine_segment_discard_book_and_resubscribe",
                "ledger_effect": "close_segment_with_sequence_gap_no_features_after_gap",
            },
            {
                "trigger": "crossed_book_detected",
                "action": "quarantine_segment_discard_book_and_resubscribe",
                "ledger_effect": "close_segment_with_book_integrity_error",
            },
            {
                "trigger": "transport_disconnect_or_stale_heartbeat",
                "action": "start_new_segment_wait_for_snapshot",
                "ledger_effect": "record_transport_gap_and_suspend_features",
            },
        ],
        "feature_emission_policy": {
            "emit_features_only_from_active_valid_segment": True,
            "drop_features_after_gap_until_next_snapshot": True,
            "never_forward_partial_book_after_gap": True,
        },
    }


def _validation(
    *,
    replay: Mapping[str, Any],
    replay_summary: Mapping[str, Any],
    replay_validation: Mapping[str, Any],
) -> dict[str, Any]:
    source_ready = bool(replay.get("replay_sequence_ready", False)) and bool(
        replay_validation.get("sequence_integrity_policy_satisfied", False)
    )
    policy_documented = True
    return {
        "source_replay_report_ready": str(replay.get("status", "")) in {
            "ws_order_book_replay_sequence_policy_verified_research_only_history_insufficient",
            "ws_order_book_replay_missing_or_invalid_research_only",
        },
        "source_replay_sequence_ready": source_ready,
        "public_source_boundary_satisfied": bool(replay_validation.get("public_source_boundary_satisfied", False)),
        "snapshot_before_updates_policy_documented": policy_documented,
        "sequence_gap_handling_documented": policy_documented,
        "crossed_book_handling_documented": policy_documented,
        "transport_disconnect_handling_documented": policy_documented,
        "feature_emission_guard_documented": policy_documented,
        "actual_reconnect_or_gap_exercised": (
            int(replay_summary.get("sequence_gap_count", 0) or 0) > 0
            or int(replay_summary.get("forced_reconnect_count", 0) or 0) > 0
            or int(replay_summary.get("transport_gap_count", 0) or 0) > 0
        ),
        "minimum_research_capture_seconds_satisfied": bool(
            replay_validation.get("minimum_research_capture_seconds_satisfied", False)
        ),
        "minimum_event_ledger_history_days_satisfied": bool(
            replay_validation.get("minimum_event_ledger_history_days_satisfied", False)
        ),
        "execution_latency_model_ready": False,
        "queue_model_ready": False,
        "resync_policy_ready": source_ready
        and bool(replay_validation.get("public_source_boundary_satisfied", False))
        and policy_documented,
    }


def _blockers(*, replay: Mapping[str, Any], validation: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not bool(validation.get("source_replay_report_ready", False)):
        blockers.append("btc_ws_l2_reconnect_resync_source_replay_report_missing")
    if not bool(validation.get("source_replay_sequence_ready", False)):
        blockers.append("btc_ws_l2_reconnect_resync_source_replay_not_ready")
    if not bool(validation.get("public_source_boundary_satisfied", False)):
        blockers.append("btc_ws_l2_reconnect_resync_public_source_boundary_not_verified")
    if not bool(validation.get("actual_reconnect_or_gap_exercised", False)):
        blockers.append("btc_ws_l2_reconnect_resync_not_exercised_on_actual_disconnect_or_gap")
    if not bool(validation.get("minimum_research_capture_seconds_satisfied", False)):
        blockers.append("btc_ws_l2_reconnect_resync_research_capture_duration_below_contract")
    if not bool(validation.get("minimum_event_ledger_history_days_satisfied", False)):
        blockers.append("btc_ws_l2_reconnect_resync_history_missing_for_event_ledger_window")
    if not bool(validation.get("execution_latency_model_ready", False)):
        blockers.append("btc_execution_latency_model_missing_ws_resync_receive_latency_is_not_execution_latency")
    if not bool(validation.get("queue_model_ready", False)):
        blockers.append("btc_queue_model_missing_resync_depth_is_proxy_only")
    blockers.extend(str(item) for item in replay.get("blockers", []) if str(item))
    return _dedupe(blockers)


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


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
