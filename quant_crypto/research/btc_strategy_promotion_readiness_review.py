from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.application.btc_strategy_registry import (
    BTCStrategyIdentityError,
    compare_strategy_identities,
    btc_strategy_registry,
)


SCHEMA_VERSION = "btc_strategy_promotion_readiness_review_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_strategy_promotion_readiness/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_promotion_readiness_report.json"
DEFAULT_MATRIX_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_promotion_readiness_matrix.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_promotion_readiness_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_BAR_REPLAY_REPORT = Path("artifacts/btc_strategy_bar_replay_visibility/latest/btc_strategy_bar_replay_visibility_report.json")
DEFAULT_LEAKAGE_AUDIT_REPORT = Path("artifacts/btc_strategy_leakage_overfit_audit/latest/btc_strategy_leakage_overfit_audit_report.json")
DEFAULT_LONG_SHORT_OBSERVER_REPORT = Path("artifacts/btc_long_short_top5_forward_observer/latest/btc_long_short_top5_forward_observer_report.json")
DEFAULT_ATTACK_OBSERVER_REPORT = Path("artifacts/btc_bankroll_attack_forward_observer/latest/btc_bankroll_attack_forward_observer_report.json")
DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT = Path("artifacts/btc_high_yield_v2_followup/latest/btc_high_yield_v2_followup_report.json")
DEFAULT_OBSERVE_ONLY_HEALTH_REPORT = Path("artifacts/btc_observe_only_health/latest/btc_observe_only_health_report.json")
DEFAULT_PERP_EXECUTION_EVIDENCE_REPORT = Path("artifacts/btc_perpetual_execution_evidence/latest/btc_perpetual_execution_evidence_report.json")
DEFAULT_PAPER_RUNTIME_REPLAY_REPORT = Path("artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_report.json")
DEFAULT_EXCHANGE_RUNTIME_GAP_REPORT = Path("artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_replay_gap_report.json")
DEFAULT_GATE_DASHBOARD_REPORT = Path("artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json")
DEFAULT_CANONICAL_BACKTEST_MANIFEST = Path("artifacts/btc_strategy_backtest_runs/latest_manifest.json")


def build_btc_strategy_promotion_readiness_review(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
    bar_replay_report_path: Path = DEFAULT_BAR_REPLAY_REPORT,
    leakage_audit_report_path: Path = DEFAULT_LEAKAGE_AUDIT_REPORT,
    long_short_observer_report_path: Path = DEFAULT_LONG_SHORT_OBSERVER_REPORT,
    attack_observer_report_path: Path = DEFAULT_ATTACK_OBSERVER_REPORT,
    high_yield_followup_report_path: Path = DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT,
    observe_only_health_report_path: Path = DEFAULT_OBSERVE_ONLY_HEALTH_REPORT,
    perp_execution_evidence_report_path: Path = DEFAULT_PERP_EXECUTION_EVIDENCE_REPORT,
    paper_runtime_replay_report_path: Path = DEFAULT_PAPER_RUNTIME_REPLAY_REPORT,
    exchange_runtime_gap_report_path: Path = DEFAULT_EXCHANGE_RUNTIME_GAP_REPORT,
    gate_dashboard_report_path: Path = DEFAULT_GATE_DASHBOARD_REPORT,
    canonical_backtest_manifest_path: Path = DEFAULT_CANONICAL_BACKTEST_MANIFEST,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    matrix_path = output_dir / DEFAULT_MATRIX_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    missing: list[str] = []
    bar_replay = _read_json(bar_replay_report_path, missing, "bar_replay_report")
    leakage = _read_json(leakage_audit_report_path, missing, "leakage_audit_report")
    long_short = _read_json(long_short_observer_report_path, missing, "long_short_observer_report")
    attack = _read_json(attack_observer_report_path, missing, "attack_observer_report")
    high_yield = _read_json(high_yield_followup_report_path, missing, "high_yield_followup_report")
    observe_health = _read_json(observe_only_health_report_path, missing, "observe_only_health_report")
    perp = _read_json(perp_execution_evidence_report_path, missing, "perp_execution_evidence_report")
    paper_runtime = _read_json(paper_runtime_replay_report_path, missing, "paper_runtime_replay_report")
    exchange_gap = _read_json(exchange_runtime_gap_report_path, missing, "exchange_runtime_gap_report")
    gate_dashboard = _read_json(gate_dashboard_report_path, missing, "gate_dashboard_report")
    canonical_backtest = _read_json(
        canonical_backtest_manifest_path,
        missing,
        "canonical_backtest_manifest",
    )

    matrix = [
        _long_short_line(bar_replay, leakage, long_short, perp, paper_runtime, canonical_backtest),
        _high_octane_line(bar_replay, leakage, attack, perp, paper_runtime),
        _high_yield_line(bar_replay, high_yield, perp, paper_runtime),
    ]
    global_gate = _global_gate(perp, paper_runtime, exchange_gap, gate_dashboard)
    blockers = _blockers(missing=missing, matrix=matrix, global_gate=global_gate, observe_health=observe_health)
    paper_runtime_health = _paper_runtime_health(paper_runtime)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "aggregation_batch_id": aggregation_batch_id or "",
        "status": "blocked_research_only" if blockers else "complete_research_only",
        "decision": "btc_strategy_promotion_readiness_blocked_no_paper_no_live" if blockers else "btc_strategy_promotion_readiness_research_only_no_paper_no_live",
        "scope": "btc_strategy_non_data_gate_matrix_for_current_research_lines",
        "code_commit": _git_commit(),
        "input": {
            "bar_replay_report": _portable_path(bar_replay_report_path),
            "leakage_audit_report": _portable_path(leakage_audit_report_path),
            "long_short_observer_report": _portable_path(long_short_observer_report_path),
            "attack_observer_report": _portable_path(attack_observer_report_path),
            "high_yield_followup_report": _portable_path(high_yield_followup_report_path),
            "observe_only_health_report": _portable_path(observe_only_health_report_path),
            "perp_execution_evidence_report": _portable_path(perp_execution_evidence_report_path),
            "paper_runtime_replay_report": _portable_path(paper_runtime_replay_report_path),
            "exchange_runtime_gap_report": _portable_path(exchange_runtime_gap_report_path),
            "gate_dashboard_report": _portable_path(gate_dashboard_report_path),
            "canonical_backtest_manifest": _portable_path(canonical_backtest_manifest_path),
        },
        "summary": {
            "strategy_line_count": len(matrix),
            "ready_for_paper_count": sum(1 for row in matrix if row["line_decision"] == "ready_for_manual_paper_gate_review"),
            "blocked_line_count": sum(1 for row in matrix if row["line_decision"] != "ready_for_manual_paper_gate_review"),
            "bar_replay_hard_fail_count": _int(_nested(bar_replay, "summary", "check_fail_count")),
            "leakage_hard_fail_count": _int(_nested(leakage, "summary", "check_fail_count")),
            "leakage_warn_count": _int(_nested(leakage, "summary", "check_warn_count")),
            "perp_execution_blocker_count": len(_list(perp.get("blockers"))),
            "paper_runtime_blocker_count": len(_list(paper_runtime.get("blockers"))),
            **paper_runtime_health,
            "observe_only_health_status": observe_health.get("status") or "missing",
            "observe_only_health_blocker_count": len(_list(observe_health.get("blockers"))),
            "exchange_runtime_gap_blocker_count": len(_list(exchange_gap.get("blockers"))),
            "gate_dashboard_status": gate_dashboard.get("status"),
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
        "matrix": matrix,
        "global_gate": global_gate,
        "deferred_data_note": {
            "status": "deferred_by_user",
            "meaning_cn": "本轮不继续补数据；数据覆盖、liquidation、mark/index 和 L2 深度证据缺口保留为 fail-closed 阻断。",
            "known_data_related_blockers": [
                blocker
                for blocker in global_gate["blockers"]
                if any(token in blocker for token in ["data", "liquidation", "depth", "slippage", "mark", "index", "coverage"])
            ],
        },
        "gate": _gate(),
        "guardrails": _guardrails(),
        "blockers": blockers,
        "outputs": {
            "json": _portable_path(report_path),
            "matrix_csv": _portable_path(matrix_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(matrix_path, matrix)
    _write_text(markdown_path, render_btc_strategy_promotion_readiness_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _long_short_line(
    bar_replay: Mapping[str, Any],
    leakage: Mapping[str, Any],
    observer: Mapping[str, Any],
    perp: Mapping[str, Any],
    paper_runtime: Mapping[str, Any],
    canonical_backtest: Mapping[str, Any],
) -> dict[str, Any]:
    progress = observer.get("observation_progress", {}) if isinstance(observer.get("observation_progress"), Mapping) else {}
    lock = observer.get("holdout_lock", {}) if isinstance(observer.get("holdout_lock"), Mapping) else {}
    audit = leakage.get("long_short_top5_audit", {}) if isinstance(leakage.get("long_short_top5_audit"), Mapping) else {}
    line_blockers = []
    if _int(_nested(bar_replay, "long_short_top5_bar_replay", "current_shift_violation_count")):
        line_blockers.append("long_short_bar_replay_shift_violation")
    if _int(_nested(bar_replay, "long_short_top5_bar_replay", "derivatives_available_time_violation_count")):
        line_blockers.append("long_short_derivatives_visibility_violation")
    line_blockers.extend(_observation_blockers("long_short_top5", progress, lock))
    line_blockers.extend(_execution_blockers(perp, paper_runtime))
    identity_binding = _long_short_identity_binding(
        backtest=canonical_backtest,
        observer=observer,
        paper_runtime=paper_runtime,
    )
    line_blockers.extend(identity_binding["blockers"])
    paper_runtime_health = _paper_runtime_health(paper_runtime)
    return {
        "strategy_line": "long_short_donchian_top5",
        "research_bucket": "稳健线",
        "bar_replay_status": _pass_fail(_int(_nested(bar_replay, "summary", "check_fail_count")) == 0, "passed", "failed"),
        "future_visibility_status": _nested(bar_replay, "long_short_top5_bar_replay", "verdict") or "unknown",
        "overfit_status": audit.get("overfit_verdict") or "not_available",
        "holdout_lock_enforced": bool(lock.get("lock_config_present")),
        "observe_only_violation_count": _int(lock.get("observe_only_violation_count")),
        "selection_use_blocked_by_lock": bool(lock.get("selection_use_blocked_by_lock")),
        "observation_count": _int(progress.get("observation_count")),
        "observation_days": _int(progress.get("observation_days")),
        "minimum_30d_complete": _int(progress.get("observation_days")) >= 30,
        "minimum_60d_complete": _int(progress.get("observation_days")) >= 60,
        "paper_runtime_status": paper_runtime.get("status") or "missing",
        **paper_runtime_health,
        "perp_execution_status": perp.get("status") or "missing",
        "strategy_identity_binding": identity_binding,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "line_decision": "observe_only_collecting_not_paper_ready" if line_blockers else "ready_for_manual_paper_gate_review",
        "line_blockers": line_blockers,
    }


def _long_short_identity_binding(
    *,
    backtest: Mapping[str, Any],
    observer: Mapping[str, Any],
    paper_runtime: Mapping[str, Any],
) -> dict[str, Any]:
    observed = backtest.get("strategy_identity", {}) if isinstance(backtest.get("strategy_identity"), Mapping) else {}
    candidate_id = str(observed.get("candidate_id") or "")
    blockers: list[str] = []
    expected: Mapping[str, Any] = {}
    if not observed:
        blockers.append("long_short_canonical_backtest_identity_missing")
    else:
        try:
            expected = btc_strategy_registry.get("long_short_donchian_top5", candidate_id).identity()
        except BTCStrategyIdentityError:
            blockers.append("long_short_canonical_backtest_candidate_not_in_frozen_registry")
        if expected:
            blockers.extend(compare_strategy_identities(expected, observed))

    observer_candidates = {
        str(row.get("candidate_id") or "")
        for row in _list_of_mappings(observer.get("latest_observations"))
    }
    if candidate_id and candidate_id not in observer_candidates:
        blockers.append("long_short_backtest_candidate_not_in_observe_only_top5")

    runtime_identities = _list_of_mappings(paper_runtime.get("strategy_identities"))
    runtime_identity = next(
        (
            row
            for row in runtime_identities
            if str(row.get("strategy_id") or "") == "long_short_donchian_top5"
            and str(row.get("candidate_id") or "") == candidate_id
        ),
        {},
    )
    if candidate_id and not runtime_identity:
        blockers.append("long_short_backtest_candidate_not_bound_in_runtime_replay")
    elif expected and runtime_identity:
        blockers.extend(compare_strategy_identities(expected, runtime_identity))

    checks = {
        "canonical_backtest_identity_present": bool(observed),
        "candidate_registered_and_params_frozen": bool(expected) and not compare_strategy_identities(expected, observed),
        "candidate_present_in_observe_only_top5": bool(candidate_id) and candidate_id in observer_candidates,
        "candidate_bound_in_runtime_replay": bool(runtime_identity),
        "backtest_promotion_credit_allowed": backtest.get("promotion_credit_allowed") is True,
    }
    if backtest and backtest.get("promotion_credit_allowed") is not True:
        blockers.append("long_short_canonical_backtest_promotion_credit_not_allowed")
    return {
        "status": "matched_research_only" if not blockers else "blocked_identity_mismatch",
        "expected_identity": dict(expected),
        "backtest_identity": dict(observed),
        "runtime_identity": dict(runtime_identity),
        "checks": checks,
        "blockers": sorted(set(blockers)),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _high_octane_line(
    bar_replay: Mapping[str, Any],
    leakage: Mapping[str, Any],
    observer: Mapping[str, Any],
    perp: Mapping[str, Any],
    paper_runtime: Mapping[str, Any],
) -> dict[str, Any]:
    progress = observer.get("observation_progress", {}) if isinstance(observer.get("observation_progress"), Mapping) else {}
    lock = observer.get("holdout_lock", {}) if isinstance(observer.get("holdout_lock"), Mapping) else {}
    audit = leakage.get("high_octane_v2_audit", {}) if isinstance(leakage.get("high_octane_v2_audit"), Mapping) else {}
    margin = _float(audit.get("best_margin_over_40pct_threshold"))
    line_blockers = _observation_blockers("high_octane_v2", progress, lock)
    if margin < 0.25:
        line_blockers.append("high_octane_40pct_survival_threshold_boundary_margin_too_small")
    if "high_overfit" in str(audit.get("overfit_verdict", "")):
        line_blockers.append("high_octane_parameter_mining_overfit_risk")
    line_blockers.extend(_execution_blockers(perp, paper_runtime))
    paper_runtime_health = _paper_runtime_health(paper_runtime)
    return {
        "strategy_line": "high_octane_attack_sleeve_v2",
        "research_bucket": "小资金激进滚仓线",
        "bar_replay_status": _pass_fail(_int(_nested(bar_replay, "summary", "check_fail_count")) == 0, "passed_with_model_boundary_warning", "failed"),
        "future_visibility_status": _nested(bar_replay, "high_octane_v2_visibility_replay", "verdict") or "unknown",
        "overfit_status": audit.get("overfit_verdict") or "not_available",
        "best_margin_over_40pct_threshold": margin,
        "holdout_lock_enforced": bool(lock.get("lock_config_present")),
        "observe_only_violation_count": _int(lock.get("observe_only_violation_count")),
        "selection_use_blocked_by_lock": bool(lock.get("selection_use_blocked_by_lock")),
        "observation_count": _int(progress.get("observation_count")),
        "observation_days": _int(progress.get("observation_days")),
        "minimum_30d_complete": _int(progress.get("observation_days")) >= 30,
        "minimum_60d_complete": _int(progress.get("observation_days")) >= 60,
        "paper_runtime_status": paper_runtime.get("status") or "missing",
        **paper_runtime_health,
        "perp_execution_status": perp.get("status") or "missing",
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "line_decision": "high_risk_observe_only_not_paper_ready" if line_blockers else "ready_for_manual_paper_gate_review",
        "line_blockers": line_blockers,
    }


def _high_yield_line(
    bar_replay: Mapping[str, Any],
    followup: Mapping[str, Any],
    perp: Mapping[str, Any],
    paper_runtime: Mapping[str, Any],
) -> dict[str, Any]:
    step1 = followup.get("step_1_daily_observation_automation", {}) if isinstance(followup.get("step_1_daily_observation_automation"), Mapping) else {}
    progress = _high_yield_observation_progress(step1)
    lock = step1.get("holdout_lock", {}) if isinstance(step1.get("holdout_lock"), Mapping) else {}
    loss = followup.get("step_2_loss_control_v3_narrow_experiment", {}) if isinstance(followup.get("step_2_loss_control_v3_narrow_experiment"), Mapping) else {}
    bar_summary = bar_replay.get("high_yield_v2_bar_replay", {}) if isinstance(bar_replay.get("high_yield_v2_bar_replay"), Mapping) else {}
    line_blockers = []
    if _int(bar_summary.get("row_count")) <= 0:
        line_blockers.append("high_yield_v2_not_in_current_bar_replay_visibility_audit")
    if _int(bar_summary.get("derivatives_available_time_violation_count")):
        line_blockers.append("high_yield_v2_derivatives_visibility_violation")
    if _int(bar_summary.get("model_boundary_row_count")):
        line_blockers.append("high_yield_v2_bar_replay_model_boundary_requires_execution_replay")
    line_blockers.extend(_observation_blockers("high_yield_v2", progress, lock))
    if _int(loss.get("retained_count")) == 0:
        line_blockers.append("high_yield_v2_loss_control_v3_retained_count_zero")
    line_blockers.extend(_execution_blockers(perp, paper_runtime))
    paper_runtime_health = _paper_runtime_health(paper_runtime)
    return {
        "strategy_line": "high_yield_donchian_v2",
        "research_bucket": "小资金高收益线",
        "bar_replay_status": "covered_with_model_boundary_warning" if _int(bar_summary.get("row_count")) > 0 else "not_covered_by_current_bar_replay_audit",
        "future_visibility_status": bar_summary.get("verdict") or "holdout_locked_observe_only_but_needs_dedicated_bar_replay",
        "overfit_status": "not_promotable_loss_control_retained_count_zero" if _int(loss.get("retained_count")) == 0 else "needs_review",
        "bar_replay_row_count": _int(bar_summary.get("row_count")),
        "bar_replay_model_boundary_row_count": _int(bar_summary.get("model_boundary_row_count")),
        "bar_replay_prior_exposure_return_violation_count": _int(bar_summary.get("prior_exposure_return_violation_count")),
        "holdout_lock_enforced": bool(lock.get("lock_config_present")),
        "observe_only_violation_count": _int(lock.get("observe_only_violation_count")),
        "selection_use_blocked_by_lock": bool(lock.get("selection_use_blocked_by_lock")),
        "observation_count": _int(progress.get("observation_count")),
        "observation_days": _int(progress.get("observation_days")),
        "minimum_30d_complete": _int(progress.get("observation_days")) >= 30,
        "minimum_60d_complete": _int(progress.get("observation_days")) >= 60,
        "paper_runtime_status": paper_runtime.get("status") or "missing",
        **paper_runtime_health,
        "perp_execution_status": perp.get("status") or "missing",
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "line_decision": "observe_only_diagnostic_not_paper_ready",
        "line_blockers": line_blockers,
    }


def _high_yield_observation_progress(step1: Mapping[str, Any]) -> dict[str, Any]:
    progress = dict(step1.get("observation_progress", {})) if isinstance(step1.get("observation_progress"), Mapping) else {}
    if "observation_count" not in progress:
        progress["observation_count"] = _int(step1.get("observation_count"))
    if "observation_days" not in progress:
        progress["observation_days"] = _observation_days_from_ledger(step1.get("observation_ledger_path"))
    return progress


def _observation_days_from_ledger(path_value: Any) -> int:
    if not path_value:
        return 0
    path = Path(str(path_value))
    if not path.exists():
        return 0
    dates: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        decision_time = row.get("decision_time")
        if isinstance(decision_time, str) and len(decision_time) >= 10:
            dates.add(decision_time[:10])
    return len(dates)


def _global_gate(
    perp: Mapping[str, Any],
    paper_runtime: Mapping[str, Any],
    exchange_gap: Mapping[str, Any],
    gate_dashboard: Mapping[str, Any],
) -> dict[str, Any]:
    blockers = [
        *[f"perp_execution:{item}" for item in _list(perp.get("blockers"))],
        *[f"paper_runtime:{item}" for item in _list(paper_runtime.get("blockers"))],
        *[f"exchange_runtime_gap:{item}" for item in _list(exchange_gap.get("blockers"))],
        *[f"gate_dashboard:{item}" for item in _list(gate_dashboard.get("blockers"))],
    ]
    return {
        "perp_execution_status": perp.get("status") or "missing",
        "paper_runtime_status": paper_runtime.get("status") or "missing",
        "exchange_runtime_gap_status": exchange_gap.get("status") or "missing",
        "gate_dashboard_status": gate_dashboard.get("status") or "missing",
        "blockers": sorted(set(blockers)),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "decision": "global_gate_fail_closed_no_paper_no_live" if blockers else "global_gate_research_only_no_paper_no_live",
    }


def _observation_blockers(line: str, progress: Mapping[str, Any], lock: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not lock.get("lock_config_present"):
        blockers.append(f"{line}_holdout_lock_missing")
    if _int(lock.get("observe_only_violation_count")):
        blockers.append(f"{line}_observe_only_lock_violation")
    if not lock.get("selection_use_blocked_by_lock"):
        blockers.append(f"{line}_selection_use_not_blocked_by_holdout_lock")
    days = _int(progress.get("observation_days"))
    if days < 30:
        blockers.append(f"{line}_forward_observation_under_30d")
    if days < 60:
        blockers.append(f"{line}_forward_observation_under_60d")
    return blockers


def _execution_blockers(perp: Mapping[str, Any], paper_runtime: Mapping[str, Any]) -> list[str]:
    blockers = [f"perp_execution:{item}" for item in _list(perp.get("blockers"))]
    blockers.extend(f"paper_runtime:{item}" for item in _list(paper_runtime.get("blockers")))
    return sorted(set(blockers))


def _paper_runtime_health(paper_runtime: Mapping[str, Any]) -> dict[str, Any]:
    summary = paper_runtime.get("summary", {}) if isinstance(paper_runtime.get("summary"), Mapping) else {}
    return {
        "paper_runtime_health_status": summary.get("paper_runtime_health_status") or "unknown",
        "paper_runtime_current_flat_heartbeat_healthy": summary.get("current_flat_heartbeat_healthy") is True,
        "paper_runtime_trade_execution_evidence_available": summary.get("trade_execution_evidence_available") is True,
        "paper_runtime_trade_execution_evidence_pending_reason": summary.get("trade_execution_evidence_pending_reason"),
        "paper_runtime_non_blocking_pending_conditions": _list(summary.get("non_blocking_pending_conditions")),
    }


def _blockers(
    *,
    missing: Sequence[str],
    matrix: Sequence[Mapping[str, Any]],
    global_gate: Mapping[str, Any],
    observe_health: Mapping[str, Any],
) -> list[str]:
    blockers = [f"missing_input:{item}" for item in missing]
    for row in matrix:
        for item in _list(row.get("line_blockers")):
            blockers.append(f"{row.get('strategy_line')}:{item}")
        if row.get("paper_queue_write_allowed") is not False:
            blockers.append(f"{row.get('strategy_line')}:paper_queue_write_not_false")
        if row.get("live_unlock_allowed") is not False:
            blockers.append(f"{row.get('strategy_line')}:live_unlock_not_false")
    blockers.extend(f"observe_only_health:{item}" for item in _list(observe_health.get("blockers")))
    blockers.extend(_list(global_gate.get("blockers")))
    return sorted(set(blockers))


def render_btc_strategy_promotion_readiness_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# BTC 策略晋级准备度总表",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 策略线数量：{summary.get('strategy_line_count')}",
        f"- 可进入人工 paper 门禁复核数量：{summary.get('ready_for_paper_count')}",
        f"- paper 队列写入：`false`",
        f"- live 解锁：`false`",
        "",
        "## 策略线",
        "",
        "| 策略线 | 桶 | 未来函数/可见性 | 过拟合状态 | 观察天数 | 30天 | 60天 | 结论 |",
        "|---|---|---|---|---:|---|---|---|",
    ]
    for row in report.get("matrix", []):
        lines.append(
            "| {strategy_line} | {research_bucket} | {future_visibility_status} | {overfit_status} | {observation_days} | {d30} | {d60} | {line_decision} |".format(
                strategy_line=row.get("strategy_line"),
                research_bucket=row.get("research_bucket"),
                future_visibility_status=row.get("future_visibility_status"),
                overfit_status=row.get("overfit_status"),
                observation_days=row.get("observation_days"),
                d30="已满" if row.get("minimum_30d_complete") else "未满",
                d60="已满" if row.get("minimum_60d_complete") else "未满",
                line_decision=row.get("line_decision"),
            )
        )
    lines.extend(
        [
            "",
            "## 关键结论",
            "",
            "- Long/Short Donchian Top5：当前没有发现直接未来函数硬失败，但 forward observe 仍不足 30/60 天，不能进 paper。",
            "- High-Octane v2：已经带 holdout observe-only，但 40% 插针剩余本金候选属于压线结果，仍按高过拟合风险处理。",
            "- High-yield v2：已做 observe-only 锁定，但不在当前 bar replay 审计覆盖内，且 loss-control v3 没保留候选。",
            "- 永续执行证据、paper runtime replay、exchange runtime gap 仍 fail-closed；本轮按用户要求不继续补数据。",
            "",
            "## 阻断项",
            "",
        ]
    )
    blockers = report.get("blockers", [])
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers[:80])
        if len(blockers) > 80:
            lines.append(f"- ... 其余 {len(blockers) - 80} 项见 JSON")
    else:
        lines.append("- 无")
    lines.append("")
    return "\n".join(lines)


def _read_json(path: Path, missing: list[str], label: str) -> dict[str, Any]:
    if not path.exists():
        missing.append(label)
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        missing.append(f"{label}_unreadable")
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_strategy_promotion_readiness_safety_status_v1",
        "status": report.get("status"),
        "decision": report.get("decision"),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "strategy_skeleton_generated": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
        "live_order_allowed": False,
        "live_unlock_allowed": False,
        "blockers": list(report.get("blockers", [])),
    }


def _gate() -> dict[str, Any]:
    return {
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "strategy_skeleton_generated": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "live_order_allowed": False,
        "live_unlock_allowed": False,
        "reason": "Readiness review is evidence-only and cannot promote strategies.",
    }


def _guardrails() -> dict[str, Any]:
    return {
        "research_only": True,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _nested(data: Mapping[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(key)
    return cur


def _pass_fail(ok: bool, ok_value: str, fail_value: str) -> str:
    return ok_value if ok else fail_value


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in _list(value) if isinstance(item, Mapping)]


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _csv_value(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    return str(value)


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _git_commit() -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None
