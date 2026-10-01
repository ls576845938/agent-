#!/usr/bin/env python3
"""Build BTC intraday remaining external evidence status.

This is a fail-closed candidate-adjacent status report. It summarizes the
remaining non-engineering evidence gates after the research candidate
definition manifest is ready. It does not generate candidate code, enqueue
paper trading, unlock live trading, or claim true scalping readiness.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
DEFAULT_DEFINITION_MANIFEST = Path(
    "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_research_candidate_definition_manifest.json"
)
DEFAULT_WS_L2_COVERAGE = Path(
    "artifacts/btc_scalping_readiness/latest/btc_true_scalping_ws_l2_capture_coverage_report.json"
)
DEFAULT_LONG_HORIZON_L2_TICK_IMPORT_CONTRACT = Path(
    "artifacts/btc_scalping_readiness/latest/btc_true_scalping_long_horizon_l2_tick_import_contract_report.json"
)
DEFAULT_EXECUTION_QUEUE_EXTERNAL_EVIDENCE_CONTRACT = Path(
    "artifacts/btc_scalping_readiness/latest/"
    "btc_true_scalping_execution_queue_external_evidence_contract_report.json"
)
DEFAULT_WS_LATENCY_QUEUE = Path(
    "artifacts/btc_scalping_readiness/latest/btc_true_scalping_ws_latency_queue_diagnostics_report.json"
)
DEFAULT_MICROSTRUCTURE_READINESS = Path(
    "artifacts/btc_scalping_readiness/latest/btc_true_scalping_microstructure_readiness_report.json"
)
DEFAULT_MICROSTRUCTURE_MODELS = Path(
    "artifacts/btc_scalping_readiness/latest/btc_true_scalping_microstructure_model_report.json"
)
DEFAULT_PAPER_READINESS = Path("artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json")
REPORT_FILENAME = "btc_intraday_short_cycle_remaining_external_evidence_status_report.json"
REPORT_SCHEMA_VERSION = "btc_intraday_short_cycle_remaining_external_evidence_status_v1"


def build_btc_intraday_short_cycle_remaining_external_evidence_status(
    *,
    repo_root: Path | None = None,
    definition_manifest_path: Path | None = None,
    ws_l2_coverage_path: Path | None = None,
    long_horizon_l2_tick_import_contract_path: Path | None = None,
    execution_queue_external_evidence_contract_path: Path | None = None,
    ws_latency_queue_path: Path | None = None,
    microstructure_readiness_path: Path | None = None,
    microstructure_models_path: Path | None = None,
    paper_readiness_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    definition_file = _resolve(root, definition_manifest_path or DEFAULT_DEFINITION_MANIFEST)
    coverage_file = _resolve(root, ws_l2_coverage_path or DEFAULT_WS_L2_COVERAGE)
    long_horizon_import_file = _resolve(
        root,
        long_horizon_l2_tick_import_contract_path or DEFAULT_LONG_HORIZON_L2_TICK_IMPORT_CONTRACT,
    )
    execution_queue_contract_file = _resolve(
        root,
        execution_queue_external_evidence_contract_path or DEFAULT_EXECUTION_QUEUE_EXTERNAL_EVIDENCE_CONTRACT,
    )
    latency_queue_file = _resolve(root, ws_latency_queue_path or DEFAULT_WS_LATENCY_QUEUE)
    micro_readiness_file = _resolve(root, microstructure_readiness_path or DEFAULT_MICROSTRUCTURE_READINESS)
    micro_models_file = _resolve(root, microstructure_models_path or DEFAULT_MICROSTRUCTURE_MODELS)
    paper_file = _resolve(root, paper_readiness_path or DEFAULT_PAPER_READINESS)
    definition = _read_json(definition_file)
    coverage = _read_json(coverage_file)
    long_horizon_import = _read_json(long_horizon_import_file)
    execution_queue_contract = _read_json(execution_queue_contract_file)
    latency_queue = _read_json(latency_queue_file)
    micro_readiness = _read_json(micro_readiness_file)
    micro_models = _read_json(micro_models_file)
    paper = _read_json(paper_file)
    checks = _checks(
        definition=definition,
        coverage=coverage,
        long_horizon_import=long_horizon_import,
        execution_queue_contract=execution_queue_contract,
        latency_queue=latency_queue,
        micro_readiness=micro_readiness,
        micro_models=micro_models,
        paper=paper,
    )
    external_requirements = _external_requirements(
        coverage=coverage,
        long_horizon_import=long_horizon_import,
        execution_queue_contract=execution_queue_contract,
        latency_queue=latency_queue,
        micro_readiness=micro_readiness,
        micro_models=micro_models,
        paper=paper,
        checks=checks,
    )
    blockers = _blockers(checks)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "scope": "remaining_external_evidence_status_no_candidate_no_paper_no_live",
        "status": _status(checks),
        "decision": _decision(checks),
        "next_required_action": _next_required_action(checks),
        "source_reports": {
            "research_candidate_definition_manifest": _relpath(definition_file, root) if definition_file.exists() else None,
            "ws_l2_capture_coverage": _relpath(coverage_file, root) if coverage_file.exists() else None,
            "long_horizon_l2_tick_import_contract": _relpath(long_horizon_import_file, root)
            if long_horizon_import_file.exists()
            else None,
            "execution_queue_external_evidence_contract": _relpath(execution_queue_contract_file, root)
            if execution_queue_contract_file.exists()
            else None,
            "ws_latency_queue_diagnostics": _relpath(latency_queue_file, root) if latency_queue_file.exists() else None,
            "microstructure_readiness": _relpath(micro_readiness_file, root) if micro_readiness_file.exists() else None,
            "microstructure_models": _relpath(micro_models_file, root) if micro_models_file.exists() else None,
            "paper_readiness": _relpath(paper_file, root) if paper_file.exists() else None,
        },
        "candidate_definition": _candidate_definition(definition),
        "checks": checks,
        "external_requirements": external_requirements,
        "remaining_external_evidence_categories": [
            requirement["category"]
            for requirement in external_requirements
            if not bool(requirement["satisfied"])
        ],
        "remaining_external_evidence_blockers": [
            requirement["blocker"]
            for requirement in external_requirements
            if not bool(requirement["satisfied"])
        ],
        "remaining_blocker_summary": {
            "manual_approval_satisfied": bool(checks["manual_approval_satisfied"]),
            "research_candidate_definition_manifest_ready": bool(checks["research_candidate_definition_manifest_ready"]),
            "only_external_evidence_blockers_remain": _only_external_evidence_blockers_remain(checks),
            "automated_engineering_blockers": _automated_engineering_blockers(checks),
            "remaining_external_evidence_category_count": sum(
                1 for requirement in external_requirements if not bool(requirement["satisfied"])
            ),
        },
        "blockers": blockers,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "true_scalping_allowed": False,
        "guardrails": {
            "research_only": True,
            "status_report_only": True,
            "strategy_code_generation_allowed": False,
            "candidate_generation_allowed": False,
            "strategy_skeleton_generation_allowed": False,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
            "true_scalping_claim_allowed": False,
        },
    }


def write_btc_intraday_short_cycle_remaining_external_evidence_status(
    payload: Mapping[str, Any],
    output_root: Path,
) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / REPORT_FILENAME
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--definition-manifest-path", default=str(DEFAULT_DEFINITION_MANIFEST))
    parser.add_argument("--ws-l2-coverage-path", default=str(DEFAULT_WS_L2_COVERAGE))
    parser.add_argument(
        "--long-horizon-l2-tick-import-contract-path",
        default=str(DEFAULT_LONG_HORIZON_L2_TICK_IMPORT_CONTRACT),
    )
    parser.add_argument(
        "--execution-queue-external-evidence-contract-path",
        default=str(DEFAULT_EXECUTION_QUEUE_EXTERNAL_EVIDENCE_CONTRACT),
    )
    parser.add_argument("--ws-latency-queue-path", default=str(DEFAULT_WS_LATENCY_QUEUE))
    parser.add_argument("--microstructure-readiness-path", default=str(DEFAULT_MICROSTRUCTURE_READINESS))
    parser.add_argument("--microstructure-models-path", default=str(DEFAULT_MICROSTRUCTURE_MODELS))
    parser.add_argument("--paper-readiness-path", default=str(DEFAULT_PAPER_READINESS))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_intraday_short_cycle_remaining_external_evidence_status(
        repo_root=Path(args.repo_root),
        definition_manifest_path=Path(args.definition_manifest_path),
        ws_l2_coverage_path=Path(args.ws_l2_coverage_path),
        long_horizon_l2_tick_import_contract_path=Path(args.long_horizon_l2_tick_import_contract_path),
        execution_queue_external_evidence_contract_path=Path(args.execution_queue_external_evidence_contract_path),
        ws_latency_queue_path=Path(args.ws_latency_queue_path),
        microstructure_readiness_path=Path(args.microstructure_readiness_path),
        microstructure_models_path=Path(args.microstructure_models_path),
        paper_readiness_path=Path(args.paper_readiness_path),
        generated_at=args.generated_at or None,
    )
    print(write_btc_intraday_short_cycle_remaining_external_evidence_status(payload, Path(args.output_root)))


def _checks(
    *,
    definition: Mapping[str, Any],
    coverage: Mapping[str, Any],
    long_horizon_import: Mapping[str, Any],
    execution_queue_contract: Mapping[str, Any],
    latency_queue: Mapping[str, Any],
    micro_readiness: Mapping[str, Any],
    micro_models: Mapping[str, Any],
    paper: Mapping[str, Any],
) -> dict[str, bool]:
    coverage_validation = _mapping(coverage.get("validation"))
    long_horizon_import_validation = _mapping(long_horizon_import.get("validation"))
    execution_queue_validation = _mapping(execution_queue_contract.get("validation"))
    latency_validation = _mapping(latency_queue.get("validation"))
    model_summaries = _mapping(micro_models.get("models"))
    latency_model = _mapping(model_summaries.get("latency_model"))
    queue_model = _mapping(model_summaries.get("queue_position_model"))
    paper_requirements = _mapping(paper.get("requirements"))
    paper_candidate_gate = _mapping(paper_requirements.get("candidate_gate"))
    ws_l2_coverage_contract_satisfied = bool(coverage.get("coverage_contract_satisfied", False)) and bool(
        coverage_validation.get("coverage_contract_satisfied", False)
    )
    long_horizon_l2_tick_import_contract_satisfied = bool(long_horizon_import.get("contract_satisfied", False)) and bool(
        long_horizon_import_validation.get("contract_satisfied", False)
    )
    execution_latency_evidence_contract_satisfied = bool(
        execution_queue_contract.get("execution_latency_evidence_contract_satisfied", False)
    ) and bool(execution_queue_validation.get("execution_latency_evidence_contract_satisfied", False))
    queue_position_evidence_contract_satisfied = bool(
        execution_queue_contract.get("queue_position_evidence_contract_satisfied", False)
    ) and bool(execution_queue_validation.get("queue_position_evidence_contract_satisfied", False))
    return {
        "manual_approval_satisfied": bool(_mapping(definition.get("evidence_requirements")).get("recorded_manual_review_approval", {}).get("satisfied", False)),
        "research_candidate_definition_manifest_ready": bool(
            definition.get("research_candidate_definition_manifest_ready", False)
        ),
        "candidate_generation_still_locked": bool(definition.get("candidate_generation_allowed", True)) is False,
        "strategy_skeleton_still_locked": bool(definition.get("strategy_skeleton_generation_allowed", True)) is False,
        "paper_live_still_locked": bool(definition.get("paper_or_live_unlock_allowed", True)) is False,
        "true_scalping_still_locked": bool(definition.get("true_scalping_allowed", True)) is False,
        "ws_l2_coverage_contract_satisfied": ws_l2_coverage_contract_satisfied,
        "long_horizon_l2_tick_import_contract_satisfied": long_horizon_l2_tick_import_contract_satisfied,
        "long_horizon_l2_tick_history_contract_satisfied": bool(
            ws_l2_coverage_contract_satisfied or long_horizon_l2_tick_import_contract_satisfied
        ),
        "ws_l2_public_source_boundary_satisfied": bool(coverage_validation.get("public_source_boundary_satisfied", False)),
        "ws_l2_required_channels_observed": bool(coverage_validation.get("required_channels_observed", False)),
        "ws_l2_resync_policy_exercised": bool(coverage_validation.get("resync_policy_exercised", False)),
        "ws_receive_latency_proxy_ready": bool(latency_validation.get("receive_latency_proxy_ready", False)),
        "ws_visible_queue_proxy_ready": bool(latency_validation.get("visible_queue_proxy_ready", False)),
        "ws_proxy_diagnostics_ready": bool(latency_queue.get("proxy_diagnostics_ready", False))
        and bool(latency_validation.get("proxy_diagnostics_ready", False)),
        "public_ws_receive_latency_is_private_order_execution_latency": bool(
            latency_validation.get("receive_latency_proxy_is_execution_latency", True)
        ),
        "public_l2_visible_queue_is_exchange_queue_position": bool(
            latency_validation.get("visible_queue_proxy_is_exchange_queue_position", True)
        ),
        "execution_queue_external_evidence_contract_satisfied": bool(
            execution_queue_contract.get("contract_satisfied", False)
        )
        and bool(execution_queue_validation.get("contract_satisfied", False)),
        "execution_latency_evidence_contract_satisfied": execution_latency_evidence_contract_satisfied,
        "queue_position_evidence_contract_satisfied": queue_position_evidence_contract_satisfied,
        "private_order_execution_latency_model_ready": bool(
            (
                bool(coverage_validation.get("execution_latency_model_ready", False))
                and bool(latency_validation.get("execution_latency_model_ready", False))
                and bool(latency_model.get("production_ready", False))
                and bool(latency_model.get("paper_or_live_usable", False))
            )
            or execution_latency_evidence_contract_satisfied
        ),
        "exchange_queue_position_model_ready": bool(
            (
                bool(coverage_validation.get("queue_model_ready", False))
                and bool(latency_validation.get("queue_model_ready", False))
                and bool(queue_model.get("production_ready", False))
                and bool(queue_model.get("paper_or_live_usable", False))
            )
            or queue_position_evidence_contract_satisfied
        ),
        "research_microstructure_models_present": str(micro_models.get("status", "")) == "pass"
        and str(micro_readiness.get("status", "")) == "microstructure_evidence_ready_research_only",
        "paper_gate_ready": str(paper.get("status", "")) == "ready"
        and bool(paper.get("paper_review_pending_allowed", False))
        and bool(paper.get("paper_gate_manual_inputs_complete", False))
        and str(paper_candidate_gate.get("status", "")) == "complete",
    }


def _external_requirements(
    *,
    coverage: Mapping[str, Any],
    long_horizon_import: Mapping[str, Any],
    execution_queue_contract: Mapping[str, Any],
    latency_queue: Mapping[str, Any],
    micro_readiness: Mapping[str, Any],
    micro_models: Mapping[str, Any],
    paper: Mapping[str, Any],
    checks: Mapping[str, bool],
) -> list[dict[str, Any]]:
    coverage_totals = _mapping(coverage.get("coverage_totals"))
    coverage_thresholds = _mapping(coverage.get("thresholds"))
    import_totals = _mapping(long_horizon_import.get("coverage_totals"))
    execution_queue_totals = _mapping(execution_queue_contract.get("coverage_totals"))
    latency_validation = _mapping(latency_queue.get("validation"))
    return [
        {
            "category": "real_long_horizon_market_data",
            "blocker": "btc_true_scalping_long_horizon_l2_tick_history_missing",
            "status": "pending_external_data",
            "satisfied": bool(checks["long_horizon_l2_tick_history_contract_satisfied"]),
            "source_status": str(coverage.get("status", "missing") or "missing"),
            "source_next_required_action": str(coverage.get("next_required_action", "")),
            "evidence_path": "artifacts/btc_scalping_readiness/latest/btc_true_scalping_ws_l2_capture_coverage_report.json",
            "details": {
                "ws_l2_coverage_contract_satisfied": bool(checks["ws_l2_coverage_contract_satisfied"]),
                "long_horizon_l2_tick_import_contract_satisfied": bool(
                    checks["long_horizon_l2_tick_import_contract_satisfied"]
                ),
                "long_horizon_l2_tick_history_contract_satisfied": bool(
                    checks["long_horizon_l2_tick_history_contract_satisfied"]
                ),
                "minimum_research_capture_seconds": _float_or_none(
                    coverage_thresholds.get("minimum_research_capture_seconds")
                ),
                "total_capture_duration_seconds": _float_or_none(
                    coverage_totals.get("total_capture_duration_seconds")
                ),
                "remaining_research_capture_seconds": _float_or_none(
                    coverage_totals.get("remaining_research_capture_seconds")
                ),
                "minimum_event_ledger_history_days": _float_or_none(
                    coverage_thresholds.get("minimum_event_ledger_history_days")
                ),
                "calendar_span_days": _float_or_none(coverage_totals.get("calendar_span_days")),
                "remaining_calendar_span_days": _float_or_none(
                    coverage_totals.get("remaining_calendar_span_days")
                ),
                "verified_public_session_count": int(coverage_totals.get("verified_public_session_count", 0) or 0),
                "import_contract_status": str(long_horizon_import.get("status", "missing") or "missing"),
                "import_manifest_count": int(import_totals.get("manifest_count", 0) or 0),
                "import_tick_history_days": _float_or_none(import_totals.get("tick_history_days")),
                "import_l2_history_days": _float_or_none(import_totals.get("l2_history_days")),
                "import_common_calendar_span_days": _float_or_none(import_totals.get("common_calendar_span_days")),
                "import_evidence_path": (
                    "artifacts/btc_scalping_readiness/latest/"
                    "btc_true_scalping_long_horizon_l2_tick_import_contract_report.json"
                ),
            },
            "source_blockers": _list_of_strings(coverage.get("blockers"))
            + _list_of_strings(long_horizon_import.get("blockers")),
        },
        {
            "category": "execution_evidence",
            "blocker": "btc_true_scalping_execution_latency_model_missing",
            "status": "pending_external_execution_evidence",
            "satisfied": bool(checks["private_order_execution_latency_model_ready"]),
            "source_status": str(latency_queue.get("status", "missing") or "missing"),
            "source_next_required_action": str(latency_queue.get("next_required_action", "")),
            "evidence_path": "artifacts/btc_scalping_readiness/latest/btc_true_scalping_ws_latency_queue_diagnostics_report.json",
            "details": {
                "public_receive_latency_proxy_ready": bool(checks["ws_receive_latency_proxy_ready"]),
                "public_receive_latency_proxy_is_private_order_execution_latency": bool(
                    checks["public_ws_receive_latency_is_private_order_execution_latency"]
                ),
                "execution_latency_model_ready": bool(checks["private_order_execution_latency_model_ready"]),
                "execution_queue_external_evidence_contract_status": str(
                    execution_queue_contract.get("status", "missing") or "missing"
                ),
                "execution_queue_external_evidence_contract_satisfied": bool(
                    checks["execution_queue_external_evidence_contract_satisfied"]
                ),
                "execution_latency_evidence_contract_satisfied": bool(
                    checks["execution_latency_evidence_contract_satisfied"]
                ),
                "execution_latency_observation_count": int(
                    execution_queue_totals.get("execution_latency_observation_count", 0) or 0
                ),
                "remaining_execution_latency_observations": int(
                    execution_queue_totals.get("remaining_execution_latency_observations", 0) or 0
                ),
                "research_microstructure_models_present": bool(checks["research_microstructure_models_present"]),
            },
            "source_blockers": _list_of_strings(latency_queue.get("blockers"))
            + _list_of_strings(execution_queue_contract.get("blockers")),
        },
        {
            "category": "queue_evidence",
            "blocker": "btc_true_scalping_queue_position_model_missing",
            "status": "pending_external_queue_evidence",
            "satisfied": bool(checks["exchange_queue_position_model_ready"]),
            "source_status": str(latency_queue.get("status", "missing") or "missing"),
            "source_next_required_action": str(latency_queue.get("next_required_action", "")),
            "evidence_path": "artifacts/btc_scalping_readiness/latest/btc_true_scalping_ws_latency_queue_diagnostics_report.json",
            "details": {
                "public_visible_queue_proxy_ready": bool(checks["ws_visible_queue_proxy_ready"]),
                "public_l2_visible_queue_is_exchange_queue_position": bool(
                    checks["public_l2_visible_queue_is_exchange_queue_position"]
                ),
                "queue_model_ready": bool(checks["exchange_queue_position_model_ready"]),
                "execution_queue_external_evidence_contract_status": str(
                    execution_queue_contract.get("status", "missing") or "missing"
                ),
                "execution_queue_external_evidence_contract_satisfied": bool(
                    checks["execution_queue_external_evidence_contract_satisfied"]
                ),
                "queue_position_evidence_contract_satisfied": bool(
                    checks["queue_position_evidence_contract_satisfied"]
                ),
                "queue_position_observation_count": int(
                    execution_queue_totals.get("queue_position_observation_count", 0) or 0
                ),
                "remaining_queue_position_observations": int(
                    execution_queue_totals.get("remaining_queue_position_observations", 0) or 0
                ),
                "research_microstructure_models_present": bool(checks["research_microstructure_models_present"]),
            },
            "source_blockers": _list_of_strings(latency_queue.get("blockers"))
            + _list_of_strings(execution_queue_contract.get("blockers")),
        },
        {
            "category": "paper_gate",
            "blocker": "btc_paper_gate_approval_and_observation_missing",
            "status": "pending_paper_gate",
            "satisfied": bool(checks["paper_gate_ready"]),
            "source_status": str(paper.get("status", "missing") or "missing"),
            "source_next_required_action": str(paper.get("next_required_action", "")),
            "evidence_path": "artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json",
            "details": {
                "paper_gate_manual_inputs_complete": bool(paper.get("paper_gate_manual_inputs_complete", False)),
                "paper_or_live_unlock_allowed": bool(paper.get("paper_or_live_unlock_allowed", False)),
                "paper_review_pending_allowed": bool(paper.get("paper_review_pending_allowed", False)),
            },
            "source_blockers": _list_of_strings(paper.get("blockers")),
        },
    ]


def _candidate_definition(definition: Mapping[str, Any]) -> dict[str, str]:
    candidate = _mapping(definition.get("candidate_definition"))
    return {
        "candidate_id": str(candidate.get("candidate_id", "")),
        "strategy_id": str(candidate.get("strategy_id", "")),
        "variant_id": str(candidate.get("variant_id", "")),
        "family_id": str(candidate.get("family_id", "")),
        "definition_scope": str(candidate.get("definition_scope", "")),
    }


def _blockers(checks: Mapping[str, bool]) -> list[str]:
    blockers: list[str] = []
    if not bool(checks["manual_approval_satisfied"]):
        blockers.append("btc_external_evidence_status_manual_approval_not_satisfied")
    if not bool(checks["research_candidate_definition_manifest_ready"]):
        blockers.append("btc_external_evidence_status_candidate_definition_manifest_not_ready")
    if not bool(checks["candidate_generation_still_locked"]):
        blockers.append("btc_external_evidence_status_candidate_generation_unexpectedly_unlocked")
    if not bool(checks["strategy_skeleton_still_locked"]):
        blockers.append("btc_external_evidence_status_strategy_skeleton_unexpectedly_unlocked")
    if not bool(checks["paper_live_still_locked"]):
        blockers.append("btc_external_evidence_status_paper_live_unexpectedly_unlocked")
    if not bool(checks["true_scalping_still_locked"]):
        blockers.append("btc_external_evidence_status_true_scalping_unexpectedly_unlocked")
    if not bool(checks["long_horizon_l2_tick_history_contract_satisfied"]):
        blockers.append("btc_external_evidence_long_horizon_l2_coverage_not_satisfied")
    if not bool(checks["private_order_execution_latency_model_ready"]):
        blockers.append("btc_external_evidence_private_execution_latency_model_missing")
    if not bool(checks["exchange_queue_position_model_ready"]):
        blockers.append("btc_external_evidence_exchange_queue_position_model_missing")
    if not bool(checks["paper_gate_ready"]):
        blockers.append("btc_external_evidence_paper_gate_not_ready")
    return blockers


def _status(checks: Mapping[str, bool]) -> str:
    if not bool(checks["manual_approval_satisfied"]) or not bool(checks["research_candidate_definition_manifest_ready"]):
        return "blocked_candidate_definition_or_manual_approval_required"
    if _only_external_evidence_blockers_remain(checks):
        return "candidate_definition_ready_external_evidence_pending"
    return "blocked_external_evidence_status_repair_required"


def _decision(checks: Mapping[str, bool]) -> str:
    if _status(checks) == "candidate_definition_ready_external_evidence_pending":
        return "continue_external_evidence_collection_no_candidate_no_paper_no_live"
    return "repair_internal_candidate_definition_evidence_before_external_collection"


def _next_required_action(checks: Mapping[str, bool]) -> str:
    if _status(checks) == "candidate_definition_ready_external_evidence_pending":
        return "collect_long_ws_l2_history_private_execution_latency_queue_evidence_then_paper_gate"
    return "repair_candidate_definition_manifest_or_manual_approval_before_external_evidence_status"


def _only_external_evidence_blockers_remain(checks: Mapping[str, bool]) -> bool:
    internal_checks = [
        "manual_approval_satisfied",
        "research_candidate_definition_manifest_ready",
        "candidate_generation_still_locked",
        "strategy_skeleton_still_locked",
        "paper_live_still_locked",
        "true_scalping_still_locked",
        "ws_l2_public_source_boundary_satisfied",
        "ws_l2_required_channels_observed",
        "ws_l2_resync_policy_exercised",
        "ws_receive_latency_proxy_ready",
        "ws_visible_queue_proxy_ready",
        "ws_proxy_diagnostics_ready",
    ]
    return all(bool(checks[name]) for name in internal_checks)


def _automated_engineering_blockers(checks: Mapping[str, bool]) -> list[str]:
    if _only_external_evidence_blockers_remain(checks):
        return []
    external = {
        "ws_l2_coverage_contract_satisfied",
        "private_order_execution_latency_model_ready",
        "exchange_queue_position_model_ready",
        "paper_gate_ready",
        "public_ws_receive_latency_is_private_order_execution_latency",
        "public_l2_visible_queue_is_exchange_queue_position",
        "long_horizon_l2_tick_import_contract_satisfied",
        "long_horizon_l2_tick_history_contract_satisfied",
        "execution_queue_external_evidence_contract_satisfied",
        "execution_latency_evidence_contract_satisfied",
        "queue_position_evidence_contract_satisfied",
    }
    return [name for name, passed in checks.items() if not passed and name not in external]


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


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _float_or_none(value: Any) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001 - metadata only.
        return "unknown"


if __name__ == "__main__":
    main()
