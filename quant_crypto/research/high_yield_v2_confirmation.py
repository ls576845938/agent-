from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.atr_regime_failure_analysis import build_market_regime_frame
from quant_crypto.research.long_short_top5_review import (
    _annual_attribution,
    _concentration_review,
    _drawdown_review,
    _forward_observation_plan,
    _holdout_split,
    _regime_attribution,
    _segment_passed,
    _slice_metrics,
    _ts,
    _trade_ledger,
    _trend_following_profile_review,
)
from quant_crypto.research.simple_trend_rule_lab import BASE_COST_BPS, DEFAULT_DERIVATIVES_ROWS, DEFAULT_MARKET_DB, INITIAL_CAPITAL
from quant_crypto.research.small_account_high_yield_near_miss_review import (
    BEST_BASE_VARIANT_ID,
    DEFAULT_REPORT_PATH as DEFAULT_NEAR_MISS_REPORT_PATH,
    ReviewPolicy,
    ReviewSimulation,
    _git_commit,
    _prepare_market_context,
    _portable_path,
    _round,
    _simulate_review_variant,
    _v2_variant,
)


SCHEMA_VERSION = "btc_high_yield_v2_confirmation_v1"
DEFAULT_SOURCE_TOP5_REVIEW_PATH = Path("artifacts/btc_long_short_top5_review/latest/btc_long_short_top5_review_report.json")
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_high_yield_v2_confirmation/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_high_yield_v2_confirmation_report.json"
DEFAULT_COMPARISON_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_high_yield_v2_confirmation_comparison.csv"
DEFAULT_OBSERVATION_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_high_yield_v2_forward_observation_plan.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_high_yield_v2_confirmation_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

FROZEN_VARIANT_ID = "hy_v2_donchian_w240_d50_200_cd12_vt120_max2p5_dd25_liq1200_trendoff"
FROZEN_VOL_TARGET_PCT = 120.0
FROZEN_MAX_LEVERAGE = 2.5
FROZEN_DRAWDOWN_GATE_PCT = 25.0
FROZEN_MIN_LIQUIDATION_BUFFER_BPS = 1200.0
FROZEN_TRENDLESS_FILTER = False


def build_btc_high_yield_v2_confirmation(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    source_near_miss_report_path: Path = DEFAULT_NEAR_MISS_REPORT_PATH,
    source_top5_review_path: Path = DEFAULT_SOURCE_TOP5_REVIEW_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    holdout_days: int = 180,
    holdout_fraction: float = 0.20,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    comparison_csv_path = output_dir / DEFAULT_COMPARISON_CSV_PATH.name
    observation_csv_path = output_dir / DEFAULT_OBSERVATION_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    near_miss_report = _read_json(source_near_miss_report_path)
    top5_report = _read_json(source_top5_review_path)
    market = _prepare_market_context(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )

    blockers: list[str] = []
    if market.get("blockers"):
        blockers.extend(str(item) for item in market["blockers"])
    if not _source_contains_frozen_candidate(near_miss_report):
        blockers.append("btc_high_yield_v2_confirmation_missing_frozen_candidate_in_near_miss_report")

    frozen_sim = _run_frozen_simulation(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    item = _as_top5_like_item(frozen_sim)
    regime_frame = build_market_regime_frame(market["bars_4h"])
    holdout_index, in_sample_index, holdout_meta = _holdout_split(
        item.returns.index,
        holdout_days=holdout_days,
        holdout_fraction=holdout_fraction,
    )
    holdout_metrics = _slice_metrics(item, holdout_index, initial_capital=initial_capital)
    holdout = {
        **holdout_meta,
        "metrics": holdout_metrics,
        "passed": _segment_passed(holdout_metrics, max_drawdown_abs_pct=25.0),
        "used_for_selection": False,
    }
    in_sample = {
        "row_count": int(len(in_sample_index)),
        "start": _ts(in_sample_index.min()) if len(in_sample_index) else None,
        "end": _ts(in_sample_index.max()) if len(in_sample_index) else None,
        "metrics": _slice_metrics(item, in_sample_index, initial_capital=initial_capital),
    }
    annual = _annual_attribution(item, initial_capital=initial_capital)
    regime = _regime_attribution(item, regime_frame=regime_frame, initial_capital=initial_capital)
    trades = _trade_ledger(item)
    concentration = _concentration_review(item, trades=trades)
    drawdown = _drawdown_review(item, regime_frame=regime_frame, initial_capital=initial_capital)
    trend_profile = _trend_following_profile_review(
        item,
        trades=trades,
        regime_frame=regime_frame,
        annual=annual,
        initial_capital=initial_capital,
    )
    forward_observation = _forward_observation_packet(
        item,
        regime_frame=regime_frame,
        observation_csv_path=observation_csv_path,
        initial_capital=initial_capital,
    )
    cost_stress = _cost_stress_summary(
        market=market,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    leverage_review = _leverage_model_review(
        frozen_sim,
        market=market,
        base_cost_bps=base_cost_bps,
    )
    robust_comparison = _robust_top5_comparison(
        frozen_sim,
        holdout=holdout,
        top5_report=top5_report,
    )
    confirmation_summary = _confirmation_summary(
        frozen_sim=frozen_sim,
        holdout=holdout,
        concentration=concentration,
        trend_profile=trend_profile,
        cost_stress=cost_stress,
        leverage_review=leverage_review,
    )

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_high_yield_v2_confirmation_research_only_no_paper_no_live",
        "scope": "frozen_high_yield_v2_confirmation_and_forward_observation_plan",
        "code_commit": _git_commit(),
        "frozen_candidate": {
            "variant_id": FROZEN_VARIANT_ID,
            "base_variant_id": BEST_BASE_VARIANT_ID,
            "vol_target_pct": FROZEN_VOL_TARGET_PCT,
            "max_leverage": FROZEN_MAX_LEVERAGE,
            "drawdown_gate_pct": FROZEN_DRAWDOWN_GATE_PCT,
            "min_liquidation_buffer_bps": FROZEN_MIN_LIQUIDATION_BUFFER_BPS,
            "trendless_filter": "off",
            "candidate_frozen_before_confirmation": True,
            "further_parameter_search_allowed_in_this_packet": False,
        },
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "source_near_miss_report_path": _portable_path(source_near_miss_report_path),
            "source_top5_review_path": _portable_path(source_top5_review_path),
            "bar_4h_rows": int(len(market["bars_4h"])),
            "bar_4h_start": _ts(market["bars_4h"].index.min()) if len(market["bars_4h"]) else None,
            "bar_4h_end": _ts(market["bars_4h"].index.max()) if len(market["bars_4h"]) else None,
            "completed_bar_rule": "1h completed bars only; 4h/1d/1w/1mo derived from completed 1h chunks",
            "derivatives_available_time_rule": "derivatives rows aligned by available_time <= decision_time",
        },
        "confirmation_design": {
            "step_1_freeze_current_best_v2": "completed",
            "step_2_confirmatory_review_packet": "completed",
            "step_3_30d_60d_forward_observation_plan": "completed_pending_future_data",
            "step_4_same_window_robust_top5_comparison": "completed",
            "step_5_leverage_model_review": "completed_research_approximation",
            "holdout_locked_for_this_review": True,
            "clean_pre_selection_holdout": False,
            "clean_pre_selection_holdout_note": (
                "The frozen high-yield v2 candidate was selected from the near-miss narrow grid. "
                "This packet is post-selection confirmation plus forward-observation setup, not fresh unseen evidence."
            ),
            "holdout_used_for_selection": False,
            "paper_live_boundary": "research_only_forward_observation_required",
        },
        "full_metrics": frozen_sim.metrics,
        "confirmation_holdout": holdout,
        "in_sample_reference": in_sample,
        "annual_attribution": annual,
        "market_regime_attribution": regime,
        "return_concentration": concentration,
        "max_drawdown_attribution": drawdown,
        "trend_following_profile": trend_profile,
        "cost_stress_summary": cost_stress,
        "leverage_model_review": leverage_review,
        "forward_observation": forward_observation,
        "robust_top5_same_window_comparison": robust_comparison,
        "confirmation_summary": confirmation_summary,
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(confirmation_summary, leverage_review),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "comparison_csv": _portable_path(comparison_csv_path),
            "forward_observation_plan_csv": _portable_path(observation_csv_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(comparison_csv_path, robust_comparison["rows"])
    _write_json(safety_path, _safety_status(report))
    _write_text(markdown_path, render_btc_high_yield_v2_confirmation_markdown(report))
    return report


def _run_frozen_simulation(market: Mapping[str, Any], *, initial_capital: float, base_cost_bps: float) -> ReviewSimulation:
    variant = _v2_variant(FROZEN_VOL_TARGET_PCT, FROZEN_MAX_LEVERAGE, FROZEN_VARIANT_ID)
    policy = ReviewPolicy(
        drawdown_gate_pct=FROZEN_DRAWDOWN_GATE_PCT,
        min_liquidation_buffer_bps=FROZEN_MIN_LIQUIDATION_BUFFER_BPS,
        enable_trendless_filter=FROZEN_TRENDLESS_FILTER,
    )
    return _simulate_review_variant(
        variant,
        base_signal=market["base_signal"],
        bars=market["bars_4h"],
        derivatives=market["derivatives_4h"],
        initial_capital=initial_capital,
        cost_bps=base_cost_bps,
        policy=policy,
    )


def _as_top5_like_item(sim: ReviewSimulation) -> Any:
    metrics = dict(sim.metrics)
    metrics["long_bar_count"] = int((sim.exposure > 0.0).sum())
    metrics["short_bar_count"] = int((sim.exposure < 0.0).sum())
    metrics["average_net_exposure"] = _round(float(sim.exposure.mean()) if len(sim.exposure) else 0.0)
    metrics["exposure_change_count"] = int((sim.exposure.diff().abs().fillna(sim.exposure.abs()) > 1e-12).sum())
    return SimpleNamespace(
        returns=sim.returns,
        exposure=sim.exposure,
        turnover=sim.turnover,
        trading_cost=sim.cost,
        funding_pnl=sim.funding_pnl,
        equity=sim.equity,
        metrics=metrics,
    )


def _cost_stress_summary(*, market: Mapping[str, Any], initial_capital: float, base_cost_bps: float) -> dict[str, Any]:
    rows = []
    for label, multiplier in [("base", 1.0), ("costs_2x", 2.0), ("costs_5x", 5.0)]:
        sim = _run_frozen_simulation(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps * multiplier)
        rows.append(
            {
                "scenario": label,
                "fixed_cost_bps": _round(base_cost_bps * multiplier),
                "annual_return_pct": sim.metrics["annual_return_pct"],
                "total_return_pct": sim.metrics["total_return_pct"],
                "max_drawdown_abs_pct": sim.metrics["max_drawdown_abs_pct"],
                "profit_factor": sim.metrics["profit_factor"],
                "calmar_ratio": sim.metrics["calmar_ratio"],
                "simulated_liquidation_count": sim.diagnostics["simulated_liquidation_count"],
                "forced_risk_reduction_count": sim.diagnostics["forced_risk_reduction_count"],
                "survives_positive_return": bool(float(sim.metrics["total_return_pct"]) > 0.0),
            }
        )
    base = rows[0]
    return {
        "model": "fixed_bps_research_approximation",
        "base_cost_bps": _round(base_cost_bps),
        "stress_rows": rows,
        "costs_2x_survives": bool(rows[1]["survives_positive_return"]),
        "costs_5x_survives": bool(rows[2]["survives_positive_return"]),
        "annual_return_drag_2x_pct": _round(float(base["annual_return_pct"]) - float(rows[1]["annual_return_pct"])),
        "annual_return_drag_5x_pct": _round(float(base["annual_return_pct"]) - float(rows[2]["annual_return_pct"])),
        "paper_live_use_allowed": False,
    }


def _leverage_model_review(sim: ReviewSimulation, *, market: Mapping[str, Any], base_cost_bps: float) -> dict[str, Any]:
    bars = market["bars_4h"].reindex(sim.exposure.index)
    exposure = sim.exposure
    previous_close = bars["close"].shift(1)
    long_adverse = (1.0 - bars["low"] / previous_close).clip(lower=0.0)
    short_adverse = (bars["high"] / previous_close - 1.0).clip(lower=0.0)
    adverse = pd.Series(0.0, index=exposure.index)
    adverse.loc[exposure > 0.0] = long_adverse.loc[exposure > 0.0]
    adverse.loc[exposure < 0.0] = short_adverse.loc[exposure < 0.0]
    exposed_adverse = adverse.loc[exposure.abs() > 1e-12].dropna()
    max_abs_exposure = float(exposure.abs().max()) if len(exposure) else 0.0
    min_buffer = float(sim.diagnostics.get("min_liquidation_buffer_bps", 0.0))
    buffer_passed = min_buffer >= FROZEN_MIN_LIQUIDATION_BUFFER_BPS and int(sim.diagnostics["simulated_liquidation_count"]) == 0
    return {
        "status": "research_approximation_requires_perp_evidence",
        "max_leverage_policy": FROZEN_MAX_LEVERAGE,
        "max_observed_abs_exposure": _round(max_abs_exposure),
        "average_abs_exposure": _round(float(exposure.abs().mean()) if len(exposure) else 0.0),
        "liquidation_buffer_policy_bps": FROZEN_MIN_LIQUIDATION_BUFFER_BPS,
        "min_observed_liquidation_buffer_bps": _round(min_buffer),
        "liquidation_buffer_passed_in_proxy": bool(buffer_passed),
        "simulated_liquidation_count": sim.diagnostics["simulated_liquidation_count"],
        "liquidation_buffer_derisk_count": sim.diagnostics["liquidation_buffer_derisk_count"],
        "forced_risk_reduction_count": sim.diagnostics["forced_risk_reduction_count"],
        "worst_4h_intrabar_adverse_move_pct": _round(float(exposed_adverse.max()) * 100.0 if len(exposed_adverse) else 0.0),
        "adverse_move_p95_pct": _round(float(exposed_adverse.quantile(0.95)) * 100.0 if len(exposed_adverse) else 0.0),
        "funding_model": "hourly_aligned_derivatives_funding_research_approximation",
        "funding_return_pct": sim.metrics.get("funding_return_pct"),
        "fixed_cost_bps": _round(base_cost_bps),
        "spot_ohlcv_proxy_for_perp_execution": True,
        "missing_before_paper": [
            "perpetual mark/index price path",
            "exchange liquidation formula and maintenance margin tiers",
            "funding settlement event ledger",
            "spread/depth-aware slippage under high volatility",
            "exchange outage and order rejection model",
        ],
        "promotion_blocker": "needs_perp_mark_funding_depth_liquidation_evidence_before_paper",
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _forward_observation_packet(
    item: Any,
    *,
    regime_frame: pd.DataFrame,
    observation_csv_path: Path,
    initial_capital: float,
) -> dict[str, Any]:
    base_plan = _forward_observation_plan(item, regime_frame=regime_frame, initial_capital=initial_capital)
    rows = _daily_observation_rows(item)
    _write_csv(observation_csv_path, rows)
    latest_ts = pd.Timestamp(item.returns.index.max()) if len(item.returns.index) else None
    latest_exposure = float(item.exposure.iloc[-1]) if len(item.exposure) else 0.0
    return {
        **base_plan,
        "daily_plan_row_count": len(rows),
        "daily_plan_path": _portable_path(observation_csv_path),
        "latest_completed_decision_time": _ts(latest_ts) if latest_ts is not None else None,
        "latest_theoretical_side": _side(latest_exposure),
        "latest_theoretical_exposure": _round(latest_exposure),
        "daily_record_required_fields": [
            "observation_date_utc",
            "actual_completed_bar_available",
            "theoretical_side",
            "theoretical_exposure",
            "net_return_pct",
            "max_adverse_move_pct",
            "risk_control_triggered",
            "paper_queue_write_allowed",
            "live_unlock_allowed",
        ],
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _daily_observation_rows(item: Any) -> list[dict[str, Any]]:
    if len(item.returns.index) == 0:
        return []
    latest_ts = pd.Timestamp(item.returns.index.max())
    rows = []
    for day in range(1, 61):
        rows.append(
            {
                "observation_day": day,
                "observation_date_utc": (latest_ts + pd.Timedelta(days=day)).date().isoformat(),
                "window": "30d" if day <= 30 else "60d",
                "status": "pending_future_data",
                "actual_completed_bar_available": False,
                "theoretical_side": "",
                "theoretical_exposure": "",
                "net_return_pct": "",
                "max_adverse_move_pct": "",
                "risk_control_triggered": "",
                "expected_shape": "少亏或空仓等待大趋势",
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
    return rows


def _robust_top5_comparison(
    frozen_sim: ReviewSimulation,
    *,
    holdout: Mapping[str, Any],
    top5_report: Mapping[str, Any],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = [
        {
            "bucket": "high_yield_v2_frozen",
            "rank": 1,
            "variant_id": FROZEN_VARIANT_ID,
            "annual_return_pct": frozen_sim.metrics.get("annual_return_pct"),
            "total_return_pct": frozen_sim.metrics.get("total_return_pct"),
            "max_drawdown_abs_pct": frozen_sim.metrics.get("max_drawdown_abs_pct"),
            "profit_factor": frozen_sim.metrics.get("profit_factor"),
            "calmar_ratio": frozen_sim.metrics.get("calmar_ratio"),
            "average_exposure": frozen_sim.metrics.get("average_exposure"),
            "holdout_total_return_pct": holdout.get("metrics", {}).get("total_return_pct"),
            "holdout_max_drawdown_abs_pct": holdout.get("metrics", {}).get("max_drawdown_abs_pct"),
            "holdout_profit_factor": holdout.get("metrics", {}).get("profit_factor"),
            "max_leverage": FROZEN_MAX_LEVERAGE,
            "review_decision": "research_only_forward_observation_required",
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        }
    ]
    detail_by_variant = {
        str(detail.get("variant_id")): detail
        for detail in top5_report.get("candidate_reviews", [])
        if isinstance(detail, Mapping)
    }
    for row in top5_report.get("candidate_rows", [])[:5]:
        if not isinstance(row, Mapping):
            continue
        detail = detail_by_variant.get(str(row.get("variant_id")), {})
        full = detail.get("full_metrics", {}) if isinstance(detail, Mapping) else {}
        rows.append(
            {
                "bucket": "robust_long_short_top5",
                "rank": row.get("rank"),
                "variant_id": row.get("variant_id"),
                "annual_return_pct": full.get("annual_return_pct"),
                "total_return_pct": row.get("full_total_return_pct"),
                "max_drawdown_abs_pct": abs(float(row.get("full_max_drawdown_pct", 0.0))),
                "profit_factor": row.get("full_profit_factor"),
                "calmar_ratio": full.get("calmar_ratio"),
                "average_exposure": full.get("average_exposure"),
                "holdout_total_return_pct": row.get("holdout_total_return_pct"),
                "holdout_max_drawdown_abs_pct": abs(float(row.get("holdout_max_drawdown_pct", 0.0))),
                "holdout_profit_factor": row.get("holdout_profit_factor"),
                "max_leverage": 1.0,
                "review_decision": row.get("review_decision"),
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
    return {
        "comparison_basis": "same BTC 4H decision window where available; high-yield v2 uses 2.5x volatility-target overlay, robust Top5 are unlevered long/short trend references",
        "row_count": len(rows),
        "rows": rows,
        "interpretation": _comparison_interpretation(rows),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _confirmation_summary(
    *,
    frozen_sim: ReviewSimulation,
    holdout: Mapping[str, Any],
    concentration: Mapping[str, Any],
    trend_profile: Mapping[str, Any],
    cost_stress: Mapping[str, Any],
    leverage_review: Mapping[str, Any],
) -> dict[str, Any]:
    flags: list[str] = []
    if not bool(holdout.get("passed")):
        flags.append("holdout_failed")
    if float(holdout.get("metrics", {}).get("profit_factor", 0.0)) < 1.0:
        flags.append("holdout_profit_factor_below_1")
    if float(concentration.get("top_3_positive_trade_share", 0.0)) > 0.70:
        flags.append("trend_return_concentration_review_required")
    if not bool(trend_profile.get("profile_passed")):
        flags.append("trend_following_profile_failed")
    if not bool(cost_stress.get("costs_2x_survives")):
        flags.append("costs_2x_failed")
    if not bool(cost_stress.get("costs_5x_survives")):
        flags.append("costs_5x_failed")
    stress_rows = {
        str(row.get("scenario")): row
        for row in cost_stress.get("stress_rows", [])
        if isinstance(row, Mapping)
    }
    if float(stress_rows.get("costs_5x", {}).get("annual_return_pct", 0.0)) < 60.0:
        flags.append("costs_5x_degrades_below_high_yield_target")
    if not bool(leverage_review.get("liquidation_buffer_passed_in_proxy")):
        flags.append("liquidation_buffer_proxy_failed")
    flags.append("forward_30d_60d_observation_required")
    flags.append("perp_execution_evidence_required_before_paper")
    return {
        "frozen_variant_id": frozen_sim.variant.variant_id,
        "annual_return_pct": frozen_sim.metrics["annual_return_pct"],
        "max_drawdown_abs_pct": frozen_sim.metrics["max_drawdown_abs_pct"],
        "profit_factor": frozen_sim.metrics["profit_factor"],
        "holdout_passed": bool(holdout.get("passed")),
        "trend_profile_passed": bool(trend_profile.get("profile_passed")),
        "costs_2x_survives": bool(cost_stress.get("costs_2x_survives")),
        "costs_5x_survives": bool(cost_stress.get("costs_5x_survives")),
        "failure_or_caution_flags": flags,
        "decision": "research_only_forward_observation_required_no_paper_no_live",
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _comparison_interpretation(rows: Sequence[Mapping[str, Any]]) -> str:
    if len(rows) < 2:
        return "robust_top5_reference_missing"
    frozen = rows[0]
    robust = [row for row in rows[1:] if row.get("bucket") == "robust_long_short_top5"]
    if not robust:
        return "robust_top5_reference_missing"
    best_robust = max(robust, key=lambda row: float(row.get("annual_return_pct") or 0.0))
    if float(frozen.get("annual_return_pct") or 0.0) > float(best_robust.get("annual_return_pct") or 0.0):
        return "high_yield_v2_has_higher_annual_return_but_uses_leverage_and_requires_forward_confirmation"
    return "robust_top5_remains_competitive_after_risk_adjustment"


def _source_contains_frozen_candidate(report: Mapping[str, Any]) -> bool:
    for key in ("high_yield_near_miss_research_watchlist", "v2_narrow_grid_rows"):
        for row in report.get(key, []):
            if isinstance(row, Mapping) and row.get("variant_id") == FROZEN_VARIANT_ID:
                return True
    return False


def _warnings(summary: Mapping[str, Any], leverage_review: Mapping[str, Any]) -> list[str]:
    warnings = ["btc_high_yield_v2_confirmation_research_only_no_paper_no_live"]
    if "forward_30d_60d_observation_required" in summary.get("failure_or_caution_flags", []):
        warnings.append("btc_high_yield_v2_forward_observation_required")
    if leverage_review.get("status") == "research_approximation_requires_perp_evidence":
        warnings.append("btc_high_yield_v2_perpetual_execution_evidence_missing")
    if "costs_5x_failed" in summary.get("failure_or_caution_flags", []):
        warnings.append("btc_high_yield_v2_costs_5x_failed_or_weak")
    if "costs_5x_degrades_below_high_yield_target" in summary.get("failure_or_caution_flags", []):
        warnings.append("btc_high_yield_v2_costs_5x_degrades_below_high_yield_target")
    return warnings


def _gate() -> dict[str, Any]:
    return {
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Frozen high-yield v2 confirmation is research-only and requires future observation plus perpetual execution evidence before any paper discussion.",
    }


def _guardrails() -> dict[str, Any]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_high_yield_v2_confirmation_safety_status_v1",
        "status": "research_only",
        "frozen_variant_id": FROZEN_VARIANT_ID,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "forward_observation_required": True,
        "perpetual_execution_evidence_required": True,
        "blockers": list(report.get("blockers", [])),
        "reason": "confirmation package cannot promote high-yield v2 to paper/live",
    }


def render_btc_high_yield_v2_confirmation_markdown(report: Mapping[str, Any]) -> str:
    frozen = report.get("frozen_candidate", {})
    summary = report.get("confirmation_summary", {})
    holdout = report.get("confirmation_holdout", {})
    leverage = report.get("leverage_model_review", {})
    forward = report.get("forward_observation", {})
    gate = report.get("gate", {})
    lines = [
        "# BTC 高收益 v2 冻结候选确认包",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策边界：`{report.get('decision')}`",
        f"- 冻结候选：`{frozen.get('variant_id')}`",
        f"- 年化 / 回撤 / PF：`{summary.get('annual_return_pct')}` / `{summary.get('max_drawdown_abs_pct')}` / `{summary.get('profit_factor')}`",
        f"- holdout 通过：`{summary.get('holdout_passed')}`，holdout 收益：`{(holdout.get('metrics') or {}).get('total_return_pct')}`",
        f"- 2x / 5x 成本压力存活：`{summary.get('costs_2x_survives')}` / `{summary.get('costs_5x_survives')}`",
        f"- 最小强平缓冲 proxy：`{leverage.get('min_observed_liquidation_buffer_bps')}` bps",
        f"- 30/60 天观察计划行数：`{forward.get('daily_plan_row_count')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 结论",
        "",
        f"`{summary.get('decision')}`。",
        "即使指标继续好看，本包也只是 research-only 确认和观察计划；需要未来 30/60 天真实观察、永续 mark/index/funding/深度/强平证据后，才有资格讨论 paper 复核。",
    ]
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _side(exposure: float) -> str:
    if exposure > 1e-12:
        return "long"
    if exposure < -1e-12:
        return "short"
    return "flat"
