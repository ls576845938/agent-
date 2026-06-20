#!/usr/bin/env python3
"""Build BTC research sandbox registry.

This is a registry summarizer only. It does not run strategies, paper, live,
brokers, or order submission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

try:
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir


DEFAULT_OUTPUT = Path("artifacts/btc_research_registry/research_registry.json")
BTC_SOURCE_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
BTC_DATA_STATUS = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")
BTC_FUNDING_RATE_GAP = Path("artifacts/btc_data_status/latest/btc_funding_rate_gap_report.json")
BTC_BUNDLE_PREFLIGHT = Path("artifacts/btc_data_status/latest/btc_perpetual_bundle_preflight_report.json")
BTC_PROVIDER_VERIFICATION = Path("artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json")
BTC_MANUAL_METADATA_CAPTURE_READINESS = Path(
    "artifacts/btc_data_status/latest/btc_manual_metadata_capture_readiness_report.json"
)
BTC_MANUAL_METADATA_CAPTURE_OPERATOR_PACKET = Path(
    "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json"
)
BTC_MANUAL_METADATA_IMPORT_REPORT = Path("artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json")
BTC_OBJECTIVE_COMPLETION_AUDIT = Path("artifacts/btc_data_status/latest/btc_objective_completion_audit_report.json")
BTC_COST_MODEL = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
BTC_FUNDING_LEDGER = Path("artifacts/btc_cost_model/latest/btc_funding_ledger_report.json")
BTC_FOLD_REGIME = Path("artifacts/btc_fold_regime/latest/fold_regime_contract_report.json")
BTC_CANDIDATE_GATE = Path("artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json")
BTC_CANDIDATE_METRIC_REPAIR = Path("artifacts/btc_candidate_gate/latest/candidate_metric_repair_report.json")
BTC_CANDIDATE_BOUNDED_RETEST = Path("artifacts/btc_candidate_gate/latest/candidate_bounded_retest_plan.json")
BTC_CANDIDATE_BOUNDED_RETEST_OUTCOME = Path(
    "artifacts/btc_candidate_gate/latest/candidate_bounded_retest_outcome_report.json"
)
BTC_NEXT_HYPOTHESIS_DECISION = Path("artifacts/btc_candidate_gate/latest/btc_next_hypothesis_decision_report.json")
BTC_STRATEGY_FAMILY_ROADMAP = Path("artifacts/btc_candidate_gate/latest/btc_strategy_family_roadmap_report.json")
BTC_INTRADAY_SHORT_CYCLE_ALPHA_PLAN = Path(
    "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_alpha_plan_report.json"
)
BTC_INTRADAY_SHORT_CYCLE_ALPHA_PROBE = Path(
    "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_alpha_probe_report.json"
)
BTC_TAIL_DEPENDENCY = Path("artifacts/btc_tail_dependency/latest/tail_dependency_report.json")
BTC_COMPRESSION_ATTRIBUTION = Path(
    "artifacts/btc_candidate_attribution/latest_compression_expansion_attribution/attribution_report.json"
)
UTC_CAPTURE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


DEFAULT_ITEMS: dict[str, dict[str, str]] = {
    "perp_dual_trend": {
        "last_run_id": "20260516T100000Z_eventreturn_alpha",
        "next_action": "do_not_resurrect_without_new_hypothesis",
        "reason": "event_PF stuck near 1.01-1.02; no stable repair pattern",
        "status": "archived",
    },
    "low_vol_uptrend": {
        "last_run_id": "20260516T120000Z_lowvol_uptrend",
        "next_action": "do_not_optimize_rejected_hypothesis",
        "reason": "event_PF_proxy 0.979469; fold stability failed",
        "status": "hypothesis_rejected",
    },
    "liquidation_shock_recovery": {
        "last_run_id": "20260517T010000Z_liquidation_shock_attribution",
        "next_action": "do_not_generate_v2_or_v3",
        "reason": "full-ledger event_PF 0.998; lifecycle drag; no ablation passed",
        "status": "archived",
    },
    "range_reclaim_momentum": {
        "last_run_id": "20260518T010000Z_range_reclaim_lifecycle",
        "next_action": "do_not_generate_skeleton",
        "reason": "full_lifecycle_event_PF_proxy=1.098985; fold_pass_rate_lifecycle=0.250000",
        "status": "hypothesis_rejected",
    },
    "compression_expansion_breakout": {
        "allowed_next_action": "archive_only",
        "archive_recommended": True,
        "limited_retest_allowed": False,
        "last_run_id": "20260516T133000Z_compression_expansion_eventledger",
        "next_action": "do_not_retest_without_new_hypothesis",
        "reason": "hypothesis layer passed but full-lifecycle event-ledger candidate failed event_PF, walk-forward, and regime gates; v2 lifecycle gate rejected the raw/target-active edge",
        "status": "archived",
    },
}


def build_btc_research_registry(*, repo_root: Path | None = None, generated_at: str | None = None) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    data = _read_json(root / BTC_DATA_STATUS)
    funding_gap = _read_json(root / BTC_FUNDING_RATE_GAP)
    provider = _read_json(root / BTC_PROVIDER_VERIFICATION)
    preflight = _read_json(root / BTC_BUNDLE_PREFLIGHT)
    manual_metadata = _manual_metadata_capture_status(root)
    manual_metadata_packet = _manual_metadata_capture_operator_packet_status(root)
    manual_metadata_import = _manual_metadata_import_status(root)
    objective_audit = _objective_completion_status(root)
    cost = _read_json(root / BTC_COST_MODEL)
    funding = _read_json(root / BTC_FUNDING_LEDGER)
    fold = _read_json(root / BTC_FOLD_REGIME)
    gate = _read_json(root / BTC_CANDIDATE_GATE)
    metric_repair = _candidate_metric_repair_status(root)
    bounded_retest = _candidate_bounded_retest_status(root)
    bounded_retest_outcome = _candidate_bounded_retest_outcome_status(root)
    next_hypothesis = _next_hypothesis_decision_status(root)
    strategy_family = _strategy_family_roadmap_status(root)
    intraday_short_cycle = _intraday_short_cycle_alpha_plan_status(root)
    intraday_short_cycle_probe = _intraday_short_cycle_alpha_probe_status(root)
    tail = _read_json(root / BTC_TAIL_DEPENDENCY)
    attribution = _read_json(root / BTC_COMPRESSION_ATTRIBUTION)
    candidate_passed_internal_gate = int(gate.get("candidate_passed_internal_gate", 0) or 0)
    current_candidates = _current_candidates_from_gate(gate)
    paper_queue_status = "pending_review" if current_candidates else "locked"
    blockers = _merge(
        data.get("blockers", []),
        funding_gap.get("blockers", []),
        provider.get("blockers", []),
        preflight.get("blockers", []),
        manual_metadata.get("blockers", []),
        objective_audit.get("blockers", []),
        cost.get("blockers", []),
        funding.get("blockers", []),
        fold.get("blockers", []),
        gate.get("blockers", []),
        metric_repair.get("blockers", []),
        bounded_retest.get("blockers", []),
        bounded_retest_outcome.get("blockers", []),
        next_hypothesis.get("blockers", []),
        strategy_family.get("blockers", []),
        intraday_short_cycle.get("blockers", []),
        intraday_short_cycle_probe.get("blockers", []),
        tail.get("blockers", []),
        attribution.get("blockers", []),
    )
    return {
        "schema_version": "btc_research_registry_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "paper_queue": "PENDING_REVIEW" if current_candidates else "LOCKED",
        "live": "FROZEN",
        "items": DEFAULT_ITEMS,
        "btc": {
            "status": "research_sandbox",
            "paper_queue_status": paper_queue_status,
            "live_status": "frozen",
            "candidate_passed_internal_gate": candidate_passed_internal_gate,
            "latest_data_status": _maybe_path(root, BTC_DATA_STATUS),
            "latest_funding_rate_gap_report": _maybe_path(root, BTC_FUNDING_RATE_GAP),
            "latest_bundle_preflight": _maybe_path(root, BTC_BUNDLE_PREFLIGHT),
            "latest_provider_verification": _maybe_path(root, BTC_PROVIDER_VERIFICATION),
            "latest_manual_metadata_capture_readiness": _maybe_path(root, BTC_MANUAL_METADATA_CAPTURE_READINESS),
            "latest_manual_metadata_capture_operator_packet": _maybe_path(
                root, BTC_MANUAL_METADATA_CAPTURE_OPERATOR_PACKET
            ),
            "latest_manual_metadata_import_report": _maybe_path(root, BTC_MANUAL_METADATA_IMPORT_REPORT),
            "latest_objective_completion_audit": _maybe_path(root, BTC_OBJECTIVE_COMPLETION_AUDIT),
            "latest_cost_model": _maybe_path(root, BTC_COST_MODEL),
            "latest_funding_ledger": _maybe_path(root, BTC_FUNDING_LEDGER),
            "latest_fold_regime_contract": _maybe_path(root, BTC_FOLD_REGIME),
            "latest_candidate_gate_audit": _maybe_path(root, BTC_CANDIDATE_GATE),
            "latest_candidate_metric_repair_report": _maybe_path(root, BTC_CANDIDATE_METRIC_REPAIR),
            "latest_candidate_bounded_retest_plan": _maybe_path(root, BTC_CANDIDATE_BOUNDED_RETEST),
            "latest_candidate_bounded_retest_outcome_report": _maybe_path(
                root, BTC_CANDIDATE_BOUNDED_RETEST_OUTCOME
            ),
            "latest_next_hypothesis_decision_report": _maybe_path(root, BTC_NEXT_HYPOTHESIS_DECISION),
            "latest_strategy_family_roadmap_report": _maybe_path(root, BTC_STRATEGY_FAMILY_ROADMAP),
            "latest_intraday_short_cycle_alpha_plan_report": _maybe_path(root, BTC_INTRADAY_SHORT_CYCLE_ALPHA_PLAN),
            "latest_intraday_short_cycle_alpha_probe_report": _maybe_path(root, BTC_INTRADAY_SHORT_CYCLE_ALPHA_PROBE),
            "latest_tail_dependency": _maybe_path(root, BTC_TAIL_DEPENDENCY),
            "latest_compression_attribution": _maybe_path(root, BTC_COMPRESSION_ATTRIBUTION),
            "manual_metadata_capture_status": manual_metadata,
            "manual_metadata_capture_operator_packet_status": manual_metadata_packet,
            "manual_metadata_import_status": manual_metadata_import,
            "objective_completion_status": objective_audit,
            "candidate_metric_repair_status": metric_repair,
            "candidate_bounded_retest_status": bounded_retest,
            "candidate_bounded_retest_outcome_status": bounded_retest_outcome,
            "next_hypothesis_decision_status": next_hypothesis,
            "strategy_family_roadmap_status": strategy_family,
            "intraday_short_cycle_alpha_plan_status": intraday_short_cycle,
            "intraday_short_cycle_alpha_probe_status": intraday_short_cycle_probe,
            "current_candidates": current_candidates,
            "attribution_only": [],
            "compression_boundary": {
                "status": "archived",
                "allowed_next_action": "archive_only",
                "archive_recommended": bool(attribution.get("archive_recommended", True)),
                "limited_retest_allowed": False,
                "paper_review_pending_allowed": False,
            },
            "archived_or_rejected": [
                "perp_dual_trend",
                "low_vol_uptrend",
                "liquidation_shock_recovery",
                "range_reclaim_momentum",
                "compression_expansion_breakout",
            ],
            "blockers": blockers,
        },
    }


def write_btc_research_registry(payload: Mapping[str, Any], output: Path) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_research_registry(repo_root=Path(args.repo_root), generated_at=args.generated_at or None)
    print(write_btc_research_registry(payload, Path(args.output)))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _current_candidates_from_gate(gate: Mapping[str, Any]) -> list[str]:
    if str(gate.get("status", "")) != "pass":
        return []
    if not bool(gate.get("paper_review_pending_allowed", False)):
        return []
    if int(gate.get("candidate_passed_internal_gate", 0) or 0) <= 0:
        return []
    strategy_id = str(gate.get("strategy_id", "")).strip()
    return [strategy_id] if strategy_id else []


def _maybe_path(root: Path, path: Path) -> str | None:
    return _relpath(root / path, root) if (root / path).exists() else None


def _manual_metadata_capture_status(root: Path) -> dict[str, Any]:
    path = root / BTC_MANUAL_METADATA_CAPTURE_READINESS
    payload = _read_json(path)
    exchange = _mapping(payload.get("exchange_info"))
    funding = _mapping(payload.get("funding_info"))
    safety = _mapping(payload.get("safety"))
    last_attempt = _mapping(payload.get("last_public_metadata_capture_status"))
    blockers = []
    if not path.exists():
        blockers.append("btc_manual_metadata_capture_readiness_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    manual_capture_required = bool(exchange.get("manual_capture_required", True)) or bool(
        funding.get("manual_capture_required", True)
    )
    if manual_capture_required:
        blockers.extend(_list_of_strings(last_attempt.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "latest_public_metadata_capture_attempt": payload.get("latest_public_metadata_capture_attempt"),
        "last_public_metadata_capture_status": str(last_attempt.get("status", "missing") or "missing"),
        "last_public_metadata_capture_network_called": bool(last_attempt.get("network_called", False)),
        "last_exchange_info_capture_status": str(last_attempt.get("exchange_info_capture_status", "missing") or "missing"),
        "last_exchange_info_http_status": last_attempt.get("exchange_info_http_status"),
        "last_funding_info_capture_status": str(last_attempt.get("funding_info_capture_status", "missing") or "missing"),
        "last_funding_info_http_status": last_attempt.get("funding_info_http_status"),
        "last_public_metadata_next_required_action": str(
            last_attempt.get("next_required_action", "manual_capture_from_allowed_network")
        ),
        "exchange_info_manual_capture_required": bool(exchange.get("manual_capture_required", True)),
        "funding_info_manual_capture_required": bool(funding.get("manual_capture_required", True)),
        "exchange_info_allowed_endpoint": str(exchange.get("allowed_endpoint", "")),
        "funding_info_allowed_endpoint": str(funding.get("allowed_endpoint", "")),
        "api_key_required": bool(safety.get("api_key_required", False)),
        "private_endpoints_allowed": bool(safety.get("private_endpoints_allowed", False)),
        "order_endpoints_allowed": bool(safety.get("order_endpoints_allowed", False)),
        "strategy_retest_allowed": bool(safety.get("strategy_retest_allowed", False)),
        "paper_or_live_unlock_allowed": bool(safety.get("paper_or_live_unlock_allowed", False)),
        "blockers": _merge(blockers),
    }


def _candidate_metric_repair_status(root: Path) -> dict[str, Any]:
    path = root / BTC_CANDIDATE_METRIC_REPAIR
    payload = _read_json(path)
    best_candidate = _mapping(payload.get("best_candidate"))
    metrics = _mapping(best_candidate.get("metrics"))
    blockers = []
    if not path.exists():
        blockers.append("btc_candidate_metric_repair_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "promotion_allowed": bool(payload.get("promotion_allowed", False)),
        "paper_review_pending_allowed": bool(payload.get("paper_review_pending_allowed", False)),
        "best_candidate_strategy_id": str(best_candidate.get("strategy_id", "")),
        "failed_metrics": _list_of_strings(payload.get("failed_metrics")),
        "event_profit_factor": _float_or_none(metrics.get("event_profit_factor")),
        "walk_forward_pass_rate": _float_or_none(metrics.get("walk_forward_pass_rate")),
        "regime_pass_rate": _float_or_none(metrics.get("regime_pass_rate")),
        "recommended_repair_actions": _repair_action_summaries(payload.get("recommended_repair_actions")),
        "blockers": _merge(blockers),
    }


def _candidate_bounded_retest_status(root: Path) -> dict[str, Any]:
    path = root / BTC_CANDIDATE_BOUNDED_RETEST
    payload = _read_json(path)
    candidate = _mapping(payload.get("candidate"))
    context = _mapping(payload.get("metric_repair_context"))
    scope = _mapping(payload.get("test_scope"))
    guardrails = _mapping(payload.get("guardrails"))
    blockers = []
    if not path.exists():
        blockers.append("btc_candidate_bounded_retest_plan_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "retest_allowed": bool(payload.get("retest_allowed", False)),
        "bounded_parameter_search_allowed": bool(payload.get("bounded_parameter_search_allowed", False)),
        "promotion_allowed": bool(payload.get("promotion_allowed", False)),
        "paper_review_pending_allowed": bool(payload.get("paper_review_pending_allowed", False)),
        "candidate_strategy_id": str(candidate.get("strategy_id", "")),
        "failed_metrics": _list_of_strings(context.get("failed_metrics")),
        "focus_failed_folds": _list_of_ints(scope.get("focus_failed_folds")),
        "ordinary_profit_factor_diagnostic_only": guardrails.get(
            "ordinary_profit_factor_diagnostic_only", True
        )
        is not False,
        "paper_or_live_unlock_allowed": bool(guardrails.get("paper_or_live_unlock_allowed", False)),
        "broker_calls_allowed": bool(guardrails.get("broker_calls_allowed", False)),
        "blockers": _merge(blockers),
    }


def _candidate_bounded_retest_outcome_status(root: Path) -> dict[str, Any]:
    path = root / BTC_CANDIDATE_BOUNDED_RETEST_OUTCOME
    payload = _read_json(path)
    metrics = _mapping(payload.get("metrics"))
    safety = _mapping(payload.get("safety"))
    blockers = []
    if not path.exists():
        blockers.append("btc_candidate_bounded_retest_outcome_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "run_id": str(payload.get("run_id", "")),
        "candidate_gate_passed": bool(payload.get("candidate_gate_passed", False)),
        "promotion_allowed": bool(payload.get("promotion_allowed", False)),
        "paper_review_pending_allowed": bool(payload.get("paper_review_pending_allowed", False)),
        "same_retest_repeat_allowed": bool(payload.get("same_retest_repeat_allowed", False)),
        "event_profit_factor": _float_or_none(metrics.get("event_profit_factor")),
        "walk_forward_pass_rate": _float_or_none(metrics.get("walk_forward_pass_rate")),
        "regime_pass_rate": _float_or_none(metrics.get("regime_pass_rate")),
        "ordinary_profit_factor": _float_or_none(metrics.get("ordinary_profit_factor")),
        "cost_stress_base_pass": bool(metrics.get("cost_stress_base_pass", False)),
        "cost_stress_harsh_pass": bool(metrics.get("cost_stress_harsh_pass", False)),
        "failed_metrics": _list_of_strings(payload.get("failed_metrics")),
        "next_required_action": str(payload.get("next_required_action", "")),
        "paper_queue_status": str(safety.get("paper_queue_status", "LOCKED")),
        "live_status": str(safety.get("live_status", "FROZEN")),
        "real_broker_api_called": bool(safety.get("real_broker_api_called", False)),
        "real_orders_created": bool(safety.get("real_orders_created", False)),
        "paper_or_live_unlock_allowed": bool(safety.get("paper_or_live_unlock_allowed", False)),
        "blockers": _merge(blockers),
    }


def _next_hypothesis_decision_status(root: Path) -> dict[str, Any]:
    path = root / BTC_NEXT_HYPOTHESIS_DECISION
    payload = _read_json(path)
    best_event = _mapping(payload.get("best_by_event_profit_factor"))
    best_wf = _mapping(payload.get("best_by_walk_forward_pass_rate"))
    blockers = []
    if not path.exists():
        blockers.append("btc_next_hypothesis_decision_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "decision": str(payload.get("decision", "")),
        "next_required_action": str(payload.get("next_required_action", "")),
        "promotion_allowed": bool(payload.get("promotion_allowed", False)),
        "paper_review_pending_allowed": bool(payload.get("paper_review_pending_allowed", False)),
        "same_family_micro_search_allowed": bool(payload.get("same_family_micro_search_allowed", False)),
        "mode_count": int(payload.get("mode_count", 0) or 0),
        "event_profit_factor_pass_count": int(payload.get("event_profit_factor_pass_count", 0) or 0),
        "walk_forward_pass_rate_pass_count": int(payload.get("walk_forward_pass_rate_pass_count", 0) or 0),
        "best_event_mode": str(best_event.get("mode", "")),
        "best_event_profit_factor": _float_or_none(best_event.get("event_profit_factor")),
        "best_event_walk_forward_pass_rate": _float_or_none(best_event.get("walk_forward_pass_rate")),
        "best_wf_mode": str(best_wf.get("mode", "")),
        "best_wf_event_profit_factor": _float_or_none(best_wf.get("event_profit_factor")),
        "best_wf_pass_rate": _float_or_none(best_wf.get("walk_forward_pass_rate")),
        "blockers": _merge(blockers),
    }


def _strategy_family_roadmap_status(root: Path) -> dict[str, Any]:
    path = root / BTC_STRATEGY_FAMILY_ROADMAP
    payload = _read_json(path)
    selected = _mapping(payload.get("selected_next_family"))
    prerequisites = _mapping(payload.get("data_prerequisites"))
    blockers = []
    if not path.exists():
        blockers.append("btc_strategy_family_roadmap_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "decision": str(payload.get("decision", "")),
        "next_required_action": str(payload.get("next_required_action", "")),
        "selected_family_id": str(selected.get("family_id", "")),
        "selected_family": str(selected.get("family", "")),
        "selected_provider": str(prerequisites.get("selected_provider", "")),
        "selected_bundle_id": str(prerequisites.get("selected_bundle_id", "")),
        "selected_bundle_duration_days": _float_or_none(prerequisites.get("selected_bundle_duration_days")),
        "min_required_history_days": _float_or_none(prerequisites.get("min_required_history_days")),
        "funding_rate_record_count": int(prerequisites.get("funding_rate_record_count", 0) or 0),
        "min_required_funding_events": int(prerequisites.get("min_required_funding_events", 0) or 0),
        "hypothesis_distribution_allowed": bool(payload.get("hypothesis_distribution_allowed", False)),
        "candidate_generation_allowed": bool(payload.get("candidate_generation_allowed", False)),
        "strategy_skeleton_generation_allowed": bool(payload.get("strategy_skeleton_generation_allowed", False)),
        "promotion_allowed": bool(payload.get("promotion_allowed", False)),
        "paper_review_pending_allowed": bool(payload.get("paper_review_pending_allowed", False)),
        "paper_or_live_unlock_allowed": bool(payload.get("paper_or_live_unlock_allowed", False)),
        "blockers": _merge(blockers),
    }


def _intraday_short_cycle_alpha_plan_status(root: Path) -> dict[str, Any]:
    path = root / BTC_INTRADAY_SHORT_CYCLE_ALPHA_PLAN
    payload = _read_json(path)
    selected = _mapping(payload.get("selected_research_style"))
    prerequisites = _mapping(payload.get("data_prerequisites"))
    intervals = _mapping(prerequisites.get("intervals"))
    blockers = []
    if not path.exists():
        blockers.append("btc_intraday_short_cycle_alpha_plan_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "decision": str(payload.get("decision", "")),
        "next_required_action": str(payload.get("next_required_action", "")),
        "selected_style_id": str(selected.get("style_id", "")),
        "primary_timeframes": _list_of_strings(selected.get("primary_timeframes")),
        "intraday_research_distribution_allowed": bool(
            payload.get("intraday_research_distribution_allowed", False)
        ),
        "short_cycle_probe_allowed": bool(payload.get("short_cycle_probe_allowed", False)),
        "true_scalping_allowed": bool(payload.get("true_scalping_allowed", False)),
        "candidate_generation_allowed": bool(payload.get("candidate_generation_allowed", False)),
        "strategy_skeleton_generation_allowed": bool(payload.get("strategy_skeleton_generation_allowed", False)),
        "promotion_allowed": bool(payload.get("promotion_allowed", False)),
        "paper_review_pending_allowed": bool(payload.get("paper_review_pending_allowed", False)),
        "paper_or_live_unlock_allowed": bool(payload.get("paper_or_live_unlock_allowed", False)),
        "sample_days": _float_or_none(prerequisites.get("sample_days")),
        "min_sample_days": _float_or_none(prerequisites.get("min_sample_days")),
        "interval_bar_counts": {
            interval: int(_mapping(intervals.get(interval)).get("bar_count", 0) or 0)
            for interval in ("5m", "15m")
        },
        "candidate_family_count": len(payload.get("candidate_families", []))
        if isinstance(payload.get("candidate_families"), list)
        else 0,
        "blockers": _merge(blockers),
    }


def _intraday_short_cycle_alpha_probe_status(root: Path) -> dict[str, Any]:
    path = root / BTC_INTRADAY_SHORT_CYCLE_ALPHA_PROBE
    payload = _read_json(path)
    best = _mapping(payload.get("best_family"))
    cost = _mapping(payload.get("cost_context"))
    data = _mapping(payload.get("data_context"))
    intervals = _mapping(data.get("intervals"))
    blockers = []
    if not path.exists():
        blockers.append("btc_intraday_short_cycle_alpha_probe_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "decision": str(payload.get("decision", "")),
        "next_required_action": str(payload.get("next_required_action", "")),
        "distribution_probe_completed": bool(payload.get("distribution_probe_completed", False)),
        "alpha_distribution_observed": bool(payload.get("alpha_distribution_observed", False)),
        "candidate_generation_allowed": bool(payload.get("candidate_generation_allowed", False)),
        "strategy_skeleton_generation_allowed": bool(payload.get("strategy_skeleton_generation_allowed", False)),
        "promotion_allowed": bool(payload.get("promotion_allowed", False)),
        "paper_review_pending_allowed": bool(payload.get("paper_review_pending_allowed", False)),
        "paper_or_live_unlock_allowed": bool(payload.get("paper_or_live_unlock_allowed", False)),
        "true_scalping_allowed": bool(payload.get("true_scalping_allowed", False)),
        "best_family_id": str(best.get("family_id", "")),
        "best_family_status": str(best.get("status", "")),
        "best_family_event_count": int(best.get("event_count", 0) or 0),
        "best_horizon": best.get("best_horizon"),
        "best_net_mean_bps": _float_or_none(best.get("best_net_mean_bps")),
        "family_count": len(payload.get("family_results", []))
        if isinstance(payload.get("family_results"), list)
        else 0,
        "round_trip_taker_cost_bps": _float_or_none(cost.get("round_trip_taker_cost_bps")),
        "interval_row_counts": {
            interval: int(_mapping(intervals.get(interval)).get("row_count", 0) or 0)
            for interval in ("5m", "15m")
        },
        "blockers": _merge(blockers),
    }


def _repair_action_summaries(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    actions: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        actions.append(
            {
                "name": str(item.get("name", "")),
                "priority": int(item.get("priority", 0) or 0),
                "status": str(item.get("status", "")),
            }
        )
    return actions


def _manual_metadata_capture_operator_packet_status(root: Path) -> dict[str, Any]:
    path = root / BTC_MANUAL_METADATA_CAPTURE_OPERATOR_PACKET
    payload = _read_json(path)
    last_status = _mapping(payload.get("last_public_metadata_capture_status"))
    required_inputs = _manual_input_statuses(payload.get("required_manual_inputs"))
    fee_tier = _mapping(payload.get("fee_tier_status"))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "operator_action": str(payload.get("operator_action", "manual_capture_from_allowed_network")),
        "manual_inputs_status": str(
            payload.get("manual_inputs_status", "awaiting_manual_inputs") or "awaiting_manual_inputs"
        ),
        "paper_gate_manual_inputs_complete": bool(payload.get("paper_gate_manual_inputs_complete", False)),
        "required_manual_input_count": len(required_inputs),
        "required_manual_inputs": required_inputs,
        "capture_request_count": len(payload.get("capture_requests", []))
        if isinstance(payload.get("capture_requests"), list)
        else 0,
        "dry_run_import_available": bool(payload.get("post_capture_dry_run_import_command")),
        "last_exchange_info_http_status": last_status.get("exchange_info_http_status"),
        "last_funding_info_http_status": last_status.get("funding_info_http_status"),
        "fee_tier_status": {
            "cost_model_report": fee_tier.get("cost_model_report"),
            "cost_model_status": str(fee_tier.get("cost_model_status", "missing") or "missing"),
            "fee_tier_verified": bool(fee_tier.get("fee_tier_verified", False)),
            "manual_capture_required": bool(fee_tier.get("manual_capture_required", True)),
            "maker_fee_bps": _float_or_none(fee_tier.get("maker_fee_bps")),
            "taker_fee_bps": _float_or_none(fee_tier.get("taker_fee_bps")),
            "fee_tier_import_report_verified": bool(fee_tier.get("fee_tier_import_report_verified", False)),
            "fee_blockers": _list_of_strings(fee_tier.get("fee_blockers")),
        },
        "blockers": _merge(_list_of_strings(payload.get("blockers"))),
    }


def _manual_metadata_import_status(root: Path) -> dict[str, Any]:
    path = root / BTC_MANUAL_METADATA_IMPORT_REPORT
    payload = _read_json(path)
    raw_input_files = _mapping(payload.get("raw_input_files"))
    exchange_raw = _raw_input_file_status(raw_input_files.get("exchange_info_raw"))
    funding_raw = _raw_input_file_status(raw_input_files.get("funding_info_raw"))
    bundle_status = _manual_import_bundle_status(payload, root)
    blockers = _manual_metadata_import_blockers(path=path, payload=payload, exchange_raw=exchange_raw, funding_raw=funding_raw)
    blockers.extend(_manual_import_bundle_blockers(payload, bundle_status))
    blockers = _merge(blockers)
    valid_for_completion = not blockers
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "dry_run": bool(payload.get("dry_run", False)),
        "captured_at": payload.get("captured_at"),
        "bundle_dir": payload.get("bundle_dir"),
        "bundle_dir_exists": bool(bundle_status["exists"]),
        "bundle_dir_matches_selected": bool(bundle_status["matches_selected_bundle"]),
        "bundle_exchange_info_exists": bool(bundle_status["exchange_info_exists"]),
        "bundle_funding_info_exists": bool(bundle_status["funding_info_exists"]),
        "bundle_exchange_info_output_hash_verified": bool(bundle_status["exchange_info_output_hash_verified"]),
        "bundle_funding_info_output_hash_verified": bool(bundle_status["funding_info_output_hash_verified"]),
        "writes_performed": bool(payload.get("writes_performed", False)),
        "exchange_info_verified": bool(payload.get("exchange_info_verified", False)),
        "funding_info_verified": bool(payload.get("funding_info_verified", False)),
        "valid_for_completion": valid_for_completion,
        "raw_input_files": {
            "exchange_info_raw": exchange_raw,
            "funding_info_raw": funding_raw,
        },
        "post_import_validation_command": payload.get("post_import_validation_command"),
        "blockers": blockers,
    }


def _raw_input_file_status(value: object) -> dict[str, Any]:
    payload = _mapping(value)
    return {
        "path": payload.get("path"),
        "exists": bool(payload.get("exists", False)),
        "size_bytes": payload.get("size_bytes"),
        "sha256": payload.get("sha256"),
        "http_status_file": payload.get("http_status_file"),
        "http_status": payload.get("http_status"),
        "http_status_verified": payload.get("http_status_verified") is True,
    }


def _manual_metadata_import_blockers(
    *,
    path: Path,
    payload: Mapping[str, Any],
    exchange_raw: Mapping[str, Any],
    funding_raw: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not path.exists():
        blockers.append("btc_manual_metadata_import_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    if payload.get("schema_version") != "btc_manual_metadata_import_report_v1":
        blockers.append("btc_manual_metadata_import_schema_version_missing_or_invalid")
    if payload.get("status") != "verified":
        blockers.append("btc_manual_metadata_import_not_verified")
    if payload.get("writes_performed") is not True:
        blockers.append("btc_manual_metadata_import_write_not_performed")
    if payload.get("exchange_info_verified") is not True:
        blockers.append("btc_manual_metadata_import_exchange_info_not_verified")
    if payload.get("funding_info_verified") is not True:
        blockers.append("btc_manual_metadata_import_funding_info_not_verified")
    if not _non_empty_text(payload.get("bundle_dir")):
        blockers.append("btc_manual_metadata_import_bundle_dir_missing")
    if not _utc_capture_timestamp(payload.get("captured_at")):
        blockers.append("btc_manual_metadata_import_captured_at_missing")
    if payload.get("post_import_validation_command") != "make validate-btc-public-data-bundle":
        blockers.append("btc_manual_metadata_import_validation_command_missing")
    if not _raw_input_file_verified(exchange_raw):
        blockers.append("btc_exchange_info_raw_import_provenance_missing")
    if not _raw_input_file_verified(funding_raw):
        blockers.append("btc_funding_info_raw_import_provenance_missing")
    if not _raw_input_http_status_verified(exchange_raw):
        blockers.append("btc_exchange_info_raw_http_status_not_200")
    if not _raw_input_http_status_verified(funding_raw):
        blockers.append("btc_funding_info_raw_http_status_not_200")
    return _merge(blockers)


def _manual_import_bundle_status(payload: Mapping[str, Any], root: Path) -> dict[str, Any]:
    selected_bundle = _selected_btc_bundle_dir(root)
    bundle_dir = _resolve_path(payload.get("bundle_dir"), root)
    exists = bool(bundle_dir and bundle_dir.exists() and bundle_dir.is_dir())
    return {
        "selected_bundle_configured": selected_bundle is not None,
        "exists": exists,
        "matches_selected_bundle": bool(bundle_dir and selected_bundle and _same_resolved_path(bundle_dir, selected_bundle)),
        "exchange_info_exists": bool(exists and bundle_dir and (bundle_dir / "exchange_info.json").exists()),
        "funding_info_exists": bool(exists and bundle_dir and (bundle_dir / "funding_info.json").exists()),
        "exchange_info_output_hash_verified": _output_hash_verified(
            payload,
            root=root,
            bundle_dir=bundle_dir,
            prefix="exchange_info",
            filename="exchange_info.json",
        ),
        "funding_info_output_hash_verified": _output_hash_verified(
            payload,
            root=root,
            bundle_dir=bundle_dir,
            prefix="funding_info",
            filename="funding_info.json",
        ),
    }


def _manual_import_bundle_blockers(payload: Mapping[str, Any], status: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not _non_empty_text(payload.get("bundle_dir")):
        return blockers
    if not status["selected_bundle_configured"]:
        blockers.append("btc_manual_metadata_import_selected_bundle_config_missing")
    if not status["exists"]:
        blockers.append("btc_manual_metadata_import_bundle_dir_missing_on_disk")
    if status["selected_bundle_configured"] and not status["matches_selected_bundle"]:
        blockers.append("btc_manual_metadata_import_bundle_dir_not_selected_bundle")
    if status["exists"] and not status["exchange_info_exists"]:
        blockers.append("btc_manual_metadata_import_bundle_exchange_info_missing")
    if status["exists"] and not status["funding_info_exists"]:
        blockers.append("btc_manual_metadata_import_bundle_funding_info_missing")
    if status["exists"] and not status["exchange_info_output_hash_verified"]:
        blockers.append("btc_manual_metadata_import_exchange_info_output_hash_mismatch")
    if status["exists"] and not status["funding_info_output_hash_verified"]:
        blockers.append("btc_manual_metadata_import_funding_info_output_hash_mismatch")
    return blockers


def _selected_btc_bundle_dir(root: Path) -> Path | None:
    return selected_btc_perpetual_bundle_dir(root, root / BTC_SOURCE_CONFIG)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _resolve_path(value: object, root: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def _same_resolved_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _output_hash_verified(
    payload: Mapping[str, Any],
    *,
    root: Path,
    bundle_dir: Path | None,
    prefix: str,
    filename: str,
) -> bool:
    expected = bundle_dir / filename if bundle_dir else None
    reported_path = _resolve_path(payload.get(f"{prefix}_output_path"), root)
    reported_hash = payload.get(f"{prefix}_output_sha256")
    return bool(
        expected
        and expected.exists()
        and reported_path
        and _same_resolved_path(reported_path, expected)
        and isinstance(reported_hash, str)
        and SHA256_RE.fullmatch(reported_hash)
        and _sha256(expected) == reported_hash
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _raw_input_file_verified(payload: Mapping[str, Any]) -> bool:
    return bool(
        payload.get("exists") is True
        and isinstance(payload.get("path"), str)
        and bool(str(payload.get("path")).strip())
        and isinstance(payload.get("size_bytes"), int)
        and payload.get("size_bytes") > 0
        and isinstance(payload.get("sha256"), str)
        and SHA256_RE.fullmatch(str(payload.get("sha256")))
        and _raw_input_http_status_verified(payload)
    )


def _raw_input_http_status_verified(payload: Mapping[str, Any]) -> bool:
    return bool(
        isinstance(payload.get("http_status_file"), str)
        and bool(str(payload.get("http_status_file")).strip())
        and payload.get("http_status") == 200
        and payload.get("http_status_verified") is True
    )


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _utc_capture_timestamp(value: object) -> bool:
    return isinstance(value, str) and bool(UTC_CAPTURE_RE.fullmatch(value))


def _objective_completion_status(root: Path) -> dict[str, Any]:
    path = root / BTC_OBJECTIVE_COMPLETION_AUDIT
    payload = _read_json(path)
    requirements = _mapping(payload.get("requirements"))
    incomplete = _list_of_strings(payload.get("incomplete_requirements"))
    complete = [
        name
        for name, value in requirements.items()
        if isinstance(value, Mapping) and value.get("status") == "complete"
    ]
    blockers = []
    if not path.exists():
        blockers.append("btc_objective_completion_audit_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "goal_complete": bool(payload.get("goal_complete", False)),
        "complete_requirements": complete,
        "incomplete_requirements": incomplete,
        "next_required_action": str(payload.get("next_required_action", "manual_capture_from_allowed_network")),
        "blockers": _merge(blockers),
    }


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _list_of_ints(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _manual_input_statuses(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        result.append(
            {
                "name": str(item.get("name", "")),
                "required_for": str(item.get("required_for", "")),
                "status": str(item.get("status", "awaiting_capture") or "awaiting_capture"),
                "action": str(
                    item.get("action", "manual_capture_from_allowed_network") or "manual_capture_from_allowed_network"
                ),
                "blockers": _list_of_strings(item.get("blockers")),
            }
        )
    return result


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _merge(*groups: object) -> list[str]:
    out = []
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            text = str(item)
            if text and text not in out:
                out.append(text)
    return out


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
