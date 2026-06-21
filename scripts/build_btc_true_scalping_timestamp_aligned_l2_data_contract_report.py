#!/usr/bin/env python3
"""Build the research-only BTC timestamp-aligned L2/tick data contract report."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_scalping_readiness/latest")
DEFAULT_SAMPLE_QUALITY = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_l2_sample_quality_report.json")
DEFAULT_FEATURE_DIAGNOSTICS = Path(
    "artifacts/btc_scalping_readiness/latest/btc_true_scalping_l2_feature_diagnostics_report.json"
)
DEFAULT_CAPTURE_REPORT = Path(
    "artifacts/btc_scalping_readiness/latest/btc_okx_l2_microstructure_sample_capture_report.json"
)
REPORT_SCHEMA_VERSION = "btc_true_scalping_timestamp_aligned_l2_data_contract_report_v1"


def build_btc_true_scalping_timestamp_aligned_l2_data_contract_report(
    *,
    repo_root: Path | None = None,
    sample_quality_path: Path | None = None,
    feature_diagnostics_path: Path | None = None,
    capture_report_path: Path | None = None,
    output_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    sample_quality_file = _resolve(root, sample_quality_path or DEFAULT_SAMPLE_QUALITY)
    feature_diagnostics_file = _resolve(root, feature_diagnostics_path or DEFAULT_FEATURE_DIAGNOSTICS)
    capture_file = _resolve(root, capture_report_path or DEFAULT_CAPTURE_REPORT)
    sample_quality = _read_json(sample_quality_file)
    feature_diagnostics = _read_json(feature_diagnostics_file)
    capture = _read_json(capture_file)
    current_evidence = _current_evidence(
        sample_quality=sample_quality,
        feature_diagnostics=feature_diagnostics,
        capture=capture,
    )
    validation_gates = _validation_gates(current_evidence)
    blockers = _blockers(
        sample_quality=sample_quality,
        feature_diagnostics=feature_diagnostics,
        capture=capture,
        validation_gates=validation_gates,
    )
    source_ready = (
        sample_quality.get("status") == "public_l2_sample_evidence_ready_research_only"
        and feature_diagnostics.get("status") == "l2_feature_diagnostics_ready_research_only_backtest_blocked"
        and capture.get("status") == "verified"
    )
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "venue_symbol": "BTC-USDT-SWAP",
        "scope": "research_only_timestamp_aligned_l2_data_contract_no_candidate_no_paper_no_live",
        "status": "timestamp_aligned_l2_capture_required_research_only"
        if source_ready
        else "timestamp_aligned_l2_contract_blocked_missing_source_evidence",
        "decision": "collect_timestamp_aligned_public_l2_tick_window_before_true_scalping_event_ledger",
        "next_required_action": "run_public_l2_trade_book_capture_or_import_archive_then_validate_same_window_alignment",
        "source_reports": {
            "sample_quality": _relpath(sample_quality_file, root) if sample_quality_file.exists() else None,
            "feature_diagnostics": _relpath(feature_diagnostics_file, root) if feature_diagnostics_file.exists() else None,
            "capture_report": _relpath(capture_file, root) if capture_file.exists() else None,
        },
        "selected_bundle_dir": str(
            capture.get("selected_bundle_dir")
            or sample_quality.get("selected_bundle_dir")
            or feature_diagnostics.get("selected_bundle_dir")
            or ""
        ),
        "current_evidence": current_evidence,
        "minimum_capture_contract": _minimum_capture_contract(),
        "required_datasets": _required_datasets(),
        "validation_gates": validation_gates,
        "blockers": blockers,
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
    (output_dir / "btc_true_scalping_timestamp_aligned_l2_data_contract_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--sample-quality-path", default=str(DEFAULT_SAMPLE_QUALITY))
    parser.add_argument("--feature-diagnostics-path", default=str(DEFAULT_FEATURE_DIAGNOSTICS))
    parser.add_argument("--capture-report-path", default=str(DEFAULT_CAPTURE_REPORT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_true_scalping_timestamp_aligned_l2_data_contract_report(
        repo_root=Path(args.repo_root),
        sample_quality_path=Path(args.sample_quality_path),
        feature_diagnostics_path=Path(args.feature_diagnostics_path),
        capture_report_path=Path(args.capture_report_path),
        output_root=Path(args.output_root),
        generated_at=args.generated_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") != "timestamp_aligned_l2_capture_required_research_only":
        raise SystemExit(2)


def _current_evidence(
    *,
    sample_quality: Mapping[str, Any],
    feature_diagnostics: Mapping[str, Any],
    capture: Mapping[str, Any],
) -> dict[str, Any]:
    quality = _mapping(sample_quality.get("sample_quality"))
    alignment = _mapping(feature_diagnostics.get("historical_alignment"))
    source_files = _mapping(feature_diagnostics.get("source_files"))
    feature_candidates = feature_diagnostics.get("feature_candidates")
    return {
        "capture_status": str(capture.get("status", "missing") or "missing"),
        "sample_quality_status": str(sample_quality.get("status", "missing") or "missing"),
        "feature_diagnostics_status": str(feature_diagnostics.get("status", "missing") or "missing"),
        "public_rest_only": bool(capture.get("public_rest_only", False)),
        "bounded_public_rest_sample_only": bool(sample_quality.get("bounded_public_rest_sample_only", False)),
        "private_endpoint_used": bool(capture.get("private_endpoint_used", False)),
        "order_endpoint_used": bool(capture.get("order_endpoint_used", False)),
        "network_called": bool(capture.get("network_called", False)),
        "completed_sample_count": _int(quality.get("completed_sample_count")),
        "trade_row_count": _int(quality.get("trade_row_count")),
        "book_level_row_count": _int(quality.get("book_level_row_count")),
        "valid_top_of_book_snapshot_count": _int(quality.get("valid_top_of_book_snapshot_count")),
        "latency_sample_count": _int(quality.get("latency_sample_count")),
        "book_snapshot_count": _int(_mapping(feature_diagnostics.get("feature_diagnostics")).get("book_snapshot_count")),
        "trade_flow_sample_count": _int(_mapping(feature_diagnostics.get("feature_diagnostics")).get("trade_flow_sample_count")),
        "joined_sample_count": _int(_mapping(feature_diagnostics.get("feature_diagnostics")).get("joined_sample_count")),
        "feature_candidate_count": len(feature_candidates) if isinstance(feature_candidates, list) else 0,
        "source_files": {
            "agg_trades_samples": _mapping(source_files.get("agg_trades_samples")),
            "order_book_depth_samples": _mapping(source_files.get("order_book_depth_samples")),
        },
        "historical_alignment_status": str(alignment.get("status", "missing") or "missing"),
        "sample_capture_start": alignment.get("sample_capture_start"),
        "sample_capture_end": alignment.get("sample_capture_end"),
        "backtest_start": alignment.get("backtest_start"),
        "backtest_end": alignment.get("backtest_end"),
        "overlaps_backtest_window": bool(alignment.get("overlaps_backtest_window", False)),
        "timestamp_aligned_l2_history_available": bool(alignment.get("timestamp_aligned_l2_history_available", False)),
        "same_window_trade_book_alignment_available": False,
        "causal_event_ledger_join_allowed": bool(alignment.get("causal_event_ledger_join_allowed", False)),
        "rest_latency_observed_but_execution_latency_model_missing": _int(quality.get("latency_sample_count")) > 0,
    }


def _minimum_capture_contract() -> dict[str, Any]:
    return {
        "venue": "okx",
        "venue_symbol": "BTC-USDT-SWAP",
        "public_data_only": True,
        "api_key_allowed": False,
        "private_endpoints_allowed": False,
        "order_endpoints_allowed": False,
        "broker_calls_allowed": False,
        "minimum_research_capture_seconds": 3600,
        "minimum_event_ledger_history_days": 30,
        "minimum_book_depth_levels": 50,
        "required_time_bases": ["exchange_ts", "local_receive_ts", "monotonic_ns"],
        "required_alignment_max_clock_skew_ms": 250,
        "required_capture_manifest": "l2_alignment_manifest.json",
        "required_cost_model_inputs": [
            "observed_top_of_book_spread_bps",
            "visible_depth_notional",
            "trade_aggressor_flow",
            "capture_receive_latency_ms",
            "missed_fill_proxy",
            "queue_position_proxy",
        ],
    }


def _required_datasets() -> list[dict[str, Any]]:
    return [
        {
            "dataset_id": "agg_trades_aligned",
            "file_name": "agg_trades_aligned.csv",
            "purpose": "same-window public trade flow and aggressor imbalance",
            "required": True,
            "minimum_records": 1,
            "timestamp_alignment_required": True,
            "required_fields": [
                "exchange_ts",
                "local_receive_ts",
                "monotonic_ns",
                "trade_id",
                "price",
                "size",
                "side",
            ],
        },
        {
            "dataset_id": "order_book_depth_aligned",
            "file_name": "order_book_depth_aligned.csv",
            "purpose": "same-window top-of-book spread, depth, and queue proxy evidence",
            "required": True,
            "minimum_records": 3600,
            "timestamp_alignment_required": True,
            "required_fields": [
                "exchange_ts",
                "local_receive_ts",
                "monotonic_ns",
                "side",
                "level",
                "price",
                "size",
                "best_bid",
                "best_ask",
                "spread_bps",
                "bid_depth_notional",
                "ask_depth_notional",
            ],
        },
        {
            "dataset_id": "l2_alignment_manifest",
            "file_name": "l2_alignment_manifest.json",
            "purpose": "reproducible capture lineage, clock source, public-channel boundary, and gap accounting",
            "required": True,
            "minimum_records": 1,
            "timestamp_alignment_required": True,
            "required_fields": [
                "data_version",
                "capture_start",
                "capture_end",
                "venue_symbol",
                "public_channels",
                "private_endpoint_used",
                "order_endpoint_used",
                "clock_source",
                "gap_count",
                "checksum_or_sequence_policy",
            ],
        },
    ]


def _validation_gates(current_evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    public_source_ok = (
        bool(current_evidence.get("public_rest_only"))
        and not bool(current_evidence.get("private_endpoint_used"))
        and not bool(current_evidence.get("order_endpoint_used"))
    )
    return [
        {
            "gate_id": "public_source_boundary",
            "required": True,
            "satisfied": public_source_ok,
            "blocker": None if public_source_ok else "btc_public_l2_source_boundary_not_verified",
        },
        {
            "gate_id": "same_window_trade_book_alignment",
            "required": True,
            "satisfied": False,
            "blocker": "btc_same_window_public_trade_book_alignment_missing",
        },
        {
            "gate_id": "historical_event_ledger_coverage",
            "required": True,
            "satisfied": False,
            "blocker": "btc_timestamp_aligned_l2_history_missing_for_event_ledger_window",
        },
        {
            "gate_id": "spread_slippage_queue_replay_inputs",
            "required": True,
            "satisfied": False,
            "blocker": "btc_spread_slippage_queue_replay_inputs_missing",
        },
        {
            "gate_id": "execution_latency_model_separated_from_rest_latency",
            "required": True,
            "satisfied": False,
            "blocker": "btc_execution_latency_model_missing_rest_latency_is_not_execution_latency",
        },
        {
            "gate_id": "aligned_capture_manifest_reproducibility",
            "required": True,
            "satisfied": False,
            "blocker": "btc_l2_alignment_manifest_missing",
        },
    ]


def _blockers(
    *,
    sample_quality: Mapping[str, Any],
    feature_diagnostics: Mapping[str, Any],
    capture: Mapping[str, Any],
    validation_gates: list[Mapping[str, Any]],
) -> list[str]:
    blockers: list[str] = []
    if capture.get("status") != "verified":
        blockers.append("btc_l2_sample_capture_report_not_verified")
    if sample_quality.get("status") != "public_l2_sample_evidence_ready_research_only":
        blockers.append("btc_l2_sample_quality_not_ready")
    if feature_diagnostics.get("status") != "l2_feature_diagnostics_ready_research_only_backtest_blocked":
        blockers.append("btc_l2_feature_diagnostics_not_ready")
    if bool(capture.get("private_endpoint_used", False)):
        blockers.append("btc_l2_capture_private_endpoint_used")
    if bool(capture.get("order_endpoint_used", False)):
        blockers.append("btc_l2_capture_order_endpoint_used")
    for gate in validation_gates:
        blocker = gate.get("blocker")
        if bool(gate.get("required")) and not bool(gate.get("satisfied")) and blocker:
            blockers.append(str(blocker))
    blockers.extend(str(item) for item in feature_diagnostics.get("blockers", []) if str(item))
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


def _int(value: object) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
