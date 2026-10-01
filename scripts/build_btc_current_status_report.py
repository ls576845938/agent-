#!/usr/bin/env python3
"""Build the single-source BTC current status report.

The report reconciles the current BTC research path without promoting it to a
paper or live candidate. It is intentionally read-only and fail-closed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_current_status/latest")
PROMOTION_GATE = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_promotion_gate_report.json")
MANUAL_REVIEW_PACKET = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_manual_review_packet.json")
DEFINITION_PREFLIGHT = Path(
    "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_research_candidate_definition_preflight.json"
)
DEFINITION_MANIFEST = Path(
    "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_research_candidate_definition_manifest.json"
)
EXTERNAL_EVIDENCE = Path(
    "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_remaining_external_evidence_status_report.json"
)
PAPER_CANDIDATE_GATE = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_paper_candidate_gate_report.json")
LEGACY_CANDIDATE_GATE = Path("artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json")
LEGACY_CANDIDATE_METRIC_REPAIR = Path("artifacts/btc_candidate_gate/latest/candidate_metric_repair_report.json")
PAPER_READINESS = Path("artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json")
BTC_REGISTRY = Path("artifacts/btc_research_registry/research_registry.json")
GLOBAL_REGISTRY = Path("artifacts/global_research_registry/research_registry.json")
REPORT_FILENAME = "btc_current_status_report.json"
BTC_STATE_SEQUENCE = [
    "research_only",
    "backtest_validated",
    "paper_candidate_ready",
    "paper_review_pending",
    "paper_observing",
]


def build_btc_current_status_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    promotion = _read_json(root / PROMOTION_GATE)
    manual = _read_json(root / MANUAL_REVIEW_PACKET)
    preflight = _read_json(root / DEFINITION_PREFLIGHT)
    manifest = _read_json(root / DEFINITION_MANIFEST)
    external = _read_json(root / EXTERNAL_EVIDENCE)
    paper_gate = _read_json(root / PAPER_CANDIDATE_GATE)
    legacy_gate = _read_json(root / LEGACY_CANDIDATE_GATE)
    legacy_metric_repair = _read_json(root / LEGACY_CANDIDATE_METRIC_REPAIR)
    paper_readiness = _read_json(root / PAPER_READINESS)
    btc_registry = _read_json(root / BTC_REGISTRY)
    global_registry = _read_json(root / GLOBAL_REGISTRY)

    candidate_definition = _candidate_definition(manifest, external)
    external_summary = _mapping(external.get("remaining_blocker_summary"))
    candidate_id = str(candidate_definition.get("candidate_id", "") or "")
    research_gate_passed = _research_gate_passed(promotion)
    definition_ready = _definition_ready(manifest)
    research_definition_passed_internal_gate = int(research_gate_passed and definition_ready and bool(candidate_id))
    current_research_definitions = [candidate_id] if research_definition_passed_internal_gate else []
    external_blockers = _list_of_strings(external.get("blockers"))
    paper_gate_ready = _paper_candidate_gate_ready(paper_gate)
    paper_gate_blockers = _list_of_strings(paper_gate.get("blockers"))
    intraday_paper_blockers = _intraday_paper_sim_blockers(external_blockers, paper_gate_ready=paper_gate_ready)
    resolved_external_blockers = _resolved_external_blockers(paper_gate_ready=paper_gate_ready)
    paper_candidate_generation_allowed = paper_gate_ready
    paper_candidate_id = str(_mapping(paper_gate.get("paper_candidate")).get("candidate_id", "") or "")
    current_paper_candidates = [paper_candidate_id] if paper_gate_ready and paper_candidate_id else []
    paper_candidate_passed_internal_gate = int(bool(current_paper_candidates))
    state_machine = _state_machine(
        research_definition_passed_internal_gate=research_definition_passed_internal_gate,
        paper_gate_ready=paper_gate_ready,
        current_paper_candidates=current_paper_candidates,
        paper_readiness=paper_readiness,
    )
    paper_readiness_status = str(state_machine["paper_readiness_status"])
    paper_queue_status = str(state_machine["paper_queue_status"])
    status_source_conflicts = _status_source_conflicts(
        legacy_gate=legacy_gate,
        paper_readiness=paper_readiness,
        btc_registry=btc_registry,
        global_registry=global_registry,
        state_machine=state_machine,
        research_definition_passed_internal_gate=research_definition_passed_internal_gate,
    )
    paper_blockers = (
        []
        if paper_gate_ready
        else (
            [
                "btc_current_status_research_definition_not_promoted_to_paper_candidate",
                *paper_gate_blockers,
            ]
            if research_definition_passed_internal_gate
            else ["btc_current_status_research_definition_not_ready"]
        )
    )

    return {
        "schema_version": "btc_current_status_report_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "status": str(state_machine["authoritative_state"]),
        "active_current_research_focus": "pullback_reclaim_intraday_v0"
        if research_definition_passed_internal_gate
        else "none",
        "research_gate_status": "passed_for_manual_review" if research_gate_passed else "not_passed_for_manual_review",
        "research_candidate_definition_status": "ready" if definition_ready else "not_ready",
        "paper_readiness_status": paper_readiness_status,
        "live_readiness_status": "frozen",
        "paper_queue_status": paper_queue_status,
        "live_status": "frozen",
        "state_machine": state_machine,
        "research_definition_passed_internal_gate": research_definition_passed_internal_gate,
        "paper_candidate_passed_internal_gate": paper_candidate_passed_internal_gate,
        "current_research_candidate_definitions": current_research_definitions,
        "current_paper_candidates": current_paper_candidates,
        "selected_candidate_definition": candidate_definition,
        "metrics": _metrics(promotion, manual, preflight, manifest),
        "source_reports": {
            "promotion_gate": _maybe_path(root, PROMOTION_GATE),
            "manual_review_packet": _maybe_path(root, MANUAL_REVIEW_PACKET),
            "research_candidate_definition_preflight": _maybe_path(root, DEFINITION_PREFLIGHT),
            "research_candidate_definition_manifest": _maybe_path(root, DEFINITION_MANIFEST),
            "remaining_external_evidence_status": _maybe_path(root, EXTERNAL_EVIDENCE),
            "paper_candidate_gate": _maybe_path(root, PAPER_CANDIDATE_GATE),
            "legacy_candidate_gate": _maybe_path(root, LEGACY_CANDIDATE_GATE),
            "legacy_candidate_metric_repair": _maybe_path(root, LEGACY_CANDIDATE_METRIC_REPAIR),
            "paper_readiness": _maybe_path(root, PAPER_READINESS),
            "btc_registry": _maybe_path(root, BTC_REGISTRY),
            "global_registry": _maybe_path(root, GLOBAL_REGISTRY),
        },
        "legacy_candidate_gate": {
            "status": str(legacy_gate.get("status", "missing") or "missing"),
            "candidate_passed_internal_gate": int(legacy_gate.get("candidate_passed_internal_gate", 0) or 0),
            "paper_review_pending_allowed": bool(legacy_gate.get("paper_review_pending_allowed", False)),
            "strategy_id": str(legacy_gate.get("strategy_id", "") or ""),
            "blockers": _list_of_strings(legacy_gate.get("blockers")),
        },
        "legacy_candidate_metric_repair": {
            "status": str(legacy_metric_repair.get("status", "missing") or "missing"),
            "promotion_allowed": bool(legacy_metric_repair.get("promotion_allowed", False)),
            "paper_review_pending_allowed": bool(legacy_metric_repair.get("paper_review_pending_allowed", False)),
            "failed_metrics": _list_of_strings(legacy_metric_repair.get("failed_metrics")),
            "blockers": _list_of_strings(legacy_metric_repair.get("blockers")),
        },
        "execution_evidence_policy": {
            "current_scope": "intraday_5m_15m_simulated_paper_not_true_scalping",
            "true_scalping_requirements_are_diagnostic_for_current_scope": True,
            "hard_requirements_for_current_intraday_paper_sim": [
                "research_candidate_definition_manifest_ready",
                "separate_paper_candidate_gate",
                "approved_paper_review",
                "simulated_broker_only",
                "fees_slippage_funding_in_ledger",
            ],
            "diagnostic_or_upgrade_requirements_for_current_scope": [
                "long_horizon_l2_coverage",
                "private_execution_latency_model",
                "exchange_queue_position_model",
            ],
            "true_scalping_hard_requirements_before_scalping_claim": [
                "1m_or_tick_data",
                "long_horizon_l2_order_book",
                "spread_latency_queue_model",
                "private_execution_latency_model",
                "exchange_queue_position_model",
            ],
        },
        "external_evidence": {
            "status": str(external.get("status", "missing") or "missing"),
            "only_external_evidence_blockers_remain": bool(
                external_summary.get("only_external_evidence_blockers_remain", False)
            ),
            "remaining_external_evidence_categories": _list_of_strings(
                external.get("remaining_external_evidence_categories")
            ),
            "remaining_external_evidence_blockers": _list_of_strings(
                external.get("remaining_external_evidence_blockers")
            ),
            "raw_blockers": external_blockers,
            "intraday_paper_sim_hard_blockers": intraday_paper_blockers,
            "true_scalping_only_blockers": [
                blocker
                for blocker in external_blockers
                if blocker not in intraday_paper_blockers and blocker not in resolved_external_blockers
            ],
        },
        "readiness_summary": {
            "paper_candidate_generation_allowed": paper_candidate_generation_allowed,
            "paper_review_pending_allowed": paper_gate_ready,
            "paper_or_live_unlock_allowed": bool(external.get("paper_or_live_unlock_allowed", False)),
            "true_scalping_allowed": bool(external.get("true_scalping_allowed", False)),
            "next_required_action": (
                str(paper_readiness.get("next_required_action") or "start_paper_validation")
                if paper_queue_status == "approved"
                else "human_paper_review_approval"
                if paper_queue_status == "pending_review"
                else (
                    "produce_current_intraday_paper_candidate_gate"
                    if research_definition_passed_internal_gate
                    else "repair_current_btc_research_status"
                )
            ),
            "paper_blockers": paper_blockers,
        },
        "status_source_conflicts": status_source_conflicts,
        "guardrails": {
            "research_only": True,
            "simulated_paper_only_until_separate_gate": True,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "paper_or_live_unlock_allowed": False,
            "true_scalping_allowed": False,
        },
        "blockers": _dedupe(
            [
                *status_source_conflicts,
                *(paper_gate_blockers if research_definition_passed_internal_gate and not paper_gate_ready else []),
            ]
        ),
    }


def write_btc_current_status_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / REPORT_FILENAME
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_current_status_report(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_current_status_report(payload, Path(args.output_root)))


def _research_gate_passed(promotion: Mapping[str, Any]) -> bool:
    gate = _mapping(promotion.get("gate"))
    return bool(
        promotion.get("status") == "ready_for_manual_candidate_review"
        and promotion.get("manual_candidate_review_allowed") is True
        and gate.get("passed") is True
        and gate.get("status") == "candidate_passed_internal_gate"
        and not _list_of_strings(promotion.get("blockers"))
    )


def _definition_ready(manifest: Mapping[str, Any]) -> bool:
    return bool(
        manifest.get("status") == "ready_research_candidate_definition_manifest_only"
        and manifest.get("research_candidate_definition_manifest_ready") is True
        and not _list_of_strings(manifest.get("blockers"))
    )


def _candidate_definition(
    manifest: Mapping[str, Any],
    external: Mapping[str, Any],
) -> dict[str, Any]:
    definition = _mapping(manifest.get("candidate_definition")) or _mapping(external.get("candidate_definition"))
    return {
        "candidate_id": str(definition.get("candidate_id", "") or ""),
        "definition_scope": str(definition.get("definition_scope", "") or ""),
        "family_id": str(definition.get("family_id", "") or ""),
        "strategy_id": str(definition.get("strategy_id", "") or ""),
        "variant_id": str(definition.get("variant_id", "") or ""),
        "source_run_id": str(definition.get("source_run_id", "") or ""),
        "source_strategy_version": str(definition.get("source_strategy_version", "") or ""),
        "source_data_version": str(definition.get("source_data_version", "") or ""),
        "params_hash": str(definition.get("params_hash", "") or ""),
    }


def _metrics(*reports: Mapping[str, Any]) -> dict[str, Any]:
    for report in reports:
        review_subject = _mapping(report.get("review_subject"))
        metrics = _mapping(review_subject.get("metrics")) or _mapping(report.get("metrics"))
        if metrics:
            return {
                "trade_count": int(metrics.get("trade_count", 0) or 0),
                "fill_count": int(metrics.get("fill_count", 0) or 0),
                "profit_factor": _float_or_none(metrics.get("profit_factor")),
                "event_profit_factor": _float_or_none(metrics.get("event_profit_factor")),
                "walk_forward_pass_rate": _float_or_none(metrics.get("walk_forward_pass_rate")),
                "regime_pass_rate": _float_or_none(metrics.get("regime_pass_rate")),
                "pbo": _float_or_none(metrics.get("pbo")),
                "dsr": _float_or_none(metrics.get("dsr")),
            }
    return {
        "trade_count": 0,
        "fill_count": 0,
        "profit_factor": None,
        "event_profit_factor": None,
        "walk_forward_pass_rate": None,
        "regime_pass_rate": None,
        "pbo": None,
        "dsr": None,
    }


def _paper_candidate_gate_ready(payload: Mapping[str, Any]) -> bool:
    return bool(
        payload.get("schema_version") == "btc_intraday_short_cycle_paper_candidate_gate_report_v1"
        and payload.get("status") == "ready_for_manual_paper_review"
        and payload.get("paper_candidate_generation_allowed") is True
        and payload.get("paper_review_pending_allowed") is True
        and payload.get("paper_execution_authorized") is False
        and payload.get("paper_or_live_unlock_allowed") is False
        and payload.get("true_scalping_allowed") is False
        and not _list_of_strings(payload.get("blockers"))
        and bool(str(_mapping(payload.get("paper_candidate")).get("candidate_id", "")).strip())
    )


def _intraday_paper_sim_blockers(external_blockers: list[str], *, paper_gate_ready: bool) -> list[str]:
    hard = {"btc_external_evidence_paper_gate_not_ready"}
    if paper_gate_ready:
        hard = set()
    return [blocker for blocker in external_blockers if blocker in hard]


def _resolved_external_blockers(*, paper_gate_ready: bool) -> set[str]:
    if paper_gate_ready:
        return {"btc_external_evidence_paper_gate_not_ready"}
    return set()


def _status_source_conflicts(
    *,
    legacy_gate: Mapping[str, Any],
    paper_readiness: Mapping[str, Any],
    btc_registry: Mapping[str, Any],
    global_registry: Mapping[str, Any],
    state_machine: Mapping[str, Any],
    research_definition_passed_internal_gate: int,
) -> list[str]:
    conflicts: list[str] = []
    legacy_count = int(legacy_gate.get("candidate_passed_internal_gate", 0) or 0)
    expected_queue = str(state_machine.get("paper_queue_status", "locked") or "locked")
    expected_readiness = str(state_machine.get("paper_readiness_status", "blocked") or "blocked")
    btc = _mapping(btc_registry.get("btc"))
    registry_queue = str(btc.get("paper_queue_status", "") or "")
    global_queue = str(global_registry.get("paper_queue_status", "") or "")
    readiness_queue = str(paper_readiness.get("paper_queue_status", "") or "")
    readiness_status = str(paper_readiness.get("status", "") or "")
    if readiness_queue and readiness_queue != expected_queue:
        conflicts.append("btc_current_status_paper_readiness_queue_conflict")
    if readiness_status and readiness_status != expected_readiness:
        conflicts.append("btc_current_status_paper_readiness_status_conflict")
    if registry_queue and registry_queue != expected_queue:
        conflicts.append("btc_current_status_btc_registry_queue_conflict")
    if global_queue and global_queue != expected_queue:
        conflicts.append("btc_current_status_global_registry_queue_conflict")
    if expected_queue == "approved" and legacy_count <= 0 and not research_definition_passed_internal_gate:
        conflicts.append("btc_current_status_approved_without_internal_gate")
    return conflicts


def _state_machine(
    *,
    research_definition_passed_internal_gate: int,
    paper_gate_ready: bool,
    current_paper_candidates: list[str],
    paper_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    readiness_status = str(paper_readiness.get("status", "") or "")
    readiness_queue = str(paper_readiness.get("paper_queue_status", "") or "")
    paper_start_allowed = bool(paper_readiness.get("paper_start_allowed", False))
    if readiness_status == "ready_for_paper_start" and readiness_queue == "approved" and paper_start_allowed:
        authoritative_state = "paper_observing"
        paper_readiness_status = readiness_status
        paper_queue_status = "approved"
        source = "btc_paper_readiness"
    elif readiness_status == "ready_for_manual_paper_review" and readiness_queue == "pending_review":
        authoritative_state = "paper_review_pending"
        paper_readiness_status = readiness_status
        paper_queue_status = "pending_review"
        source = "btc_paper_readiness"
    elif paper_gate_ready and current_paper_candidates:
        authoritative_state = "paper_candidate_ready"
        paper_readiness_status = readiness_status if readiness_status else "ready_for_manual_paper_review"
        paper_queue_status = readiness_queue if readiness_queue in {"pending_review", "approved"} else "pending_review"
        source = "btc_current_status"
    elif research_definition_passed_internal_gate:
        authoritative_state = "backtest_validated"
        paper_readiness_status = readiness_status if readiness_status else "blocked"
        paper_queue_status = "locked"
        source = "btc_current_status"
    else:
        authoritative_state = "research_only"
        paper_readiness_status = readiness_status if readiness_status else "blocked"
        paper_queue_status = "locked"
        source = "btc_current_status"
    return {
        "authoritative_state": authoritative_state,
        "state_source": source,
        "allowed_sequence": BTC_STATE_SEQUENCE,
        "paper_queue_status": paper_queue_status,
        "paper_readiness_status": paper_readiness_status,
        "live_status": "frozen",
        "live_transition_allowed": False,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _maybe_path(root: Path, path: Path) -> str | None:
    full = root / path
    return _relpath(full, root) if full.exists() else None


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
