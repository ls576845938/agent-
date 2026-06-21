#!/usr/bin/env python3
"""Build the BTC intraday short-cycle manual promotion gate report.

This is a research-only evidence gate. It can allow manual candidate review,
but it must not generate strategy skeletons, enqueue paper trading, unlock live
trading, or claim true scalping readiness.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
DEFAULT_EVENT_LEDGER = Path(
    "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_drift_guarded_event_ledger_report.json"
)
REPORT_FILENAME = "btc_intraday_short_cycle_promotion_gate_report.json"


def build_btc_intraday_short_cycle_promotion_gate_report(
    *,
    repo_root: Path | None = None,
    event_ledger_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    event_ledger_file = _resolve(root, event_ledger_path or DEFAULT_EVENT_LEDGER)
    event_ledger = _read_json(event_ledger_file)
    source_reports = _source_reports(root=root, event_ledger_file=event_ledger_file, event_ledger=event_ledger)
    run_manifest = _read_json(_resolve_optional(root, source_reports.get("run_manifest")))
    checks = _checks(event_ledger_file=event_ledger_file, event_ledger=event_ledger, run_manifest=run_manifest)
    blockers = _blockers(checks)
    manual_review_allowed = not blockers
    gate = _mapping(event_ledger.get("gate"))
    metrics = _mapping(event_ledger.get("metrics"))
    manifest = _manifest_summary(run_manifest)
    return {
        "schema_version": "btc_intraday_short_cycle_promotion_gate_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "strategy_id": str(event_ledger.get("strategy_id", "")),
        "variant_id": str(event_ledger.get("variant_id", "")),
        "family_id": str(event_ledger.get("family_id", "")),
        "status": "ready_for_manual_candidate_review" if manual_review_allowed else "blocked_promotion_gate",
        "decision": (
            "continue_research_manual_review_only"
            if manual_review_allowed
            else "back_to_event_definition_or_evidence_repair"
        ),
        "next_required_action": (
            "manual_review_before_any_candidate_generation"
            if manual_review_allowed
            else "repair_failed_promotion_gate_checks"
        ),
        "source_reports": source_reports,
        "checks": checks,
        "blockers": blockers,
        "metrics": {
            "trade_count": int(metrics.get("trade_count", 0) or 0),
            "fill_count": int(metrics.get("fill_count", 0) or 0),
            "profit_factor": _float_or_none(metrics.get("profit_factor")),
            "event_profit_factor": _float_or_none(metrics.get("event_profit_factor")),
            "walk_forward_pass_rate": _float_or_none(metrics.get("walk_forward_pass_rate")),
            "regime_pass_rate": _float_or_none(metrics.get("regime_pass_rate")),
            "pbo": _float_or_none(metrics.get("pbo")),
            "dsr": _float_or_none(metrics.get("dsr")),
        },
        "gate": {
            "status": str(gate.get("status", "")),
            "passed": bool(gate.get("passed", False)),
            "fail_reasons": _list_of_strings(gate.get("fail_reasons")),
            "thresholds": _mapping(gate.get("thresholds")),
        },
        "manifest": manifest,
        "limitations": [
            "manual_candidate_review_does_not_generate_strategy_skeleton",
            "paper_and_live_remain_locked_until_separate_recorded_review_and_paper_gate",
            "true_scalping_remains_blocked_until_1m_tick_orderbook_spread_latency_queue_model",
        ],
        "manual_candidate_review_allowed": manual_review_allowed,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "true_scalping_allowed": False,
        "guardrails": {
            "research_only": True,
            "manual_review_gate_only": True,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
            "pnl_from_fill_ledger_required": True,
        },
    }


def write_btc_intraday_short_cycle_promotion_gate_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / REPORT_FILENAME
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--event-ledger-path", default=str(DEFAULT_EVENT_LEDGER))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_intraday_short_cycle_promotion_gate_report(
        repo_root=Path(args.repo_root),
        event_ledger_path=Path(args.event_ledger_path),
        generated_at=args.generated_at or None,
    )
    print(write_btc_intraday_short_cycle_promotion_gate_report(payload, Path(args.output_root)))
    if payload.get("status") != "ready_for_manual_candidate_review":
        raise SystemExit(2)


def _source_reports(
    *,
    root: Path,
    event_ledger_file: Path,
    event_ledger: Mapping[str, Any],
) -> dict[str, str | None]:
    artifacts = _mapping(event_ledger.get("artifacts"))
    return {
        "drift_guarded_event_ledger": _relpath(event_ledger_file, root) if event_ledger_file.exists() else None,
        "canonical_backtest_report": _relpath_if_exists(root, artifacts.get("canonical_backtest_report")),
        "event_objects": _relpath_if_exists(root, artifacts.get("event_objects")),
        "trade_ledger": _relpath_if_exists(root, artifacts.get("trade_ledger")),
        "cost_stress_report": _relpath_if_exists(root, artifacts.get("cost_stress_report")),
        "walk_forward_report": _relpath_if_exists(root, artifacts.get("walk_forward_report")),
        "regime_report": _relpath_if_exists(root, artifacts.get("regime_report")),
        "tail_dependency_report": _relpath_if_exists(root, artifacts.get("tail_dependency_report")),
        "run_manifest": _relpath_if_exists(root, artifacts.get("run_manifest")),
    }


def _checks(
    *,
    event_ledger_file: Path,
    event_ledger: Mapping[str, Any],
    run_manifest: Mapping[str, Any],
) -> dict[str, bool]:
    gate = _mapping(event_ledger.get("gate"))
    thresholds = _mapping(gate.get("thresholds"))
    metrics = _mapping(event_ledger.get("metrics"))
    cost = _mapping(event_ledger.get("cost_stress"))
    cost_context = _mapping(event_ledger.get("cost_context"))
    data_context = _mapping(event_ledger.get("data_context"))
    event_definition = _mapping(event_ledger.get("event_definition"))
    tail = _mapping(event_ledger.get("tail_dependency"))
    safety = _mapping(event_ledger.get("safety"))
    guardrails = _mapping(event_ledger.get("guardrails"))
    wf_threshold = float(thresholds.get("walk_forward_pass_rate", 0.8) or 0.8)
    regime_threshold = float(thresholds.get("regime_pass_rate", 0.75) or 0.75)
    return {
        "event_ledger_report_present": event_ledger_file.exists(),
        "event_ledger_completed": bool(event_ledger.get("event_ledger_completed", False)),
        "internal_gate_passed": bool(gate.get("passed", False)) and str(gate.get("status", "")) == "candidate_passed_internal_gate",
        "cost_stress_base_passed": bool(cost.get("base_passed", False)),
        "cost_stress_harsh_survives": bool(cost.get("harsh_survives", False)),
        "cost_stress_required_scenarios_present": bool(cost_context.get("required_scenarios_present", False)),
        "walk_forward_pass_rate_met": _float_or_none(metrics.get("walk_forward_pass_rate")) is not None
        and float(metrics.get("walk_forward_pass_rate")) >= wf_threshold,
        "regime_pass_rate_met": _float_or_none(metrics.get("regime_pass_rate")) is not None
        and float(metrics.get("regime_pass_rate")) >= regime_threshold,
        "tail_dependency_passed": str(tail.get("status", "")) == "pass" and not _list_of_strings(tail.get("blockers")),
        "data_status_passed": str(data_context.get("data_status", "")) == "pass",
        "cost_model_passed": str(cost_context.get("cost_model_status", "")) == "pass",
        "manifest_file_present": bool(run_manifest),
        "manifest_data_version_present": _non_empty_text(run_manifest.get("data_version")),
        "manifest_strategy_version_present": _non_empty_text(run_manifest.get("strategy_version")),
        "manifest_params_present": isinstance(run_manifest.get("params"), Mapping) and bool(run_manifest.get("params")),
        "manifest_cost_model_present": _non_empty_text(run_manifest.get("cost_model")),
        "manifest_slippage_model_present": _non_empty_text(run_manifest.get("slippage_model")),
        "manifest_commit_hash_present": _non_empty_text(run_manifest.get("commit_hash")),
        "pnl_from_fill_ledger_required": bool(guardrails.get("pnl_from_fill_ledger_required_for_promotion", False)),
        "strategy_signal_or_order_intent_only": bool(event_definition.get("simulated_order_intent_only", False))
        and bool(event_definition.get("future_label_used_for_signal", True)) is False
        and bool(event_definition.get("lookahead_used_for_signal", True)) is False,
        "private_order_broker_paths_locked": all(
            bool(value) is False
            for value in (
                guardrails.get("broker_calls_allowed", True),
                guardrails.get("private_endpoints_allowed", True),
                guardrails.get("order_endpoints_allowed", True),
                safety.get("real_broker_api_called", True),
                safety.get("real_orders_created", True),
            )
        ),
        "candidate_generation_still_locked": bool(event_ledger.get("candidate_generation_allowed", True)) is False
        and bool(event_ledger.get("strategy_skeleton_generation_allowed", True)) is False,
        "paper_live_still_locked": bool(event_ledger.get("paper_or_live_unlock_allowed", True)) is False
        and str(safety.get("paper_queue", "")) == "LOCKED"
        and str(safety.get("live", "")) == "FROZEN",
        "true_scalping_still_locked": bool(event_ledger.get("true_scalping_allowed", True)) is False
        and bool(guardrails.get("true_scalping_allowed", True)) is False,
    }


def _manifest_summary(run_manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "data_version": run_manifest.get("data_version"),
        "strategy_version": run_manifest.get("strategy_version"),
        "params_hash": run_manifest.get("params_hash"),
        "params": dict(_mapping(run_manifest.get("params"))),
        "cost_model": run_manifest.get("cost_model"),
        "slippage_model": run_manifest.get("slippage_model"),
        "commit_hash": run_manifest.get("commit_hash"),
    }


def _blockers(checks: Mapping[str, bool]) -> list[str]:
    return [f"btc_intraday_promotion_gate_{name}_failed" for name, passed in checks.items() if not passed]


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


def _list_of_strings(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _resolve_optional(root: Path, value: str | None) -> Path | None:
    if not value:
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


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001 - metadata only.
        return "unknown"


if __name__ == "__main__":
    main()
