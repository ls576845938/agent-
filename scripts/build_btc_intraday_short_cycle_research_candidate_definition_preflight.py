#!/usr/bin/env python3
"""Build BTC intraday research candidate-definition preflight.

This is a fail-closed bridge after manual review. It can only allow a
research-candidate definition manifest. It never authorizes candidate
generation, strategy skeleton generation, paper/live execution, broker access,
private endpoints, order endpoints, or true scalping.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
DEFAULT_MANUAL_REVIEW_PACKET = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_manual_review_packet.json")
REPORT_FILENAME = "btc_intraday_short_cycle_research_candidate_definition_preflight.json"
REPORT_SCHEMA_VERSION = "btc_intraday_short_cycle_research_candidate_definition_preflight_v1"


def build_btc_intraday_short_cycle_research_candidate_definition_preflight(
    *,
    repo_root: Path | None = None,
    manual_review_packet_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    review_file = _resolve(root, manual_review_packet_path or DEFAULT_MANUAL_REVIEW_PACKET)
    review = _read_json(review_file)
    source_reports = _source_reports(root=root, review_file=review_file, review=review)
    promotion = _read_json(_resolve_optional(root, source_reports.get("promotion_gate")))
    event_ledger = _read_json(_resolve_optional(root, source_reports.get("drift_guarded_event_ledger")))
    run_manifest = _read_json(_resolve_optional(root, source_reports.get("run_manifest")))
    checks = _checks(review_file=review_file, review=review, promotion=promotion, event_ledger=event_ledger, run_manifest=run_manifest)
    blockers = _blockers(checks)
    definition_allowed = not blockers
    status = (
        "ready_for_research_candidate_definition_manifest"
        if definition_allowed
        else "blocked_manual_review_required"
        if review_file.exists()
        else "blocked_candidate_definition_preflight"
    )
    decision = (
        "allow_research_candidate_definition_manifest_only"
        if definition_allowed
        else "continue_research_manual_review_required"
        if review_file.exists()
        else "back_to_manual_review_or_promotion_gate_repair"
    )
    next_action = (
        "create_research_candidate_definition_manifest_no_strategy_skeleton"
        if definition_allowed
        else "record_manual_review_approval_before_candidate_definition"
        if review_file.exists()
        else "repair_manual_review_packet_before_candidate_definition"
    )
    subject = _review_subject(review=review, promotion=promotion, event_ledger=event_ledger)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "scope": "research_candidate_definition_preflight_no_strategy_skeleton_no_paper_no_live",
        "status": status,
        "decision": decision,
        "next_required_action": next_action,
        "source_reports": source_reports,
        "review_subject": subject,
        "checks": checks,
        "blockers": blockers,
        "candidate_definition_blueprint": _candidate_definition_blueprint(subject=subject, run_manifest=run_manifest),
        "research_candidate_definition_manifest_allowed": definition_allowed,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "true_scalping_allowed": False,
        "guardrails": {
            "research_only": True,
            "candidate_definition_manifest_only": True,
            "strategy_code_generation_allowed": False,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "pnl_from_fill_ledger_required": True,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
            "approval_scope": "research_candidate_definition_only",
        },
    }


def write_btc_intraday_short_cycle_research_candidate_definition_preflight(
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
    parser.add_argument("--manual-review-packet-path", default=str(DEFAULT_MANUAL_REVIEW_PACKET))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_intraday_short_cycle_research_candidate_definition_preflight(
        repo_root=Path(args.repo_root),
        manual_review_packet_path=Path(args.manual_review_packet_path),
        generated_at=args.generated_at or None,
    )
    print(write_btc_intraday_short_cycle_research_candidate_definition_preflight(payload, Path(args.output_root)))


def _source_reports(*, root: Path, review_file: Path, review: Mapping[str, Any]) -> dict[str, str | None]:
    reports = _mapping(review.get("source_reports"))
    return {
        "manual_review_packet": _relpath(review_file, root) if review_file.exists() else None,
        "promotion_gate": _relpath_if_exists(root, reports.get("promotion_gate")),
        "drift_guarded_event_ledger": _relpath_if_exists(root, reports.get("drift_guarded_event_ledger")),
        "canonical_backtest_report": _relpath_if_exists(root, reports.get("canonical_backtest_report")),
        "cost_stress_report": _relpath_if_exists(root, reports.get("cost_stress_report")),
        "walk_forward_report": _relpath_if_exists(root, reports.get("walk_forward_report")),
        "regime_report": _relpath_if_exists(root, reports.get("regime_report")),
        "tail_dependency_report": _relpath_if_exists(root, reports.get("tail_dependency_report")),
        "run_manifest": _relpath_if_exists(root, reports.get("run_manifest")),
    }


def _checks(
    *,
    review_file: Path,
    review: Mapping[str, Any],
    promotion: Mapping[str, Any],
    event_ledger: Mapping[str, Any],
    run_manifest: Mapping[str, Any],
) -> dict[str, bool]:
    guardrails = _mapping(review.get("guardrails"))
    promotion_guardrails = _mapping(promotion.get("guardrails"))
    event_guardrails = _mapping(event_ledger.get("guardrails"))
    return {
        "manual_review_packet_present": review_file.exists(),
        "manual_review_packet_approved": str(review.get("status", "")) == "approved_for_research_candidate_definition",
        "recorded_manual_review_approved": bool(review.get("recorded_manual_review_approved", False)),
        "research_candidate_definition_allowed_by_review": bool(
            review.get("research_candidate_definition_allowed", False)
        ),
        "candidate_generation_still_locked": bool(review.get("candidate_generation_allowed", True)) is False,
        "strategy_skeleton_still_locked": bool(review.get("strategy_skeleton_generation_allowed", True)) is False,
        "paper_live_still_locked": bool(review.get("paper_or_live_unlock_allowed", True)) is False,
        "true_scalping_still_locked": bool(review.get("true_scalping_allowed", True)) is False,
        "review_scope_candidate_definition_only": guardrails.get("approval_scope") == "research_candidate_definition_only",
        "broker_private_order_paths_locked": bool(guardrails.get("broker_calls_allowed", True)) is False
        and bool(guardrails.get("private_endpoints_allowed", True)) is False
        and bool(guardrails.get("order_endpoints_allowed", True)) is False,
        "promotion_gate_manual_review_only": str(promotion.get("status", "")) == "ready_for_manual_candidate_review"
        and bool(promotion.get("manual_candidate_review_allowed", False))
        and bool(promotion.get("candidate_generation_allowed", True)) is False
        and bool(promotion.get("paper_or_live_unlock_allowed", True)) is False
        and bool(promotion.get("true_scalping_allowed", True)) is False,
        "event_ledger_passed_internal_gate": str(event_ledger.get("status", ""))
        == "event_ledger_passed_internal_research_gate_candidate_still_locked"
        and bool(event_ledger.get("event_ledger_completed", False))
        and bool(_mapping(event_ledger.get("gate")).get("passed", False)),
        "pnl_from_fill_ledger_required": bool(promotion_guardrails.get("pnl_from_fill_ledger_required", False))
        or bool(event_guardrails.get("pnl_from_fill_ledger_required_for_promotion", False)),
        "run_manifest_data_version_present": bool(run_manifest.get("data_version")),
        "run_manifest_strategy_version_present": bool(run_manifest.get("strategy_version")),
        "run_manifest_params_present": bool(run_manifest.get("params")),
        "run_manifest_cost_model_present": bool(run_manifest.get("cost_model")),
        "run_manifest_slippage_model_present": bool(run_manifest.get("slippage_model")),
        "run_manifest_commit_hash_present": bool(run_manifest.get("commit_hash")),
    }


def _blockers(checks: Mapping[str, bool]) -> list[str]:
    return [
        f"btc_intraday_research_candidate_definition_preflight_{name}_failed"
        for name, passed in checks.items()
        if not passed
    ]


def _review_subject(
    *,
    review: Mapping[str, Any],
    promotion: Mapping[str, Any],
    event_ledger: Mapping[str, Any],
) -> dict[str, Any]:
    subject = _mapping(review.get("review_subject"))
    metrics = _mapping(subject.get("metrics") or promotion.get("metrics") or event_ledger.get("metrics"))
    gate = _mapping(subject.get("gate") or promotion.get("gate") or event_ledger.get("gate"))
    return {
        "strategy_id": str(subject.get("strategy_id") or promotion.get("strategy_id") or event_ledger.get("strategy_id") or ""),
        "variant_id": str(subject.get("variant_id") or promotion.get("variant_id") or event_ledger.get("variant_id") or ""),
        "family_id": str(subject.get("family_id") or promotion.get("family_id") or event_ledger.get("family_id") or ""),
        "metrics": {
            "trade_count": int(metrics.get("trade_count", 0) or 0),
            "fill_count": int(metrics.get("fill_count", 0) or 0),
            "profit_factor": _float_or_none(metrics.get("profit_factor")),
            "event_profit_factor": _float_or_none(metrics.get("event_profit_factor")),
            "walk_forward_pass_rate": _float_or_none(metrics.get("walk_forward_pass_rate")),
            "regime_pass_rate": _float_or_none(metrics.get("regime_pass_rate")),
        },
        "gate": {
            "status": str(gate.get("status", "")),
            "passed": bool(gate.get("passed", False)),
        },
    }


def _candidate_definition_blueprint(*, subject: Mapping[str, Any], run_manifest: Mapping[str, Any]) -> dict[str, Any]:
    strategy_id = str(subject.get("strategy_id", "") or "")
    variant_id = str(subject.get("variant_id", "") or "")
    candidate_id = f"{strategy_id}:{variant_id}:research_candidate_definition_v1" if strategy_id and variant_id else ""
    return {
        "candidate_id": candidate_id,
        "strategy_id": strategy_id,
        "variant_id": variant_id,
        "definition_scope": "research_candidate_definition_only",
        "source_run_id": str(run_manifest.get("run_id", "")),
        "source_strategy_version": str(run_manifest.get("strategy_version", "")),
        "source_data_version": str(run_manifest.get("data_version", "")),
        "params_hash": str(run_manifest.get("params_hash", "")),
        "required_next_artifact": "research_candidate_definition_manifest",
        "forbidden_outputs": [
            "strategy_code",
            "broker_order",
            "paper_runtime_entry",
            "live_runtime_entry",
            "true_scalping_claim",
        ],
    }


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
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


def _resolve_optional(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    return _resolve(root, Path(value))


def _relpath_if_exists(root: Path, value: Any) -> str | None:
    path = _resolve_optional(root, value)
    return _relpath(path, root) if path is not None and path.exists() else None


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001 - metadata only.
        return "unknown"


if __name__ == "__main__":
    main()
