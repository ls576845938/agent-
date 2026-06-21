#!/usr/bin/env python3
"""Build BTC intraday research candidate-definition manifest.

This manifest is a fail-closed status artifact. It can document a
research-only candidate definition, but it never unlocks candidate generation,
strategy skeleton generation, paper/live execution, broker access, private
endpoints, order endpoints, or true scalping claims.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
DEFAULT_PREFLIGHT = Path(
    "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_research_candidate_definition_preflight.json"
)
REPORT_FILENAME = "btc_intraday_short_cycle_research_candidate_definition_manifest.json"
REPORT_SCHEMA_VERSION = "btc_intraday_short_cycle_research_candidate_definition_manifest_v1"

MANUAL_GATE_CHECKS = {
    "preflight_ready_for_definition_manifest",
    "preflight_allows_definition_manifest",
    "manual_review_packet_approved",
    "recorded_manual_review_approved",
    "research_candidate_definition_allowed_by_review",
}


def build_btc_intraday_short_cycle_research_candidate_definition_manifest(
    *,
    repo_root: Path | None = None,
    preflight_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    preflight_file = _resolve(root, preflight_path or DEFAULT_PREFLIGHT)
    preflight = _read_json(preflight_file)
    subject = _mapping(preflight.get("review_subject"))
    blueprint = _mapping(preflight.get("candidate_definition_blueprint"))
    checks = _checks(preflight_file=preflight_file, preflight=preflight, blueprint=blueprint)
    blockers = _blockers(checks=checks, preflight=preflight)
    manifest_ready = not blockers
    remaining = _remaining_manual_or_external_blockers(checks)
    automated = _automated_engineering_blockers(checks=checks, preflight=preflight)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "scope": "research_candidate_definition_manifest_no_strategy_skeleton_no_paper_no_live",
        "status": _status(preflight_file=preflight_file, checks=checks, manifest_ready=manifest_ready),
        "decision": _decision(preflight_file=preflight_file, checks=checks, manifest_ready=manifest_ready),
        "next_required_action": _next_required_action(
            preflight_file=preflight_file,
            checks=checks,
            manifest_ready=manifest_ready,
        ),
        "source_reports": _source_reports(root=root, preflight_file=preflight_file, preflight=preflight),
        "review_subject": _review_subject(subject),
        "checks": checks,
        "blockers": blockers,
        "candidate_definition": _candidate_definition(subject=subject, blueprint=blueprint),
        "evidence_requirements": _evidence_requirements(checks),
        "remaining_manual_or_external_blockers": remaining,
        "remaining_blocker_summary": {
            "only_manual_or_external_blockers_remain": not automated,
            "automated_engineering_blockers": automated,
            "manual_or_external_blocker_count": len(remaining),
            "manifest_blocker_count": len(blockers),
        },
        "research_candidate_definition_manifest_ready": manifest_ready,
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
            "candidate_generation_allowed": False,
            "strategy_skeleton_generation_allowed": False,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "pnl_from_fill_ledger_required": True,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
            "approval_scope": "research_candidate_definition_only",
            "true_scalping_claim_allowed": False,
        },
    }


def write_btc_intraday_short_cycle_research_candidate_definition_manifest(
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
    parser.add_argument("--preflight-path", default=str(DEFAULT_PREFLIGHT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_intraday_short_cycle_research_candidate_definition_manifest(
        repo_root=Path(args.repo_root),
        preflight_path=Path(args.preflight_path),
        generated_at=args.generated_at or None,
    )
    print(write_btc_intraday_short_cycle_research_candidate_definition_manifest(payload, Path(args.output_root)))


def _checks(*, preflight_file: Path, preflight: Mapping[str, Any], blueprint: Mapping[str, Any]) -> dict[str, bool]:
    preflight_checks = _mapping(preflight.get("checks"))
    guardrails = _mapping(preflight.get("guardrails"))
    forbidden_outputs = set(_list_of_strings(blueprint.get("forbidden_outputs")))
    return {
        "preflight_present": preflight_file.exists(),
        "preflight_ready_for_definition_manifest": str(preflight.get("status", ""))
        == "ready_for_research_candidate_definition_manifest",
        "preflight_allows_definition_manifest": bool(
            preflight.get("research_candidate_definition_manifest_allowed", False)
        ),
        "manual_review_packet_approved": bool(preflight_checks.get("manual_review_packet_approved", False)),
        "recorded_manual_review_approved": bool(preflight_checks.get("recorded_manual_review_approved", False)),
        "research_candidate_definition_allowed_by_review": bool(
            preflight_checks.get("research_candidate_definition_allowed_by_review", False)
        ),
        "candidate_generation_still_locked": bool(preflight.get("candidate_generation_allowed", True)) is False,
        "strategy_skeleton_still_locked": bool(preflight.get("strategy_skeleton_generation_allowed", True)) is False,
        "paper_live_still_locked": bool(preflight.get("paper_or_live_unlock_allowed", True)) is False,
        "true_scalping_still_locked": bool(preflight.get("true_scalping_allowed", True)) is False,
        "broker_private_order_paths_locked": bool(preflight_checks.get("broker_private_order_paths_locked", False))
        or (
            bool(guardrails.get("broker_calls_allowed", True)) is False
            and bool(guardrails.get("private_endpoints_allowed", True)) is False
            and bool(guardrails.get("order_endpoints_allowed", True)) is False
        ),
        "blueprint_scope_candidate_definition_only": str(blueprint.get("definition_scope", ""))
        == "research_candidate_definition_only",
        "blueprint_required_next_artifact_manifest": str(blueprint.get("required_next_artifact", ""))
        == "research_candidate_definition_manifest",
        "source_run_id_present": bool(str(blueprint.get("source_run_id", "")).strip()),
        "source_strategy_version_present": bool(str(blueprint.get("source_strategy_version", "")).strip()),
        "source_data_version_present": bool(str(blueprint.get("source_data_version", "")).strip()),
        "params_hash_present": bool(str(blueprint.get("params_hash", "")).strip()),
        "forbidden_outputs_include_strategy_code": "strategy_code" in forbidden_outputs,
        "forbidden_outputs_include_broker_order": "broker_order" in forbidden_outputs,
        "forbidden_outputs_include_paper_live_runtime": {
            "paper_runtime_entry",
            "live_runtime_entry",
        }.issubset(forbidden_outputs),
        "forbidden_outputs_include_true_scalping_claim": "true_scalping_claim" in forbidden_outputs,
    }


def _blockers(*, checks: Mapping[str, bool], preflight: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not checks.get("preflight_present", False):
        blockers.append("btc_intraday_research_candidate_definition_manifest_preflight_missing")
        return blockers
    if not checks.get("preflight_ready_for_definition_manifest", False) or not checks.get(
        "preflight_allows_definition_manifest", False
    ):
        blockers.append("btc_intraday_research_candidate_definition_manifest_preflight_not_allowed")
        blockers.extend(_list_of_strings(preflight.get("blockers")))
    safety_and_lineage_checks = {
        name: passed
        for name, passed in checks.items()
        if name
        not in {
            "preflight_present",
            "preflight_ready_for_definition_manifest",
            "preflight_allows_definition_manifest",
            "manual_review_packet_approved",
            "recorded_manual_review_approved",
            "research_candidate_definition_allowed_by_review",
        }
    }
    blockers.extend(
        f"btc_intraday_research_candidate_definition_manifest_{name}_failed"
        for name, passed in safety_and_lineage_checks.items()
        if not passed
    )
    return _dedupe(blockers)


def _automated_engineering_blockers(*, checks: Mapping[str, bool], preflight: Mapping[str, Any]) -> list[str]:
    failed = [name for name, passed in checks.items() if not passed and name not in MANUAL_GATE_CHECKS]
    non_manual_preflight = [
        blocker
        for blocker in _list_of_strings(preflight.get("blockers"))
        if "manual_review" not in blocker and "research_candidate_definition_allowed_by_review" not in blocker
    ]
    return _dedupe(failed + non_manual_preflight)


def _remaining_manual_or_external_blockers(checks: Mapping[str, bool]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    if not (
        checks.get("manual_review_packet_approved", False)
        and checks.get("recorded_manual_review_approved", False)
        and checks.get("research_candidate_definition_allowed_by_review", False)
    ):
        blockers.append(
            {
                "blocker": "btc_intraday_manual_review_recorded_approval_missing",
                "category": "manual_approval",
                "status": "missing",
                "required_for": "research_candidate_definition_manifest_ready",
            }
        )
    blockers.extend(
        [
            {
                "blocker": "btc_true_scalping_long_horizon_l2_tick_history_missing",
                "category": "real_long_horizon_market_data",
                "status": "external_data_required",
                "required_for": "true_scalping_claim_or_execution_queue_model",
            },
            {
                "blocker": "btc_true_scalping_execution_latency_model_missing",
                "category": "execution_evidence",
                "status": "external_evidence_required",
                "required_for": "paper_or_true_scalping_execution_readiness",
            },
            {
                "blocker": "btc_true_scalping_queue_position_model_missing",
                "category": "queue_evidence",
                "status": "external_evidence_required",
                "required_for": "paper_or_true_scalping_execution_readiness",
            },
            {
                "blocker": "btc_paper_gate_approval_and_observation_missing",
                "category": "paper_gate",
                "status": "external_evidence_required",
                "required_for": "paper_or_live_unlock",
            },
        ]
    )
    return blockers


def _evidence_requirements(checks: Mapping[str, bool]) -> dict[str, Any]:
    manual_ready = bool(
        checks.get("manual_review_packet_approved", False)
        and checks.get("recorded_manual_review_approved", False)
        and checks.get("research_candidate_definition_allowed_by_review", False)
    )
    return {
        "recorded_manual_review_approval": {
            "required": True,
            "satisfied": manual_ready,
            "required_for": "research_candidate_definition_manifest_ready",
        },
        "true_long_horizon_l2_tick_history": {
            "required": True,
            "satisfied": False,
            "required_for": "true_scalping_claim_or_execution_queue_model",
        },
        "execution_latency_model": {
            "required": True,
            "satisfied": False,
            "required_for": "paper_or_true_scalping_execution_readiness",
        },
        "queue_position_model": {
            "required": True,
            "satisfied": False,
            "required_for": "paper_or_true_scalping_execution_readiness",
        },
        "paper_gate": {
            "required": True,
            "satisfied": False,
            "required_for": "paper_or_live_unlock",
        },
    }


def _status(*, preflight_file: Path, checks: Mapping[str, bool], manifest_ready: bool) -> str:
    if manifest_ready:
        return "ready_research_candidate_definition_manifest_only"
    if not preflight_file.exists():
        return "blocked_research_candidate_definition_manifest_preflight_missing"
    if not (
        checks.get("manual_review_packet_approved", False)
        and checks.get("recorded_manual_review_approved", False)
        and checks.get("research_candidate_definition_allowed_by_review", False)
    ):
        return "blocked_research_candidate_definition_manifest_manual_review_required"
    return "blocked_research_candidate_definition_manifest_preflight_repair_required"


def _decision(*, preflight_file: Path, checks: Mapping[str, bool], manifest_ready: bool) -> str:
    if manifest_ready:
        return "publish_research_candidate_definition_manifest_only"
    if preflight_file.exists() and not (
        checks.get("manual_review_packet_approved", False)
        and checks.get("recorded_manual_review_approved", False)
        and checks.get("research_candidate_definition_allowed_by_review", False)
    ):
        return "continue_research_manual_review_required"
    return "repair_research_candidate_definition_preflight_before_manifest"


def _next_required_action(*, preflight_file: Path, checks: Mapping[str, bool], manifest_ready: bool) -> str:
    if manifest_ready:
        return "review_research_candidate_definition_manifest_no_strategy_skeleton"
    if preflight_file.exists() and not (
        checks.get("manual_review_packet_approved", False)
        and checks.get("recorded_manual_review_approved", False)
        and checks.get("research_candidate_definition_allowed_by_review", False)
    ):
        return "record_manual_review_approval_before_candidate_definition"
    return "repair_research_candidate_definition_preflight_before_manifest"


def _source_reports(*, root: Path, preflight_file: Path, preflight: Mapping[str, Any]) -> dict[str, str | None]:
    reports = _mapping(preflight.get("source_reports"))
    return {
        "candidate_definition_preflight": _relpath(preflight_file, root) if preflight_file.exists() else None,
        "manual_review_packet": _relpath_if_exists(root, reports.get("manual_review_packet")),
        "promotion_gate": _relpath_if_exists(root, reports.get("promotion_gate")),
        "drift_guarded_event_ledger": _relpath_if_exists(root, reports.get("drift_guarded_event_ledger")),
        "canonical_backtest_report": _relpath_if_exists(root, reports.get("canonical_backtest_report")),
        "cost_stress_report": _relpath_if_exists(root, reports.get("cost_stress_report")),
        "walk_forward_report": _relpath_if_exists(root, reports.get("walk_forward_report")),
        "regime_report": _relpath_if_exists(root, reports.get("regime_report")),
        "tail_dependency_report": _relpath_if_exists(root, reports.get("tail_dependency_report")),
        "run_manifest": _relpath_if_exists(root, reports.get("run_manifest")),
    }


def _review_subject(subject: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _mapping(subject.get("metrics"))
    gate = _mapping(subject.get("gate"))
    return {
        "strategy_id": str(subject.get("strategy_id", "")),
        "variant_id": str(subject.get("variant_id", "")),
        "family_id": str(subject.get("family_id", "")),
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


def _candidate_definition(*, subject: Mapping[str, Any], blueprint: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": str(blueprint.get("candidate_id", "")),
        "strategy_id": str(blueprint.get("strategy_id", "")),
        "variant_id": str(blueprint.get("variant_id", "")),
        "family_id": str(subject.get("family_id", "")),
        "definition_scope": "research_candidate_definition_only",
        "source_run_id": str(blueprint.get("source_run_id", "")),
        "source_strategy_version": str(blueprint.get("source_strategy_version", "")),
        "source_data_version": str(blueprint.get("source_data_version", "")),
        "params_hash": str(blueprint.get("params_hash", "")),
        "allowed_output": "research_candidate_definition_manifest",
        "forbidden_outputs": _list_of_strings(blueprint.get("forbidden_outputs")),
        "strategy_may_emit_only": ["Signal", "OrderIntent", "TargetPosition"],
        "simulated_order_intent_only": True,
        "strategy_may_call_broker": False,
        "private_endpoints_allowed": False,
        "order_endpoints_allowed": False,
        "paper_runtime_entry_allowed": False,
        "live_runtime_entry_allowed": False,
        "true_scalping_claim_allowed": False,
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
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _dedupe(items: list[str]) -> list[str]:
    result = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


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
