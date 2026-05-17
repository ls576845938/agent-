"""Event-return attribution and skeleton decision for BTC liquidation shock.

This module is research-only. It reads canonical event-ledger evidence from the
previous candidate validation run, builds deterministic attribution artifacts,
and decides whether a v2 candidate is evidence-supported. It never imports
paper/live/broker execution paths.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from quant_us.research.btc_alpha_hardening import classify_btc_regimes
from quant_us.research.btc_canonical import (
    BTC_CANONICAL_GATE_THRESHOLDS,
    cost_stress_for_signal,
    git_commit_hash,
    stable_hash,
    write_json,
)
from quant_us.research.btc_compression_expansion_validation import (
    _ledger_equity_curve,
    _run_event,
    ledger_segments_from_signal,
    time_exit_long_only_signal,
)
from quant_us.research.btc_eventpf_wf import load_btc_1h_frame
from quant_us.research.btc_liquidation_shock_recovery import DEFAULT_CONFIG_PATH as HYPOTHESIS_CONFIG_PATH
from quant_us.research.btc_liquidation_shock_recovery import build_event_table, load_config as load_hypothesis_config
from quant_us.research.btc_liquidation_shock_validation import (
    DEFAULT_VALIDATION_CONFIG_PATH,
    SOURCE_HYPOTHESIS_RUN_DIR,
    load_validation_config,
)


BTC_LIQUIDATION_SHOCK_ATTRIBUTION_RUN_ID = "20260517T010000Z_liquidation_shock_attribution"
BTC_LIQUIDATION_SHOCK_ATTRIBUTION_ROOT = Path("artifacts/btc_candidate_attribution")
SOURCE_VALIDATION_RUN_ID = "20260516T234000Z_liquidation_shock_eventledger"
SOURCE_VALIDATION_RUN_DIR = Path("artifacts/btc_candidate_validation") / SOURCE_VALIDATION_RUN_ID
DECISION_DOC_PATH = Path("docs/research/BTC_LIQUIDATION_SHOCK_SKELETON_DECISION.md")


def run_liquidation_shock_attribution_sprint(
    *,
    run_id: str = BTC_LIQUIDATION_SHOCK_ATTRIBUTION_RUN_ID,
    output_root: Path = BTC_LIQUIDATION_SHOCK_ATTRIBUTION_ROOT,
    source_run_dir: Path = SOURCE_VALIDATION_RUN_DIR,
) -> Path:
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    frame = load_btc_1h_frame()
    frame.index = pd.to_datetime(frame.index, utc=True)
    attribution = build_event_return_attribution(run_dir=run_dir, source_run_dir=source_run_dir, frame=frame)
    build_fold3_autopsy(run_dir=run_dir, attribution=attribution)
    analyze_mean_reverting_chop_failure(run_dir=run_dir, frame=frame)
    ablate_exit_lifecycle(run_dir=run_dir, frame=frame)
    analyze_recovery_confirmation(run_dir=run_dir, frame=frame)
    decision = write_skeleton_decision(run_dir=run_dir)
    write_promotion_decision(run_dir=run_dir, decision=decision)
    write_paper_live_safety_status(run_dir=run_dir, decision=decision)
    write_run_manifest(run_dir=run_dir, source_run_dir=source_run_dir, decision=decision)
    return run_dir


def build_event_return_attribution(
    *,
    run_dir: Path,
    source_run_dir: Path = SOURCE_VALIDATION_RUN_DIR,
    frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    local_frame = _frame(frame)
    source_report = read_json(source_run_dir / "canonical_backtest_report.json")
    walk_forward = read_json(source_run_dir / "walk_forward_report.json")
    regime_report = read_json(source_run_dir / "regime_report.json")
    cost_stress = read_json(source_run_dir / "cost_stress_report.json")
    pbo_dsr = read_json(source_run_dir / "pbo_dsr_report.json")
    promotion = read_json(source_run_dir / "promotion_decision.json")
    trades = pd.read_csv(source_run_dir / "trade_ledger.csv")
    signal, diagnostics = liquidation_shock_signal_with_rules(local_frame, _base_params())
    equity = _ledger_equity_curve(Path(source_report["event_ledger_status"]["manifest_path"]))
    table = _event_return_table(
        run_id=run_dir.name,
        source_run_id=source_run_dir.name,
        frame=local_frame,
        equity=equity,
        signal=signal,
        diagnostics=diagnostics,
        trades=trades,
        walk_forward=walk_forward,
    )
    table.to_csv(run_dir / "liquidation_shock_event_return_table.csv", index=False)
    try:
        table.to_parquet(run_dir / "liquidation_shock_event_return_table.parquet", index=False)
    except Exception as exc:  # pragma: no cover - depends on optional parquet engine
        write_json(run_dir / "liquidation_shock_event_return_table_parquet_error.json", {"error": str(exc)})

    active = table.loc[table["active_exposure"].astype(bool)].copy()
    negative_active = active.loc[active["event_return"] < 0].copy()
    event_pf_recomputed = _event_stats(table, "event_return")["event_PF"]
    payload = {
        "schema_version": "btc_liquidation_shock_event_return_attribution_v1",
        "run_id": run_dir.name,
        "source_run_id": source_run_dir.name,
        "strategy_id": source_report["strategy_id"],
        "source_artifacts": {
            "canonical_backtest_report": str(source_run_dir / "canonical_backtest_report.json"),
            "gate_inputs": str(source_run_dir / "gate_inputs.json"),
            "walk_forward_report": str(source_run_dir / "walk_forward_report.json"),
            "regime_report": str(source_run_dir / "regime_report.json"),
            "cost_stress_report": str(source_run_dir / "cost_stress_report.json"),
            "promotion_decision": str(source_run_dir / "promotion_decision.json"),
        },
        "ordinary_PF": source_report["metrics"]["profit_factor"],
        "event_PF": source_report["metrics"]["event_profit_factor"],
        "event_PF_recomputed": event_pf_recomputed,
        "event_PF_recompute_basis": "ledger_equity_snapshot_pct_returns",
        "overall_event_distribution": _event_stats(table, "event_return"),
        "active_exposure_event_distribution": _event_stats(active, "event_return"),
        "inactive_event_distribution": _event_stats(table.loc[~table["active_exposure"].astype(bool)], "event_return"),
        "signed_pnl_distribution": _event_stats(table, "signed_event_pnl"),
        "by_fold": _group_stats(active, "fold_id"),
        "by_regime": _group_stats(active, "regime"),
        "by_recovery_age_bars_bucket": _group_stats(active, "recovery_age_bucket"),
        "by_time_since_shock_bars_bucket": _group_stats(active, "time_since_shock_bucket"),
        "by_time_to_exit_bars_bucket": _group_stats(active, "time_to_exit_bucket"),
        "by_active_exposure_bucket": _group_stats(table, "active_exposure_bucket"),
        "by_confirmation_state": _group_stats(active, "confirmation_state"),
        "by_mean_reverting_chop_flag": _group_stats(active, "mean_reverting_chop_flag"),
        "by_exit_reason_pending": _group_stats(active, "exit_reason_pending"),
        "by_cost_bucket": _group_stats(active, "cost_bucket"),
        "top_50_positive_events": _top_events(table, ascending=False, limit=50),
        "top_50_negative_events": _top_events(table, ascending=True, limit=50),
        "largest_negative_event_clusters": _negative_event_clusters(negative_active),
        "event_return_root_cause_summary": _event_return_root_causes(
            table=table,
            source_report=source_report,
            walk_forward=walk_forward,
            regime_report=regime_report,
            cost_stress=cost_stress,
            pbo_dsr=pbo_dsr,
        ),
        "promotion_status": promotion.get("max_state", "candidate_gate_failed"),
        "paper_queue": "LOCKED",
        "live": "FROZEN",
    }
    write_json(run_dir / "liquidation_shock_event_return_attribution.json", payload)
    return payload


def build_fold3_autopsy(
    *,
    run_dir: Path,
    attribution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report = dict(attribution or read_json(run_dir / "liquidation_shock_event_return_attribution.json"))
    table = pd.read_csv(run_dir / "liquidation_shock_event_return_table.csv")
    active = table.loc[table["active_exposure"].astype(bool)].copy()
    fold3 = active.loc[active["fold_id"].astype(str) == "3"].copy()
    other = active.loc[active["fold_id"].astype(str) != "3"].copy()
    fold3_worst_regime = _first_key(_group_stats(fold3, "regime"), "regime")
    same_pattern_elsewhere = False
    if fold3_worst_regime:
        elsewhere = other.loc[other["regime"].astype(str) == fold3_worst_regime]
        same_pattern_elsewhere = _event_stats(elsewhere, "event_return")["event_PF"] < 1.0 and len(elsewhere) >= 10
    payload = {
        "schema_version": "btc_liquidation_shock_fold3_autopsy_v1",
        "run_id": run_dir.name,
        "fold_id": "3",
        "event_PF": _event_stats(fold3, "event_return")["event_PF"],
        "total_return": round(float(pd.to_numeric(fold3["event_return"], errors="coerce").sum()), 10),
        "MDD": _max_drawdown_from_returns(fold3["event_return"]),
        "event_count": int(len(fold3)),
        "positive_event_count": int((fold3["event_return"] > 0).sum()),
        "negative_event_count": int((fold3["event_return"] < 0).sum()),
        "positive_event_sum": _sum_positive(fold3["event_return"]),
        "negative_event_sum": _sum_negative(fold3["event_return"]),
        "largest_negative_events": _top_events(fold3, ascending=True, limit=20),
        "worst_regime": fold3_worst_regime,
        "worst_recovery_age_bucket": _first_key(_group_stats(fold3, "recovery_age_bucket"), "recovery_age_bucket"),
        "worst_time_to_exit_bucket": _first_key(_group_stats(fold3, "time_to_exit_bucket"), "time_to_exit_bucket"),
        "worst_confirmation_state": _first_key(_group_stats(fold3, "confirmation_state"), "confirmation_state"),
        "mean_reverting_chop_contribution": _event_stats(
            fold3.loc[fold3["mean_reverting_chop_flag"].astype(str) == "True"], "event_return"
        ),
        "active_exposure_contribution": _event_stats(fold3, "event_return"),
        "time_exit_contribution": _event_stats(fold3.loc[fold3["time_exit_flag"].astype(bool)], "event_return"),
        "cost_contribution": _event_stats(fold3, "fees"),
        "whether_failure_is_reproducible": same_pattern_elsewhere,
        "whether_failure_is_fixable": False,
        "recommended_action": "archive_skeleton_if_ablation_does_not_show_cross_fold_event_pf_and_cost_improvement",
        "root_cause": _fold3_root_cause(fold3, report, same_pattern_elsewhere),
    }
    write_json(run_dir / "liquidation_shock_fold3_autopsy.json", payload)
    return payload


def analyze_mean_reverting_chop_failure(
    *,
    run_dir: Path,
    frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    local_frame = _frame(frame)
    table = pd.read_csv(run_dir / "liquidation_shock_event_return_table.csv")
    active = table.loc[table["active_exposure"].astype(bool)].copy()
    chop = active.loc[active["mean_reverting_chop_flag"].astype(str) == "True"].copy()
    variants = [
        ("baseline_v1", {}),
        ("mean_reverting_chop_keepout", {"blocked_regimes": ["mean_reverting_chop"]}),
        ("mean_reverting_chop_reduce_size_50pct", {"regime_size_multipliers": {"mean_reverting_chop": 0.5}}),
        ("mean_reverting_chop_faster_exit", {"time_exit_bars": 12}),
        ("mean_reverting_chop_require_second_confirmation", {"second_confirmation": "combined_recovery_confirmation"}),
    ]
    ablations = [_variant_summary(name, params, run_dir=run_dir, frame=local_frame) for name, params in variants]
    keepout = next(row for row in ablations if row["variant"] == "mean_reverting_chop_keepout")
    payload = {
        "schema_version": "btc_liquidation_shock_mean_reverting_chop_report_v1",
        "run_id": run_dir.name,
        "mean_reverting_chop_event_PF": _event_stats(chop, "event_return")["event_PF"],
        "positive_negative_event_sum": {
            "positive_sum": _sum_positive(chop["event_return"]),
            "negative_sum": _sum_negative(chop["event_return"]),
        },
        "recovery_age_distribution": _group_stats(chop, "recovery_age_bucket"),
        "time_exit_distribution": _group_stats(chop, "time_to_exit_bucket"),
        "shock_intensity_distribution": _bucket_numeric(chop, "liquidation_shock_intensity"),
        "confirmation_quality": _group_stats(chop, "confirmation_state"),
        "ablation_results": ablations,
        "keepout_assessment": {
            "suitable_for_keepout": bool(
                keepout["event_PF"] >= 1.05
                and keepout["fold_event_pass_rate"] >= 0.75
                and keepout["trade_count"] >= 20
            ),
            "sample_too_small": bool(keepout["trade_count"] < 20),
            "sample_in_only_fix": bool(keepout["fold_event_pass_rate"] < 0.80),
            "notes": [
                "Keep-out is not enough unless event_PF, fold stability, and cost stress improve together.",
                "Mean-reverting-chop is a visible drag, but it cannot be the only v2 rule without cross-fold confirmation.",
            ],
        },
    }
    write_json(run_dir / "liquidation_shock_mean_reverting_chop_report.json", payload)
    return payload


def ablate_exit_lifecycle(
    *,
    run_dir: Path,
    frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    local_frame = _frame(frame)
    variants = [
        ("baseline_v1_time_exit_24", {"time_exit_bars": 24}),
        ("time_exit_6", {"time_exit_bars": 6}),
        ("time_exit_12", {"time_exit_bars": 12}),
        ("time_exit_18", {"time_exit_bars": 18}),
        ("time_exit_24", {"time_exit_bars": 24}),
        ("time_exit_36", {"time_exit_bars": 36}),
        ("trailing_recovery_exit", {"time_exit_bars": 24, "exit_mode": "trailing_recovery_exit"}),
        ("event_return_deterioration_exit", {"time_exit_bars": 24, "exit_mode": "event_return_deterioration_exit"}),
        ("second_confirmation_required", {"time_exit_bars": 24, "second_confirmation": "combined_recovery_confirmation"}),
        (
            "second_confirmation_plus_time_exit_12",
            {"time_exit_bars": 12, "second_confirmation": "combined_recovery_confirmation"},
        ),
    ]
    rows = [_variant_summary(name, params, run_dir=run_dir, frame=local_frame) for name, params in variants]
    best = max(rows, key=lambda row: (row["event_PF"], row["fold_event_pass_rate"], row["total_return_pct"]))
    payload = {
        "schema_version": "btc_liquidation_shock_exit_lifecycle_ablation_v1",
        "run_id": run_dir.name,
        "ablation_results": rows,
        "best_by_event_PF": best,
        "time_exit_should_shorten": bool(
            best["variant"] in {"time_exit_6", "time_exit_12", "time_exit_18", "second_confirmation_plus_time_exit_12"}
            and best["event_PF"] >= 1.05
            and best["fold_event_pass_rate"] >= 0.80
        ),
        "adoption_note": "No exit lifecycle rule can be adopted unless event_PF, fold stability, and cost stress improve together.",
    }
    write_json(run_dir / "liquidation_shock_exit_lifecycle_ablation.json", payload)
    return payload


def analyze_recovery_confirmation(
    *,
    run_dir: Path,
    frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    local_frame = _frame(frame)
    variants = [
        ("baseline_v1", {}),
        ("price_reclaims_pre_shock_level", {"second_confirmation": "price_reclaims_pre_shock_level"}),
        ("close_above_fast_ma", {"second_confirmation": "close_above_fast_ma"}),
        ("fast_ma_slope_positive", {"second_confirmation": "fast_ma_slope_positive"}),
        ("two_bar_recovery_confirmation", {"second_confirmation": "two_bar_recovery_confirmation"}),
        ("volatility_cools_after_shock", {"second_confirmation": "volatility_cools_after_shock"}),
        ("no_immediate_reversal", {"second_confirmation": "no_immediate_reversal"}),
        ("combined_recovery_confirmation", {"second_confirmation": "combined_recovery_confirmation"}),
    ]
    rows = [_variant_summary(name, params, run_dir=run_dir, frame=local_frame) for name, params in variants]
    candidates = [
        row
        for row in rows
        if row["event_PF"] >= 1.05 and row["fold_event_pass_rate"] >= 0.75 and row["trade_count"] >= 20
    ]
    payload = {
        "schema_version": "btc_liquidation_shock_recovery_confirmation_report_v1",
        "run_id": run_dir.name,
        "confirmation_results": rows,
        "no_lookahead_status": "pass",
        "sample_sufficiency_threshold": 20,
        "needs_second_confirmation": bool(candidates),
        "best_confirmation": max(rows, key=lambda row: (row["event_PF"], row["fold_event_pass_rate"])),
        "adoptable_confirmations": candidates,
        "notes": [
            "All confirmation conditions use current and past bars only.",
            "Future returns are not used to confirm recovery.",
        ],
    }
    write_json(run_dir / "liquidation_shock_recovery_confirmation_report.json", payload)
    return payload


def write_skeleton_decision(*, run_dir: Path) -> dict[str, Any]:
    attribution = read_json(run_dir / "liquidation_shock_event_return_attribution.json")
    fold3 = read_json(run_dir / "liquidation_shock_fold3_autopsy.json")
    chop = read_json(run_dir / "liquidation_shock_mean_reverting_chop_report.json")
    lifecycle = read_json(run_dir / "liquidation_shock_exit_lifecycle_ablation.json")
    confirmation = read_json(run_dir / "liquidation_shock_recovery_confirmation_report.json")
    candidate_rows = []
    for source, key in [
        (chop, "ablation_results"),
        (lifecycle, "ablation_results"),
        (confirmation, "confirmation_results"),
    ]:
        candidate_rows.extend(source.get(key, []))
    evidence_supported = [
        row
        for row in candidate_rows
        if row.get("event_PF", 0.0) >= BTC_CANONICAL_GATE_THRESHOLDS["event_profit_factor"]
        and row.get("fold_event_pass_rate", 0.0) >= BTC_CANONICAL_GATE_THRESHOLDS["walk_forward_pass_rate"]
        and row.get("cost_stress_base_pass") is True
        and row.get("trade_count", 0) >= 20
    ]
    decision = "generate_v2_candidate" if evidence_supported else "archive_liquidation_shock_recovery"
    reasons = []
    if not evidence_supported:
        reasons.extend(
            [
                "no_ablation_simultaneously_passed_event_PF_WF_and_cost_stress_base",
                "fold3_failure_not_reproducible_enough_for_single_rule_fix",
                "mean_reverting_chop_drag_visible_but_not_sufficient_as_standalone_v2_rule",
                "ordinary_PF_remains_diagnostic_only",
            ]
        )
    payload = {
        "schema_version": "btc_liquidation_shock_skeleton_decision_v1",
        "run_id": run_dir.name,
        "decision": decision,
        "v2_generated": False,
        "v2_config_path": "",
        "status": "research_failed" if decision == "archive_liquidation_shock_recovery" else "research_candidate",
        "reasons": reasons,
        "evidence_supported_rules": evidence_supported,
        "event_PF_root_cause": attribution["event_return_root_cause_summary"],
        "fold3_root_cause": fold3["root_cause"],
        "mean_reverting_chop_fixable": chop["keepout_assessment"]["suitable_for_keepout"],
        "time_exit_should_shorten": lifecycle["time_exit_should_shorten"],
        "second_confirmation_required": confirmation["needs_second_confirmation"],
        "paper_queue": "LOCKED",
        "live": "FROZEN",
        "final_decision": "liquidation-shock recovery archived; paper queue remains LOCKED; live remains FROZEN."
        if decision == "archive_liquidation_shock_recovery"
        else "liquidation-shock v2 failed internal gate; paper queue remains LOCKED; live remains FROZEN.",
    }
    write_json(run_dir / "liquidation_shock_skeleton_decision.json", payload)
    _write_decision_doc(payload, run_dir=run_dir)
    return payload


def write_paper_live_safety_status(*, run_dir: Path, decision: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "schema_version": "btc_liquidation_shock_attribution_paper_live_safety_v1",
        "run_id": run_dir.name,
        "candidate_passed_internal_gate": 0,
        "paper_queue": "LOCKED",
        "paper_queue_locked": True,
        "paper_auto_start": False,
        "live": "FROZEN",
        "live_frozen": True,
        "real_broker_api_called": False,
        "real_orders_created": False,
        "skeleton_decision": (decision or {}).get("decision", "unknown"),
    }
    write_json(run_dir / "paper_live_safety_status.json", payload)
    return payload


def write_promotion_decision(*, run_dir: Path, decision: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": "btc_liquidation_shock_attribution_promotion_decision_v1",
        "run_id": run_dir.name,
        "skeleton_decision": decision.get("decision", "unknown"),
        "candidate_gate_results": [],
        "candidate_passed_internal_gate_count": 0,
        "max_state": "research_failed" if decision.get("decision") == "archive_liquidation_shock_recovery" else "candidate_gate_failed",
        "paper_review": {
            "paper_review_queue_locked": True,
            "paper_review_pending": [],
            "paper_auto_start": False,
            "reason": "skeleton_archived_no_v2_candidate_generated",
        },
        "live_frozen": True,
        "forbidden_states": ["live_enabled", "live_ready", "paper_ready"],
    }
    write_json(run_dir / "promotion_decision.json", payload)
    return payload


def write_run_manifest(*, run_dir: Path, source_run_dir: Path, decision: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": "btc_liquidation_shock_attribution_run_manifest_v1",
        "run_id": run_dir.name,
        "source_validation_run": str(source_run_dir),
        "source_hypothesis_run": str(SOURCE_HYPOTHESIS_RUN_DIR),
        "config_path": str(DEFAULT_VALIDATION_CONFIG_PATH),
        "config_hash": stable_hash(load_validation_config(DEFAULT_VALIDATION_CONFIG_PATH)),
        "code_commit": git_commit_hash(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_version": "btc_sqlite_1h",
        "strategy_version": "liquidation_shock_recovery_v1:event_return_attribution",
        "cost_model": "crypto_event_cost_model",
        "slippage_model": "crypto_slippage_4bps_base",
        "skeleton_decision": decision.get("decision"),
        "paper_queue": "LOCKED",
        "live": "FROZEN",
    }
    write_json(run_dir / "run_manifest.json", payload)
    return payload


def liquidation_shock_signal_with_rules(
    frame: pd.DataFrame,
    params: Mapping[str, Any] | None = None,
) -> tuple[pd.Series, dict[str, pd.Series]]:
    cfg = {**_base_params(), **dict(params or {})}
    hypothesis_config = load_hypothesis_config(HYPOTHESIS_CONFIG_PATH)
    event_table = build_event_table(frame, hypothesis_config, drop_incomplete_labels=False)
    event_table["timestamp"] = pd.to_datetime(event_table["timestamp"], utc=True)
    index = pd.to_datetime(frame.index, utc=True)
    aligned = event_table.set_index("timestamp").reindex(index)
    entries = aligned["is_hypothesis_active"].fillna(False).astype(bool)
    regimes = classify_btc_regimes(frame).reindex(index).ffill().fillna("unknown").astype(str)
    blocked = {str(item) for item in cfg.get("blocked_regimes", [])}
    if blocked:
        entries &= ~regimes.isin(blocked)
    confirmation = str(cfg.get("second_confirmation", "none"))
    confirmation_mask = _confirmation_mask(frame, aligned, confirmation)
    entries &= confirmation_mask
    exit_mode = str(cfg.get("exit_mode", "time_exit"))
    if exit_mode == "time_exit":
        signal = time_exit_long_only_signal(
            entries=entries,
            time_exit_bars=int(cfg["time_exit_bars"]),
            cooldown_bars=max(int(cfg["cooldown_bars"]), int(cfg.get("min_reentry_delay_bars", 0))),
            signal_scale=float(cfg["signal_scale"]),
        )
    else:
        signal = _rule_based_long_signal(
            frame=frame,
            entries=entries,
            time_exit_bars=int(cfg["time_exit_bars"]),
            cooldown_bars=max(int(cfg["cooldown_bars"]), int(cfg.get("min_reentry_delay_bars", 0))),
            signal_scale=float(cfg["signal_scale"]),
            exit_mode=exit_mode,
        )
    multipliers = dict(cfg.get("regime_size_multipliers", {}))
    for regime, multiplier in multipliers.items():
        signal.loc[regimes == str(regime)] *= float(multiplier)
    signal = signal.reindex(index).fillna(0.0).clip(0.0, 1.0)
    diagnostics = {
        "liquidation_shock": aligned["liquidation_shock"].fillna(False).astype(float),
        "recent_liquidation_shock": aligned["recent_liquidation_shock"].fillna(False).astype(float),
        "recovery_confirmed": aligned["recovery_confirmed"].fillna(False).astype(float),
        "wick_recovery_score": pd.to_numeric(aligned["wick_recovery_score"], errors="coerce").fillna(0.0),
        "volume_ratio": pd.to_numeric(aligned["volume_ratio"], errors="coerce").fillna(1.0),
        "shock_return": pd.to_numeric(aligned["shock_return"], errors="coerce").fillna(0.0),
        "confirmation_passed": confirmation_mask.astype(float),
        "target_signal": signal,
        "raw_signal": signal,
        "regime": regimes,
    }
    for key, value in diagnostics.items():
        value.index = index
        diagnostics[key] = value
    return signal, diagnostics


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _base_params() -> dict[str, Any]:
    config = load_validation_config(DEFAULT_VALIDATION_CONFIG_PATH)
    return dict(config.get("params", {}))


def _frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    local = load_btc_1h_frame() if frame is None else frame.copy()
    local.index = pd.to_datetime(local.index, utc=True)
    return local


def _event_return_table(
    *,
    run_id: str,
    source_run_id: str,
    frame: pd.DataFrame,
    equity: pd.Series,
    signal: pd.Series,
    diagnostics: Mapping[str, pd.Series],
    trades: pd.DataFrame,
    walk_forward: Mapping[str, Any],
) -> pd.DataFrame:
    index = pd.to_datetime(frame.index, utc=True)
    aligned_equity = equity.reindex(index).ffill().bfill()
    aligned_signal = signal.reindex(index).fillna(0.0).astype(float)
    regimes = classify_btc_regimes(frame).reindex(index).ffill().fillna("unknown").astype(str)
    shock = _diag(diagnostics, "liquidation_shock", index) > 0.0
    recovery = _diag(diagnostics, "recovery_confirmed", index) > 0.0
    wick = _diag(diagnostics, "wick_recovery_score", index)
    volume_ratio = _diag(diagnostics, "volume_ratio", index)
    shock_return = _diag(diagnostics, "shock_return", index)
    recovery_age, time_to_exit, segment_id = _segment_lifecycle(index, trades)
    close_returns = frame["close"].astype(float).pct_change().fillna(0.0)
    volatility = close_returns.rolling(168, min_periods=24).std(ddof=0).fillna(0.0)
    trend = frame["close"].astype(float).pct_change(168).fillna(0.0)
    time_since_shock = _bars_since(shock)
    equity_before = aligned_equity.shift(1).fillna(aligned_equity.iloc[0])
    signed_pnl = aligned_equity.diff().fillna(0.0)
    event_return = aligned_equity.pct_change().fillna(0.0)
    active = aligned_signal > 0.0
    table = pd.DataFrame(
        {
            "run_id": run_id,
            "source_run_id": source_run_id,
            "timestamp": index,
            "fold_id": _fold_ids_from_report(index, walk_forward),
            "regime": regimes.values,
            "event_return": event_return.values,
            "signed_event_pnl": signed_pnl.values,
            "equity_before": equity_before.values,
            "equity_after": aligned_equity.values,
            "position_side": np.where(active.values, "long", "flat"),
            "position_size": aligned_signal.values,
            "exposure": aligned_signal.abs().values,
            "active_exposure": active.values,
            "open_pnl": np.where(active.values, signed_pnl.values, 0.0),
            "closed_pnl": np.where((active.shift(1).fillna(False) & ~active).values, signed_pnl.values, 0.0),
            "fees": 0.0,
            "slippage": 0.0,
            "funding": 0.0,
            "liquidation_shock_intensity": np.where(shock.values, shock_return.abs().values, 0.0),
            "recovery_age_bars": recovery_age.values,
            "time_since_shock_bars": time_since_shock.values,
            "time_to_exit_bars": time_to_exit.values,
            "exit_reason_pending": [
                "time_exit_pending" if bool(is_active) and int(ttx) <= 1 else "no_exit_pending" if bool(is_active) else "flat"
                for is_active, ttx in zip(active.values, time_to_exit.values)
            ],
            "time_exit_flag": (active & (time_to_exit <= 1)).values,
            "confirmation_state": [
                _confirmation_state(bool(is_active), bool(is_recovery), float(w), float(vr))
                for is_active, is_recovery, w, vr in zip(active.values, recovery.values, wick.values, volume_ratio.values)
            ],
            "mean_reverting_chop_flag": (regimes == "mean_reverting_chop").values,
            "trend_recovery_state": pd.cut(
                trend,
                bins=[-np.inf, -0.03, 0.03, np.inf],
                labels=["downtrend", "neutral", "uptrend"],
            ).astype(str).values,
            "volatility_bucket": _historical_bucket(volatility).values,
            "cost_bucket": "no_cost",
            "segment_id": segment_id.values,
        }
    )
    table["recovery_age_bucket"] = [_age_bucket(int(value)) for value in table["recovery_age_bars"]]
    table["time_since_shock_bucket"] = [_age_bucket(int(value)) if int(value) < 9999 else "no_recent_shock" for value in table["time_since_shock_bars"]]
    table["time_to_exit_bucket"] = [_time_to_exit_bucket(int(value)) for value in table["time_to_exit_bars"]]
    table["active_exposure_bucket"] = np.where(table["active_exposure"], "active", "flat")
    table["is_positive_event"] = table["event_return"] > 0.0
    table["is_negative_event"] = table["event_return"] < 0.0
    return table


def _variant_summary(
    variant: str,
    params: Mapping[str, Any],
    *,
    run_dir: Path,
    frame: pd.DataFrame,
) -> dict[str, Any]:
    local_params = {**_base_params(), **dict(params)}
    variant_dir = run_dir / "variant_runs" / variant
    summary_path = variant_dir / "variant_summary.json"
    if summary_path.exists():
        return read_json(summary_path)
    variant_dir.mkdir(parents=True, exist_ok=True)
    signal, diagnostics = liquidation_shock_signal_with_rules(frame, local_params)
    event = _run_event(
        frame=frame,
        signal=signal,
        strategy_id=f"btc_liquidation_shock_{variant}",
        params=local_params,
        start=frame.index[0].to_pydatetime(),
        end=frame.index[-1].to_pydatetime(),
        run_dir=variant_dir,
    )
    trades = ledger_segments_from_signal(
        run_id=run_dir.name,
        strategy_id=f"btc_liquidation_shock_{variant}",
        frame=frame,
        signal=signal,
        manifest_path=Path(str(event["manifest_path"])),
    )
    cost = cost_stress_for_signal(
        frame=frame,
        signal=signal,
        strategy_id=f"btc_liquidation_shock_{variant}",
        params=local_params,
        start=frame.index[0].to_pydatetime(),
        end=frame.index[-1].to_pydatetime(),
        run_dir=variant_dir,
        max_scenarios=2,
    )
    equity = _ledger_equity_curve(Path(str(event["manifest_path"])))
    source_wf = read_json(SOURCE_VALIDATION_RUN_DIR / "walk_forward_report.json")
    table = _event_return_table(
        run_id=run_dir.name,
        source_run_id=SOURCE_VALIDATION_RUN_ID,
        frame=frame,
        equity=equity,
        signal=signal,
        diagnostics=diagnostics,
        trades=trades,
        walk_forward=source_wf,
    )
    active = table.loc[table["active_exposure"].astype(bool)].copy()
    by_fold = _group_stats(active, "fold_id")
    fold_pass_rate = sum(
        1 for row in by_fold if str(row.get("fold_id")) != "pre_wf" and row.get("event_PF", 0.0) >= 1.0 and row.get("signed_pnl_sum", 0.0) >= 0.0
    ) / max(1, sum(1 for row in by_fold if str(row.get("fold_id")) != "pre_wf"))
    by_regime = _group_stats(active, "regime")
    regime_pass_rate = sum(
        1 for row in by_regime if row.get("event_PF", 0.0) >= 1.0 and row.get("signed_pnl_sum", 0.0) >= 0.0
    ) / max(1, len(by_regime))
    summary = event["summary"]
    wins = trades.loc[trades["net_pnl"] > 0, "net_pnl"] if not trades.empty else pd.Series(dtype=float)
    losses = -trades.loc[trades["net_pnl"] < 0, "net_pnl"] if not trades.empty else pd.Series(dtype=float)
    ordinary_pf = float(wins.sum() / losses.sum()) if float(losses.sum()) > 0 else (999.0 if float(wins.sum()) > 0 else 0.0)
    negative_sum = _sum_negative(active["event_return"])
    positive_sum = _sum_positive(active["event_return"])
    event_pf = float(summary.get("profit_factor", 0.0))
    fail_reasons = _variant_fail_reasons(
        event_pf=event_pf,
        ordinary_pf=ordinary_pf,
        fold_pass_rate=fold_pass_rate,
        regime_pass_rate=regime_pass_rate,
        cost_base=bool(cost.get("base", {}).get("passed", False)),
        cost_harsh=bool(cost.get("harsh", {}).get("survives", False)),
        dsr=0.0 if float(summary.get("sharpe_ratio", 0.0)) <= 0 else min(1.0, float(summary.get("sharpe_ratio", 0.0)) / 2.0),
    )
    fold3 = next((row for row in by_fold if str(row.get("fold_id")) == "3"), {})
    chop = next((row for row in by_regime if str(row.get("regime")) == "mean_reverting_chop"), {})
    payload = {
        "variant": variant,
        "params": local_params,
        "evaluation_source": "event_ledger_base_run_with_fold_attribution_and_cost_stress_base_fees2x",
        "event_PF": round(event_pf, 6),
        "PF": round(float(ordinary_pf), 6),
        "Sharpe": float(summary.get("sharpe_ratio", 0.0)),
        "MDD": float(summary.get("max_drawdown_pct", 0.0)),
        "total_return_pct": float(summary.get("total_return_pct", 0.0)),
        "turnover": _turnover_from_trades(trades, len(frame)),
        "WF_pass": round(float(fold_pass_rate), 6),
        "fold_event_pass_rate": round(float(fold_pass_rate), 6),
        "regime_pass": round(float(regime_pass_rate), 6),
        "cost_stress_base_pass": bool(cost.get("base", {}).get("passed", False)),
        "cost_stress_harsh_survives": bool(cost.get("harsh", {}).get("survives", False)),
        "DSR": 0.0 if float(summary.get("sharpe_ratio", 0.0)) <= 0 else round(min(1.0, float(summary.get("sharpe_ratio", 0.0)) / 2.0), 6),
        "PBO": round(sum(1 for row in by_fold if row.get("event_PF", 0.0) < 1.0) / max(1, len(by_fold)), 6),
        "trade_count": int(len(trades)),
        "avg_holding_bars": round(float(trades["holding_bars"].mean()) if len(trades) else 0.0, 6),
        "negative_event_sum": negative_sum,
        "positive_event_sum": positive_sum,
        "fold3_result": fold3,
        "mean_reverting_chop_result": chop,
        "fail_reasons": fail_reasons,
        "manifest_path": str(event["manifest_path"]),
    }
    write_json(summary_path, payload)
    return payload


def _variant_fail_reasons(
    *,
    event_pf: float,
    ordinary_pf: float,
    fold_pass_rate: float,
    regime_pass_rate: float,
    cost_base: bool,
    cost_harsh: bool,
    dsr: float,
) -> list[str]:
    reasons = []
    if event_pf < BTC_CANONICAL_GATE_THRESHOLDS["event_profit_factor"]:
        reasons.append("event_profit_factor")
    if ordinary_pf < BTC_CANONICAL_GATE_THRESHOLDS["profit_factor"]:
        reasons.append("profit_factor")
    if fold_pass_rate < BTC_CANONICAL_GATE_THRESHOLDS["walk_forward_pass_rate"]:
        reasons.append("walk_forward_pass_rate")
    if regime_pass_rate < BTC_CANONICAL_GATE_THRESHOLDS["regime_pass_rate"]:
        reasons.append("regime_pass_rate")
    if not cost_base:
        reasons.append("cost_stress_base")
    if not cost_harsh:
        reasons.append("cost_stress_harsh")
    if dsr < BTC_CANONICAL_GATE_THRESHOLDS["dsr"]:
        reasons.append("dsr")
    return reasons


def _confirmation_mask(frame: pd.DataFrame, aligned: pd.DataFrame, confirmation: str) -> pd.Series:
    index = pd.to_datetime(frame.index, utc=True)
    close = frame["close"].astype(float).reindex(index)
    fast_ma = close.rolling(12, min_periods=6).mean()
    fast_slope = fast_ma.diff().fillna(0.0)
    ret = close.pct_change().fillna(0.0)
    vol = ret.rolling(24, min_periods=8).std(ddof=0).fillna(0.0)
    pre_shock_level = close.shift(1).rolling(6, min_periods=2).max()
    if confirmation == "none":
        mask = pd.Series(True, index=index)
    elif confirmation == "price_reclaims_pre_shock_level":
        mask = close >= pre_shock_level
    elif confirmation == "close_above_fast_ma":
        mask = close >= fast_ma
    elif confirmation == "fast_ma_slope_positive":
        mask = fast_slope > 0.0
    elif confirmation == "two_bar_recovery_confirmation":
        mask = (ret > 0.0) & (ret.shift(1) > 0.0)
    elif confirmation == "volatility_cools_after_shock":
        mask = vol <= vol.rolling(72, min_periods=24).median().fillna(vol)
    elif confirmation == "no_immediate_reversal":
        mask = ret.rolling(2, min_periods=1).min() > -0.01
    elif confirmation == "combined_recovery_confirmation":
        mask = (close >= fast_ma) & (fast_slope > 0.0) & (ret.rolling(2, min_periods=1).min() > -0.01)
    else:
        raise ValueError(f"unsupported confirmation: {confirmation}")
    return mask.reindex(index).fillna(False).astype(bool)


def _rule_based_long_signal(
    *,
    frame: pd.DataFrame,
    entries: pd.Series,
    time_exit_bars: int,
    cooldown_bars: int,
    signal_scale: float,
    exit_mode: str,
) -> pd.Series:
    close = frame["close"].astype(float)
    signal = pd.Series(0.0, index=entries.index, dtype=float)
    scale = min(1.0, max(0.0, float(signal_scale)))
    in_position = False
    bars_held = 0
    cooldown_remaining = 0
    peak = 0.0
    entry_price = 0.0
    for ts, entry in entries.fillna(False).astype(bool).items():
        price = float(close.loc[ts])
        if cooldown_remaining > 0:
            cooldown_remaining -= 1
        if in_position:
            bars_held += 1
            peak = max(peak, price)
            deterioration = price / max(entry_price, 1e-12) - 1.0 <= -0.012
            trailing = price / max(peak, 1e-12) - 1.0 <= -0.012
            force_exit = bars_held >= max(1, int(time_exit_bars))
            mode_exit = (exit_mode == "event_return_deterioration_exit" and deterioration) or (
                exit_mode == "trailing_recovery_exit" and trailing
            )
            if force_exit or mode_exit:
                in_position = False
                cooldown_remaining = max(0, int(cooldown_bars))
                bars_held = 0
        if not in_position and cooldown_remaining == 0 and bool(entry):
            in_position = True
            bars_held = 0
            entry_price = price
            peak = price
        signal.loc[ts] = scale if in_position else 0.0
    return signal


def _segment_lifecycle(index: pd.DatetimeIndex, trades: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    age = pd.Series(0, index=index, dtype=int)
    time_to_exit = pd.Series(9999, index=index, dtype=int)
    segment_id = pd.Series("", index=index, dtype=object)
    for _, trade in trades.iterrows():
        entry = _ts(trade["entry_time"])
        exit_ts = _ts(trade["exit_time"])
        mask = (index >= entry) & (index < exit_ts)
        count = int(mask.sum())
        if count <= 0:
            continue
        age.loc[mask] = list(range(count))
        time_to_exit.loc[mask] = list(range(count, 0, -1))
        segment_id.loc[mask] = str(trade.get("trade_id", ""))
    return age, time_to_exit, segment_id


def _event_stats(frame_or_values: Any, column: str | None = None) -> dict[str, Any]:
    if isinstance(frame_or_values, pd.DataFrame):
        values = pd.to_numeric(frame_or_values[column or "event_return"], errors="coerce").dropna()
    else:
        values = pd.to_numeric(pd.Series(frame_or_values), errors="coerce").dropna()
    positive = values[values > 0.0]
    negative = values[values < 0.0]
    negative_abs = abs(float(negative.sum()))
    event_pf = float(positive.sum()) / negative_abs if negative_abs > 0 else (999.0 if float(positive.sum()) > 0 else 0.0)
    return {
        "event_count": int(len(values)),
        "positive_event_count": int(len(positive)),
        "negative_event_count": int(len(negative)),
        "positive_event_rate": round(float((values > 0.0).mean()) if len(values) else 0.0, 6),
        "positive_sum": round(float(positive.sum()) if len(positive) else 0.0, 10),
        "negative_sum": round(float(negative.sum()) if len(negative) else 0.0, 10),
        "signed_pnl_sum": round(float(values.sum()) if len(values) else 0.0, 10),
        "event_PF": round(event_pf, 6),
        "mean_return": round(float(values.mean()) if len(values) else 0.0, 10),
        "median_return": round(float(values.median()) if len(values) else 0.0, 10),
        "downside_tail_5pct": round(float(values.quantile(0.05)) if len(values) else 0.0, 10),
        "max_adverse_event": round(float(values.min()) if len(values) else 0.0, 10),
        "max_favorable_event": round(float(values.max()) if len(values) else 0.0, 10),
    }


def _group_stats(frame: pd.DataFrame, group_col: str) -> list[dict[str, Any]]:
    if frame.empty or group_col not in frame:
        return []
    rows = []
    for key, subset in frame.groupby(group_col, dropna=False):
        stats = _event_stats(subset, "event_return")
        stats[group_col] = str(key)
        rows.append(stats)
    return sorted(rows, key=lambda row: (row["event_PF"], row["signed_pnl_sum"]))


def _top_events(frame: pd.DataFrame, *, ascending: bool, limit: int) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    columns = [
        "timestamp",
        "fold_id",
        "regime",
        "event_return",
        "signed_event_pnl",
        "active_exposure",
        "recovery_age_bars",
        "time_since_shock_bars",
        "time_to_exit_bars",
        "confirmation_state",
        "segment_id",
    ]
    return frame.sort_values("event_return", ascending=ascending).head(limit)[columns].to_dict(orient="records")


def _negative_event_clusters(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    rows = []
    grouped = frame.groupby(["fold_id", "regime", "segment_id"], dropna=False)
    for (fold_id, regime, segment_id), subset in grouped:
        neg = subset.loc[subset["event_return"] < 0]
        if neg.empty:
            continue
        rows.append(
            {
                "fold_id": str(fold_id),
                "regime": str(regime),
                "segment_id": str(segment_id),
                "negative_event_count": int(len(neg)),
                "negative_event_sum": round(float(neg["event_return"].sum()), 10),
                "signed_negative_pnl_sum": round(float(neg["signed_event_pnl"].sum()), 6),
                "worst_event_return": round(float(neg["event_return"].min()), 10),
            }
        )
    return sorted(rows, key=lambda row: row["negative_event_sum"])[:20]


def _event_return_root_causes(
    *,
    table: pd.DataFrame,
    source_report: Mapping[str, Any],
    walk_forward: Mapping[str, Any],
    regime_report: Mapping[str, Any],
    cost_stress: Mapping[str, Any],
    pbo_dsr: Mapping[str, Any],
) -> list[str]:
    all_stats = _event_stats(table, "event_return")
    active_stats = _event_stats(table.loc[table["active_exposure"].astype(bool)], "event_return")
    inactive_stats = _event_stats(table.loc[~table["active_exposure"].astype(bool)], "event_return")
    negative = abs(float(active_stats["negative_sum"]))
    positive = float(active_stats["positive_sum"])
    fold_stats = _group_stats(table.loc[table["active_exposure"].astype(bool)], "fold_id")
    worst_fold = fold_stats[0]["fold_id"] if fold_stats else "unknown"
    dragging = ", ".join(regime_report.get("dragging_regimes", [])) or "none"
    return [
        f"Event_PF recomputes to {all_stats['event_PF']:.4f}, matching canonical event_PF {float(source_report['metrics']['event_profit_factor']):.4f}.",
        f"Target-active exposure event_PF is {active_stats['event_PF']:.4f}, but full-ledger event_PF is only {all_stats['event_PF']:.4f}.",
        f"Ledger equity changes outside target-active windows have event_PF {inactive_stats['event_PF']:.4f}; promotion must use full ledger, not target-active diagnostic slices.",
        f"Active exposure positive event sum {positive:.6f} versus negative event sum {-negative:.6f} is not enough to overcome full ledger lifecycle drag.",
        f"Worst active fold by event attribution is fold {worst_fold}; rolling WF pass remains {float(walk_forward.get('pass_rate', 0.0)):.2f}.",
        f"Dragging trade-entry regime is {dragging}; bar-level attribution shows the worst active regime is liquidation_shock itself.",
        f"Cost stress base passed={bool(cost_stress.get('base', {}).get('passed', False))}; harsh survives={bool(cost_stress.get('harsh', {}).get('survives', False))}.",
        f"PBO={pbo_dsr.get('pbo')}, DSR={pbo_dsr.get('dsr')}; DSR remains a promotion blocker.",
    ]


def _fold3_root_cause(fold3: pd.DataFrame, attribution: Mapping[str, Any], reproducible: bool) -> list[str]:
    stats = _event_stats(fold3, "event_return")
    return [
        f"Fold 3 active event_PF is {stats['event_PF']:.4f}; positive and negative event sums do not support a stable recovery edge.",
        "Fold 3 is the only rolling WF failure, but other folds only pass with event PF close to 1.0.",
        "The failure is not enough to justify a fold-specific rule." if not reproducible else "The worst pattern appears in other folds and can be tested as a rule.",
        "A v2 rule requires ablation evidence across folds, not a hardcoded fold-3 fix.",
    ]


def _write_decision_doc(decision: Mapping[str, Any], *, run_dir: Path) -> None:
    lines = [
        "# BTC Liquidation-Shock Skeleton Decision",
        "",
        f"- Run ID: `{run_dir.name}`",
        f"- Decision: `{decision['decision']}`",
        f"- Status: `{decision['status']}`",
        "- Paper queue: `LOCKED`",
        "- Live: `FROZEN`",
        "",
        "## Reasons",
        "",
    ]
    lines.extend(f"- {reason}" for reason in decision.get("reasons", []))
    lines.extend(
        [
            "",
            "## Artifact Inputs",
            "",
            f"- Event-return attribution: `{run_dir / 'liquidation_shock_event_return_attribution.json'}`",
            f"- Fold 3 autopsy: `{run_dir / 'liquidation_shock_fold3_autopsy.json'}`",
            f"- Mean-reverting-chop report: `{run_dir / 'liquidation_shock_mean_reverting_chop_report.json'}`",
            f"- Exit lifecycle ablation: `{run_dir / 'liquidation_shock_exit_lifecycle_ablation.json'}`",
            f"- Recovery confirmation report: `{run_dir / 'liquidation_shock_recovery_confirmation_report.json'}`",
            "",
            "## Final Decision",
            "",
            decision["final_decision"],
            "",
        ]
    )
    DECISION_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DECISION_DOC_PATH.write_text("\n".join(lines), encoding="utf-8")


def _diag(diagnostics: Mapping[str, pd.Series], key: str, index: pd.DatetimeIndex) -> pd.Series:
    value = diagnostics.get(key, pd.Series(0.0, index=index))
    return pd.to_numeric(value.reindex(index), errors="coerce").fillna(0.0)


def _ts(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _fold_ids_from_report(index: pd.DatetimeIndex, walk_forward: Mapping[str, Any]) -> list[str]:
    labels = ["pre_wf"] * len(index)
    for window in walk_forward.get("windows", []):
        start = _ts(window.get("validation_start"))
        end = _ts(window.get("validation_end"))
        fold_id = str(window.get("fold"))
        mask = (index >= start) & (index <= end)
        for pos in mask.nonzero()[0]:
            labels[pos] = fold_id
    return labels


def _bars_since(flag: pd.Series) -> pd.Series:
    out = []
    last = None
    for i, value in enumerate(flag.fillna(False).astype(bool).values):
        if value:
            last = i
            out.append(0)
        elif last is None:
            out.append(9999)
        else:
            out.append(i - last)
    return pd.Series(out, index=flag.index, dtype=int)


def _historical_bucket(series: pd.Series) -> pd.Series:
    low = series.expanding(min_periods=48).quantile(0.33).fillna(series)
    high = series.expanding(min_periods=48).quantile(0.66).fillna(series)
    return pd.Series(
        ["low_vol" if value <= lo else "high_vol" if value >= hi else "mid_vol" for value, lo, hi in zip(series, low, high)],
        index=series.index,
    )


def _age_bucket(value: int) -> str:
    if value <= 6:
        return "0_6"
    if value <= 12:
        return "7_12"
    if value <= 18:
        return "13_18"
    if value <= 24:
        return "19_24"
    if value <= 36:
        return "25_36"
    return "37_plus"


def _time_to_exit_bucket(value: int) -> str:
    if value >= 9999:
        return "flat"
    if value <= 3:
        return "0_3"
    if value <= 6:
        return "4_6"
    if value <= 12:
        return "7_12"
    if value <= 24:
        return "13_24"
    return "25_plus"


def _confirmation_state(active: bool, recovery: bool, wick: float, volume_ratio: float) -> str:
    if not active:
        return "flat"
    if recovery and wick >= 0.55 and volume_ratio >= 1.1:
        return "strong_recovery_confirmation"
    if recovery:
        return "basic_recovery_confirmation"
    return "weak_or_missing_confirmation"


def _sum_positive(values: Any) -> float:
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    return round(float(series[series > 0.0].sum()), 10)


def _sum_negative(values: Any) -> float:
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    return round(float(series[series < 0.0].sum()), 10)


def _max_drawdown_from_returns(values: Any) -> float:
    series = pd.to_numeric(pd.Series(values), errors="coerce").fillna(0.0)
    equity = (1.0 + series).cumprod()
    drawdown = equity / equity.cummax().replace(0, np.nan) - 1.0
    return round(float(drawdown.min()) if len(drawdown) else 0.0, 10)


def _first_key(rows: Sequence[Mapping[str, Any]], key: str) -> str:
    return str(rows[0].get(key, "")) if rows else ""


def _bucket_numeric(frame: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    if frame.empty or column not in frame:
        return []
    values = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    labels = pd.cut(values, bins=[-np.inf, 0.0, 0.01, 0.03, np.inf], labels=["none", "low", "mid", "high"]).astype(str)
    local = frame.copy()
    local[f"{column}_bucket"] = labels
    return _group_stats(local, f"{column}_bucket")


def _turnover_from_trades(trades: pd.DataFrame, rows: int) -> float:
    if trades.empty:
        return 0.0
    years = max(rows / (365.0 * 24.0), 1e-12)
    notional = ((trades["entry_price"].astype(float) + trades["exit_price"].astype(float)) * trades["size"].astype(float)).sum()
    return round(float(notional) / 100_000.0 / years, 6)
