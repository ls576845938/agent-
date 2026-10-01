#!/usr/bin/env python3
"""Build a BTC candidate metric repair report from persisted research evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
DEFAULT_CANDIDATE_GATE = Path("artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json")
DEFAULT_WF_ATTRIBUTION = Path(
    "artifacts/btc_canonical/20260516T080000Z_eventpf_wf/walk_forward_fold_attribution.json"
)
DEFAULT_EXIT_ABLATION = Path("artifacts/btc_canonical/20260516T080000Z_eventpf_wf/exit_surgery_ablation_report.json")
DEFAULT_SIDE_ABLATION = Path("artifacts/btc_canonical/20260516T080000Z_eventpf_wf/side_regime_ablation_report.json")


def build_btc_candidate_metric_repair_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    candidate_gate = _read_json(root / DEFAULT_CANDIDATE_GATE)
    wf_attribution = _read_json(root / DEFAULT_WF_ATTRIBUTION)
    exit_ablation = _read_json(root / DEFAULT_EXIT_ABLATION)
    side_ablation = _read_json(root / DEFAULT_SIDE_ABLATION)
    best_candidate = _candidate_summary(candidate_gate.get("best_available_candidate"))
    gate_thresholds = _gate_thresholds(candidate_gate, best_candidate)
    metric_failures = _metric_failures(candidate_gate, best_candidate)
    repair_plan = _mapping(candidate_gate.get("candidate_repair_plan"))
    data_cost_stage = _repair_stage(repair_plan, "perpetual_data_cost_evidence")
    data_cost_blockers = _list_of_strings(data_cost_stage.get("blockers"))
    fold_diagnostics = _fold_failure_diagnostics(wf_attribution)
    ablation_diagnostics = _ablation_diagnostics(exit_ablation, side_ablation)
    status = _status(candidate_gate, metric_failures, data_cost_blockers)
    blockers = _blockers(status, metric_failures, data_cost_blockers)
    return {
        "schema_version": "btc_candidate_metric_repair_report_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "status": status,
        "paper_review_pending_allowed": status == "candidate_metric_gate_passed"
        and bool(candidate_gate.get("paper_review_pending_allowed", False)),
        "promotion_allowed": status == "candidate_metric_gate_passed"
        and bool(candidate_gate.get("paper_review_pending_allowed", False)),
        "source_artifacts": {
            "candidate_gate": _relpath(root / DEFAULT_CANDIDATE_GATE, root)
            if (root / DEFAULT_CANDIDATE_GATE).exists()
            else None,
            "walk_forward_fold_attribution": _relpath(root / DEFAULT_WF_ATTRIBUTION, root)
            if (root / DEFAULT_WF_ATTRIBUTION).exists()
            else None,
            "exit_surgery_ablation": _relpath(root / DEFAULT_EXIT_ABLATION, root)
            if (root / DEFAULT_EXIT_ABLATION).exists()
            else None,
            "side_regime_ablation": _relpath(root / DEFAULT_SIDE_ABLATION, root)
            if (root / DEFAULT_SIDE_ABLATION).exists()
            else None,
        },
        "best_candidate": best_candidate,
        "gate_thresholds": gate_thresholds,
        "failed_metrics": metric_failures,
        "fold_failure_diagnostics": fold_diagnostics,
        "ablation_diagnostics": ablation_diagnostics,
        "recommended_repair_actions": _recommended_actions(
            metric_failures=metric_failures,
            data_cost_blockers=data_cost_blockers,
            fold_diagnostics=fold_diagnostics,
            ablation_diagnostics=ablation_diagnostics,
            best_candidate=best_candidate,
        ),
        "safety": {
            "report_only": True,
            "strategy_retest_allowed": True,
            "paper_or_live_unlock_allowed": False,
            "ordinary_profit_factor_diagnostic_only": True,
            "requires_event_ledger_fills_pnl": True,
            "requires_walk_forward_pass": True,
            "requires_cost_stress_pass": True,
            "requires_perpetual_data_cost_evidence": True,
        },
        "blockers": blockers,
    }


def write_btc_candidate_metric_repair_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "candidate_metric_repair_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_candidate_metric_repair_report(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_candidate_metric_repair_report(payload, Path(args.output_root)))


def _status(
    candidate_gate: Mapping[str, Any],
    metric_failures: list[str],
    data_cost_blockers: list[str],
) -> str:
    if str(candidate_gate.get("status", "fail")) == "pass" and not metric_failures and not data_cost_blockers:
        return "candidate_metric_gate_passed"
    if data_cost_blockers:
        return "blocked_by_perpetual_data_cost"
    if metric_failures:
        return "needs_metric_repair"
    return "needs_candidate_promotion_decision"


def _blockers(status: str, metric_failures: list[str], data_cost_blockers: list[str]) -> list[str]:
    blockers: list[str] = []
    if status == "candidate_metric_gate_passed":
        return blockers
    blockers.extend(data_cost_blockers)
    for metric in metric_failures:
        blockers.append(f"btc_candidate_metric_repair_{metric}_failed")
    if status == "needs_candidate_promotion_decision":
        blockers.append("btc_candidate_metric_repair_promotion_decision_missing")
    return _dedupe(blockers)


def _recommended_actions(
    *,
    metric_failures: list[str],
    data_cost_blockers: list[str],
    fold_diagnostics: Mapping[str, Any],
    ablation_diagnostics: Mapping[str, Any],
    best_candidate: Mapping[str, Any],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if data_cost_blockers:
        actions.append(
            {
                "name": "complete_perpetual_data_cost_evidence",
                "priority": 1,
                "status": "blocked",
                "reason": "candidate metrics must be retested on verified USD-M perpetual data and cost evidence",
                "inputs": data_cost_blockers,
            }
        )
    next_priority = 2 if actions else 1
    if "event_profit_factor" in metric_failures:
        actions.append(
            {
                "name": "run_bounded_event_pf_retest",
                "priority": next_priority,
                "status": "pending",
                "reason": "best candidate event_PF remains below threshold",
                "inputs": [
                    str(best_candidate.get("source_run_dir", "")),
                    str(best_candidate.get("strategy_id", "")),
                ],
            }
        )
        next_priority += 1
    if "walk_forward_pass_rate" in metric_failures:
        actions.append(
            {
                "name": "repair_late_walk_forward_folds",
                "priority": next_priority,
                "status": "pending",
                "reason": "walk-forward pass rate is below threshold; failed fold evidence must drive retest scope",
                "inputs": [str(item) for item in fold_diagnostics.get("failed_folds", [])],
            }
        )
        next_priority += 1
    if "regime_pass_rate" in metric_failures:
        actions.append(
            {
                "name": "recheck_regime_gate_after_candidate_selection",
                "priority": next_priority,
                "status": "pending",
                "reason": "primary candidate regime gate failed; best available candidate may differ from primary source run",
                "inputs": [str(best_candidate.get("strategy_id", ""))],
            }
        )
        next_priority += 1
    if ablation_diagnostics.get("short_reintroduction_rejected"):
        actions.append(
            {
                "name": "avoid_broad_short_reintroduction",
                "priority": next_priority,
                "status": "guardrail",
                "reason": "side-regime ablation shows short-side probes degrade fold or regime evidence",
                "inputs": _list_of_strings(ablation_diagnostics.get("rejected_side_rules")),
            }
        )
        next_priority += 1
    actions.append(
        {
            "name": "do_not_promote_on_ordinary_profit_factor",
            "priority": next_priority,
            "status": "guardrail",
            "reason": "ordinary PF is diagnostic only; promotion requires event-ledger PF, costs, and walk-forward robustness",
            "inputs": [],
        }
    )
    return actions


def _candidate_summary(value: object) -> dict[str, Any]:
    candidate = _mapping(value)
    metrics = _mapping(candidate.get("metrics"))
    thresholds = _mapping(candidate.get("thresholds"))
    return {
        "strategy_id": str(candidate.get("strategy_id", "")),
        "source_run_dir": str(candidate.get("source_run_dir", "")),
        "status": str(candidate.get("status", "candidate_gate_unknown") or "candidate_gate_unknown"),
        "passed_metric_count": int(candidate.get("passed_metric_count", 0) or 0),
        "required_metric_count": int(candidate.get("required_metric_count", 0) or 0),
        "failed_metrics": _list_of_strings(candidate.get("failed_metrics")),
        "metrics": {
            "event_profit_factor": _float_or_none(metrics.get("event_profit_factor")),
            "walk_forward_pass_rate": _float_or_none(metrics.get("walk_forward_pass_rate")),
            "regime_pass_rate": _float_or_none(metrics.get("regime_pass_rate")),
            "profit_factor": _float_or_none(metrics.get("profit_factor")),
            "dsr": _float_or_none(metrics.get("dsr")),
            "pbo": _float_or_none(metrics.get("pbo")),
            "max_drawdown": _float_or_none(metrics.get("max_drawdown")),
            "trade_count": _int_or_none(metrics.get("trade_count")),
            "fill_count": _int_or_none(metrics.get("fill_count")),
        },
        "thresholds": {
            "event_profit_factor": _float_or_none(thresholds.get("event_profit_factor")),
            "walk_forward_pass_rate": _float_or_none(thresholds.get("walk_forward_pass_rate")),
            "regime_pass_rate": _float_or_none(thresholds.get("regime_pass_rate")),
        },
    }


def _gate_thresholds(candidate_gate: Mapping[str, Any], best_candidate: Mapping[str, Any]) -> dict[str, Any]:
    thresholds = _mapping(candidate_gate.get("candidate_gate_thresholds"))
    best_thresholds = _mapping(best_candidate.get("thresholds"))
    return {
        "event_profit_factor": _float_or_none(
            thresholds.get("event_profit_factor", best_thresholds.get("event_profit_factor"))
        ),
        "walk_forward_pass_rate": _float_or_none(
            thresholds.get("walk_forward_pass_rate", best_thresholds.get("walk_forward_pass_rate"))
        ),
        "regime_pass_rate": _float_or_none(
            thresholds.get("regime_pass_rate", best_thresholds.get("regime_pass_rate"))
        ),
        "cost_stress_required": bool(thresholds.get("cost_stress_required", True)),
    }


def _metric_failures(candidate_gate: Mapping[str, Any], best_candidate: Mapping[str, Any]) -> list[str]:
    best_failed = _list_of_strings(best_candidate.get("failed_metrics"))
    if best_failed:
        return [item for item in best_failed if item in {"event_profit_factor", "walk_forward_pass_rate", "regime_pass_rate", "cost_stress"}]
    return _list_of_strings(candidate_gate.get("metric_failures"))


def _repair_stage(repair_plan: Mapping[str, Any], name: str) -> dict[str, Any]:
    stages = repair_plan.get("stages")
    if not isinstance(stages, list):
        return {}
    for item in stages:
        if isinstance(item, Mapping) and item.get("name") == name:
            return dict(item)
    return {}


def _fold_failure_diagnostics(payload: Mapping[str, Any]) -> dict[str, Any]:
    answers = _mapping(payload.get("answers"))
    failure_sources = _mapping(answers.get("failure_sources"))
    failed_folds = payload.get("failed_folds")
    folds = payload.get("folds")
    return {
        "source_strategy_id": str(payload.get("strategy_id", "")),
        "method": str(payload.get("method", "")),
        "pass_rate": _float_or_none(payload.get("pass_rate")),
        "failed_folds": [int(item) for item in failed_folds if isinstance(item, int)] if isinstance(failed_folds, list) else [],
        "failure_sources": {str(key): int(value) for key, value in failure_sources.items() if _int_or_none(value) is not None},
        "fold_count": len(folds) if isinstance(folds, list) else 0,
        "stable_rules": _list_of_strings(answers.get("stable_rules")),
        "unstable_or_overfit_rules": _list_of_strings(answers.get("unstable_or_overfit_rules")),
    }


def _ablation_diagnostics(exit_ablation: Mapping[str, Any], side_ablation: Mapping[str, Any]) -> dict[str, Any]:
    exit_best = _mapping(exit_ablation.get("best_by_event_PF"))
    side_best = _mapping(side_ablation.get("best_by_event_PF"))
    rejected_side = _list_of_strings(side_ablation.get("rejected_rules"))
    return {
        "exit_surgery_best": _ablation_best_summary(exit_best),
        "side_regime_best": _ablation_best_summary(side_best),
        "adopted_exit_rules": _list_of_strings(exit_ablation.get("adopted_rules")),
        "adopted_side_rules": _list_of_strings(side_ablation.get("adopted_rules")),
        "rejected_exit_rules": _list_of_strings(exit_ablation.get("rejected_rules")),
        "rejected_side_rules": rejected_side,
        "short_reintroduction_rejected": any("short" in item for item in rejected_side),
    }


def _ablation_best_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "mode": str(row.get("mode", "")),
        "event_profit_factor": _float_or_none(row.get("event_PF")),
        "walk_forward_pass_rate": _float_or_none(row.get("walk_forward_pass_rate")),
        "regime_pass_rate": _float_or_none(row.get("regime_pass_rate")),
        "max_drawdown": _float_or_none(row.get("MDD")),
        "gate_status": str(row.get("gate_status", "")),
        "fail_reasons": _list_of_strings(row.get("fail_reasons")),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
