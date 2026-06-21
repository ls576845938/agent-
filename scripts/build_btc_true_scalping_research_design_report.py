#!/usr/bin/env python3
"""Build the BTC true-scalping research-only design report."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_scalping_readiness/latest")
DEFAULT_REVIEW = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_research_design_review.json")
DEFAULT_READINESS = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_microstructure_readiness_report.json")
DEFAULT_EVENT_LEDGER = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_drift_guarded_event_ledger_report.json")


def build_btc_true_scalping_research_design_report(
    *,
    repo_root: Path | None = None,
    review_path: Path | None = None,
    readiness_path: Path | None = None,
    event_ledger_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    review_file = _resolve(root, review_path or DEFAULT_REVIEW)
    readiness_file = _resolve(root, readiness_path or DEFAULT_READINESS)
    event_ledger_file = _resolve(root, event_ledger_path or DEFAULT_EVENT_LEDGER)
    review = _read_json(review_file)
    readiness = _read_json(readiness_file)
    event_ledger = _read_json(event_ledger_file)
    blockers = _blockers(review=review, readiness=readiness, event_ledger=event_ledger)
    passed = not blockers
    return {
        "schema_version": "btc_true_scalping_research_design_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "status": "research_only_scalping_design_ready_for_event_ledger_prototype"
        if passed
        else "research_only_scalping_design_blocked",
        "decision": "build_research_only_true_scalping_event_ledger_backtest"
        if passed
        else "repair_scalping_design_review_before_event_ledger",
        "next_required_action": "build_research_only_true_scalping_event_ledger_backtest"
        if passed
        else "repair_scalping_design_review_before_event_ledger",
        "source_reports": {
            "research_design_review": _relpath(review_file, root) if review_file.exists() else None,
            "microstructure_readiness": _relpath(readiness_file, root) if readiness_file.exists() else None,
            "drift_guarded_intraday_event_ledger": _relpath(event_ledger_file, root) if event_ledger_file.exists() else None,
        },
        "strategy_design": _strategy_design(readiness=readiness, event_ledger=event_ledger),
        "event_ledger_requirements": {
            "event_object_required_fields": [
                "event_timestamp",
                "book_snapshot_timestamp",
                "trigger_state",
                "context_state",
                "spread_bps_at_decision",
                "queue_assumption",
                "latency_ms_assumption",
                "label_horizon_seconds",
            ],
            "simulated_order_intent_only": True,
            "pnl_from_fill_ledger_required": True,
            "future_label_used_for_signal": False,
            "lookahead_used_for_signal": False,
            "required_manifest_fields": [
                "data_version",
                "strategy_version",
                "params",
                "cost_model",
                "slippage_model",
                "commit_hash",
            ],
            "required_stress_tests": [
                "base_10bps_round_trip_taker_cost",
                "double_taker_fee",
                "conservative_spread_crossing",
                "latency_delayed_entry",
                "missed_fill_or_no_queue_priority",
                "adverse_selection_after_touch",
            ],
            "required_robustness_gates": [
                "walk_forward_pass_rate",
                "regime_pass_rate",
                "tail_dependency",
                "cost_stress_survival",
                "minimum_fill_count",
            ],
        },
        "blockers": blockers,
        "research_only_event_ledger_prototype_allowed": passed,
        "research_only_scalping_design_allowed": passed,
        "true_scalping_allowed": False,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "guardrails": {
            "research_only": True,
            "strategy_may_emit_only": ["Signal", "OrderIntent"],
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
        },
    }


def write_btc_true_scalping_research_design_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_true_scalping_research_design_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--review-path", default=str(DEFAULT_REVIEW))
    parser.add_argument("--readiness-path", default=str(DEFAULT_READINESS))
    parser.add_argument("--event-ledger-path", default=str(DEFAULT_EVENT_LEDGER))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_true_scalping_research_design_report(
        repo_root=Path(args.repo_root),
        review_path=Path(args.review_path),
        readiness_path=Path(args.readiness_path),
        event_ledger_path=Path(args.event_ledger_path),
        generated_at=args.generated_at or None,
    )
    print(write_btc_true_scalping_research_design_report(payload, Path(args.output_root)))
    if payload.get("status") != "research_only_scalping_design_ready_for_event_ledger_prototype":
        raise SystemExit(2)


def _strategy_design(*, readiness: Mapping[str, Any], event_ledger: Mapping[str, Any]) -> dict[str, Any]:
    evidence = _mapping(readiness.get("evidence"))
    metrics = _mapping(event_ledger.get("metrics"))
    event_definition = _mapping(event_ledger.get("event_definition"))
    return {
        "strategy_id": "btc_true_scalp_liquidity_reclaim_research_v0",
        "family_id": "btc_true_scalping_research_v0",
        "scope": "research_only_event_ledger_design_no_candidate_no_paper_no_live",
        "primary_timeframe": "1m",
        "microstructure_inputs": {
            "tick_or_agg_trade_history": _mapping(evidence.get("tick_or_agg_trade_history")).get("files", []),
            "order_book_depth_history": _mapping(evidence.get("order_book_depth_history")).get("files", []),
            "spread_model": _mapping(evidence.get("spread_model")).get("files", []),
            "latency_model": _mapping(evidence.get("latency_model")).get("files", []),
            "queue_position_model": _mapping(evidence.get("queue_position_model")).get("files", []),
        },
        "signal_definition": {
            "name": "liquidity_reclaim_after_short_horizon_dislocation",
            "trigger": "1m pullback/reclaim state with current spread and visible best-level queue constraints",
            "context": "reuse drift-guarded intraday event-ledger regimes as coarse context until dedicated subminute regimes exist",
            "entry_intent": "maker_or_conservative_taker_order_intent_simulated_only",
            "exit_intent": "time_stop_or_adverse_spread_expansion_simulated_only",
            "label_horizon_seconds": [60, 180, 300],
            "max_hold_seconds": 300,
        },
        "source_intraday_context": {
            "strategy_id": event_ledger.get("strategy_id"),
            "variant_id": event_ledger.get("variant_id"),
            "event_count": _mapping(event_definition).get("event_count"),
            "trade_count": metrics.get("trade_count"),
            "fill_count": metrics.get("fill_count"),
            "event_profit_factor": metrics.get("event_profit_factor"),
            "walk_forward_pass_rate": metrics.get("walk_forward_pass_rate"),
            "regime_pass_rate": metrics.get("regime_pass_rate"),
        },
        "explicit_non_goals": [
            "no_live_exchange_order_book_streaming_in_this_step",
            "no_broker_or_private_exchange_endpoint",
            "no_candidate_strategy_generation",
            "no_paper_or_live_queue_unlock",
            "no_sharpe_optimization_before_cost_and_walk_forward_validation",
        ],
    }


def _blockers(*, review: Mapping[str, Any], readiness: Mapping[str, Any], event_ledger: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if str(review.get("status", "")) != "research_only_scalping_design_review_passed":
        blockers.append("btc_true_scalping_research_design_review_not_passed")
    if not bool(review.get("research_only_scalping_design_allowed", False)):
        blockers.append("btc_true_scalping_research_design_not_allowed")
    if bool(readiness.get("true_scalping_allowed", False)):
        blockers.append("btc_true_scalping_unexpectedly_unlocked")
    if bool(event_ledger.get("candidate_generation_allowed", False)):
        blockers.append("btc_intraday_event_ledger_candidate_generation_unexpectedly_unlocked")
    if bool(event_ledger.get("paper_or_live_unlock_allowed", False)):
        blockers.append("btc_intraday_event_ledger_paper_live_unexpectedly_unlocked")
    return blockers


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
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
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001 - metadata only.
        return "unknown"


if __name__ == "__main__":
    main()
