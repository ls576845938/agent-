#!/usr/bin/env python3
"""Build the BTC intraday short-cycle manual review packet.

This packet is a fail-closed bridge between a passed research promotion gate
and any later research candidate definition. It never authorizes paper/live
execution, broker access, private endpoints, or true scalping.
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


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
DEFAULT_DATA_ROOT = Path("data")
DEFAULT_PROMOTION_GATE = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_promotion_gate_report.json")
DEFAULT_REVIEW_ID = "btc_intraday_short_cycle_manual_review_v1"
REPORT_FILENAME = "btc_intraday_short_cycle_manual_review_packet.json"
APPROVAL_SCHEMA_VERSION = "btc_intraday_short_cycle_manual_review_approval_v1"
REVIEW_SCHEMA_VERSION = "btc_intraday_short_cycle_manual_review_v1"
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def build_btc_intraday_short_cycle_manual_review_packet(
    *,
    repo_root: Path | None = None,
    data_root: Path | None = None,
    promotion_gate_path: Path | None = None,
    review_id: str = DEFAULT_REVIEW_ID,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    resolved_data_root = _resolve(root, data_root or DEFAULT_DATA_ROOT)
    promotion_file = _resolve(root, promotion_gate_path or DEFAULT_PROMOTION_GATE)
    promotion = _read_json(promotion_file)
    approval_path = resolved_data_root / "research/btc_intraday_candidate_reviews" / review_id / "review.json"
    approval_review = _read_json(approval_path)
    promotion_hash = _promotion_review_source_sha256(promotion_file=promotion_file, promotion=promotion)
    approval = _approval_status(
        root=root,
        approval_path=approval_path,
        approval_review=approval_review,
        promotion_file=promotion_file,
        promotion=promotion,
        promotion_hash=promotion_hash,
    )
    hard_checks = _hard_checks(promotion_file=promotion_file, promotion=promotion)
    hard_blockers = _blockers_from_checks("btc_intraday_manual_review", hard_checks)
    blockers = _dedupe([*hard_blockers, *_list_of_strings(approval.get("blockers"))])
    approved = bool(approval.get("approved", False)) and not blockers
    packet_ready = not hard_blockers
    if approved:
        status = "approved_for_research_candidate_definition"
        decision = "allow_research_candidate_definition_only"
        next_required_action = "build_research_candidate_definition_manifest"
    elif packet_ready:
        status = "awaiting_recorded_manual_review"
        decision = "continue_research_manual_review_required"
        next_required_action = "record_manual_review_approval_before_candidate_definition"
    else:
        status = "blocked_manual_review_packet"
        decision = "back_to_promotion_gate_repair"
        next_required_action = "repair_promotion_gate_before_manual_review"
    return {
        "schema_version": "btc_intraday_short_cycle_manual_review_packet_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "review_id": review_id,
        "status": status,
        "decision": decision,
        "next_required_action": next_required_action,
        "source_reports": _source_reports(root=root, promotion_file=promotion_file, promotion=promotion),
        "promotion_gate_sha256": promotion_hash,
        "review_subject": _review_subject(promotion),
        "hard_checks": hard_checks,
        "approval": approval,
        "approval_template": _approval_template(
            root=root,
            review_id=review_id,
            approval_path=approval_path,
            promotion_file=promotion_file,
            promotion=promotion,
            promotion_hash=promotion_hash,
        ),
        "blockers": blockers,
        "manual_review_packet_ready": packet_ready,
        "recorded_manual_review_approved": approved,
        "research_candidate_definition_allowed": approved,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "true_scalping_allowed": False,
        "guardrails": {
            "research_only": True,
            "manual_review_record_only": True,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
            "approval_scope": "research_candidate_definition_only",
        },
    }


def write_btc_intraday_short_cycle_manual_review_packet(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / REPORT_FILENAME
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--promotion-gate-path", default=str(DEFAULT_PROMOTION_GATE))
    parser.add_argument("--review-id", default=DEFAULT_REVIEW_ID)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_intraday_short_cycle_manual_review_packet(
        repo_root=Path(args.repo_root),
        data_root=Path(args.data_root),
        promotion_gate_path=Path(args.promotion_gate_path),
        review_id=args.review_id,
        generated_at=args.generated_at or None,
    )
    print(write_btc_intraday_short_cycle_manual_review_packet(payload, Path(args.output_root)))


def _hard_checks(*, promotion_file: Path, promotion: Mapping[str, Any]) -> dict[str, bool]:
    checks = _mapping(promotion.get("checks"))
    return {
        "promotion_gate_report_present": promotion_file.exists(),
        "promotion_gate_ready_for_manual_review": str(promotion.get("status", "")) == "ready_for_manual_candidate_review",
        "promotion_gate_has_no_blockers": not _list_of_strings(promotion.get("blockers")),
        "manual_candidate_review_allowed": bool(promotion.get("manual_candidate_review_allowed", False)),
        "manifest_data_version_present": bool(checks.get("manifest_data_version_present", False)),
        "manifest_strategy_version_present": bool(checks.get("manifest_strategy_version_present", False)),
        "manifest_params_present": bool(checks.get("manifest_params_present", False)),
        "manifest_cost_model_present": bool(checks.get("manifest_cost_model_present", False)),
        "manifest_slippage_model_present": bool(checks.get("manifest_slippage_model_present", False)),
        "manifest_commit_hash_present": bool(checks.get("manifest_commit_hash_present", False)),
        "private_order_broker_paths_locked": bool(checks.get("private_order_broker_paths_locked", False)),
        "paper_live_still_locked": bool(checks.get("paper_live_still_locked", False)),
        "true_scalping_still_locked": bool(checks.get("true_scalping_still_locked", False)),
    }


def _approval_status(
    *,
    root: Path,
    approval_path: Path,
    approval_review: Mapping[str, Any],
    promotion_file: Path,
    promotion: Mapping[str, Any],
    promotion_hash: str,
) -> dict[str, Any]:
    approval = _mapping(approval_review.get("approval"))
    gate_snapshot = _mapping(approval.get("gate_snapshot"))
    source = _resolve_optional(root, approval.get("source"))
    blockers: list[str] = []
    if not approval_path.exists():
        blockers.append("btc_intraday_manual_review_recorded_approval_missing")
    else:
        if approval_review.get("schema_version") != REVIEW_SCHEMA_VERSION:
            blockers.append("btc_intraday_manual_review_schema_invalid")
        if str(approval_review.get("status", "") or "") != "APPROVED_FOR_RESEARCH_CANDIDATE_DEFINITION_ONLY":
            blockers.append("btc_intraday_manual_review_status_not_candidate_definition_only")
        if str(approval_review.get("strategy_id", "") or "") != str(promotion.get("strategy_id", "") or ""):
            blockers.append("btc_intraday_manual_review_strategy_mismatch")
        if str(approval_review.get("variant_id", "") or "") != str(promotion.get("variant_id", "") or ""):
            blockers.append("btc_intraday_manual_review_variant_mismatch")
        if approval.get("schema_version") != APPROVAL_SCHEMA_VERSION:
            blockers.append("btc_intraday_manual_review_approval_schema_invalid")
        if str(approval.get("decision", "") or "") != "approve_research_candidate_definition_only":
            blockers.append("btc_intraday_manual_review_approval_decision_invalid")
        if not str(approval.get("reviewer", "") or "").strip():
            blockers.append("btc_intraday_manual_review_reviewer_missing")
        if not _utc_timestamp(approval.get("timestamp")):
            blockers.append("btc_intraday_manual_review_timestamp_invalid")
        if source is None:
            blockers.append("btc_intraday_manual_review_source_missing")
        elif source.resolve() != promotion_file.resolve():
            blockers.append("btc_intraday_manual_review_source_not_promotion_gate")
        if not SHA256_RE.match(str(approval.get("source_sha256", "") or "")):
            blockers.append("btc_intraday_manual_review_source_sha256_invalid")
        elif str(approval.get("source_sha256")) != promotion_hash:
            blockers.append("btc_intraday_manual_review_source_sha256_mismatch")
        if _list_of_strings(approval.get("blockers")):
            blockers.append("btc_intraday_manual_review_approval_has_blockers")
        if not gate_snapshot:
            blockers.append("btc_intraday_manual_review_gate_snapshot_missing")
        elif gate_snapshot != _approval_gate_snapshot(promotion):
            blockers.append("btc_intraday_manual_review_gate_snapshot_mismatch")
        if gate_snapshot and gate_snapshot.get("authorization_scope") != "research_candidate_definition_only":
            blockers.append("btc_intraday_manual_review_scope_invalid")
    valid = not blockers
    return {
        "path": _relpath(approval_path, root),
        "exists": approval_path.exists(),
        "approved": valid,
        "status": str(approval_review.get("status", "missing") or "missing"),
        "review_id": str(approval_review.get("review_id", "")),
        "strategy_id": str(approval_review.get("strategy_id", "")),
        "variant_id": str(approval_review.get("variant_id", "")),
        "approval": {
            "valid": valid,
            "schema_version": str(approval.get("schema_version", "")),
            "decision": str(approval.get("decision", "")),
            "reviewer": str(approval.get("reviewer", "")),
            "timestamp": str(approval.get("timestamp", "")),
            "source": str(approval.get("source", "")),
            "source_sha256": str(approval.get("source_sha256", "")),
            "gate_snapshot": dict(gate_snapshot),
            "blockers": blockers,
        },
        "blockers": blockers,
    }


def _approval_template(
    *,
    root: Path,
    review_id: str,
    approval_path: Path,
    promotion_file: Path,
    promotion: Mapping[str, Any],
    promotion_hash: str,
) -> dict[str, Any]:
    source = _relpath(promotion_file, root)
    return {
        "write_to": _relpath(approval_path, root),
        "review": {
            "schema_version": REVIEW_SCHEMA_VERSION,
            "review_id": review_id,
            "status": "APPROVED_FOR_RESEARCH_CANDIDATE_DEFINITION_ONLY",
            "strategy_id": str(promotion.get("strategy_id", "")),
            "variant_id": str(promotion.get("variant_id", "")),
            "source_promotion_gate_report": source,
            "approval": {
                "schema_version": APPROVAL_SCHEMA_VERSION,
                "decision": "approve_research_candidate_definition_only",
                "reviewer": "<required-human-reviewer>",
                "reason": "research candidate definition approval only; no paper/live/true scalping authorization",
                "timestamp": "YYYY-MM-DDTHH:MM:SSZ",
                "source": source,
                "source_sha256": promotion_hash,
                "gate_snapshot": _approval_gate_snapshot(promotion),
                "blockers": [],
            },
        },
    }


def _approval_gate_snapshot(promotion: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "strategy_id": str(promotion.get("strategy_id", "")),
        "variant_id": str(promotion.get("variant_id", "")),
        "promotion_status": str(promotion.get("status", "")),
        "manual_candidate_review_allowed": bool(promotion.get("manual_candidate_review_allowed", False)),
        "candidate_generation_allowed": bool(promotion.get("candidate_generation_allowed", False)),
        "paper_or_live_unlock_allowed": bool(promotion.get("paper_or_live_unlock_allowed", False)),
        "true_scalping_allowed": bool(promotion.get("true_scalping_allowed", False)),
        "authorization_scope": "research_candidate_definition_only",
    }


def _source_reports(*, root: Path, promotion_file: Path, promotion: Mapping[str, Any]) -> dict[str, str | None]:
    reports = _mapping(promotion.get("source_reports"))
    return {
        "promotion_gate": _relpath(promotion_file, root) if promotion_file.exists() else None,
        "drift_guarded_event_ledger": _relpath_if_exists(root, reports.get("drift_guarded_event_ledger")),
        "canonical_backtest_report": _relpath_if_exists(root, reports.get("canonical_backtest_report")),
        "cost_stress_report": _relpath_if_exists(root, reports.get("cost_stress_report")),
        "walk_forward_report": _relpath_if_exists(root, reports.get("walk_forward_report")),
        "regime_report": _relpath_if_exists(root, reports.get("regime_report")),
        "tail_dependency_report": _relpath_if_exists(root, reports.get("tail_dependency_report")),
        "run_manifest": _relpath_if_exists(root, reports.get("run_manifest")),
    }


def _review_subject(promotion: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "strategy_id": str(promotion.get("strategy_id", "")),
        "variant_id": str(promotion.get("variant_id", "")),
        "family_id": str(promotion.get("family_id", "")),
        "metrics": dict(_mapping(promotion.get("metrics"))),
        "gate": dict(_mapping(promotion.get("gate"))),
    }


def _blockers_from_checks(prefix: str, checks: Mapping[str, bool]) -> list[str]:
    return [f"{prefix}_{name}_failed" for name, passed in checks.items() if not passed]


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
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            output.append(value)
            seen.add(value)
    return output


def _utc_timestamp(value: Any) -> bool:
    return isinstance(value, str) and bool(UTC_RE.match(value))


def _promotion_review_source_sha256(*, promotion_file: Path, promotion: Mapping[str, Any]) -> str:
    if not promotion_file.exists():
        return ""
    canonical = dict(promotion)
    canonical.pop("generated_at", None)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _resolve_optional(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return _resolve(root, Path(value))


def _relpath_if_exists(root: Path, value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = _resolve(root, Path(value))
    return _relpath(path, root) if path.exists() else None


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
