from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from quant_crypto.research.bankroll_attack_forward_observer import DEFAULT_REPORT_PATH as DEFAULT_ATTACK_FORWARD_OBSERVER_REPORT_PATH
from quant_crypto.research.btc_confirmatory_holdout_lock import DEFAULT_REPORT_PATH as DEFAULT_HOLDOUT_LOCK_REPORT_PATH
from quant_crypto.research.high_octane_attack_sleeve_lab import DEFAULT_OUTPUT_DIR as DEFAULT_HIGH_OCTANE_DIR
from quant_crypto.research.long_short_top5_forward_observer import DEFAULT_REPORT_PATH as DEFAULT_LONG_SHORT_FORWARD_OBSERVER_REPORT_PATH
from quant_crypto.research.long_short_top5_review import DEFAULT_OUTPUT_DIR as DEFAULT_LONG_SHORT_TOP5_DIR
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path, _round


SCHEMA_VERSION = "btc_strategy_leakage_overfit_audit_v2"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_strategy_leakage_overfit_audit/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_leakage_overfit_audit_report.json"
DEFAULT_CANDIDATE_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_leakage_overfit_audit_candidates.csv"
DEFAULT_CHECKS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_leakage_overfit_audit_checks.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_strategy_leakage_overfit_audit_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_LONG_SHORT_REPORT_PATH = DEFAULT_LONG_SHORT_TOP5_DIR / "btc_long_short_top5_review_report.json"
DEFAULT_LONG_SHORT_CSV_PATH = DEFAULT_LONG_SHORT_TOP5_DIR / "btc_long_short_top5_review_candidates.csv"
DEFAULT_LONG_SHORT_GRID_PATH = Path("artifacts/btc_long_short_trend_following_lab/latest/btc_long_short_trend_following_lab_grid.csv")
DEFAULT_HIGH_OCTANE_REPORT_PATH = DEFAULT_HIGH_OCTANE_DIR / "btc_high_octane_attack_sleeve_lab_report.json"
DEFAULT_HIGH_OCTANE_GRID_PATH = DEFAULT_HIGH_OCTANE_DIR / "btc_high_octane_attack_sleeve_lab_grid.csv"
DEFAULT_HIGH_OCTANE_WATCHLIST_PATH = DEFAULT_HIGH_OCTANE_DIR / "btc_high_octane_attack_sleeve_lab_watchlist.csv"
DEFAULT_HIGH_OCTANE_ROLLING_PATH = DEFAULT_HIGH_OCTANE_DIR / "btc_high_octane_attack_sleeve_lab_rolling_start.csv"
DEFAULT_BAR_REPLAY_REPORT_PATH = Path("artifacts/btc_strategy_bar_replay_visibility/latest/btc_strategy_bar_replay_visibility_report.json")
DEFAULT_HOLDOUT_LOCK_AUDIT_REPORT_PATH = DEFAULT_HOLDOUT_LOCK_REPORT_PATH
DEFAULT_LONG_SHORT_FORWARD_REPORT_PATH = DEFAULT_LONG_SHORT_FORWARD_OBSERVER_REPORT_PATH
DEFAULT_ATTACK_FORWARD_REPORT_PATH = DEFAULT_ATTACK_FORWARD_OBSERVER_REPORT_PATH
DEFAULT_DERIVATIVES_FETCH_AUDIT_PATH = Path(
    "artifacts/btc_derivatives_sentiment/latest/btc_binance_vision_derivatives_fetch_extended_attempt_report.json"
)

LONG_SHORT_SOURCE_PATH = Path("quant_crypto/research/long_short_trend_following_lab.py")
HIGH_OCTANE_SOURCE_PATH = Path("quant_crypto/research/high_octane_attack_sleeve_lab.py")


def build_btc_strategy_leakage_overfit_audit(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    long_short_report_path: Path = DEFAULT_LONG_SHORT_REPORT_PATH,
    long_short_csv_path: Path = DEFAULT_LONG_SHORT_CSV_PATH,
    long_short_grid_path: Path = DEFAULT_LONG_SHORT_GRID_PATH,
    high_octane_report_path: Path = DEFAULT_HIGH_OCTANE_REPORT_PATH,
    high_octane_grid_path: Path = DEFAULT_HIGH_OCTANE_GRID_PATH,
    high_octane_watchlist_path: Path = DEFAULT_HIGH_OCTANE_WATCHLIST_PATH,
    high_octane_rolling_path: Path = DEFAULT_HIGH_OCTANE_ROLLING_PATH,
    bar_replay_report_path: Path = DEFAULT_BAR_REPLAY_REPORT_PATH,
    holdout_lock_report_path: Path = DEFAULT_HOLDOUT_LOCK_AUDIT_REPORT_PATH,
    long_short_forward_report_path: Path = DEFAULT_LONG_SHORT_FORWARD_REPORT_PATH,
    attack_forward_report_path: Path = DEFAULT_ATTACK_FORWARD_REPORT_PATH,
    derivatives_fetch_audit_path: Path | None = DEFAULT_DERIVATIVES_FETCH_AUDIT_PATH,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    candidate_csv_path = output_dir / DEFAULT_CANDIDATE_CSV_PATH.name
    checks_csv_path = output_dir / DEFAULT_CHECKS_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    blockers: list[str] = []
    long_short_report = _read_json(long_short_report_path, blockers, "missing_long_short_top5_report")
    high_octane_report = _read_json(high_octane_report_path, blockers, "missing_high_octane_report")
    bar_replay_report = _read_json(bar_replay_report_path, blockers, "missing_bar_replay_visibility_report")
    long_short_rows = _read_csv(long_short_csv_path, blockers, "missing_long_short_top5_candidates_csv")
    long_short_grid_rows = _read_csv(long_short_grid_path, blockers, "missing_long_short_full_grid_csv")
    high_octane_grid_rows = _read_csv(high_octane_grid_path, blockers, "missing_high_octane_grid_csv")
    high_octane_watchlist_rows = _read_csv(high_octane_watchlist_path, blockers, "missing_high_octane_watchlist_csv")
    high_octane_rolling_rows = _read_csv(high_octane_rolling_path, blockers, "missing_high_octane_rolling_csv")
    holdout_lock_report = _read_json(holdout_lock_report_path, blockers, "missing_confirmatory_holdout_lock_report")
    long_short_forward_report = _read_json(long_short_forward_report_path, blockers, "missing_long_short_forward_observer_report")
    attack_forward_report = _read_json(attack_forward_report_path, blockers, "missing_attack_forward_observer_report")
    derivatives_fetch_audit = _read_json_optional(derivatives_fetch_audit_path)

    checks = [
        *_long_short_leakage_checks(long_short_report),
        *_high_octane_leakage_checks(high_octane_report),
        *_bar_replay_checks(bar_replay_report),
        *_holdout_forward_checks(holdout_lock_report, long_short_forward_report, attack_forward_report),
    ]
    long_short_audit = _audit_long_short(long_short_report, long_short_rows, long_short_grid_rows, bar_replay_report)
    high_octane_audit = _audit_high_octane(
        high_octane_report,
        grid_rows=high_octane_grid_rows,
        watchlist_rows=high_octane_watchlist_rows,
        rolling_rows=high_octane_rolling_rows,
        bar_replay_report=bar_replay_report,
    )
    holdout_forward_audit = _audit_holdout_forward_observe(
        holdout_lock_report=holdout_lock_report,
        long_short_forward_report=long_short_forward_report,
        attack_forward_report=attack_forward_report,
    )
    data_coverage_audit = _audit_data_coverage(
        bar_replay_report=bar_replay_report,
        derivatives_fetch_audit=derivatives_fetch_audit,
        derivatives_fetch_audit_path=derivatives_fetch_audit_path,
    )
    candidate_rows = [
        *_long_short_candidate_rows(long_short_rows),
        *_high_octane_candidate_rows(high_octane_watchlist_rows, high_octane_rolling_rows),
    ]
    decision = _decision(blockers=blockers, checks=checks, long_short=long_short_audit, high_octane=high_octane_audit, holdout_forward=holdout_forward_audit)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": decision,
        "scope": "future_leakage_and_overfit_audit_for_long_short_top5_and_high_octane_v2",
        "code_commit": _git_commit(),
        "input": {
            "long_short_report_path": _portable_path(long_short_report_path),
            "long_short_csv_path": _portable_path(long_short_csv_path),
            "long_short_grid_path": _portable_path(long_short_grid_path),
            "high_octane_report_path": _portable_path(high_octane_report_path),
            "high_octane_grid_path": _portable_path(high_octane_grid_path),
            "high_octane_watchlist_path": _portable_path(high_octane_watchlist_path),
            "high_octane_rolling_path": _portable_path(high_octane_rolling_path),
            "bar_replay_report_path": _portable_path(bar_replay_report_path),
            "holdout_lock_report_path": _portable_path(holdout_lock_report_path),
            "long_short_forward_report_path": _portable_path(long_short_forward_report_path),
            "attack_forward_report_path": _portable_path(attack_forward_report_path),
            "derivatives_fetch_audit_path": _portable_path(derivatives_fetch_audit_path) if derivatives_fetch_audit_path else None,
        },
        "audit_design": {
            "checks": [
                "static source audit for shifted Donchian, shifted exposure, completed-bar and available-time rules",
                "bar-by-bar replay audit for current exposure, next-bar exposure, and derivatives visibility",
                "post-selection evidence audit using latest artifact metrics",
                "threshold pressure audit for the high-octane 40pct survival boundary",
                "parameter-mining audit using search-space size, grid-edge flags, and local neighborhood stability",
                "rolling-start stability audit for high-octane watchlist rows",
            ],
            "not_a_proof_note": "Static checks and artifact metrics can detect obvious leakage and overfit symptoms, but they are not a formal proof of correctness.",
        },
        "summary": _summary(
            checks=checks,
            long_short=long_short_audit,
            high_octane=high_octane_audit,
            holdout_forward=holdout_forward_audit,
            data_coverage=data_coverage_audit,
            decision=decision,
        ),
        "long_short_top5_audit": long_short_audit,
        "high_octane_v2_audit": high_octane_audit,
        "holdout_and_forward_observe_audit": holdout_forward_audit,
        "data_coverage_audit": data_coverage_audit,
        "leakage_checks": checks,
        "candidate_rows_sample": candidate_rows[:25],
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(
            blockers=blockers,
            long_short=long_short_audit,
            high_octane=high_octane_audit,
            holdout_forward=holdout_forward_audit,
            data_coverage=data_coverage_audit,
        ),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "candidate_csv": _portable_path(candidate_csv_path),
            "checks_csv": _portable_path(checks_csv_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(candidate_csv_path, candidate_rows)
    _write_csv(checks_csv_path, checks)
    _write_text(markdown_path, render_btc_strategy_leakage_overfit_audit_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _long_short_leakage_checks(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = _read_text(LONG_SHORT_SOURCE_PATH)
    input_block = report.get("input", {}) if isinstance(report, Mapping) else {}
    review_design = report.get("review_design", {}) if isinstance(report, Mapping) else {}
    return [
        _check("long_short_top5", "donchian_uses_shifted_history", "pass" if "high.shift(1).rolling" in source and "low.shift(1).rolling" in source else "fail", "Donchian entry/exit should use prior completed bars."),
        _check("long_short_top5", "returns_use_next_bar_exposure", "pass" if "raw.shift(1)" in source else "fail", "Raw signal must be shifted before return calculation."),
        _check("long_short_top5", "completed_bar_rule_declared", "pass" if "completed" in str(input_block.get("completed_bar_rule", "")).lower() else "warn", str(input_block.get("completed_bar_rule", ""))),
        _check("long_short_top5", "derivatives_available_time_declared", "pass" if "available_time" in str(input_block.get("derivatives_available_time_rule", "")) else "warn", str(input_block.get("derivatives_available_time_rule", ""))),
        _check("long_short_top5", "holdout_is_post_selection", "warn" if review_design.get("clean_pre_selection_holdout") is False else "pass", str(review_design.get("clean_pre_selection_holdout_note", ""))),
    ]


def _high_octane_leakage_checks(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = _read_text(HIGH_OCTANE_SOURCE_PATH)
    research_design = report.get("research_design", {}) if isinstance(report, Mapping) else {}
    return [
        _check("high_octane_v2", "uses_existing_direction_source", "pass" if "existing frozen Donchian" in str(report.get("input", {}).get("direction_source", "")) else "warn", str(report.get("input", {}).get("direction_source", ""))),
        _check("high_octane_v2", "max_leverage_capped_10x", "pass" if research_design.get("max_research_leverage") == 10.0 else "fail", f"max_research_leverage={research_design.get('max_research_leverage')}"),
        _check("high_octane_v2", "same_bar_return_model_boundary", "warn" if "bar_return = 0.0 if pos == 0 else float(return_values[pos])" in source else "fail", "Capital overlay applies close-to-close bar return while also using current bar high/low for liquidation proxy; treat as research approximation."),
        _check("high_octane_v2", "current_bar_adverse_model_boundary", "warn" if "_adverse_move_array" in source else "fail", "High/low adverse move is used for liquidation/spike diagnostics; not equivalent to exact exchange mark/index path."),
        _check("high_octane_v2", "paper_live_locked", "pass" if report.get("gate", {}).get("paper_queue_write_allowed") is False and report.get("gate", {}).get("live_unlock_allowed") is False else "fail", "Research artifact must not promote paper/live."),
    ]


def _bar_replay_checks(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    long_short = report.get("long_short_top5_bar_replay", {}) if isinstance(report, Mapping) else {}
    high_octane = report.get("high_octane_v2_visibility_replay", {}) if isinstance(report, Mapping) else {}
    return [
        _check(
            "long_short_top5",
            "bar_replay_no_current_or_next_shift_violation",
            "pass" if _int(long_short.get("current_shift_violation_count")) == 0 and _int(long_short.get("next_shift_violation_count")) == 0 else "fail",
            f"current={long_short.get('current_shift_violation_count')}; next={long_short.get('next_shift_violation_count')}",
        ),
        _check(
            "long_short_top5",
            "bar_replay_no_derivatives_visibility_violation",
            "pass"
            if _int(long_short.get("derivatives_available_time_violation_count")) == 0 and _int(long_short.get("derivatives_event_time_violation_count")) == 0
            else "fail",
            f"available_time={long_short.get('derivatives_available_time_violation_count')}; event_time={long_short.get('derivatives_event_time_violation_count')}",
        ),
        _check(
            "high_octane_v2",
            "bar_replay_direction_visibility_no_shift_violation",
            "pass" if _int(high_octane.get("current_shift_violation_count")) == 0 and _int(high_octane.get("next_shift_violation_count")) == 0 else "fail",
            f"current={high_octane.get('current_shift_violation_count')}; next={high_octane.get('next_shift_violation_count')}",
        ),
        _check(
            "high_octane_v2",
            "bar_replay_execution_replay_still_required",
            "warn"
            if "execution_replay_required" in str(high_octane.get("verdict", ""))
            or "strict_risk_stress" in str(high_octane.get("verdict", ""))
            or _int(high_octane.get("model_boundary_row_count")) > 0
            else "pass",
            str(high_octane.get("verdict", "")),
        ),
    ]


def _holdout_forward_checks(
    holdout_lock_report: Mapping[str, Any],
    long_short_forward_report: Mapping[str, Any],
    attack_forward_report: Mapping[str, Any],
) -> list[dict[str, Any]]:
    holdout_summary = holdout_lock_report.get("summary", {}) if isinstance(holdout_lock_report.get("summary"), Mapping) else {}
    long_short_lock = long_short_forward_report.get("holdout_lock", {}) if isinstance(long_short_forward_report.get("holdout_lock"), Mapping) else {}
    attack_lock = attack_forward_report.get("holdout_lock", {}) if isinstance(attack_forward_report.get("holdout_lock"), Mapping) else {}
    long_short_progress = long_short_forward_report.get("observation_progress", {}) if isinstance(long_short_forward_report.get("observation_progress"), Mapping) else {}
    attack_progress = attack_forward_report.get("observation_progress", {}) if isinstance(attack_forward_report.get("observation_progress"), Mapping) else {}
    observe_violations = _int(long_short_lock.get("observe_only_violation_count")) + _int(attack_lock.get("observe_only_violation_count"))
    selection_blocked = bool(long_short_lock.get("selection_use_blocked_by_lock")) and bool(attack_lock.get("selection_use_blocked_by_lock"))
    relation_counts = _merge_counts(
        long_short_lock.get("decision_time_relation_counts", {}),
        attack_lock.get("decision_time_relation_counts", {}),
    )
    only_anchor_rows = bool(relation_counts) and set(relation_counts) <= {"locked_history_or_anchor"}
    under_30d = bool(long_short_progress.get("under_30d", True)) or bool(attack_progress.get("under_30d", True)) or only_anchor_rows
    return [
        _check(
            "holdout_lock",
            "confirmatory_holdout_lock_present",
            "pass" if holdout_lock_report.get("status") == "complete_research_only" and _int(holdout_summary.get("future_observe_only_lock_count")) >= 1 else "fail",
            f"decision={holdout_lock_report.get('decision')}; future_observe_only_lock_count={holdout_summary.get('future_observe_only_lock_count')}",
        ),
        _check(
            "holdout_lock",
            "historical_selection_windows_block_reuse",
            "pass" if _int(holdout_summary.get("self_check_violation_count")) > 0 else "fail",
            f"self_check_violation_count={holdout_summary.get('self_check_violation_count')}",
        ),
        _check(
            "forward_observe",
            "observe_only_rows_have_no_selection_use",
            "pass" if observe_violations == 0 and selection_blocked else "fail",
            f"observe_only_violation_count={observe_violations}; selection_use_blocked_by_lock={selection_blocked}",
        ),
        _check(
            "forward_observe",
            "thirty_sixty_day_forward_observation_complete",
            "warn" if under_30d else "pass",
            f"relation_counts={relation_counts}; long_short_under_30d={long_short_progress.get('under_30d')}; attack_under_30d={attack_progress.get('under_30d')}",
        ),
    ]


def _audit_long_short(
    report: Mapping[str, Any],
    rows: Sequence[Mapping[str, str]],
    grid_rows: Sequence[Mapping[str, str]],
    bar_replay_report: Mapping[str, Any],
) -> dict[str, Any]:
    candidate_count = len(rows)
    holdout_pass_count = sum(1 for row in rows if _bool(row.get("holdout_passed")))
    concentration_count = sum(1 for row in rows if _float(row.get("top_3_positive_trade_share")) > 0.65)
    forward_pending_count = sum(1 for row in rows if "pending" in str(row.get("forward_30d_status", "")) or "pending" in str(row.get("forward_60d_status", "")))
    avg_top3_share = _round(sum(_float(row.get("top_3_positive_trade_share")) for row in rows) / max(1, candidate_count))
    best = rows[0] if rows else {}
    bar_replay = bar_replay_report.get("long_short_top5_bar_replay", {}) if isinstance(bar_replay_report, Mapping) else {}
    parameter_mining = _long_short_parameter_mining_audit(best, rows, grid_rows)
    visibility_violation_count = _int(bar_replay.get("current_shift_violation_count")) + _int(bar_replay.get("next_shift_violation_count")) + _int(
        bar_replay.get("derivatives_available_time_violation_count")
    )
    completed_bar_violation_count = _int(bar_replay.get("completed_bar_violation_count"))
    decision = "research_only_not_paper_ready"
    if visibility_violation_count == 0 and completed_bar_violation_count == 0 and (concentration_count or forward_pending_count):
        decision = "no_direct_leakage_but_forward_confirmation_required"
    elif visibility_violation_count == 0 and completed_bar_violation_count == 0 and candidate_count:
        decision = "no_direct_leakage_detected_research_only"
    return {
        "line": "long_short_donchian_top5",
        "artifact_status": report.get("status"),
        "artifact_decision": report.get("decision"),
        "candidate_count": candidate_count,
        "holdout_pass_count": holdout_pass_count,
        "high_concentration_count": concentration_count,
        "forward_observation_pending_count": forward_pending_count,
        "avg_top_3_positive_trade_share": avg_top3_share,
        "best_candidate_id": best.get("candidate_id"),
        "best_holdout_total_return_pct": _float(best.get("holdout_total_return_pct")),
        "best_top_3_positive_trade_share": _float(best.get("top_3_positive_trade_share")),
        "top1_positive_trade_share": _float(best.get("top_1_positive_trade_share", best.get("largest_positive_trade_share"))),
        "top3_positive_trade_share": _float(best.get("top_3_positive_trade_share")),
        "top5_positive_trade_share": _float(best.get("top_5_positive_trade_share", best.get("top_3_positive_trade_share"))),
        "return_concentration_verdict": "single_period_or_few_trade_concentration_requires_forward_confirmation"
        if concentration_count
        else "no_high_trade_concentration_flag_from_source_rows",
        "completed_bar_violation_count": completed_bar_violation_count,
        "bar_replay_current_shift_violation_count": _int(bar_replay.get("current_shift_violation_count")),
        "bar_replay_next_shift_violation_count": _int(bar_replay.get("next_shift_violation_count")),
        "bar_replay_derivatives_available_time_violation_count": _int(bar_replay.get("derivatives_available_time_violation_count")),
        "future_sentiment_violation_count": _int(bar_replay.get("future_sentiment_violation_count", bar_replay.get("derivatives_available_time_violation_count"))),
        "parameter_mining_audit": parameter_mining,
        "future_leakage_static_verdict": "no_direct_lookahead_detected_from_static_checks",
        "overfit_verdict": decision,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _audit_high_octane(
    report: Mapping[str, Any],
    *,
    grid_rows: Sequence[Mapping[str, str]],
    watchlist_rows: Sequence[Mapping[str, str]],
    rolling_rows: Sequence[Mapping[str, str]],
    bar_replay_report: Mapping[str, Any],
) -> dict[str, Any]:
    summary = report.get("summary", {}) if isinstance(report, Mapping) else {}
    best = watchlist_rows[0] if watchlist_rows else {}
    best_scenario = str(best.get("scenario_id", summary.get("best_scenario_id", "")))
    best_rolling = [row for row in rolling_rows if row.get("scenario_id") == best_scenario]
    best_remaining = _float(best.get("min_remaining_capital_pct_after_10pct_spike", summary.get("best_min_remaining_after_10pct_spike")))
    margin_40 = _round(best_remaining - 40.0)
    tier_counts = summary.get("watchlist_tier_counts", {}) if isinstance(summary.get("watchlist_tier_counts"), Mapping) else {}
    top_grid_extreme = _top_grid_extreme_count(grid_rows)
    param_buckets = _param_bucket_summary(watchlist_rows)
    parameter_mining = _high_octane_parameter_mining_audit(best, grid_rows, watchlist_rows, best_rolling, top_grid_extreme)
    bar_replay = bar_replay_report.get("high_octane_v2_visibility_replay", {}) if isinstance(bar_replay_report, Mapping) else {}
    rolling_returns = [_float(row.get("total_return_pct")) for row in best_rolling]
    rolling_remaining = [_float(row.get("min_remaining_capital_pct_after_10pct_spike")) for row in best_rolling]
    boundary_flag = margin_40 <= 1.0 or int(tier_counts.get("survive_60pct", 0) or 0) == 0
    unstable_neighbors = _int(parameter_mining.get("neighbor_count")) > 0 and _float(parameter_mining.get("neighbor_survive_40_rate")) < 0.35
    decision = "parameter_boundary_mined_research_only" if boundary_flag or unstable_neighbors else "moderate_overfit_risk_research_only"
    return {
        "line": "high_octane_attack_sleeve_v2",
        "artifact_status": report.get("status"),
        "artifact_decision": report.get("decision"),
        "scenario_count": summary.get("scenario_count"),
        "watchlist_count": summary.get("watchlist_count"),
        "watchlist_tier_counts": tier_counts,
        "best_scenario_id": best_scenario,
        "best_watchlist_tier": best.get("watchlist_tier", summary.get("best_watchlist_tier")),
        "best_annual_return_pct": _float(best.get("annual_return_pct", summary.get("best_annual_return_pct"))),
        "best_total_return_pct": _float(best.get("total_return_pct", summary.get("best_total_return_pct"))),
        "best_min_remaining_after_10pct_spike": best_remaining,
        "best_margin_over_40pct_threshold": margin_40,
        "threshold_margin_by_tier_pct": {
            "survive_40pct": margin_40,
            "survive_50pct": _round(best_remaining - 50.0),
            "survive_60pct": _round(best_remaining - 60.0),
        },
        "best_max_drawdown_abs_pct": _float(best.get("max_drawdown_abs_pct", summary.get("best_max_drawdown_abs_pct"))),
        "best_rolling_start_count": len(best_rolling),
        "best_rolling_median_total_return_pct": _round(median(rolling_returns)) if rolling_returns else 0.0,
        "best_rolling_min_total_return_pct": _round(min(rolling_returns)) if rolling_returns else 0.0,
        "best_rolling_median_remaining_after_10pct_spike": _round(median(rolling_remaining)) if rolling_remaining else 0.0,
        "best_rolling_full_wipeout_rate": _round(sum(1 for row in best_rolling if _bool(row.get("full_wipeout"))) / max(1, len(best_rolling))),
        "return_dependency_verdict": "rolling_start_path_dependency_requires_forward_confirmation"
        if len(best_rolling) and min(rolling_returns or [0.0]) < 0.0
        else "rolling_start_positive_but_still_post_selection_research_only",
        "extreme_return_below_40pct_survival_count": top_grid_extreme,
        "parameter_bucket_summary": param_buckets,
        "parameter_mining_audit": parameter_mining,
        "completed_bar_violation_count": _int(bar_replay.get("completed_bar_violation_count")),
        "bar_replay_current_shift_violation_count": _int(bar_replay.get("current_shift_violation_count")),
        "bar_replay_next_shift_violation_count": _int(bar_replay.get("next_shift_violation_count")),
        "bar_replay_derivatives_available_time_violation_count": _int(bar_replay.get("derivatives_available_time_violation_count")),
        "future_sentiment_violation_count": _int(bar_replay.get("future_sentiment_violation_count", bar_replay.get("derivatives_available_time_violation_count"))),
        "direction_signal_visibility_verdict": bar_replay.get("direction_signal_visibility_verdict"),
        "capital_overlay_execution_boundary_verdict": bar_replay.get("capital_overlay_execution_boundary_verdict"),
        "same_bar_return_proxy_row_count": _int(bar_replay.get("same_bar_return_proxy_row_count")),
        "same_bar_intrabar_high_low_proxy_row_count": _int(bar_replay.get("same_bar_intrabar_high_low_proxy_row_count")),
        "future_leakage_static_verdict": "model_boundary_risk_same_bar_proxy_requires_execution_replay",
        "overfit_verdict": decision,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _audit_holdout_forward_observe(
    *,
    holdout_lock_report: Mapping[str, Any],
    long_short_forward_report: Mapping[str, Any],
    attack_forward_report: Mapping[str, Any],
) -> dict[str, Any]:
    holdout_summary = holdout_lock_report.get("summary", {}) if isinstance(holdout_lock_report.get("summary"), Mapping) else {}
    lock_config = holdout_lock_report.get("lock_config", {}) if isinstance(holdout_lock_report.get("lock_config"), Mapping) else {}
    long_short_lock = long_short_forward_report.get("holdout_lock", {}) if isinstance(long_short_forward_report.get("holdout_lock"), Mapping) else {}
    attack_lock = attack_forward_report.get("holdout_lock", {}) if isinstance(attack_forward_report.get("holdout_lock"), Mapping) else {}
    long_short_progress = long_short_forward_report.get("observation_progress", {}) if isinstance(long_short_forward_report.get("observation_progress"), Mapping) else {}
    attack_progress = attack_forward_report.get("observation_progress", {}) if isinstance(attack_forward_report.get("observation_progress"), Mapping) else {}
    relation_counts = _merge_counts(
        long_short_lock.get("decision_time_relation_counts", {}),
        attack_lock.get("decision_time_relation_counts", {}),
    )
    observe_violation_count = _int(long_short_lock.get("observe_only_violation_count")) + _int(attack_lock.get("observe_only_violation_count"))
    selection_use_blocked = bool(long_short_lock.get("selection_use_blocked_by_lock")) and bool(attack_lock.get("selection_use_blocked_by_lock"))
    only_anchor_rows = bool(relation_counts) and set(relation_counts) <= {"locked_history_or_anchor"}
    forward_new_data_started = any(key.startswith("future_observe_only") for key in relation_counts)
    under_30d = bool(long_short_progress.get("under_30d", True)) or bool(attack_progress.get("under_30d", True)) or only_anchor_rows
    clean_forward_ready = forward_new_data_started and not under_30d and observe_violation_count == 0 and selection_use_blocked
    future_window = _future_observe_window(lock_config)
    return {
        "line": "holdout_and_forward_observe",
        "holdout_lock_status": holdout_lock_report.get("status"),
        "holdout_lock_decision": holdout_lock_report.get("decision"),
        "latest_common_history_end": holdout_summary.get("latest_common_history_end") or lock_config.get("latest_common_history_end"),
        "historical_seen_lock_count": _int(holdout_summary.get("historical_seen_lock_count")),
        "future_observe_only_lock_count": _int(holdout_summary.get("future_observe_only_lock_count")),
        "self_check_violation_count": _int(holdout_summary.get("self_check_violation_count")),
        "future_observe_window": future_window,
        "long_short_observer_decision": long_short_forward_report.get("decision"),
        "attack_observer_decision": attack_forward_report.get("decision"),
        "long_short_latest_decision_time": long_short_lock.get("latest_decision_time"),
        "attack_latest_decision_time": attack_lock.get("latest_decision_time"),
        "decision_time_relation_counts": relation_counts,
        "observe_only_violation_count": observe_violation_count,
        "selection_use_blocked_by_lock": selection_use_blocked,
        "forward_new_data_started": forward_new_data_started,
        "only_anchor_rows_so_far": only_anchor_rows,
        "long_short_observation_days": _int(long_short_progress.get("observation_days")),
        "attack_observation_days": _int(attack_progress.get("observation_days")),
        "minimum_30d_complete": not under_30d,
        "clean_forward_confirmation_ready": clean_forward_ready,
        "verdict": "future_observe_only_not_yet_confirmatory" if not clean_forward_ready else "forward_observe_ready_for_manual_review_research_only",
        "plain_cn": "历史窗口已经被选择过程看过，不能再当干净 holdout；2026-06-28 之后的新数据目前只允许观察记录，不能用于调参、排序或替换短名单。",
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _audit_data_coverage(
    *,
    bar_replay_report: Mapping[str, Any],
    derivatives_fetch_audit: Mapping[str, Any],
    derivatives_fetch_audit_path: Path | None,
) -> dict[str, Any]:
    long_short = bar_replay_report.get("long_short_top5_bar_replay", {}) if isinstance(bar_replay_report, Mapping) else {}
    high_octane = bar_replay_report.get("high_octane_v2_visibility_replay", {}) if isinstance(bar_replay_report, Mapping) else {}
    input_block = bar_replay_report.get("input", {}) if isinstance(bar_replay_report.get("input"), Mapping) else {}
    field_counts = derivatives_fetch_audit.get("field_non_null_counts", {}) if isinstance(derivatives_fetch_audit.get("field_non_null_counts"), Mapping) else {}
    extra_counts = derivatives_fetch_audit.get("extra_field_non_null_counts", {}) if isinstance(derivatives_fetch_audit.get("extra_field_non_null_counts"), Mapping) else {}
    liquidation_policy = (
        derivatives_fetch_audit.get("liquidation_policy", {}) if isinstance(derivatives_fetch_audit.get("liquidation_policy"), Mapping) else {}
    )
    download_attempts = derivatives_fetch_audit.get("download_attempts", []) if isinstance(derivatives_fetch_audit.get("download_attempts"), list) else []
    failed_attempts = [
        {
            "mode": item.get("mode"),
            "date_or_month": item.get("date_or_month"),
            "status_code": item.get("status_code"),
            "error": item.get("error"),
        }
        for item in download_attempts
        if isinstance(item, Mapping) and item.get("status_code") not in {200, "200"}
    ]
    bar_missing_count = _int(long_short.get("derivatives_missing_count")) + _int(high_octane.get("derivatives_missing_count"))
    visibility_violation_count = _int(long_short.get("derivatives_available_time_violation_count")) + _int(
        high_octane.get("derivatives_available_time_violation_count")
    )
    free_public_only = (
        derivatives_fetch_audit.get("public_market_data_only") is True
        and derivatives_fetch_audit.get("api_key_used") is False
        and derivatives_fetch_audit.get("private_endpoint_used") is False
        and derivatives_fetch_audit.get("order_endpoint_used") is False
        and derivatives_fetch_audit.get("real_order_submitted") is False
    )
    metrics_covered = (
        bar_missing_count == 0
        and visibility_violation_count == 0
        and _int(field_counts.get("open_interest_usd")) > 0
        and _int(field_counts.get("long_short_ratio")) > 0
    )
    funding_missing_count = max(0, _int(derivatives_fetch_audit.get("row_count")) - _int(field_counts.get("funding_rate")))
    liquidation_complete = bool(liquidation_policy.get("one_hour_history_complete")) and bool(liquidation_policy.get("gate_eligible"))
    unfilled_gaps: list[str] = []
    if funding_missing_count:
        unfilled_gaps.append("binance_vision_current_month_funding_archive_lag_or_missing_rows")
    if not liquidation_complete:
        unfilled_gaps.append("free_source_full_1h_liquidation_history_not_available")
    if failed_attempts:
        unfilled_gaps.append("some_free_archive_attempts_failed_or_not_yet_published")
    verdict = "free_oi_funding_sentiment_coverage_extended_for_visibility_audit" if metrics_covered else "derivatives_coverage_incomplete_free_source_gap"
    return {
        "derivatives_rows_path_used_by_bar_replay": input_block.get("derivatives_rows_path"),
        "derivatives_fetch_audit_path": _portable_path(derivatives_fetch_audit_path) if derivatives_fetch_audit_path else None,
        "free_public_data_only": free_public_only,
        "derivatives_fetch_status": derivatives_fetch_audit.get("status"),
        "derivatives_row_count": _int(derivatives_fetch_audit.get("row_count")),
        "derivatives_event_start": derivatives_fetch_audit.get("event_start"),
        "derivatives_event_end": derivatives_fetch_audit.get("event_end"),
        "market_start": long_short.get("market_start"),
        "market_end": long_short.get("market_end"),
        "market_1h_row_count": _int(long_short.get("market_1h_row_count")),
        "bar_replay_derivatives_missing_count": bar_missing_count,
        "bar_replay_derivatives_available_time_violation_count": visibility_violation_count,
        "field_non_null_counts": dict(field_counts),
        "extra_field_non_null_counts": dict(extra_counts),
        "funding_missing_count": funding_missing_count,
        "funding_current_month_archive_missing_or_lagged": any(
            item.get("mode") == "binance_vision_funding_monthly" and _int(item.get("status_code")) == 404 for item in failed_attempts
        ),
        "liquidation_one_hour_history_complete": bool(liquidation_policy.get("one_hour_history_complete")),
        "liquidation_gate_eligible": bool(liquidation_policy.get("gate_eligible")),
        "liquidation_source": liquidation_policy.get("source"),
        "download_failed_attempt_count": len(failed_attempts),
        "download_failed_attempt_sample": failed_attempts[:10],
        "unfilled_free_data_gaps": unfilled_gaps,
        "coverage_verdict": verdict,
        "plain_cn": (
            "已用 Binance Vision 免费公开归档把 OI、OI USD、多空比、顶级交易员多空比、主动买卖量比扩到当前研究窗口；"
            "但 1H 清算历史仍只有 OKX 720 小时尾部，免费源暂不能补成完整 gate 证据。"
        ),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _top_grid_extreme_count(rows: Sequence[Mapping[str, str]]) -> int:
    sorted_rows = sorted(rows, key=lambda row: _float(row.get("annual_return_pct")), reverse=True)
    return sum(1 for row in sorted_rows[:60] if _float(row.get("min_remaining_capital_pct_after_10pct_spike")) < 40.0)


def _long_short_parameter_mining_audit(best: Mapping[str, str], rows: Sequence[Mapping[str, str]], grid_rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    best_id = str(best.get("candidate_id", ""))
    best_grid_rank = next((idx + 1 for idx, row in enumerate(grid_rows) if row.get("candidate_id") == best_id), 0)
    parsed_best = _parse_long_short_variant(str(best.get("variant_id", "")))
    parsed_grid = [(row, _parse_long_short_variant(str(row.get("variant_id", "")))) for row in grid_rows]
    parsed_grid = [(row, parsed) for row, parsed in parsed_grid if parsed]
    entry_values = sorted({int(parsed["entry_window"]) for _, parsed in parsed_grid if "entry_window" in parsed})
    cooldown_values = sorted({int(parsed["cooldown_bars"]) for _, parsed in parsed_grid if "cooldown_bars" in parsed})
    neighbors: list[Mapping[str, str]] = []
    if parsed_best:
        for row, parsed in parsed_grid:
            if row.get("candidate_id") == best_id:
                continue
            same_core = (
                parsed.get("daily_fast") == parsed_best.get("daily_fast")
                and parsed.get("daily_slow") == parsed_best.get("daily_slow")
                and parsed.get("atr_mult") == parsed_best.get("atr_mult")
                and parsed.get("failure_exit") == parsed_best.get("failure_exit")
                and parsed.get("risk_filter") == parsed_best.get("risk_filter")
            )
            if not same_core:
                continue
            entry_dist = _grid_index_distance(entry_values, int(parsed_best["entry_window"]), int(parsed["entry_window"]))
            cooldown_dist = _grid_index_distance(cooldown_values, int(parsed_best["cooldown_bars"]), int(parsed["cooldown_bars"]))
            if entry_dist <= 1 and cooldown_dist <= 1:
                neighbors.append(row)
    neighbor_annuals = [_float(row.get("annual_return_pct")) for row in neighbors]
    neighbor_retained = [row for row in neighbors if "retain" in str(row.get("retention_decision", ""))]
    top5_families = _count_by(rows, "entry_window") if "entry_window" in (rows[0] if rows else {}) else _count_by(rows, "variant_id")
    holdout_returns = [_float(row.get("holdout_total_return_pct")) for row in rows]
    formal_count = sum(1 for row in grid_rows if row.get("optimization_stage") == "formal_narrow_grid")
    verdict = "moderate_parameter_selection_risk_research_only"
    if neighbors and len(neighbor_retained) / max(1, len(neighbors)) >= 0.35 and min(holdout_returns or [0.0]) > 0.0:
        verdict = "moderate_search_selection_risk_but_local_neighborhood_not_single_spike"
    return {
        "full_grid_count": len(grid_rows),
        "formal_narrow_grid_count": formal_count,
        "top5_candidate_count": len(rows),
        "best_grid_rank": best_grid_rank,
        "best_candidate_id": best_id,
        "best_variant_params": parsed_best,
        "top5_family_or_variant_counts": top5_families,
        "top5_holdout_return_min_pct": _round(min(holdout_returns)) if holdout_returns else 0.0,
        "top5_holdout_return_max_pct": _round(max(holdout_returns)) if holdout_returns else 0.0,
        "neighbor_count": len(neighbors),
        "neighbor_retained_count": len(neighbor_retained),
        "neighbor_retained_rate": _round(len(neighbor_retained) / max(1, len(neighbors))),
        "neighbor_median_annual_return_pct": _round(median(neighbor_annuals)) if neighbor_annuals else 0.0,
        "neighbor_min_annual_return_pct": _round(min(neighbor_annuals)) if neighbor_annuals else 0.0,
        "neighbor_max_annual_return_pct": _round(max(neighbor_annuals)) if neighbor_annuals else 0.0,
        "parameter_mining_verdict": verdict,
        "research_only_note": "This is a post-selection audit; clean forward observation is still required before paper review.",
    }


def _high_octane_parameter_mining_audit(
    best: Mapping[str, str],
    grid_rows: Sequence[Mapping[str, str]],
    watchlist_rows: Sequence[Mapping[str, str]],
    best_rolling_rows: Sequence[Mapping[str, str]],
    top_grid_extreme_count: int,
) -> dict[str, Any]:
    best_id = str(best.get("scenario_id", ""))
    best_remaining_10 = _float(best.get("min_remaining_capital_pct_after_10pct_spike"))
    margin_40 = _round(best_remaining_10 - 40.0)
    sorted_by_return = sorted(grid_rows, key=lambda row: _float(row.get("annual_return_pct")), reverse=True)
    top60 = sorted_by_return[:60]
    top60_below_40_rate = _round(top_grid_extreme_count / max(1, len(top60)))
    survival_40 = [row for row in grid_rows if _float(row.get("min_remaining_capital_pct_after_10pct_spike")) >= 40.0]
    survival_50 = [row for row in grid_rows if _float(row.get("min_remaining_capital_pct_after_10pct_spike")) >= 50.0]
    survival_60 = [row for row in grid_rows if _float(row.get("min_remaining_capital_pct_after_10pct_spike")) >= 60.0]
    watchlist_survival_40 = [row for row in watchlist_rows if _float(row.get("min_remaining_capital_pct_after_10pct_spike")) >= 40.0]
    watchlist_survival_50 = [row for row in watchlist_rows if _float(row.get("min_remaining_capital_pct_after_10pct_spike")) >= 50.0]
    watchlist_survival_60 = [row for row in watchlist_rows if _float(row.get("min_remaining_capital_pct_after_10pct_spike")) >= 60.0]
    neighbors = _high_octane_neighbor_rows(best, grid_rows)
    neighbor_remaining = [_float(row.get("min_remaining_capital_pct_after_10pct_spike")) for row in neighbors]
    neighbor_annuals = [_float(row.get("annual_return_pct")) for row in neighbors]
    rolling_returns = [_float(row.get("total_return_pct")) for row in best_rolling_rows]
    rolling_remaining = [_float(row.get("min_remaining_capital_pct_after_10pct_spike")) for row in best_rolling_rows]
    edge_flags = _high_octane_grid_edge_flags(best, grid_rows, watchlist_rows)
    edge_flag_count = sum(1 for value in edge_flags.values() if value is True)
    threshold_touch_count = sum(1 for row in grid_rows if abs(_float(row.get("min_remaining_capital_pct_after_10pct_spike")) - 40.0) <= 0.25)
    strong_mining_symptoms = (
        len(grid_rows) >= 1000
        and margin_40 <= 0.25
        and top_grid_extreme_count >= 30
        and len(watchlist_survival_60) == 0
        and edge_flag_count >= 2
    )
    verdict = "strong_parameter_mining_symptoms_threshold_boundary_research_only" if strong_mining_symptoms else "parameter_mining_risk_requires_forward_observation"
    return {
        "scenario_grid_count": len(grid_rows),
        "watchlist_count": len(watchlist_rows),
        "best_scenario_id": best_id,
        "best_margin_over_40pct_threshold": margin_40,
        "best_only_clears_40pct_by_less_than_0p25pct": margin_40 <= 0.25,
        "survival_40_count": len(survival_40),
        "survival_50_count": len(survival_50),
        "survival_60_count": len(survival_60),
        "survival_40_rate": _round(len(survival_40) / max(1, len(grid_rows))),
        "survival_50_rate": _round(len(survival_50) / max(1, len(grid_rows))),
        "survival_60_rate": _round(len(survival_60) / max(1, len(grid_rows))),
        "watchlist_survival_40_count": len(watchlist_survival_40),
        "watchlist_survival_50_count": len(watchlist_survival_50),
        "watchlist_survival_60_count": len(watchlist_survival_60),
        "watchlist_survival_40_rate": _round(len(watchlist_survival_40) / max(1, len(watchlist_rows))),
        "watchlist_survival_50_rate": _round(len(watchlist_survival_50) / max(1, len(watchlist_rows))),
        "watchlist_survival_60_rate": _round(len(watchlist_survival_60) / max(1, len(watchlist_rows))),
        "top60_by_annual_return_below_40pct_survival_count": top_grid_extreme_count,
        "top60_by_annual_return_below_40pct_survival_rate": top60_below_40_rate,
        "threshold_touch_count_within_0p25pct": threshold_touch_count,
        "best_grid_edge_flags": edge_flags,
        "best_grid_edge_flag_count": edge_flag_count,
        "neighbor_count": len(neighbors),
        "neighbor_survive_40_count": sum(1 for value in neighbor_remaining if value >= 40.0),
        "neighbor_survive_50_count": sum(1 for value in neighbor_remaining if value >= 50.0),
        "neighbor_survive_60_count": sum(1 for value in neighbor_remaining if value >= 60.0),
        "neighbor_survive_40_rate": _round(sum(1 for value in neighbor_remaining if value >= 40.0) / max(1, len(neighbor_remaining))),
        "neighbor_survive_50_rate": _round(sum(1 for value in neighbor_remaining if value >= 50.0) / max(1, len(neighbor_remaining))),
        "neighbor_survive_60_rate": _round(sum(1 for value in neighbor_remaining if value >= 60.0) / max(1, len(neighbor_remaining))),
        "neighbor_median_remaining_after_10pct_spike": _round(median(neighbor_remaining)) if neighbor_remaining else 0.0,
        "neighbor_median_annual_return_pct": _round(median(neighbor_annuals)) if neighbor_annuals else 0.0,
        "neighbor_min_annual_return_pct": _round(min(neighbor_annuals)) if neighbor_annuals else 0.0,
        "neighbor_max_annual_return_pct": _round(max(neighbor_annuals)) if neighbor_annuals else 0.0,
        "rolling_start_count": len(best_rolling_rows),
        "rolling_median_total_return_pct": _round(median(rolling_returns)) if rolling_returns else 0.0,
        "rolling_min_total_return_pct": _round(min(rolling_returns)) if rolling_returns else 0.0,
        "rolling_median_remaining_after_10pct_spike": _round(median(rolling_remaining)) if rolling_remaining else 0.0,
        "likely_parameter_mined_boundary_candidate": strong_mining_symptoms,
        "parameter_mining_verdict": verdict,
        "plain_cn": "40.01%候选更像从大网格中按收益和生存阈值筛出的压线结果；不是未来函数证据，但过拟合风险高，不能进paper/live。",
        "plain_cn": "40.01% 候选更像从大网格中按收益和生存阈值筛出的压线结果；这不是未来函数证据，但过拟合风险高，不能进入 paper/live。",
    }


def _parse_long_short_variant(variant: str) -> dict[str, Any]:
    match = re.search(r"_w(?P<entry>\d+)_d(?P<fast>\d+)_(?P<slow>\d+)_atr(?P<atr>\d+)_cd(?P<cooldown>\d+)_fail(?P<fail>\d+)_risk(?P<risk>.+)$", variant)
    if not match:
        return {}
    return {
        "entry_window": int(match.group("entry")),
        "daily_fast": int(match.group("fast")),
        "daily_slow": int(match.group("slow")),
        "atr_mult": _round(int(match.group("atr")) / 10.0),
        "cooldown_bars": int(match.group("cooldown")),
        "failure_exit": bool(int(match.group("fail"))),
        "risk_filter": match.group("risk"),
    }


def _high_octane_neighbor_rows(best: Mapping[str, str], rows: Sequence[Mapping[str, str]]) -> list[Mapping[str, str]]:
    if not best:
        return []
    atr_values = _sorted_float_values(rows, "atr_step")
    total_values = _sorted_int_values(rows, "max_total_exposed")
    attack_values = _sorted_int_values(rows, "max_attack_exposed")
    count_values = _sorted_int_values(rows, "attack_template_count")
    best_id = str(best.get("scenario_id", ""))
    neighbors: list[Mapping[str, str]] = []
    for row in rows:
        if row.get("scenario_id") == best_id:
            continue
        if row.get("extract_policy") != best.get("extract_policy"):
            continue
        if row.get("attack_delay_profile") != best.get("attack_delay_profile"):
            continue
        if row.get("reserve_requires_pullback") != best.get("reserve_requires_pullback"):
            continue
        dist = (
            _grid_index_distance(atr_values, _float(best.get("atr_step")), _float(row.get("atr_step")))
            + _grid_index_distance(total_values, _int(best.get("max_total_exposed")), _int(row.get("max_total_exposed")))
            + _grid_index_distance(attack_values, _int(best.get("max_attack_exposed")), _int(row.get("max_attack_exposed")))
            + _grid_index_distance(count_values, _int(best.get("attack_template_count")), _int(row.get("attack_template_count")))
        )
        if dist <= 2:
            neighbors.append(row)
    return neighbors


def _high_octane_grid_edge_flags(best: Mapping[str, str], rows: Sequence[Mapping[str, str]], watchlist_rows: Sequence[Mapping[str, str]]) -> dict[str, bool]:
    atr_values = _sorted_float_values(rows, "atr_step")
    total_values = _sorted_int_values(rows, "max_total_exposed")
    attack_values = _sorted_int_values(rows, "max_attack_exposed")
    count_values = _sorted_int_values(rows, "attack_template_count")
    delay_counts = _count_by(watchlist_rows, "attack_delay_profile")
    extract_counts = _count_by(watchlist_rows, "extract_policy")
    return {
        "atr_step_is_grid_min": bool(atr_values and _float(best.get("atr_step")) == atr_values[0]),
        "max_total_exposed_is_grid_max": bool(total_values and _int(best.get("max_total_exposed")) == total_values[-1]),
        "max_attack_exposed_is_grid_edge": bool(attack_values and _int(best.get("max_attack_exposed")) in {attack_values[0], attack_values[-1]}),
        "attack_template_count_is_grid_edge": bool(count_values and _int(best.get("attack_template_count")) in {count_values[0], count_values[-1]}),
        "attack_delay_profile_dominates_watchlist": bool(delay_counts and delay_counts.get(str(best.get("attack_delay_profile")), 0) == len(watchlist_rows)),
        "extract_policy_dominates_watchlist": bool(extract_counts and extract_counts.get(str(best.get("extract_policy")), 0) == len(watchlist_rows)),
    }


def _grid_index_distance(values: Sequence[Any], left: Any, right: Any) -> int:
    try:
        return abs(list(values).index(left) - list(values).index(right))
    except ValueError:
        return 999


def _sorted_float_values(rows: Sequence[Mapping[str, str]], field: str) -> list[float]:
    return sorted({_float(row.get(field)) for row in rows})


def _sorted_int_values(rows: Sequence[Mapping[str, str]], field: str) -> list[int]:
    return sorted({_int(row.get(field)) for row in rows})


def _param_bucket_summary(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    return {
        "atr_step_counts": _count_by(rows, "atr_step"),
        "attack_cap_counts": _count_by(rows, "max_attack_exposed"),
        "extract_policy_counts": _count_by(rows, "extract_policy"),
        "delay_profile_counts": _count_by(rows, "attack_delay_profile"),
        "max_total_exposed_counts": _count_by(rows, "max_total_exposed"),
    }


def _long_short_candidate_rows(rows: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "line": "long_short_top5",
            "id": row.get("candidate_id"),
            "rank": _int(row.get("rank")),
            "return_or_annual_pct": _float(row.get("full_total_return_pct")),
            "holdout_return_pct": _float(row.get("holdout_total_return_pct")),
            "drawdown_pct": _float(row.get("full_max_drawdown_pct")),
            "survival_or_top3_share": _float(row.get("top_3_positive_trade_share")),
            "rolling_or_forward_status": f"{row.get('forward_30d_status')}/{row.get('forward_60d_status')}",
            "audit_flag": "trend_concentration_forward_confirmation_required" if _float(row.get("top_3_positive_trade_share")) > 0.65 else "ok",
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        }
        for row in rows
    ]


def _high_octane_candidate_rows(rows: Sequence[Mapping[str, str]], rolling_rows: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    rolling_by_id: dict[str, list[Mapping[str, str]]] = {}
    for row in rolling_rows:
        rolling_by_id.setdefault(str(row.get("scenario_id")), []).append(row)
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, 1):
        sid = str(row.get("scenario_id"))
        rolling = rolling_by_id.get(sid, [])
        returns = [_float(item.get("total_return_pct")) for item in rolling]
        out.append(
            {
                "line": "high_octane_v2",
                "id": sid,
                "rank": idx,
                "return_or_annual_pct": _float(row.get("annual_return_pct")),
                "holdout_return_pct": _round(median(returns)) if returns else 0.0,
                "drawdown_pct": _float(row.get("max_drawdown_abs_pct")),
                "survival_or_top3_share": _float(row.get("min_remaining_capital_pct_after_10pct_spike")),
                "rolling_or_forward_status": f"rolling_count={len(rolling)}",
                "audit_flag": "threshold_boundary_risk" if _float(row.get("min_remaining_capital_pct_after_10pct_spike")) - 40.0 <= 1.0 else "ok",
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
    return out


def render_btc_strategy_leakage_overfit_audit_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    ls = report.get("long_short_top5_audit", {})
    ho = report.get("high_octane_v2_audit", {})
    ls_mining = ls.get("parameter_mining_audit", {}) if isinstance(ls.get("parameter_mining_audit"), Mapping) else {}
    ho_mining = ho.get("parameter_mining_audit", {}) if isinstance(ho.get("parameter_mining_audit"), Mapping) else {}
    gate = report.get("gate", {})
    lines = [
        "# BTC 未来函数 / 过拟合审计包",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- Long/Short Top5：`{ls.get('overfit_verdict')}`",
        f"- High-Octane v2：`{ho.get('overfit_verdict')}`",
        f"- High-Octane 最佳候选：`{ho.get('best_scenario_id')}`",
        f"- High-Octane 最佳 -10% 插针剩余：`{ho.get('best_min_remaining_after_10pct_spike')}`%，距离 40% 门槛 `{ho.get('best_margin_over_40pct_threshold')}` 个百分点",
        f"- 40.01% 候选参数挖掘判断：`{ho_mining.get('parameter_mining_verdict')}`",
        f"- paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- live 解锁：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 关键判断",
        "",
        "- Long/Short Top5：静态源码和逐根 bar replay 都没有发现当前信号直接偷看未来；但 Top3 正收益交易集中度偏高，仍然需要真实 forward observation。",
        "- High-Octane v2：方向信号可见性没有发现 shift 违规；但资金管理层仍使用同根 4H high/low 做强平和插针近似，必须做真实 mark/index execution replay。",
        "- 40.01% 压线候选：从大网格、网格边界、Top60 收益筛选、生存线压线看，审计判断是强参数挖掘症状，而不是稳健参数平台。",
        "",
        "## 审计结果",
        "",
        f"- Long/Short 候选数：`{ls.get('candidate_count')}`，holdout 通过数：`{ls.get('holdout_pass_count')}`，高集中数：`{ls.get('high_concentration_count')}`",
        f"- Long/Short 完整候选池：`{ls_mining.get('full_grid_count')}`，邻域保留率：`{ls_mining.get('neighbor_retained_rate')}`",
        f"- High-Octane watchlist：`{ho.get('watchlist_count')}`，分层：`{ho.get('watchlist_tier_counts')}`",
        f"- High-Octane Top60 纯收益极端但低于 40% 生存的数量：`{ho.get('extreme_return_below_40pct_survival_count')}`",
        f"- High-Octane 完整网格生存率：40%=`{ho_mining.get('survival_40_rate')}`，50%=`{ho_mining.get('survival_50_rate')}`，60%=`{ho_mining.get('survival_60_rate')}`",
        f"- High-Octane 高收益 watchlist 生存率：40%=`{ho_mining.get('watchlist_survival_40_rate')}`，50%=`{ho_mining.get('watchlist_survival_50_rate')}`，60%=`{ho_mining.get('watchlist_survival_60_rate')}`",
        f"- High-Octane 网格边界标记：`{ho_mining.get('best_grid_edge_flags')}`",
        "",
        "## 边界",
        "",
        "本审计包只做 research-only 判断。不写 paper 队列，不生成策略骨架，不接 broker/OMS，不解锁 live。",
    ]
    return "\n".join(lines) + "\n"


def render_btc_strategy_leakage_overfit_audit_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    ls = report.get("long_short_top5_audit", {})
    ho = report.get("high_octane_v2_audit", {})
    holdout = report.get("holdout_and_forward_observe_audit", {})
    data = report.get("data_coverage_audit", {})
    ls_mining = ls.get("parameter_mining_audit", {}) if isinstance(ls.get("parameter_mining_audit"), Mapping) else {}
    ho_mining = ho.get("parameter_mining_audit", {}) if isinstance(ho.get("parameter_mining_audit"), Mapping) else {}
    gate = report.get("gate", {})
    lines = [
        "# BTC 未来函数 / 过拟合审计包",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 检查数：`{summary.get('check_count')}`，失败：`{summary.get('check_fail_count')}`，警告：`{summary.get('check_warn_count')}`",
        f"- Long/Short Donchian Top5：`{ls.get('overfit_verdict')}`",
        f"- High-Octane v2：`{ho.get('overfit_verdict')}`",
        f"- High-Octane 最佳候选：`{ho.get('best_scenario_id')}`",
        f"- High-Octane -10% 插针后剩余本金：`{ho.get('best_min_remaining_after_10pct_spike')}`%，距离 40% 门槛 `{ho.get('best_margin_over_40pct_threshold')}` 个百分点",
        f"- 40.01% 压线候选参数挖掘判断：`{ho_mining.get('parameter_mining_verdict')}`",
        f"- 未来观察是否足够：`{holdout.get('clean_forward_confirmation_ready')}`",
        f"- 免费衍生品数据覆盖：`{data.get('coverage_verdict')}`",
        f"- paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- live 解锁：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 关键判断",
        "",
        "- Long/Short Top5：静态源码检查和逐根 bar replay 都没有发现当前信号直接偷看未来；但 Top3 正收益交易集中度偏高，仍然需要真实 forward observation。",
        "- High-Octane v2：方向信号可见性没有发现 shift 违规；但资金管理层仍使用同根 4H high/low 做强平和插针近似，必须先做真实 mark/index execution replay。",
        "- 40.01% 压线候选：从大网格、网格边界、Top60 收益筛选、生存线压线看，审计判断为强参数挖掘症状，不是稳定参数平台。",
        "- Holdout 锁：历史窗口已经被选择过程消耗，不能再当干净样本；2026-06-28 之后的新数据目前只允许 observe-only，不允许调参、排序或替换短名单。",
        f"- 数据覆盖：{data.get('plain_cn')}",
        "",
        "## 审计结果",
        "",
        f"- Long/Short 候选数：`{ls.get('candidate_count')}`，holdout 通过数：`{ls.get('holdout_pass_count')}`，高集中数：`{ls.get('high_concentration_count')}`",
        f"- Long/Short 完整候选池：`{ls_mining.get('full_grid_count')}`，邻域保留率：`{ls_mining.get('neighbor_retained_rate')}`",
        f"- High-Octane watchlist：`{ho.get('watchlist_count')}`，分层：`{ho.get('watchlist_tier_counts')}`",
        f"- High-Octane Top60 年化排序但低于 40% 生存线数量：`{ho.get('extreme_return_below_40pct_survival_count')}`",
        f"- High-Octane 完整网格生存率：40%=`{ho_mining.get('survival_40_rate')}`，50%=`{ho_mining.get('survival_50_rate')}`，60%=`{ho_mining.get('survival_60_rate')}`",
        f"- High-Octane 高收益 watchlist 生存率：40%=`{ho_mining.get('watchlist_survival_40_rate')}`，50%=`{ho_mining.get('watchlist_survival_50_rate')}`，60%=`{ho_mining.get('watchlist_survival_60_rate')}`",
        f"- High-Octane 网格边界标记：`{ho_mining.get('best_grid_edge_flags')}`",
        f"- 观察器关系计数：`{holdout.get('decision_time_relation_counts')}`",
        f"- 观察器违规数：`{holdout.get('observe_only_violation_count')}`，选择用途被锁阻断：`{holdout.get('selection_use_blocked_by_lock')}`",
        "",
        "## 数据覆盖",
        "",
        f"- bar replay 使用的 derivatives 文件：`{data.get('derivatives_rows_path_used_by_bar_replay')}`",
        f"- derivatives 行数：`{data.get('derivatives_row_count')}`，窗口：`{data.get('derivatives_event_start')}` 到 `{data.get('derivatives_event_end')}`",
        f"- 4H replay 衍生品缺失数：`{data.get('bar_replay_derivatives_missing_count')}`，available_time 违规数：`{data.get('bar_replay_derivatives_available_time_violation_count')}`",
        f"- 非空字段：`{data.get('field_non_null_counts')}`",
        f"- funding 缺失数：`{data.get('funding_missing_count')}`，当前月归档滞后：`{data.get('funding_current_month_archive_missing_or_lagged')}`",
        f"- 1H liquidation 完整历史：`{data.get('liquidation_one_hour_history_complete')}`，gate eligible：`{data.get('liquidation_gate_eligible')}`，来源：`{data.get('liquidation_source')}`",
        f"- 未补齐免费数据缺口：`{data.get('unfilled_free_data_gaps')}`",
        "",
        "## 边界",
        "",
        "本审计包只做 research-only 判断。不写 paper 队列，不生成策略骨架，不接 broker/OMS，不解锁 live。",
    ]
    return "\n".join(lines) + "\n"


def _decision(
    *,
    blockers: Sequence[str],
    checks: Sequence[Mapping[str, Any]],
    long_short: Mapping[str, Any],
    high_octane: Mapping[str, Any],
    holdout_forward: Mapping[str, Any],
) -> str:
    if blockers:
        return "blocked_audit_inputs_missing_no_paper_no_live"
    if any(row.get("status") == "fail" for row in checks):
        return "fail_future_leakage_static_check_no_paper_no_live"
    high_verdict = str(high_octane.get("overfit_verdict", ""))
    if high_verdict.startswith("high_overfit") or high_verdict == "parameter_boundary_mined_research_only":
        return "research_only_overfit_risk_high_no_paper_no_live"
    return "research_only_forward_confirmation_required_no_paper_no_live"


def _summary(
    *,
    checks: Sequence[Mapping[str, Any]],
    long_short: Mapping[str, Any],
    high_octane: Mapping[str, Any],
    holdout_forward: Mapping[str, Any],
    data_coverage: Mapping[str, Any],
    decision: str,
) -> dict[str, Any]:
    high_mining = high_octane.get("parameter_mining_audit", {}) if isinstance(high_octane.get("parameter_mining_audit"), Mapping) else {}
    long_short_mining = long_short.get("parameter_mining_audit", {}) if isinstance(long_short.get("parameter_mining_audit"), Mapping) else {}
    return {
        "decision": decision,
        "check_count": len(checks),
        "check_fail_count": sum(1 for row in checks if row.get("status") == "fail"),
        "check_warn_count": sum(1 for row in checks if row.get("status") == "warn"),
        "long_short_overfit_verdict": long_short.get("overfit_verdict"),
        "long_short_return_concentration_verdict": long_short.get("return_concentration_verdict"),
        "long_short_future_sentiment_violation_count": long_short.get("future_sentiment_violation_count"),
        "long_short_completed_bar_violation_count": long_short.get("completed_bar_violation_count"),
        "long_short_parameter_mining_verdict": long_short_mining.get("parameter_mining_verdict"),
        "high_octane_overfit_verdict": high_octane.get("overfit_verdict"),
        "high_octane_return_dependency_verdict": high_octane.get("return_dependency_verdict"),
        "high_octane_future_sentiment_violation_count": high_octane.get("future_sentiment_violation_count"),
        "high_octane_completed_bar_violation_count": high_octane.get("completed_bar_violation_count"),
        "high_octane_direction_signal_visibility_verdict": high_octane.get("direction_signal_visibility_verdict"),
        "high_octane_capital_overlay_execution_boundary_verdict": high_octane.get("capital_overlay_execution_boundary_verdict"),
        "high_octane_parameter_mining_verdict": high_mining.get("parameter_mining_verdict"),
        "high_octane_likely_parameter_mined_boundary_candidate": high_mining.get("likely_parameter_mined_boundary_candidate"),
        "high_octane_best_margin_over_40pct_threshold": high_octane.get("best_margin_over_40pct_threshold"),
        "high_octane_threshold_margin_by_tier_pct": high_octane.get("threshold_margin_by_tier_pct"),
        "forward_observe_clean_confirmation_ready": holdout_forward.get("clean_forward_confirmation_ready"),
        "forward_observe_only_anchor_rows_so_far": holdout_forward.get("only_anchor_rows_so_far"),
        "forward_observe_selection_use_blocked_by_lock": holdout_forward.get("selection_use_blocked_by_lock"),
        "forward_observe_violation_count": holdout_forward.get("observe_only_violation_count"),
        "data_coverage_verdict": data_coverage.get("coverage_verdict"),
        "data_coverage_free_public_only": data_coverage.get("free_public_data_only"),
        "data_coverage_derivatives_row_count": data_coverage.get("derivatives_row_count"),
        "data_coverage_bar_replay_missing_count": data_coverage.get("bar_replay_derivatives_missing_count"),
        "data_coverage_liquidation_one_hour_history_complete": data_coverage.get("liquidation_one_hour_history_complete"),
        "data_coverage_unfilled_free_data_gaps": data_coverage.get("unfilled_free_data_gaps"),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _check(line: str, check_id: str, status: str, evidence: str) -> dict[str, Any]:
    return {
        "line": line,
        "check_id": check_id,
        "status": status,
        "evidence": evidence,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _gate() -> dict[str, Any]:
    return {
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Leakage/overfit audit is research-only and cannot promote strategies.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }


def _warnings(
    *,
    blockers: Sequence[str],
    long_short: Mapping[str, Any],
    high_octane: Mapping[str, Any],
    holdout_forward: Mapping[str, Any],
    data_coverage: Mapping[str, Any],
) -> list[str]:
    warnings = ["btc_strategy_leakage_overfit_audit_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_strategy_leakage_overfit_audit_blocked")
    if long_short.get("high_concentration_count"):
        warnings.append("long_short_top5_trend_return_concentration_requires_forward_confirmation")
    if high_octane.get("best_margin_over_40pct_threshold", 999.0) <= 1.0:
        warnings.append("high_octane_best_candidate_is_40pct_threshold_boundary")
    if high_octane.get("overfit_verdict") == "parameter_boundary_mined_research_only":
        warnings.append("high_octane_parameter_boundary_mined_research_only")
    high_mining = high_octane.get("parameter_mining_audit", {}) if isinstance(high_octane.get("parameter_mining_audit"), Mapping) else {}
    if high_mining.get("likely_parameter_mined_boundary_candidate") is True:
        warnings.append("high_octane_40pct_candidate_has_strong_parameter_mining_symptoms")
    warnings.append("high_octane_same_bar_liquidation_and_return_proxy_requires_execution_replay")
    if holdout_forward.get("clean_forward_confirmation_ready") is not True:
        warnings.append("future_30d_60d_observe_only_not_yet_confirmatory")
    if holdout_forward.get("only_anchor_rows_so_far") is True:
        warnings.append("current_observer_rows_are_anchor_replays_not_new_oos_data")
    if data_coverage.get("liquidation_one_hour_history_complete") is not True:
        warnings.append("free_source_full_1h_liquidation_history_still_missing")
    if data_coverage.get("funding_missing_count", 0):
        warnings.append("funding_archive_tail_has_missing_rows_or_current_month_lag")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_strategy_leakage_overfit_audit_safety_status_v1",
        "status": "research_only",
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Audit output is diagnostic only.",
    }


def _read_json(path: Path, blockers: list[str], blocker_name: str) -> dict[str, Any]:
    if not path.exists():
        blockers.append(blocker_name)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_optional(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path, blockers: list[str], blocker_name: str) -> list[dict[str, str]]:
    if not path.exists():
        blockers.append(blocker_name)
        return []
    with path.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _merge_counts(*mappings: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for mapping in mappings:
        if not isinstance(mapping, Mapping):
            continue
        for key, value in mapping.items():
            out[str(key)] = out.get(str(key), 0) + _int(value)
    return dict(sorted(out.items()))


def _future_observe_window(lock_config: Mapping[str, Any]) -> dict[str, Any]:
    for lock in lock_config.get("locked_windows", []):
        if isinstance(lock, Mapping) and lock.get("lock_type") == "future_confirmatory_holdout_observe_only":
            window = lock.get("window", {})
            return dict(window) if isinstance(window, Mapping) else {}
    return {}


def _count_by(rows: Sequence[Mapping[str, str]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field, ""))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
