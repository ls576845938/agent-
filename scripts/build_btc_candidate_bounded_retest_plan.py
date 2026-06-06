#!/usr/bin/env python3
"""Build a fail-closed BTC candidate bounded retest plan."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
DEFAULT_METRIC_REPAIR = Path("artifacts/btc_candidate_gate/latest/candidate_metric_repair_report.json")
DEFAULT_WF_ATTRIBUTION = Path(
    "artifacts/btc_canonical/20260516T080000Z_eventpf_wf/walk_forward_fold_attribution.json"
)
DEFAULT_RETEST_RUNNER = Path("scripts/research/run_btc_eventpf_wf_stabilization.py")
DEFAULT_SOURCE_RUN_DIR = Path("artifacts/btc_canonical/20260516T061000Z_attribution")
DEFAULT_EXISTING_RUN_MANIFEST = Path("artifacts/btc_canonical/20260516T080000Z_eventpf_wf/run_manifest.json")
DEFAULT_EXISTING_EVENT_MANIFEST = Path(
    "artifacts/btc_canonical/20260516T080000Z_eventpf_wf/manifests/run_btc_perp_dual_trend_v4_eventpf_wf_base.json"
)
RETEST_READINESS_CHECK_COMMAND = "make check-btc-candidate-bounded-retest-readiness"
RETEST_COMMAND_TEMPLATE = (
    "python3 scripts/research/run_btc_eventpf_wf_stabilization.py "
    "--run-id BTC_CANDIDATE_RETEST_YYYYMMDDTHHMMSSZ "
    "--output-root artifacts/btc_canonical "
    "--source-run-dir artifacts/btc_canonical/20260516T061000Z_attribution"
)
POST_RETEST_VALIDATION_COMMAND = "make validate-btc-evidence"
EVENT_MANIFEST_REQUIRED_FIELDS = [
    "data_version",
    "strategy_version",
    "strategy_params",
    "cost_model",
    "slippage_model",
    "commit_hash",
]


def build_btc_candidate_bounded_retest_plan(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    metric_path = root / DEFAULT_METRIC_REPAIR
    wf_path = root / DEFAULT_WF_ATTRIBUTION
    metric_repair = _read_json(metric_path)
    wf_attribution = _read_json(wf_path)
    candidate = _mapping(metric_repair.get("best_candidate"))
    candidate_metrics = _mapping(candidate.get("metrics"))
    thresholds = _mapping(metric_repair.get("gate_thresholds"))
    failed_metrics = _list_of_strings(metric_repair.get("failed_metrics"))
    data_cost_action = _action(metric_repair, "complete_perpetual_data_cost_evidence")
    data_cost_blockers = _list_of_strings(data_cost_action.get("inputs"))
    metric_status = str(metric_repair.get("status", "missing") or "missing")
    status = _status(
        metric_path_exists=metric_path.exists(),
        metric_status=metric_status,
        data_cost_blockers=data_cost_blockers,
        failed_metrics=failed_metrics,
    )
    retest_allowed = status == "ready_for_bounded_retest"
    fold_scope = _fold_scope(metric_repair, wf_attribution)
    guardrails = _guardrails(retest_allowed=retest_allowed)
    blockers = _blockers(
        status=status,
        metric_path_exists=metric_path.exists(),
        data_cost_blockers=data_cost_blockers,
        failed_metrics=failed_metrics,
    )
    return {
        "schema_version": "btc_candidate_bounded_retest_plan_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "status": status,
        "retest_allowed": retest_allowed,
        "bounded_parameter_search_allowed": retest_allowed,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "source_artifacts": {
            "candidate_metric_repair_report": _relpath(metric_path, root) if metric_path.exists() else None,
            "walk_forward_fold_attribution": _relpath(wf_path, root) if wf_path.exists() else None,
        },
        "candidate": _candidate_summary(candidate),
        "data_cost_prerequisite": {
            "status": "complete" if not data_cost_blockers and metric_path.exists() else "blocked",
            "required_before_retest": True,
            "action": str(data_cost_action.get("name", "complete_perpetual_data_cost_evidence")),
            "blockers": data_cost_blockers,
        },
        "metric_repair_context": {
            "status": metric_status,
            "failed_metrics": failed_metrics,
            "event_profit_factor": _float_or_none(candidate_metrics.get("event_profit_factor")),
            "walk_forward_pass_rate": _float_or_none(candidate_metrics.get("walk_forward_pass_rate")),
            "regime_pass_rate": _float_or_none(candidate_metrics.get("regime_pass_rate")),
            "ordinary_profit_factor": _float_or_none(candidate_metrics.get("profit_factor")),
            "metric_repair_blockers": _list_of_strings(metric_repair.get("blockers")),
        },
        "acceptance_criteria": {
            "event_profit_factor_min": _float_or_none(thresholds.get("event_profit_factor")),
            "walk_forward_pass_rate_min": _float_or_none(thresholds.get("walk_forward_pass_rate")),
            "regime_pass_rate_min": _float_or_none(thresholds.get("regime_pass_rate")),
            "cost_stress_required": bool(thresholds.get("cost_stress_required", True)),
            "ledger_fill_pnl_required": True,
            "walk_forward_recompute_required": True,
            "manifest_required": True,
        },
        "test_scope": {
            "primary_objectives": [
                "event_profit_factor",
                "walk_forward_pass_rate",
                "regime_pass_rate",
                "cost_stress",
            ],
            "diagnostic_only_metrics": [
                "ordinary_profit_factor",
                "sharpe",
                "total_return",
            ],
            "focus_failed_metrics": failed_metrics,
            "focus_failed_folds": fold_scope["focus_failed_folds"],
            "folds_required_for_rerun": fold_scope["folds_required_for_rerun"],
            "allowed_rule_changes": _allowed_rule_changes(metric_repair),
            "disallowed_rule_changes": _disallowed_rule_changes(metric_repair),
        },
        "retest_steps": _retest_steps(retest_allowed=retest_allowed, failed_metrics=failed_metrics, fold_scope=fold_scope),
        "execution_plan": _execution_plan(
            root=root,
            status=status,
            retest_allowed=retest_allowed,
            candidate=candidate,
            data_cost_blockers=data_cost_blockers,
        ),
        "guardrails": guardrails,
        "blockers": blockers,
    }


def write_btc_candidate_bounded_retest_plan(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "candidate_bounded_retest_plan.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_candidate_bounded_retest_plan(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_candidate_bounded_retest_plan(payload, Path(args.output_root)))


def _status(
    *,
    metric_path_exists: bool,
    metric_status: str,
    data_cost_blockers: list[str],
    failed_metrics: list[str],
) -> str:
    if not metric_path_exists:
        return "blocked_missing_metric_repair_report"
    if metric_status == "candidate_metric_gate_passed" and not failed_metrics:
        return "not_required_candidate_metric_gate_passed"
    if data_cost_blockers:
        return "blocked_by_perpetual_data_cost"
    if failed_metrics:
        return "ready_for_bounded_retest"
    return "blocked_missing_metric_failures"


def _blockers(
    *,
    status: str,
    metric_path_exists: bool,
    data_cost_blockers: list[str],
    failed_metrics: list[str],
) -> list[str]:
    if status in {"ready_for_bounded_retest", "not_required_candidate_metric_gate_passed"}:
        return []
    blockers: list[str] = []
    if not metric_path_exists:
        blockers.append("btc_candidate_metric_repair_report_missing")
    blockers.extend(data_cost_blockers)
    if status == "blocked_by_perpetual_data_cost":
        for metric in failed_metrics:
            blockers.append(f"btc_candidate_bounded_retest_waiting_on_data_cost_before_{metric}")
    if status == "blocked_missing_metric_failures":
        blockers.append("btc_candidate_bounded_retest_metric_failures_missing")
    return _dedupe(blockers)


def _candidate_summary(candidate: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _mapping(candidate.get("metrics"))
    thresholds = _mapping(candidate.get("thresholds"))
    return {
        "strategy_id": str(candidate.get("strategy_id", "")),
        "source_run_dir": str(candidate.get("source_run_dir", "")),
        "status": str(candidate.get("status", "candidate_gate_unknown") or "candidate_gate_unknown"),
        "failed_metrics": _list_of_strings(candidate.get("failed_metrics")),
        "metrics": {
            "event_profit_factor": _float_or_none(metrics.get("event_profit_factor")),
            "walk_forward_pass_rate": _float_or_none(metrics.get("walk_forward_pass_rate")),
            "regime_pass_rate": _float_or_none(metrics.get("regime_pass_rate")),
            "ordinary_profit_factor": _float_or_none(metrics.get("profit_factor")),
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


def _fold_scope(metric_repair: Mapping[str, Any], wf_attribution: Mapping[str, Any]) -> dict[str, Any]:
    fold_diagnostics = _mapping(metric_repair.get("fold_failure_diagnostics"))
    failed = [int(item) for item in fold_diagnostics.get("failed_folds", []) if _int_or_none(item) is not None]
    folds = wf_attribution.get("folds")
    fold_ids = []
    if isinstance(folds, list):
        for item in folds:
            if not isinstance(item, Mapping):
                continue
            fold_id = _int_or_none(item.get("fold_id"))
            if fold_id is not None:
                fold_ids.append(fold_id)
    if not fold_ids:
        fold_ids = failed
    return {
        "focus_failed_folds": failed,
        "folds_required_for_rerun": fold_ids,
    }


def _allowed_rule_changes(metric_repair: Mapping[str, Any]) -> list[str]:
    ablation = _mapping(metric_repair.get("ablation_diagnostics"))
    allowed = _list_of_strings(ablation.get("adopted_exit_rules"))
    allowed.extend(_list_of_strings(ablation.get("adopted_side_rules")))
    return _dedupe(allowed)


def _disallowed_rule_changes(metric_repair: Mapping[str, Any]) -> list[str]:
    ablation = _mapping(metric_repair.get("ablation_diagnostics"))
    disallowed = _list_of_strings(ablation.get("rejected_exit_rules"))
    disallowed.extend(_list_of_strings(ablation.get("rejected_side_rules")))
    disallowed.extend(
        [
            "broad_short_reintroduction",
            "ordinary_profit_factor_primary_objective",
            "sharpe_first_search",
            "paper_or_live_unlock_from_retest_plan",
        ]
    )
    return _dedupe(disallowed)


def _retest_steps(
    *,
    retest_allowed: bool,
    failed_metrics: list[str],
    fold_scope: Mapping[str, Any],
) -> list[dict[str, Any]]:
    data_status = "complete" if retest_allowed else "blocked"
    return [
        {
            "name": "complete_perpetual_data_cost_evidence",
            "status": data_status,
            "required": True,
            "description": "verified USD-M perpetual metadata, funding metadata, fee tier, funding ledger, and cost model",
        },
        {
            "name": "rerun_event_ledger_candidate_with_fixed_manifest",
            "status": "pending" if retest_allowed else "blocked",
            "required": bool(failed_metrics),
            "description": "rerun from fills and ledger with data_version, strategy_version, params, costs, slippage, and commit hash recorded",
        },
        {
            "name": "repair_late_walk_forward_folds",
            "status": "pending" if retest_allowed and fold_scope.get("focus_failed_folds") else "blocked",
            "required": "walk_forward_pass_rate" in failed_metrics,
            "description": "fold diagnostics must cover the failed folds before any candidate promotion",
        },
        {
            "name": "rerun_cost_stress_and_walk_forward_gate",
            "status": "pending" if retest_allowed else "blocked",
            "required": True,
            "description": "promotion requires event PF, walk-forward, regime, cost stress, and ledger checks together",
        },
    ]


def _execution_plan(
    *,
    root: Path,
    status: str,
    retest_allowed: bool,
    candidate: Mapping[str, Any],
    data_cost_blockers: list[str],
) -> dict[str, Any]:
    runner = _runner_contract(root)
    manifest = _event_manifest_contract(root)
    source_run_dir = root / DEFAULT_SOURCE_RUN_DIR
    runner_ready = bool(runner["exists"] and runner["supports_run_id_arg"] and runner["supports_output_root_arg"])
    manifest_ready = bool(manifest["existing_event_manifest_contract_ok"])
    if status == "not_required_candidate_metric_gate_passed":
        execution_status = "not_required"
    elif retest_allowed and runner_ready and manifest_ready:
        execution_status = "ready"
    else:
        execution_status = "blocked"
    runner_blockers: list[str] = []
    if not runner["exists"]:
        runner_blockers.append("btc_candidate_bounded_retest_runner_missing")
    if runner["exists"] and not runner["supports_run_id_arg"]:
        runner_blockers.append("btc_candidate_bounded_retest_runner_run_id_arg_missing")
    if runner["exists"] and not runner["supports_output_root_arg"]:
        runner_blockers.append("btc_candidate_bounded_retest_runner_output_root_arg_missing")
    manifest_blockers = _list_of_strings(manifest.get("blockers"))
    return {
        "status": execution_status,
        "readiness_check_command": RETEST_READINESS_CHECK_COMMAND,
        "retest_command": RETEST_COMMAND_TEMPLATE if execution_status == "ready" else "",
        "retest_command_template": RETEST_COMMAND_TEMPLATE,
        "post_retest_validation_command": POST_RETEST_VALIDATION_COMMAND,
        "runner": runner,
        "input_artifacts": [
            _relpath(root / DEFAULT_METRIC_REPAIR, root),
            _relpath(root / DEFAULT_WF_ATTRIBUTION, root),
            _relpath(source_run_dir, root),
        ],
        "required_output_artifacts": _required_output_artifacts(),
        "manifest_contract": manifest,
        "preflight_checks": [
            {
                "name": "perpetual_data_cost_evidence_complete",
                "status": "complete" if not data_cost_blockers else "blocked",
                "blockers": data_cost_blockers,
            },
            {
                "name": "bounded_retest_runner_contract",
                "status": "complete" if not runner_blockers else "blocked",
                "blockers": runner_blockers,
            },
            {
                "name": "event_backtest_manifest_contract",
                "status": "complete" if not manifest_blockers else "blocked",
                "blockers": manifest_blockers,
            },
        ],
        "strategy_id": str(candidate.get("strategy_id", "")),
    }


def _runner_contract(root: Path) -> dict[str, Any]:
    path = root / DEFAULT_RETEST_RUNNER
    source = path.read_text(encoding="utf-8") if path.exists() else ""
    return {
        "path": _relpath(path, root) if path.exists() else _relpath(path, root),
        "exists": path.exists(),
        "module": "quant_us.research.btc_eventpf_wf.run_stabilization_sprint",
        "supports_run_id_arg": "--run-id" in source,
        "supports_output_root_arg": "--output-root" in source,
        "supports_source_run_dir_arg": "--source-run-dir" in source,
        "broker_calls_allowed": False,
        "paper_or_live_unlock_allowed": False,
    }


def _event_manifest_contract(root: Path) -> dict[str, Any]:
    run_manifest_path = root / DEFAULT_EXISTING_RUN_MANIFEST
    event_manifest_path = root / DEFAULT_EXISTING_EVENT_MANIFEST
    run_manifest = _read_json(run_manifest_path)
    event_manifest = _read_json(event_manifest_path)
    fields_present = {field: event_manifest.get(field) not in (None, "", []) for field in EVENT_MANIFEST_REQUIRED_FIELDS}
    blockers = []
    if not event_manifest_path.exists():
        blockers.append("btc_candidate_bounded_retest_event_manifest_missing")
    for field, present in fields_present.items():
        if not present:
            blockers.append(f"btc_candidate_bounded_retest_event_manifest_{field}_missing")
    return {
        "required_event_manifest_fields": EVENT_MANIFEST_REQUIRED_FIELDS,
        "params_field": "strategy_params",
        "existing_run_manifest_path": _relpath(run_manifest_path, root) if run_manifest_path.exists() else None,
        "existing_run_manifest_has_artifact_paths": bool(run_manifest.get("artifact_paths")),
        "existing_event_manifest_path": _relpath(event_manifest_path, root) if event_manifest_path.exists() else None,
        "existing_event_manifest_fields_present": fields_present,
        "existing_event_manifest_contract_ok": not blockers,
        "blockers": blockers,
    }


def _required_output_artifacts() -> list[str]:
    prefix = "artifacts/btc_canonical/BTC_CANDIDATE_RETEST_YYYYMMDDTHHMMSSZ"
    return [
        f"{prefix}/run_manifest.json",
        f"{prefix}/promotion_decision.json",
        f"{prefix}/paper_live_safety_status.json",
        f"{prefix}/btc_perp_dual_trend_v4_eventpf_wf_results.json",
        f"{prefix}/btc_perp_dual_trend_v4_eventpf_wf_decision.json",
        f"{prefix}/btc_perp_dual_trend_v4_eventpf_wf/canonical_backtest_report.json",
        f"{prefix}/btc_perp_dual_trend_v4_eventpf_wf/gate_inputs.json",
        f"{prefix}/walk_forward_fold_attribution.json",
        f"{prefix}/manifests/run_btc_perp_dual_trend_v4_eventpf_wf_base.json",
        f"{prefix}/manifests/run_btc_perp_dual_trend_v4_eventpf_wf_cost_costs_2x.json",
        f"{prefix}/manifests/run_btc_perp_dual_trend_v4_eventpf_wf_wf1.json",
        f"{prefix}/manifests/run_btc_perp_dual_trend_v4_eventpf_wf_wf2.json",
        f"{prefix}/manifests/run_btc_perp_dual_trend_v4_eventpf_wf_wf3.json",
        f"{prefix}/manifests/run_btc_perp_dual_trend_v4_eventpf_wf_wf4.json",
    ]


def _guardrails(*, retest_allowed: bool) -> dict[str, Any]:
    return {
        "report_only": True,
        "strategy_retest_allowed": retest_allowed,
        "bounded_parameter_search_only": True,
        "paper_or_live_unlock_allowed": False,
        "broker_calls_allowed": False,
        "private_endpoints_allowed": False,
        "order_endpoints_allowed": False,
        "ordinary_profit_factor_diagnostic_only": True,
        "requires_event_ledger_fills_pnl": True,
        "requires_walk_forward_pass": True,
        "requires_cost_stress_pass": True,
        "requires_perpetual_data_cost_evidence": True,
        "requires_manifest": True,
        "no_future_function": True,
    }


def _action(payload: Mapping[str, Any], name: str) -> dict[str, Any]:
    actions = payload.get("recommended_repair_actions")
    if not isinstance(actions, list):
        return {}
    for item in actions:
        if isinstance(item, Mapping) and item.get("name") == name:
            return dict(item)
    return {}


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
