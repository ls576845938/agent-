#!/usr/bin/env python3
"""Build a BTC paper-review evidence pack and human review template.

This builder is read-only with respect to trading. It never approves a paper
review, never starts paper validation, and never touches broker/order paths.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "btc_paper_review_evidence_pack_report_v1"
EVIDENCE_SCHEMA_VERSION = "btc_paper_review_evidence_pack_v1"
REVIEW_TEMPLATE_SCHEMA_VERSION = "paper_review_candidate_template_v1"
APPROVAL_SCHEMA_VERSION = "paper_review_approval_v1"
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_paper_readiness/latest")
DEFAULT_DATA_ROOT = Path("data")
DEFAULT_REVIEW_ID = "btc_pullback_reclaim_intraday_paper_review_v1"
DEFAULT_PROPOSED_CAPITAL = 25_000.0
DEFAULT_CURRENT_STATUS = Path("artifacts/btc_current_status/latest/btc_current_status_report.json")
DEFAULT_PAPER_CANDIDATE_GATE = Path(
    "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_paper_candidate_gate_report.json"
)
DEFAULT_READINESS = Path("artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json")
DEFAULT_START_REPORT = Path("artifacts/btc_paper_readiness/latest/btc_paper_validation_start_report.json")
REPORT_FILENAME = "btc_paper_review_evidence_pack_report.json"
EVIDENCE_FILENAME = "evidence_pack.json"
REVIEW_TEMPLATE_FILENAME = "review_template.json"
REQUIRED_EVIDENCE_FIELDS = [
    "strategy_id",
    "research_question",
    "economic_hypothesis",
    "data_source",
    "data_version",
    "start_time",
    "end_time",
    "decision_time_rule",
    "execution_time_rule",
    "cost_model",
    "slippage_model",
    "params",
    "params_hash",
    "candidate_count",
    "trial_count",
    "selected_by",
    "walk_forward_summary",
    "regime_summary",
    "parameter_stability_summary",
    "cost_stress_summary",
    "ledger_reconciliation",
    "promotion_decision",
]
REQUIRED_MINIMUM_METRICS = [
    "total_return",
    "annualized_return",
    "annualized_volatility",
    "risk_adjusted_return",
    "max_drawdown",
    "turnover",
    "average_holding_period",
    "exposure_ratio",
    "number_of_bets",
    "fee_paid",
    "slippage_paid_or_modeled",
    "best_year_contribution_share",
    "worst_year",
    "capacity_proxy",
]


def build_btc_paper_review_evidence_pack_report(
    *,
    repo_root: Path | None = None,
    data_root: Path | None = None,
    review_id: str = DEFAULT_REVIEW_ID,
    current_status_path: Path | None = None,
    paper_candidate_gate_path: Path | None = None,
    readiness_path: Path | None = None,
    start_report_path: Path | None = None,
    proposed_capital: float = DEFAULT_PROPOSED_CAPITAL,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    resolved_data_root = _resolve(root, data_root or DEFAULT_DATA_ROOT)
    current_file = _resolve(root, current_status_path or DEFAULT_CURRENT_STATUS)
    paper_gate_file = _resolve(root, paper_candidate_gate_path or DEFAULT_PAPER_CANDIDATE_GATE)
    readiness_file = _resolve(root, readiness_path or DEFAULT_READINESS)
    start_file = _resolve(root, start_report_path or DEFAULT_START_REPORT)
    generated = generated_at or _utc_z_now()

    current = _read_json(current_file)
    paper_gate = _read_json(paper_gate_file)
    readiness = _read_json(readiness_file)
    start_report = _read_json(start_file)
    paper_candidate = _mapping(paper_gate.get("paper_candidate"))
    research_candidate = _mapping(paper_gate.get("research_candidate_definition"))
    candidate_id = str(paper_candidate.get("candidate_id", "") or "")
    review_dir = resolved_data_root / "research" / "paper_reviews" / review_id
    evidence_dir = resolved_data_root / "research" / "evidence_packs" / review_id
    evidence_path = evidence_dir / EVIDENCE_FILENAME
    review_template_path = review_dir / REVIEW_TEMPLATE_FILENAME
    final_review_path = review_dir / "review.json"

    source_reports = {
        "current_status": _relpath(current_file, root) if current_file.exists() else None,
        "paper_candidate_gate": _relpath(paper_gate_file, root) if paper_gate_file.exists() else None,
        "paper_readiness": _relpath(readiness_file, root) if readiness_file.exists() else None,
        "paper_validation_start_report": _relpath(start_file, root) if start_file.exists() else None,
        **{
            f"paper_candidate_source_{key}": value
            for key, value in _mapping(paper_gate.get("source_reports")).items()
            if isinstance(value, str) and value
        },
    }
    source_reports.update(_run_evidence_source_reports(root=root, source_reports=source_reports))
    promotion_evidence_contract = _promotion_evidence_contract(
        root=root,
        source_reports=source_reports,
        current=current,
        paper_gate=paper_gate,
    )
    blockers = _evidence_pack_blockers(
        current_file=current_file,
        current=current,
        paper_gate_file=paper_gate_file,
        paper_gate=paper_gate,
        readiness_file=readiness_file,
        readiness=readiness,
        start_report=start_report,
        candidate_id=candidate_id,
        proposed_capital=proposed_capital,
    )
    blockers.extend(_list_of_strings(promotion_evidence_contract.get("blockers")))
    blockers = _dedupe(blockers)
    status = "ready_for_human_paper_review" if not blockers else "blocked"
    decision = "await_human_approval_no_auto_start" if not blockers else "repair_evidence_before_review"

    evidence_pack = _evidence_pack(
        generated_at=generated,
        review_id=review_id,
        candidate_id=candidate_id,
        proposed_capital=proposed_capital,
        source_reports=source_reports,
        current=current,
        paper_gate=paper_gate,
        readiness=readiness,
        start_report=start_report,
        blockers=blockers,
        status=status,
        decision=decision,
        promotion_evidence_contract=promotion_evidence_contract,
    )
    evidence_sha = _json_sha256(evidence_pack)
    review_template = _review_template(
        root=root,
        generated_at=generated,
        review_id=review_id,
        candidate_id=candidate_id,
        paper_candidate=paper_candidate,
        evidence_path=evidence_path,
        evidence_sha=evidence_sha,
        proposed_capital=proposed_capital,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "review_id": review_id,
        "status": status,
        "decision": decision,
        "next_required_action": "human_paper_review_approval" if not blockers else "repair_paper_review_evidence_pack",
        "evidence_pack_path": _relpath(evidence_path, root),
        "evidence_pack_sha256": evidence_sha,
        "review_template_path": _relpath(review_template_path, root),
        "final_review_path": _relpath(final_review_path, root),
        "candidate_id": candidate_id,
        "proposed_symbols": ["BTCUSDT"] if candidate_id else [],
        "proposed_capital": float(proposed_capital),
        "source_reports": source_reports,
        "source_hashes": _source_hashes(root, source_reports),
        "promotion_evidence_contract": promotion_evidence_contract,
        "evidence_pack": evidence_pack,
        "review_template": review_template,
        "blockers": blockers,
        "paper_start_allowed": False,
        "paper_execution_authorized": False,
        "live_status": "frozen",
        "guardrails": _guardrails(),
    }


def write_btc_paper_review_evidence_pack_artifacts(payload: Mapping[str, Any], *, output_root: Path) -> str:
    evidence_pack = _mapping(payload.get("evidence_pack"))
    review_template = _mapping(payload.get("review_template"))
    evidence_path = Path(str(payload.get("evidence_pack_path", "")))
    review_template_path = Path(str(payload.get("review_template_path", "")))
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    review_template_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_file(evidence_path, evidence_pack)
    evidence_sha = _sha256(evidence_path)
    report = dict(payload)
    report["evidence_pack_sha256"] = evidence_sha
    template = dict(review_template)
    approval = dict(_mapping(template.get("approval")))
    approval["source_sha256"] = evidence_sha
    template["approval"] = approval
    _write_json_file(review_template_path, template)
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / REPORT_FILENAME
    report["evidence_pack"] = {
        "schema_version": evidence_pack.get("schema_version", ""),
        "status": evidence_pack.get("status", ""),
        "candidate_id": evidence_pack.get("candidate_id", ""),
    }
    report["review_template"] = {
        "schema_version": template.get("schema_version", ""),
        "status": template.get("status", ""),
        "paper_review_id": template.get("paper_review_id", ""),
    }
    _write_json_file(output, report)
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--review-id", default=DEFAULT_REVIEW_ID)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--proposed-capital", type=float, default=DEFAULT_PROPOSED_CAPITAL)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_paper_review_evidence_pack_report(
        repo_root=Path(args.repo_root),
        data_root=Path(args.data_root),
        review_id=args.review_id,
        proposed_capital=float(args.proposed_capital),
        generated_at=args.generated_at or None,
    )
    print(write_btc_paper_review_evidence_pack_artifacts(payload, output_root=Path(args.output_root)))


def _evidence_pack(
    *,
    generated_at: str,
    review_id: str,
    candidate_id: str,
    proposed_capital: float,
    source_reports: Mapping[str, str | None],
    current: Mapping[str, Any],
    paper_gate: Mapping[str, Any],
    readiness: Mapping[str, Any],
    start_report: Mapping[str, Any],
    blockers: list[str],
    status: str,
    decision: str,
    promotion_evidence_contract: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "generated_at": generated_at,
        "review_id": review_id,
        "candidate_id": candidate_id,
        "asset": "btc",
        "symbol": "BTCUSDT",
        "market_type": "usds_m_perpetual",
        "status": status,
        "decision": decision,
        "paper_review_scope": "btc_intraday_short_cycle_manual_paper_review",
        "proposed_symbols": ["BTCUSDT"] if candidate_id else [],
        "proposed_capital": float(proposed_capital),
        "source_reports": dict(source_reports),
        "promotion_evidence_contract": dict(promotion_evidence_contract),
        "candidate": {
            "research_candidate_definition": dict(_mapping(paper_gate.get("research_candidate_definition"))),
            "paper_candidate": dict(_mapping(paper_gate.get("paper_candidate"))),
            "metrics": dict(_mapping(paper_gate.get("metrics"))),
            "checks": dict(_mapping(paper_gate.get("checks"))),
            "execution_evidence_policy": dict(_mapping(paper_gate.get("execution_evidence_policy"))),
        },
        "readiness": {
            "status": str(readiness.get("status", "")),
            "paper_queue_status": str(readiness.get("paper_queue_status", "")),
            "paper_start_allowed": bool(readiness.get("paper_start_allowed", False)),
            "paper_execution_authorized": bool(readiness.get("paper_execution_authorized", False)),
            "next_required_action": str(readiness.get("next_required_action", "")),
            "requirements": dict(_mapping(readiness.get("requirements"))),
            "approved_paper_review": dict(_mapping(readiness.get("approved_paper_review"))),
        },
        "start_report": {
            "status": str(start_report.get("status", "")),
            "paper_start_allowed": bool(start_report.get("paper_start_allowed", False)),
            "paper_execution_authorized": bool(start_report.get("paper_execution_authorized", False)),
            "next_required_action": str(start_report.get("next_required_action", "")),
        },
        "current_status": {
            "status": str(current.get("status", "")),
            "paper_queue_status": str(current.get("paper_queue_status", "")),
            "live_status": str(current.get("live_status", "")),
            "selected_candidate_definition": dict(_mapping(current.get("selected_candidate_definition"))),
        },
        "blockers": list(blockers),
        "guardrails": _guardrails(),
    }


def _promotion_evidence_contract(
    *,
    root: Path,
    source_reports: Mapping[str, str | None],
    current: Mapping[str, Any],
    paper_gate: Mapping[str, Any],
) -> dict[str, Any]:
    run_manifest_path = _resolve_source(root, source_reports, "paper_candidate_source_current_candidate_run_manifest")
    canonical_path = _resolve_source(root, source_reports, "current_candidate_canonical_backtest")
    walk_forward_path = _resolve_source(root, source_reports, "current_candidate_walk_forward")
    regime_path = _resolve_source(root, source_reports, "current_candidate_regime")
    cost_stress_path = _resolve_source(root, source_reports, "paper_candidate_source_current_candidate_cost_stress")
    promotion_path = _resolve_source(root, source_reports, "current_candidate_promotion_decision")
    trade_ledger_path = _resolve_source(root, source_reports, "paper_candidate_source_current_candidate_trade_ledger")

    run_manifest = _read_json(run_manifest_path) if run_manifest_path else {}
    canonical = _read_json(canonical_path) if canonical_path else {}
    walk_forward = _read_json(walk_forward_path) if walk_forward_path else {}
    regime = _read_json(regime_path) if regime_path else {}
    cost_stress = _read_json(cost_stress_path) if cost_stress_path else {}
    promotion = _read_json(promotion_path) if promotion_path else {}
    ledger_metrics = _trade_ledger_metrics(trade_ledger_path) if trade_ledger_path else {}
    metrics = _mapping(canonical.get("metrics"))
    data_range = _mapping(canonical.get("data_range"))
    gate_decision = _mapping(canonical.get("gate_decision"))
    candidate = _mapping(paper_gate.get("paper_candidate"))
    research_candidate = _mapping(paper_gate.get("research_candidate_definition"))
    run_dir = run_manifest_path.parent if run_manifest_path else None

    fields = {
        "strategy_id": _evidence_field(run_manifest.get("strategy_id") or candidate.get("strategy_id"), run_manifest_path),
        "research_question": _evidence_field(
            "Can a BTCUSDT 5m pullback-reclaim signal gated by 15m context and high-volatility trend filters produce ledger-positive, cost-stressed intraday fills without look-ahead?",
            canonical_path,
        ),
        "economic_hypothesis": _evidence_field(
            "After an intraday pullback reclaims prior structure, BTC perpetual flow can continue in high-volatility non-expansion regimes; the edge should survive taker fees, slippage stress, and walk-forward splits.",
            canonical_path,
        ),
        "data_source": _evidence_field(
            {
                "data_version": run_manifest.get("data_version") or research_candidate.get("source_data_version"),
                "source_reports": {
                    key: value
                    for key, value in source_reports.items()
                    if key in {"paper_candidate_source_data_status", "paper_candidate_source_current_candidate_run_manifest"}
                },
            },
            run_manifest_path,
        ),
        "data_version": _evidence_field(run_manifest.get("data_version"), run_manifest_path),
        "start_time": _evidence_field(data_range.get("start"), canonical_path),
        "end_time": _evidence_field(data_range.get("end"), canonical_path),
        "decision_time_rule": _evidence_field(
            {
                "rule": "closed_bar_features_only_available_before_next_bar_decision",
                "basis": _mapping(canonical.get("no_lookahead_status")).get("basis"),
                "status": _mapping(canonical.get("no_lookahead_status")).get("status"),
            },
            canonical_path,
        ),
        "execution_time_rule": _evidence_field(
            "event_engine_next_bar_execution_after_signal_bar_close",
            canonical_path,
        ),
        "cost_model": _evidence_field(run_manifest.get("cost_model") or canonical.get("cost_model_id"), run_manifest_path),
        "slippage_model": _evidence_field(run_manifest.get("slippage_model"), run_manifest_path),
        "params": _evidence_field(run_manifest.get("params"), run_manifest_path),
        "params_hash": _evidence_field(run_manifest.get("params_hash") or research_candidate.get("params_hash"), run_manifest_path),
        "candidate_count": _evidence_field(
            {
                "paper_candidates": len(_list_of_strings(current.get("current_paper_candidates"))),
                "research_candidate_definitions": len(_list_of_strings(current.get("current_research_candidate_definitions"))),
            },
            Path(str(source_reports.get("current_status") or "")),
        ),
        "trial_count": _evidence_field(_trial_count(run_dir), run_manifest_path),
        "selected_by": _evidence_field(
            {
                "paper_candidate_gate_decision": paper_gate.get("decision"),
                "canonical_gate_status": gate_decision.get("status"),
                "selection_rule": "passed_internal_gate_then_manual_paper_review_only",
            },
            Path(str(source_reports.get("paper_candidate_gate") or "")),
        ),
        "walk_forward_summary": _evidence_field(_walk_forward_summary(walk_forward), walk_forward_path),
        "regime_summary": _evidence_field(_regime_summary(regime), regime_path),
        "parameter_stability_summary": _evidence_field(
            {
                "params_hash": run_manifest.get("params_hash"),
                "walk_forward_fold_count": walk_forward.get("fold_count"),
                "fixed_params_across_folds": bool(run_manifest.get("params_hash") and walk_forward.get("fold_count")),
                "source_check": _mapping(paper_gate.get("checks")).get("current_run_manifest_params_hash_matches"),
            },
            run_manifest_path,
        ),
        "cost_stress_summary": _evidence_field(_cost_stress_summary(cost_stress), cost_stress_path),
        "ledger_reconciliation": _evidence_field(
            {
                "status": _mapping(canonical.get("event_ledger_status")).get("status"),
                "ledger_equity_consistent": _mapping(canonical.get("event_ledger_status")).get("ledger_equity_consistent"),
                "pnl_source": _mapping(canonical.get("event_ledger_status")).get("pnl_source"),
                "manifest_path": _mapping(canonical.get("event_ledger_status")).get("manifest_path"),
            },
            canonical_path,
        ),
        "promotion_decision": _evidence_field(
            {
                "research_promotion_decision": promotion.get("decision"),
                "paper_candidate_gate_decision": paper_gate.get("decision"),
                "paper_start_allowed": False,
                "live": "FROZEN",
            },
            promotion_path,
        ),
    }
    minimum_metrics = _minimum_metrics(metrics=metrics, cost_stress=cost_stress, ledger_metrics=ledger_metrics)
    missing_fields = [key for key in REQUIRED_EVIDENCE_FIELDS if not _present(fields.get(key, {}).get("value"))]
    missing_metrics = [key for key in REQUIRED_MINIMUM_METRICS if not _present(minimum_metrics.get(key))]
    blockers = [f"btc_promotion_evidence_missing_{key}" for key in missing_fields]
    blockers.extend(f"btc_promotion_evidence_metric_missing_{key}" for key in missing_metrics)
    if _mapping(fields["ledger_reconciliation"]["value"]).get("ledger_equity_consistent") is not True:
        blockers.append("btc_promotion_evidence_ledger_reconciliation_not_consistent")
    return {
        "schema_version": "btc_promotion_evidence_contract_v1",
        "status": "complete" if not blockers else "blocked",
        "required_fields": REQUIRED_EVIDENCE_FIELDS,
        "minimum_metrics_required": REQUIRED_MINIMUM_METRICS,
        "fields": fields,
        "minimum_metrics": minimum_metrics,
        "missing_fields": missing_fields,
        "missing_minimum_metrics": missing_metrics,
        "blockers": _dedupe(blockers),
    }


def _review_template(
    *,
    root: Path,
    generated_at: str,
    review_id: str,
    candidate_id: str,
    paper_candidate: Mapping[str, Any],
    evidence_path: Path,
    evidence_sha: str,
    proposed_capital: float,
) -> dict[str, Any]:
    evidence_source = _relpath(evidence_path, root)
    gate_snapshot = {
        "candidate_id": candidate_id,
        "decision": "READY_FOR_PAPER_REVIEW",
        "paper_execution_authorized": False,
        "authorization_scope": "human_review_only",
    }
    return {
        "schema_version": REVIEW_TEMPLATE_SCHEMA_VERSION,
        "paper_review_id": review_id,
        "strategy_manifest_id": candidate_id,
        "portfolio_sim_id": "",
        "evidence_pack_path": evidence_source,
        "source_candidate_ids": [candidate_id] if candidate_id else [],
        "evidence_gate_status": "READY_FOR_REVIEW" if candidate_id else "BLOCKED",
        "evidence_gate_blocking_reasons": [],
        "proposed_symbols": ["BTCUSDT"] if candidate_id else [],
        "proposed_capital": float(proposed_capital),
        "proposed_risk_envelope": {
            "market_type": "usds_m_perpetual",
            "paper_mode": str(paper_candidate.get("paper_mode", "simulated_broker_only") or "simulated_broker_only"),
            "validation_days_required": int(paper_candidate.get("validation_days_required", 30) or 30),
        },
        "status": "PENDING_HUMAN_REVIEW",
        "reviewer": "",
        "review_notes": "",
        "created_at": generated_at,
        "reviewed_at": "",
        "approval": {
            "valid": False,
            "schema_version": APPROVAL_SCHEMA_VERSION,
            "reviewer": "<required-human-reviewer>",
            "reason": "human paper review approval only; no live authorization",
            "timestamp": "YYYY-MM-DDTHH:MM:SSZ",
            "candidate_id": candidate_id,
            "commit_hash": _git(["rev-parse", "--short", "HEAD"], cwd=root),
            "source": evidence_source,
            "source_sha256": evidence_sha,
            "gate_snapshot": gate_snapshot,
            "blockers": ["human_approval_not_recorded"],
        },
        "instructions": {
            "write_final_approval_to": _relpath(evidence_path.parent.parent.parent / "paper_reviews" / review_id / "review.json", root),
            "required_final_status": "APPROVED_FOR_PAPER_ONLY",
            "required_approval_valid": True,
            "paper_execution_authorized_in_snapshot_must_remain_false": True,
            "authorization_scope": "human_review_only",
        },
    }


def _evidence_pack_blockers(
    *,
    current_file: Path,
    current: Mapping[str, Any],
    paper_gate_file: Path,
    paper_gate: Mapping[str, Any],
    readiness_file: Path,
    readiness: Mapping[str, Any],
    start_report: Mapping[str, Any],
    candidate_id: str,
    proposed_capital: float,
) -> list[str]:
    blockers: list[str] = []
    if not current_file.exists():
        blockers.append("btc_paper_review_current_status_missing")
    if not paper_gate_file.exists():
        blockers.append("btc_paper_review_candidate_gate_missing")
    if not readiness_file.exists():
        blockers.append("btc_paper_review_readiness_missing")
    if str(current.get("status", "")) != "paper_candidate_ready_for_manual_review":
        blockers.append("btc_paper_review_current_status_not_ready")
    if str(paper_gate.get("status", "")) != "ready_for_manual_paper_review":
        blockers.append("btc_paper_review_candidate_gate_not_ready")
    if str(readiness.get("status", "")) != "ready_for_manual_paper_review":
        blockers.append("btc_paper_review_readiness_not_waiting_for_manual_review")
    if bool(readiness.get("paper_start_allowed", False)):
        blockers.append("btc_paper_review_readiness_already_allows_start")
    if bool(readiness.get("paper_execution_authorized", False)):
        blockers.append("btc_paper_review_execution_already_authorized")
    if str(start_report.get("status", "")) not in {"", "blocked"}:
        blockers.append("btc_paper_review_start_report_not_blocked")
    if not candidate_id:
        blockers.append("btc_paper_review_candidate_id_missing")
    if proposed_capital <= 0:
        blockers.append("btc_paper_review_proposed_capital_missing")
    blockers.extend(_list_of_strings(paper_gate.get("blockers")))
    return _dedupe(blockers)


def _run_evidence_source_reports(*, root: Path, source_reports: Mapping[str, str | None]) -> dict[str, str]:
    run_manifest = _resolve_source(root, source_reports, "paper_candidate_source_current_candidate_run_manifest")
    if not run_manifest:
        return {}
    run_dir = run_manifest.parent
    candidates = {
        "current_candidate_canonical_backtest": run_dir / "canonical_backtest_report.json",
        "current_candidate_walk_forward": run_dir / "walk_forward_report.json",
        "current_candidate_regime": run_dir / "regime_report.json",
        "current_candidate_promotion_decision": run_dir / "promotion_decision.json",
    }
    return {key: _relpath(path, root) for key, path in candidates.items() if path.exists()}


def _resolve_source(root: Path, source_reports: Mapping[str, str | None], key: str) -> Path | None:
    value = source_reports.get(key)
    if not isinstance(value, str) or not value:
        return None
    path = _resolve(root, Path(value))
    return path if path.exists() else None


def _evidence_field(value: Any, source: Path | None) -> dict[str, Any]:
    return {
        "present": _present(value),
        "value": value,
        "source": source.as_posix() if isinstance(source, Path) and str(source) else "",
    }


def _present(value: Any) -> bool:
    if value is None:
        return False
    if value == "":
        return False
    if isinstance(value, (list, dict, tuple, set)) and not value:
        return False
    return True


def _trial_count(run_dir: Path | None) -> int:
    if run_dir is None:
        return 0
    manifest_dir = run_dir / "manifests"
    if not manifest_dir.exists():
        return 0
    return len([path for path in manifest_dir.glob("*.json") if path.is_file()])


def _walk_forward_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    windows = [dict(item) for item in payload.get("windows", [])] if isinstance(payload.get("windows"), list) else []
    return {
        "method": payload.get("method"),
        "fold_count": payload.get("fold_count"),
        "pass_rate": payload.get("pass_rate"),
        "failed_folds": [item.get("fold") for item in windows if item.get("passed") is False],
        "windows": windows,
    }


def _regime_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    regimes = [dict(item) for item in payload.get("regimes", [])] if isinstance(payload.get("regimes"), list) else []
    return {
        "pass_rate": payload.get("pass_rate"),
        "dragging_regimes": list(payload.get("dragging_regimes", [])) if isinstance(payload.get("dragging_regimes"), list) else [],
        "regimes": regimes,
    }


def _cost_stress_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    scenarios = [dict(item) for item in payload.get("scenarios", [])] if isinstance(payload.get("scenarios"), list) else []
    return {
        "required_scenarios": list(payload.get("required_scenarios", []))
        if isinstance(payload.get("required_scenarios"), list)
        else [],
        "required_scenarios_present": bool(payload.get("required_scenarios_present", False)),
        "scenario_count": int(payload.get("scenario_count", len(scenarios)) or 0),
        "survival_rate": payload.get("survival_rate"),
        "base": dict(_mapping(payload.get("base"))),
        "harsh": dict(_mapping(payload.get("harsh"))),
        "scenarios": scenarios,
    }


def _minimum_metrics(
    *,
    metrics: Mapping[str, Any],
    cost_stress: Mapping[str, Any],
    ledger_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    base_summary = _mapping(_mapping(cost_stress.get("base")).get("summary"))
    return {
        "total_return": metrics.get("total_return_pct"),
        "annualized_return": base_summary.get("annual_return_pct"),
        "annualized_volatility": base_summary.get("annual_volatility_pct"),
        "risk_adjusted_return": {
            "sharpe": metrics.get("sharpe"),
            "sortino": metrics.get("sortino"),
            "profit_factor": metrics.get("profit_factor"),
        },
        "max_drawdown": metrics.get("max_drawdown"),
        "turnover": metrics.get("annual_turnover"),
        "average_holding_period": {
            "bars": metrics.get("avg_holding_bars"),
            "hours": ledger_metrics.get("average_holding_hours"),
        },
        "exposure_ratio": metrics.get("exposure"),
        "number_of_bets": metrics.get("trade_count"),
        "fee_paid": metrics.get("fees", ledger_metrics.get("fee_paid")),
        "slippage_paid_or_modeled": metrics.get("slippage", ledger_metrics.get("slippage_paid")),
        "best_year_contribution_share": ledger_metrics.get("best_year_contribution_share"),
        "worst_year": ledger_metrics.get("worst_year"),
        "capacity_proxy": ledger_metrics.get("capacity_proxy"),
    }


def _trade_ledger_metrics(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {}
    yearly_pnl: dict[str, float] = {}
    total_fees = 0.0
    total_slippage = 0.0
    holding_hours: list[float] = []
    max_entry_notional = 0.0
    for row in rows:
        exit_time = str(row.get("exit_time", ""))
        year = exit_time[:4] if len(exit_time) >= 4 else "unknown"
        net_pnl = _float(row.get("net_pnl"))
        yearly_pnl[year] = yearly_pnl.get(year, 0.0) + net_pnl
        total_fees += _float(row.get("fees"))
        total_slippage += _float(row.get("slippage"))
        if row.get("holding_hours") not in {"", None}:
            holding_hours.append(_float(row.get("holding_hours")))
        max_entry_notional = max(max_entry_notional, abs(_float(row.get("entry_price")) * _float(row.get("size"))))
    best_year, best_year_pnl = max(yearly_pnl.items(), key=lambda item: item[1])
    worst_year, worst_year_pnl = min(yearly_pnl.items(), key=lambda item: item[1])
    positive_pnl = sum(value for value in yearly_pnl.values() if value > 0)
    contribution_share = best_year_pnl / positive_pnl if positive_pnl else 0.0
    return {
        "trade_count": len(rows),
        "fee_paid": round(total_fees, 8),
        "slippage_paid": round(total_slippage, 8),
        "average_holding_hours": round(sum(holding_hours) / len(holding_hours), 8) if holding_hours else None,
        "yearly_net_pnl": {key: round(value, 8) for key, value in sorted(yearly_pnl.items())},
        "best_year_contribution_share": {
            "year": best_year,
            "share_of_positive_year_pnl": round(contribution_share, 8),
            "net_pnl": round(best_year_pnl, 8),
        },
        "worst_year": {"year": worst_year, "net_pnl": round(worst_year_pnl, 8)},
        "capacity_proxy": {
            "max_recorded_entry_notional": round(max_entry_notional, 8),
            "unit": "USDT_notional_at_recorded_trade_size",
            "interpretation": "diagnostic capacity proxy from historical ledger size, not live capacity approval",
        },
    }


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _source_hashes(root: Path, source_reports: Mapping[str, str | None]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in source_reports.items():
        if not isinstance(value, str) or not value:
            continue
        path = _resolve(root, Path(value))
        if path.exists() and path.is_file():
            out[key] = _sha256(path)
    return out


def _guardrails() -> dict[str, Any]:
    return {
        "review_only": True,
        "paper_start_allowed": False,
        "paper_execution_authorized": False,
        "paper_auto_start": False,
        "broker_calls_allowed": False,
        "private_endpoints_allowed": False,
        "order_endpoints_allowed": False,
        "real_orders_created": False,
        "live": "FROZEN",
    }


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
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), indent=2, sort_keys=True) + "\n"


def _json_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json_text(payload).encode("utf-8")).hexdigest()


def _write_json_file(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_bytes(_json_text(payload).encode("utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001 - metadata only.
        return "unknown"


if __name__ == "__main__":
    main()
