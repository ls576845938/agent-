from __future__ import annotations

import csv
import json
import math
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.long_short_trend_following_lab import (
    LongShortTrendSpec,
    aggregate_ohlcv_calendar,
    evaluate_long_short_trend_rule,
    long_short_trend_following_specs,
)
from quant_crypto.research.short_interval_data_refresh import load_market_klines_frame
from quant_crypto.research.simple_trend_rule_lab import (
    BASE_COST_BPS,
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    INITIAL_CAPITAL,
    aggregate_ohlcv,
    align_derivatives_to_index,
    load_market_1h,
)
from quant_crypto.research.small_account_high_yield_lab import (
    DEFAULT_REPORT_PATH as DEFAULT_HIGH_YIELD_REPORT_PATH,
    DEFAULT_SOURCE_TOP5_REPORT,
    _intraday_signal,
)


SCHEMA_VERSION = "btc_small_account_high_yield_near_miss_review_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_small_account_high_yield_near_miss/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_small_account_high_yield_near_miss_review_report.json"
DEFAULT_TOP10_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_small_account_high_yield_near_miss_top10_review.csv"
DEFAULT_V2_GRID_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_small_account_high_yield_near_miss_v2_grid.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_small_account_high_yield_near_miss_review_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

HIGH_YIELD_TARGET_ANNUAL_RETURN_PCT = 60.0
MIN_PROFIT_FACTOR = 1.15
DEFAULT_DRAWDOWN_GATE_PCT = 40.0
DEFAULT_MIN_LIQUIDATION_BUFFER_BPS = 500.0
V2_VOL_TARGETS = (100.0, 110.0, 120.0, 130.0, 140.0)
V2_MAX_LEVERAGES = (2.0, 2.5, 3.0)
V2_DRAWDOWN_GATES = (20.0, 25.0, 30.0)
V2_LIQUIDATION_BUFFERS_BPS = (800.0, 1200.0, 1600.0)
V2_TRENDLESS_FILTERS = (False, True)
TRENDLESS_EFFICIENCY_THRESHOLD = 0.18
BEST_BASE_VARIANT_ID = "formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone"


@dataclass(frozen=True)
class ReviewVariant:
    bucket: str
    variant_id: str
    base_variant_id: str
    mode: str
    fixed_leverage: float | None
    target_volatility_pct: float | None
    max_leverage: float
    interval: str
    interval_hours: float
    signal_kind: str


@dataclass(frozen=True)
class ReviewPolicy:
    drawdown_gate_pct: float = DEFAULT_DRAWDOWN_GATE_PCT
    min_liquidation_buffer_bps: float = DEFAULT_MIN_LIQUIDATION_BUFFER_BPS
    enable_costs: bool = True
    enable_drawdown_gate: bool = True
    enable_consecutive_loss_derisk: bool = True
    enable_liquidation_buffer_derisk: bool = True
    enable_trendless_filter: bool = False
    trend_efficiency_threshold: float = TRENDLESS_EFFICIENCY_THRESHOLD
    fast_stop_base_pct: float = 6.0
    fast_stop_floor_pct: float = 1.5
    fast_stop_cap_pct: float = 6.0
    stop_cooldown_bars: int = 6
    consecutive_loss_trigger_bars: int = 3
    consecutive_loss_derisk_bars: int = 12
    consecutive_loss_derisk_factor: float = 0.5
    liquidation_buffer_cooldown_bars: int = 6
    enable_failed_breakout_exit: bool = False
    failed_breakout_window_bars: int = 3
    failed_breakout_return_threshold_pct: float = 1.2
    failed_breakout_cooldown_bars: int = 6


@dataclass
class ReviewSimulation:
    variant: ReviewVariant
    policy: ReviewPolicy
    exposure: pd.Series
    returns: pd.Series
    turnover: pd.Series
    cost: pd.Series
    funding_pnl: pd.Series
    equity: pd.Series
    metrics: dict[str, Any]
    diagnostics: dict[str, Any]


def build_btc_small_account_high_yield_near_miss_review(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    source_high_yield_report_path: Path = DEFAULT_HIGH_YIELD_REPORT_PATH,
    source_top5_report_path: Path = DEFAULT_SOURCE_TOP5_REPORT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    top10_csv_path = output_dir / DEFAULT_TOP10_CSV_PATH.name
    v2_grid_csv_path = output_dir / DEFAULT_V2_GRID_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    source_report = _read_json(source_high_yield_report_path)
    source_rows = sorted(
        [row for row in source_report.get("candidate_rows", []) if isinstance(row, Mapping)],
        key=lambda row: (-float(row.get("annual_return_pct", 0.0)), float(row.get("max_drawdown_abs_pct", 999.0)), str(row.get("variant_id"))),
    )
    top10_rows = source_rows[:10]

    market = _prepare_market_context(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    blockers: list[str] = []
    if not source_report:
        blockers.append("btc_high_yield_near_miss_source_report_missing")
    if not top10_rows:
        blockers.append("btc_high_yield_near_miss_no_top10_rows")
    if market.get("blockers"):
        blockers.extend(str(item) for item in market["blockers"])

    top10_review = _review_top10_near_misses(
        top10_rows,
        market=market,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    vol_vs_fixed = _vol_target_vs_fixed_3x(top10_rows, market=market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    intraday_contribution = _intraday_contribution(source_rows)
    v2_rows = _run_v2_narrow_grid(market=market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    v2_rows = sorted(v2_rows, key=lambda row: (-float(row["annual_return_pct"]), float(row["max_drawdown_abs_pct"]), row["variant_id"]))
    v2_watchlist = [row for row in v2_rows if row["retention_decision"] == "retain_high_yield_near_miss_research_watchlist_only"]

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_small_account_high_yield_near_miss_research_only_no_paper_no_live",
        "scope": "near_miss_review_and_v2_narrow_grid_only",
        "code_commit": _git_commit(),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "source_high_yield_report_path": _portable_path(source_high_yield_report_path),
            "source_top5_report_path": _portable_path(source_top5_report_path),
            "base_variant_id": market.get("base_variant_id"),
            "source_best_variant_id": source_report.get("summary", {}).get("best_variant_id") if isinstance(source_report.get("summary"), Mapping) else None,
        },
        "validation_design": {
            "target_annual_return_pct": HIGH_YIELD_TARGET_ANNUAL_RETURN_PCT,
            "top10_review_count": len(top10_review),
            "v2_candidate_count": len(v2_rows),
            "v2_expected_candidate_count": 270,
            "v2_grid": {
                "vol_targets_pct": list(V2_VOL_TARGETS),
                "max_leverages": list(V2_MAX_LEVERAGES),
                "drawdown_gates_pct": list(V2_DRAWDOWN_GATES),
                "min_liquidation_buffers_bps": list(V2_LIQUIDATION_BUFFERS_BPS),
                "trendless_filters": ["off", "on"],
            },
            "trendless_filter": {
                "enabled_values": ["off", "on"],
                "formula": "abs(close / close.shift(72) - 1) / rolling_sum(abs(4h_return), 72)",
                "uses_shift_1": True,
                "threshold": TRENDLESS_EFFICIENCY_THRESHOLD,
            },
            "paper_live_boundary": "research_only_watchlist_only",
        },
        "near_miss_summary": _near_miss_summary(top10_review, v2_rows, v2_watchlist),
        "top10_near_miss_review": top10_review,
        "vol_target_120_vs_fixed_3x": vol_vs_fixed,
        "intraday_contribution": intraday_contribution,
        "v2_narrow_grid_rows": v2_rows,
        "high_yield_near_miss_research_watchlist": v2_watchlist,
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(top10_review, v2_rows, intraday_contribution),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "top10_review_csv": _portable_path(top10_csv_path),
            "v2_grid_csv": _portable_path(v2_grid_csv_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(top10_csv_path, top10_review)
    _write_csv(v2_grid_csv_path, v2_rows)
    _write_json(safety_path, _safety_status(report))
    _write_text(markdown_path, render_btc_small_account_high_yield_near_miss_markdown(report))
    return report


def _prepare_market_context(
    *,
    market_db_path: Path,
    derivatives_rows_path: Path,
    initial_capital: float,
    base_cost_bps: float,
) -> dict[str, Any]:
    blockers: list[str] = []
    source_1h = load_market_1h(market_db_path)
    bars_4h = aggregate_ohlcv(source_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(source_1h, interval_hours=24)
    bars_1w = aggregate_ohlcv_calendar(source_1h, timeframe="1w")
    bars_1mo = aggregate_ohlcv_calendar(source_1h, timeframe="1mo")
    derivatives_4h = align_derivatives_to_index(derivatives_rows_path, bars_4h.index)
    spec_map = {spec.variant_id: spec for spec in long_short_trend_following_specs(run_profile="formal_narrow")}
    base_spec = spec_map.get(BEST_BASE_VARIANT_ID)
    if base_spec is None:
        blockers.append("btc_high_yield_near_miss_best_base_spec_missing")
        base_signal = pd.Series(0.0, index=bars_4h.index)
        base_variant_id = BEST_BASE_VARIANT_ID
    else:
        item = evaluate_long_short_trend_rule(
            base_spec,
            bars_4h=bars_4h,
            bars_1d=bars_1d,
            bars_1w=bars_1w,
            bars_1mo=bars_1mo,
            derivatives_4h=derivatives_4h,
            initial_capital=initial_capital,
            cost_bps=base_cost_bps,
        )
        base_signal = item.exposure
        base_variant_id = base_spec.variant_id
    return {
        "blockers": blockers,
        "bars_4h": bars_4h,
        "bars_1d": bars_1d,
        "derivatives_4h": derivatives_4h,
        "base_signal": base_signal,
        "base_variant_id": base_variant_id,
        "market_db_path": market_db_path,
        "derivatives_rows_path": derivatives_rows_path,
    }


def _review_top10_near_misses(
    rows: Sequence[Mapping[str, Any]],
    *,
    market: Mapping[str, Any],
    initial_capital: float,
    base_cost_bps: float,
) -> list[dict[str, Any]]:
    review_rows: list[dict[str, Any]] = []
    for rank, row in enumerate(rows, start=1):
        variant = _variant_from_source_row(row)
        base_signal, bars, derivatives = _signal_context_for_variant(variant, market=market)
        current = _simulate_review_variant(
            variant,
            base_signal=base_signal,
            bars=bars,
            derivatives=derivatives,
            initial_capital=initial_capital,
            cost_bps=base_cost_bps,
            policy=ReviewPolicy(),
        )
        no_cost = _simulate_review_variant(
            variant,
            base_signal=base_signal,
            bars=bars,
            derivatives=derivatives,
            initial_capital=initial_capital,
            cost_bps=0.0,
            policy=ReviewPolicy(enable_costs=False),
        )
        no_drawdown = _simulate_review_variant(
            variant,
            base_signal=base_signal,
            bars=bars,
            derivatives=derivatives,
            initial_capital=initial_capital,
            cost_bps=base_cost_bps,
            policy=ReviewPolicy(enable_drawdown_gate=False),
        )
        no_consecutive = _simulate_review_variant(
            variant,
            base_signal=base_signal,
            bars=bars,
            derivatives=derivatives,
            initial_capital=initial_capital,
            cost_bps=base_cost_bps,
            policy=ReviewPolicy(enable_consecutive_loss_derisk=False),
        )
        no_liq_buffer = _simulate_review_variant(
            variant,
            base_signal=base_signal,
            bars=bars,
            derivatives=derivatives,
            initial_capital=initial_capital,
            cost_bps=base_cost_bps,
            policy=ReviewPolicy(enable_liquidation_buffer_derisk=False),
        )
        gap = max(0.0, HIGH_YIELD_TARGET_ANNUAL_RETURN_PCT - float(row.get("annual_return_pct", current.metrics["annual_return_pct"])))
        explained = sum(
            max(0.0, float(sim.metrics["annual_return_pct"]) - float(current.metrics["annual_return_pct"]))
            for sim in (no_cost, no_drawdown, no_consecutive, no_liq_buffer)
        )
        review_rows.append(
            {
                "rank": rank,
                "variant_id": row.get("variant_id"),
                "bucket": row.get("bucket"),
                "mode": row.get("mode"),
                "annual_return_pct": row.get("annual_return_pct", current.metrics["annual_return_pct"]),
                "gap_to_60_pct": _round(gap),
                "cost_drag_annual_pct": _counterfactual_gain(current, no_cost),
                "drawdown_gate_drag_annual_pct": _counterfactual_gain(current, no_drawdown),
                "consecutive_loss_derisk_drag_annual_pct": _counterfactual_gain(current, no_consecutive),
                "liquidation_buffer_derisk_drag_annual_pct": _counterfactual_gain(current, no_liq_buffer),
                "trendless_or_low_exposure_gap_pct": _round(max(0.0, gap - explained)),
                "average_exposure": row.get("average_exposure", current.metrics["average_exposure"]),
                "bars_with_exposure": current.metrics["bars_with_exposure"],
                "turnover": row.get("turnover", current.metrics["turnover"]),
                "max_drawdown_abs_pct": row.get("max_drawdown_abs_pct", current.metrics["max_drawdown_abs_pct"]),
                "profit_factor": row.get("profit_factor", current.metrics["profit_factor"]),
                "cost_2x_total_return_pct": row.get("cost_2x_total_return_pct"),
                "forced_risk_reduction_count": current.diagnostics["forced_risk_reduction_count"],
                "consecutive_loss_derisk_count": current.diagnostics["consecutive_loss_derisk_count"],
                "drawdown_stop_count": current.diagnostics["drawdown_stop_count"],
                "liquidation_buffer_derisk_count": current.diagnostics["liquidation_buffer_derisk_count"],
                "simulated_liquidation_count": current.diagnostics["simulated_liquidation_count"],
                "min_liquidation_buffer_bps": current.diagnostics["min_liquidation_buffer_bps"],
                "diagnosis": _near_miss_diagnosis(gap, explained, current),
                "paper_queue_write_allowed": False,
                "paper_candidate_created": False,
                "live_unlock_allowed": False,
            }
        )
    return review_rows


def _vol_target_vs_fixed_3x(
    rows: Sequence[Mapping[str, Any]],
    *,
    market: Mapping[str, Any],
    initial_capital: float,
    base_cost_bps: float,
) -> dict[str, Any]:
    vol_row = next((row for row in rows if row.get("base_variant_id") == BEST_BASE_VARIANT_ID and row.get("target_volatility_pct") == 120.0), {})
    fixed_row = next((row for row in rows if row.get("base_variant_id") == BEST_BASE_VARIANT_ID and row.get("fixed_leverage") == 3.0), {})
    vol_variant = _variant_from_source_row(vol_row) if vol_row else _v2_variant(120.0, 3.0, "vol_vs_fixed_vol_target_120")
    fixed_variant = _variant_from_source_row(fixed_row) if fixed_row else ReviewVariant(
        bucket="donchian_leverage_overlay",
        variant_id="vol_vs_fixed_fixed_3x",
        base_variant_id=BEST_BASE_VARIANT_ID,
        mode="fixed_leverage",
        fixed_leverage=3.0,
        target_volatility_pct=None,
        max_leverage=3.0,
        interval="4h",
        interval_hours=4.0,
        signal_kind="donchian_top5_overlay",
    )
    base_signal, bars, derivatives = _signal_context_for_variant(vol_variant, market=market)
    vol = _simulate_review_variant(vol_variant, base_signal=base_signal, bars=bars, derivatives=derivatives, initial_capital=initial_capital, cost_bps=base_cost_bps, policy=ReviewPolicy())
    fixed = _simulate_review_variant(fixed_variant, base_signal=base_signal, bars=bars, derivatives=derivatives, initial_capital=initial_capital, cost_bps=base_cost_bps, policy=ReviewPolicy())
    vol_hv = _high_vol_loss_profile(vol, bars=bars)
    fixed_hv = _high_vol_loss_profile(fixed, bars=bars)
    return {
        "same_window_same_signal": True,
        "vol_target_variant_id": vol_variant.variant_id,
        "fixed_3x_variant_id": fixed_variant.variant_id,
        "vol_target_120": _comparison_metrics(vol),
        "fixed_3x": _comparison_metrics(fixed),
        "high_volatility_loss_comparison": {
            "vol_target_120": vol_hv,
            "fixed_3x": fixed_hv,
            "vol_target_less_negative_high_vol_loss": bool(vol_hv["negative_return_pct"] > fixed_hv["negative_return_pct"]),
        },
        "diagnosis": (
            "vol_target_120_reduced_drawdown_and_high_volatility_loss_vs_fixed_3x"
            if float(vol.metrics["max_drawdown_abs_pct"]) < float(fixed.metrics["max_drawdown_abs_pct"])
            else "vol_target_120_did_not_reduce_drawdown_vs_fixed_3x"
        ),
    }


def _intraday_contribution(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_bucket: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_bucket.setdefault(str(row.get("bucket")), []).append(row)
    bucket_rows = []
    for bucket, items in sorted(by_bucket.items()):
        sorted_items = sorted(items, key=lambda row: -float(row.get("annual_return_pct", 0.0)))
        best = sorted_items[0] if sorted_items else {}
        bucket_rows.append(
            {
                "bucket": bucket,
                "candidate_count": len(sorted_items),
                "best_variant_id": best.get("variant_id"),
                "best_annual_return_pct": best.get("annual_return_pct", 0.0),
                "best_max_drawdown_abs_pct": best.get("max_drawdown_abs_pct", 0.0),
                "best_profit_factor": best.get("profit_factor", 0.0),
                "best_cost_2x_total_return_pct": best.get("cost_2x_total_return_pct", 0.0),
                "best_turnover": best.get("turnover", 0.0),
            }
        )
    donchian = next((row for row in bucket_rows if row["bucket"] == "donchian_leverage_overlay"), {})
    intraday = next((row for row in bucket_rows if row["bucket"] == "intraday_15m"), {})
    intraday_has_edge = bool(intraday) and float(intraday.get("best_annual_return_pct", -999.0)) > float(donchian.get("best_annual_return_pct", 0.0))
    return {
        "bucket_comparison": bucket_rows,
        "intraday_15m_evaluated": bool(intraday),
        "intraday_15m_not_mixed_into_v2_grid": True,
        "diagnosis": "intraday_15m_has_current_topline_edge" if intraday_has_edge else "four_hour_donchian_high_yield_overlay_remains_stronger",
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _run_v2_narrow_grid(*, market: Mapping[str, Any], initial_capital: float, base_cost_bps: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    base_signal = market["base_signal"]
    bars = market["bars_4h"]
    derivatives = market["derivatives_4h"]
    for vol_target in V2_VOL_TARGETS:
        for max_leverage in V2_MAX_LEVERAGES:
            for drawdown_gate in V2_DRAWDOWN_GATES:
                for liq_buffer in V2_LIQUIDATION_BUFFERS_BPS:
                    for trendless_on in V2_TRENDLESS_FILTERS:
                        variant = _v2_variant(
                            vol_target,
                            max_leverage,
                            f"hy_v2_donchian_w240_d50_200_cd12_vt{int(vol_target)}_max{str(max_leverage).replace('.', 'p')}_dd{int(drawdown_gate)}_liq{int(liq_buffer)}_trend{'on' if trendless_on else 'off'}",
                        )
                        policy = ReviewPolicy(
                            drawdown_gate_pct=drawdown_gate,
                            min_liquidation_buffer_bps=liq_buffer,
                            enable_trendless_filter=trendless_on,
                        )
                        sim = _simulate_review_variant(
                            variant,
                            base_signal=base_signal,
                            bars=bars,
                            derivatives=derivatives,
                            initial_capital=initial_capital,
                            cost_bps=base_cost_bps,
                            policy=policy,
                        )
                        cost_2x = _cost_2x_proxy(sim, initial_capital=initial_capital)
                        rows.append(_v2_row(sim, cost_2x=cost_2x))
    return rows


def _simulate_review_variant(
    variant: ReviewVariant,
    *,
    base_signal: pd.Series,
    bars: pd.DataFrame,
    derivatives: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
    policy: ReviewPolicy,
) -> ReviewSimulation:
    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    index = close.index
    base = base_signal.reindex(index).fillna(0.0).clip(-1.0, 1.0)
    leverage = _leverage_series(variant, close=close)
    raw_target = (base * leverage).clip(-variant.max_leverage, variant.max_leverage)
    target = _apply_crowding_filter(raw_target, derivatives.reindex(index))
    target = _apply_high_vol_trend_boost(target, close=close, max_leverage=variant.max_leverage)
    trendless_filter_bar_count = 0
    if policy.enable_trendless_filter:
        trend_efficiency = _trend_efficiency_72(close)
        before = target.copy()
        target.loc[trend_efficiency < policy.trend_efficiency_threshold] = 0.0
        trendless_filter_bar_count = int(((before.abs() > 1e-12) & (target.abs() <= 1e-12)).sum())

    close_returns = close.pct_change().fillna(0.0)
    funding = pd.to_numeric(derivatives.reindex(index).get("funding_rate", pd.Series(0.0, index=index)), errors="coerce").fillna(0.0)
    actual_exposure: list[float] = []
    returns: list[float] = []
    costs: list[float] = []
    funding_pnl: list[float] = []
    equity_values: list[float] = []
    previous_exposure = 0.0
    equity = float(initial_capital)
    peak = equity
    cooldown_until = -1
    derisk_until = -1
    drawdown_locked = False
    consecutive_loss_bars = 0
    forced_reduce_count = 0
    partial_take_profit_count = 0
    consecutive_loss_derisk_count = 0
    failed_breakout_exit_count = 0
    drawdown_stop_count = 0
    simulated_liquidation_count = 0
    liquidation_buffer_derisk_count = 0
    min_liquidation_buffer_bps: float | None = None
    crowding_filter_bar_count = int((target.abs() < raw_target.abs().reindex(index).fillna(0.0) - 1e-12).sum())
    open_trade_age = 0
    previous_side = 0.0

    for pos, _ts in enumerate(index):
        desired = float(target.iloc[pos])
        if drawdown_locked or pos < cooldown_until:
            desired = 0.0
        elif pos < derisk_until:
            desired *= float(policy.consecutive_loss_derisk_factor)
        turnover = abs(desired - previous_exposure)
        cost = turnover * (float(cost_bps) / 10_000.0) if policy.enable_costs else 0.0
        fund = -desired * float(funding.iloc[pos]) * (variant.interval_hours / 8.0)
        bar_return = desired * float(close_returns.iloc[pos]) - cost + fund

        if pos > 0 and abs(desired) > 1e-12:
            current_side = math.copysign(1.0, desired)
            if current_side != previous_side:
                open_trade_age = 0
            else:
                open_trade_age += 1
            prev_close = float(close.iloc[pos - 1])
            if desired > 0.0:
                adverse = max(0.0, 1.0 - float(low.iloc[pos]) / prev_close)
                favorable = max(0.0, float(high.iloc[pos]) / prev_close - 1.0)
            else:
                adverse = max(0.0, float(high.iloc[pos]) / prev_close - 1.0)
                favorable = max(0.0, 1.0 - float(low.iloc[pos]) / prev_close)
            exposure_abs = abs(desired)
            liquidation_threshold = 0.80 / exposure_abs
            buffer_bps = max(0.0, (liquidation_threshold - adverse) * 10_000.0)
            min_liquidation_buffer_bps = buffer_bps if min_liquidation_buffer_bps is None else min(min_liquidation_buffer_bps, buffer_bps)
            fast_stop = max(
                float(policy.fast_stop_floor_pct) / 100.0,
                min(float(policy.fast_stop_cap_pct) / 100.0, (float(policy.fast_stop_base_pct) / 100.0) / exposure_abs),
            )
            take_profit = max(0.03, min(0.10, 0.09 / exposure_abs))
            if adverse >= liquidation_threshold:
                simulated_liquidation_count += 1
                forced_reduce_count += 1
                bar_return = -0.80 - cost + fund
                cooldown_until = max(cooldown_until, pos + 12)
                desired = 0.0
            elif policy.enable_liquidation_buffer_derisk and buffer_bps < policy.min_liquidation_buffer_bps:
                liquidation_buffer_derisk_count += 1
                forced_reduce_count += 1
                desired *= 0.5
                cooldown_until = max(cooldown_until, pos + int(policy.liquidation_buffer_cooldown_bars))
            elif adverse >= fast_stop:
                forced_reduce_count += 1
                bar_return = -exposure_abs * fast_stop - cost + fund
                cooldown_until = max(cooldown_until, pos + int(policy.stop_cooldown_bars))
                desired = 0.0
            elif (
                policy.enable_failed_breakout_exit
                and open_trade_age <= int(policy.failed_breakout_window_bars)
                and desired * float(close_returns.iloc[pos]) < -float(policy.failed_breakout_return_threshold_pct) / 100.0
            ):
                failed_breakout_exit_count += 1
                forced_reduce_count += 1
                cooldown_until = max(cooldown_until, pos + int(policy.failed_breakout_cooldown_bars))
                desired = 0.0
            elif favorable >= take_profit:
                partial_take_profit_count += 1
                signed_take = math.copysign(take_profit, desired)
                bar_return = desired * (0.5 * signed_take + 0.5 * float(close_returns.iloc[pos])) - cost + fund
                derisk_until = max(derisk_until, pos + 2)

        equity *= 1.0 + bar_return
        peak = max(peak, equity)
        drawdown = equity / peak - 1.0 if peak > 0.0 else -1.0
        if policy.enable_drawdown_gate and drawdown <= -policy.drawdown_gate_pct / 100.0 and not drawdown_locked:
            drawdown_locked = True
            drawdown_stop_count += 1
            cooldown_until = len(index) + 1
        if abs(desired) > 1e-12 and bar_return < 0.0:
            consecutive_loss_bars += 1
        elif bar_return > 0.0:
            consecutive_loss_bars = 0
        if policy.enable_consecutive_loss_derisk and consecutive_loss_bars >= int(policy.consecutive_loss_trigger_bars):
            derisk_until = max(derisk_until, pos + int(policy.consecutive_loss_derisk_bars))
            consecutive_loss_derisk_count += 1
            consecutive_loss_bars = 0

        actual_exposure.append(float(desired))
        returns.append(float(bar_return))
        costs.append(float(cost))
        funding_pnl.append(float(fund))
        equity_values.append(float(equity))
        previous_exposure = float(desired)
        previous_side = math.copysign(1.0, desired) if abs(desired) > 1e-12 else 0.0

    exposure = pd.Series(actual_exposure, index=index, dtype=float)
    strategy_returns = pd.Series(returns, index=index, dtype=float)
    cost_series = pd.Series(costs, index=index, dtype=float)
    funding_series = pd.Series(funding_pnl, index=index, dtype=float)
    equity_series = pd.Series(equity_values, index=index, dtype=float)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    metrics = _performance_metrics(
        strategy_returns=strategy_returns,
        equity=equity_series,
        exposure=exposure,
        turnover=turnover,
        cost=cost_series,
        interval=variant.interval,
        initial_capital=initial_capital,
    )
    metrics["funding_return_pct"] = _round(float(funding_series.sum()) * 100.0)
    metrics["trading_cost_return_pct"] = _round(float(cost_series.sum()) * -100.0)
    diagnostics = {
        "forced_risk_reduction_count": forced_reduce_count,
        "partial_take_profit_count": partial_take_profit_count,
        "consecutive_loss_derisk_count": consecutive_loss_derisk_count,
        "failed_breakout_exit_count": failed_breakout_exit_count,
        "drawdown_stop_count": drawdown_stop_count,
        "simulated_liquidation_count": simulated_liquidation_count,
        "liquidation_buffer_derisk_count": liquidation_buffer_derisk_count,
        "min_liquidation_buffer_bps": _round(min_liquidation_buffer_bps or 0.0),
        "crowding_filter_bar_count": crowding_filter_bar_count,
        "trendless_filter_bar_count": trendless_filter_bar_count,
        "risk_research_approximation": True,
    }
    return ReviewSimulation(variant, policy, exposure, strategy_returns, turnover, cost_series, funding_series, equity_series, metrics, diagnostics)


def _signal_context_for_variant(variant: ReviewVariant, *, market: Mapping[str, Any]) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    if variant.bucket == "intraday_15m":
        bars_15m = load_market_klines_frame(Path(market["market_db_path"]), interval="15m")
        derivatives_15m = align_derivatives_to_index(Path(market["derivatives_rows_path"]), bars_15m.index)
        signal = _intraday_signal(bars_15m, kind=variant.signal_kind).shift(1).fillna(0.0)
        return signal, bars_15m, derivatives_15m
    return market["base_signal"], market["bars_4h"], market["derivatives_4h"]


def _variant_from_source_row(row: Mapping[str, Any]) -> ReviewVariant:
    return ReviewVariant(
        bucket=str(row.get("bucket") or "donchian_leverage_overlay"),
        variant_id=str(row.get("variant_id") or "unknown_variant"),
        base_variant_id=str(row.get("base_variant_id") or BEST_BASE_VARIANT_ID),
        mode=str(row.get("mode") or "volatility_target"),
        fixed_leverage=_optional_float(row.get("fixed_leverage")),
        target_volatility_pct=_optional_float(row.get("target_volatility_pct")),
        max_leverage=float(row.get("max_leverage") or 3.0),
        interval=str(row.get("interval") or "4h"),
        interval_hours=0.25 if str(row.get("interval") or "4h") == "15m" else 4.0,
        signal_kind=str(row.get("signal_kind") or "donchian_top5_overlay"),
    )


def _v2_variant(vol_target: float, max_leverage: float, variant_id: str) -> ReviewVariant:
    return ReviewVariant(
        bucket="donchian_v2_narrow_grid",
        variant_id=variant_id,
        base_variant_id=BEST_BASE_VARIANT_ID,
        mode="volatility_target",
        fixed_leverage=None,
        target_volatility_pct=float(vol_target),
        max_leverage=float(max_leverage),
        interval="4h",
        interval_hours=4.0,
        signal_kind="donchian_top5_overlay",
    )


def _v2_row(sim: ReviewSimulation, *, cost_2x: Mapping[str, Any]) -> dict[str, Any]:
    m = sim.metrics
    d = sim.diagnostics
    decision = _v2_retention_decision(m, d, cost_2x)
    return {
        "variant_id": sim.variant.variant_id,
        "bucket": sim.variant.bucket,
        "base_variant_id": sim.variant.base_variant_id,
        "vol_target_pct": sim.variant.target_volatility_pct,
        "max_leverage": sim.variant.max_leverage,
        "drawdown_gate_pct": sim.policy.drawdown_gate_pct,
        "min_liquidation_buffer_bps_policy": sim.policy.min_liquidation_buffer_bps,
        "trendless_filter": "on" if sim.policy.enable_trendless_filter else "off",
        "trend_efficiency_threshold": sim.policy.trend_efficiency_threshold,
        "annual_return_pct": m["annual_return_pct"],
        "total_return_pct": m["total_return_pct"],
        "max_drawdown_abs_pct": m["max_drawdown_abs_pct"],
        "max_drawdown_pct": m["max_drawdown_pct"],
        "calmar_ratio": m["calmar_ratio"],
        "profit_factor": m["profit_factor"],
        "average_exposure": m["average_exposure"],
        "turnover": m["turnover"],
        "cost_2x_total_return_pct": cost_2x["total_return_pct"],
        "cost_2x_profit_factor": cost_2x["profit_factor"],
        "forced_risk_reduction_count": d["forced_risk_reduction_count"],
        "consecutive_loss_derisk_count": d["consecutive_loss_derisk_count"],
        "drawdown_stop_count": d["drawdown_stop_count"],
        "liquidation_buffer_derisk_count": d["liquidation_buffer_derisk_count"],
        "trendless_filter_bar_count": d["trendless_filter_bar_count"],
        "simulated_liquidation_count": d["simulated_liquidation_count"],
        "min_liquidation_buffer_bps": d["min_liquidation_buffer_bps"],
        "retention_decision": decision,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
    }


def _v2_retention_decision(metrics: Mapping[str, Any], diagnostics: Mapping[str, Any], cost_2x: Mapping[str, Any]) -> str:
    if float(metrics.get("annual_return_pct", 0.0)) < HIGH_YIELD_TARGET_ANNUAL_RETURN_PCT:
        return "reject_v2_annual_return_below_60"
    if float(metrics.get("max_drawdown_abs_pct", 999.0)) > 40.0:
        return "reject_v2_drawdown_above_40"
    if float(metrics.get("profit_factor", 0.0)) < MIN_PROFIT_FACTOR:
        return "reject_v2_profit_factor_below_1p15"
    if int(diagnostics.get("simulated_liquidation_count", 0)) > 0:
        return "reject_v2_simulated_liquidation"
    if float(cost_2x.get("total_return_pct", 0.0)) <= 0.0:
        return "reject_v2_cost_2x_non_positive"
    return "retain_high_yield_near_miss_research_watchlist_only"


def _leverage_series(variant: ReviewVariant, *, close: pd.Series) -> pd.Series:
    if variant.mode == "fixed_leverage":
        return pd.Series(float(variant.fixed_leverage or 1.0), index=close.index)
    returns = close.pct_change().fillna(0.0)
    bars_per_year = _bars_per_year(variant.interval)
    window = 42 if variant.interval == "4h" else 96
    realized = returns.rolling(window, min_periods=max(10, window // 3)).std(ddof=0).shift(1) * math.sqrt(bars_per_year)
    target = float(variant.target_volatility_pct or 60.0) / 100.0
    leverage = (target / realized.replace(0.0, math.nan)).replace([math.inf, -math.inf], math.nan).fillna(1.0)
    return leverage.clip(0.0, float(variant.max_leverage))


def _apply_crowding_filter(target: pd.Series, derivatives: pd.DataFrame) -> pd.Series:
    if derivatives.empty:
        return target
    funding = pd.to_numeric(derivatives.get("funding_rate", pd.Series(0.0, index=target.index)), errors="coerce").fillna(0.0)
    oi = pd.to_numeric(derivatives.get("open_interest_usd", pd.Series(math.nan, index=target.index)), errors="coerce")
    long_short = pd.to_numeric(derivatives.get("long_short_ratio", pd.Series(math.nan, index=target.index)), errors="coerce")
    oi_change = oi.pct_change()
    oi_mean = oi_change.rolling(60, min_periods=20).mean().shift(1)
    oi_std = oi_change.rolling(60, min_periods=20).std(ddof=0).shift(1)
    oi_z = ((oi_change - oi_mean) / oi_std.replace(0.0, math.nan)).fillna(0.0)
    long_crowded = (funding > 0.0003) | (oi_z > 2.5) | (long_short > 1.30)
    short_crowded = (funding < -0.0003) | (oi_z > 2.5) | (long_short < 0.75)
    output = target.copy()
    output.loc[(target > 0.0) & long_crowded] = 0.0
    output.loc[(target < 0.0) & short_crowded] = 0.0
    return output


def _apply_high_vol_trend_boost(target: pd.Series, *, close: pd.Series, max_leverage: float) -> pd.Series:
    returns = close.pct_change().fillna(0.0)
    realized = returns.rolling(6, min_periods=4).std(ddof=0)
    cap = realized.rolling(180, min_periods=60).quantile(0.85).shift(1)
    high_vol = (realized > cap) & cap.notna() & (target.abs() > 0.0)
    output = target.copy()
    output.loc[high_vol] = (output.loc[high_vol] * 1.15).clip(-float(max_leverage), float(max_leverage))
    return output


def _trend_efficiency_72(close: pd.Series) -> pd.Series:
    returns = close.pct_change().fillna(0.0)
    numerator = (close / close.shift(72) - 1.0).abs()
    denominator = returns.abs().rolling(72, min_periods=30).sum()
    return (numerator / denominator.replace(0.0, math.nan)).shift(1).fillna(0.0)


def _performance_metrics(
    *,
    strategy_returns: pd.Series,
    equity: pd.Series,
    exposure: pd.Series,
    turnover: pd.Series,
    cost: pd.Series,
    interval: str,
    initial_capital: float,
) -> dict[str, Any]:
    if strategy_returns.empty:
        return {
            "total_return_pct": 0.0,
            "annual_return_pct": 0.0,
            "annual_volatility_pct": 0.0,
            "sharpe_ratio": 0.0,
            "calmar_ratio": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "max_drawdown_abs_pct": 0.0,
            "final_equity": _round(initial_capital),
            "average_exposure": 0.0,
            "bars_with_exposure": 0,
            "turnover": 0.0,
            "fee_return_pct": 0.0,
        }
    total_return = float(equity.iloc[-1] / float(initial_capital) - 1.0)
    elapsed_days = max(1.0, float((strategy_returns.index.max() - strategy_returns.index.min()).total_seconds()) / 86_400.0)
    annual_return = (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0 if total_return > -1.0 else -1.0
    bars_per_year = _bars_per_year(interval)
    std = float(strategy_returns.std(ddof=0))
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
    positive = float(strategy_returns[strategy_returns > 0.0].sum())
    negative = float(strategy_returns[strategy_returns < 0.0].sum())
    profit_factor = positive / abs(negative) if negative < 0.0 else (999.0 if positive > 0.0 else 0.0)
    return {
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "annual_volatility_pct": _round(std * math.sqrt(bars_per_year) * 100.0),
        "sharpe_ratio": _round(float(strategy_returns.mean() / std * math.sqrt(bars_per_year)) if std > 0.0 else 0.0),
        "calmar_ratio": _round(float(annual_return / abs(max_drawdown)) if max_drawdown < 0.0 else 0.0),
        "profit_factor": _round(profit_factor),
        "max_drawdown_pct": _round(max_drawdown * 100.0),
        "max_drawdown_abs_pct": _round(abs(max_drawdown) * 100.0),
        "final_equity": _round(float(equity.iloc[-1])),
        "average_exposure": _round(float(exposure.abs().mean())),
        "bars_with_exposure": int((exposure.abs() > 0.0).sum()),
        "turnover": _round(float(turnover.sum())),
        "fee_return_pct": _round(float(cost.sum()) * -100.0),
    }


def _cost_2x_proxy(sim: ReviewSimulation, *, initial_capital: float) -> dict[str, Any]:
    returns = sim.returns - sim.cost
    equity = initial_capital * (1.0 + returns).cumprod()
    return _performance_metrics(
        strategy_returns=returns,
        equity=equity,
        exposure=sim.exposure,
        turnover=sim.turnover,
        cost=sim.cost * 2.0,
        interval=sim.variant.interval,
        initial_capital=initial_capital,
    )


def _high_vol_loss_profile(sim: ReviewSimulation, *, bars: pd.DataFrame) -> dict[str, Any]:
    close = bars["close"].astype(float).reindex(sim.returns.index)
    realized = close.pct_change().fillna(0.0).rolling(6, min_periods=4).std(ddof=0)
    cap = realized.rolling(180, min_periods=60).quantile(0.85).shift(1)
    mask = (realized > cap) & cap.notna()
    subset = sim.returns.loc[mask]
    exposure = sim.exposure.loc[mask]
    return {
        "bar_count": int(mask.sum()),
        "total_return_pct": _round(float(subset.sum()) * 100.0) if len(subset) else 0.0,
        "negative_return_pct": _round(float(subset[subset < 0.0].sum()) * 100.0) if len(subset) else 0.0,
        "average_exposure": _round(float(exposure.abs().mean())) if len(exposure) else 0.0,
    }


def _comparison_metrics(sim: ReviewSimulation) -> dict[str, Any]:
    return {
        "annual_return_pct": sim.metrics["annual_return_pct"],
        "max_drawdown_abs_pct": sim.metrics["max_drawdown_abs_pct"],
        "profit_factor": sim.metrics["profit_factor"],
        "calmar_ratio": sim.metrics["calmar_ratio"],
        "average_exposure": sim.metrics["average_exposure"],
        "forced_risk_reduction_count": sim.diagnostics["forced_risk_reduction_count"],
        "consecutive_loss_derisk_count": sim.diagnostics["consecutive_loss_derisk_count"],
        "min_liquidation_buffer_bps": sim.diagnostics["min_liquidation_buffer_bps"],
    }


def _near_miss_summary(
    top10_review: Sequence[Mapping[str, Any]],
    v2_rows: Sequence[Mapping[str, Any]],
    watchlist: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    best_v2 = v2_rows[0] if v2_rows else {}
    return {
        "top10_review_count": len(top10_review),
        "v2_candidate_count": len(v2_rows),
        "v2_watchlist_count": len(watchlist),
        "best_v2_variant_id": best_v2.get("variant_id"),
        "best_v2_annual_return_pct": best_v2.get("annual_return_pct", 0.0),
        "best_v2_max_drawdown_abs_pct": best_v2.get("max_drawdown_abs_pct", 0.0),
        "best_v2_profit_factor": best_v2.get("profit_factor", 0.0),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _near_miss_diagnosis(gap: float, explained: float, sim: ReviewSimulation) -> str:
    if gap <= 0.0:
        return "already_meets_60pct_threshold_research_only"
    if sim.diagnostics["drawdown_stop_count"] > 0:
        return "drawdown_gate_constrains_return"
    if sim.diagnostics["consecutive_loss_derisk_count"] > 0 and explained >= gap:
        return "risk_derisk_controls_explain_gap"
    if explained < gap:
        return "gap_not_fully_explained_by_risk_controls_likely_low_exposure_or_no_trend_time"
    return "gap_explained_by_cost_and_risk_controls"


def _counterfactual_gain(current: ReviewSimulation, counterfactual: ReviewSimulation) -> float:
    return _round(max(0.0, float(counterfactual.metrics["annual_return_pct"]) - float(current.metrics["annual_return_pct"])))


def _warnings(
    top10_review: Sequence[Mapping[str, Any]],
    v2_rows: Sequence[Mapping[str, Any]],
    intraday_contribution: Mapping[str, Any],
) -> list[str]:
    warnings = ["btc_high_yield_near_miss_research_only_no_paper_no_live"]
    if any(float(row.get("gap_to_60_pct", 0.0)) > 0.0 for row in top10_review):
        warnings.append("near_miss_candidates_remain_below_60pct_target")
    if any(row.get("retention_decision") == "retain_high_yield_near_miss_research_watchlist_only" for row in v2_rows):
        warnings.append("v2_candidates_require_manual_extended_research_review_only")
    if intraday_contribution.get("diagnosis") != "intraday_15m_has_current_topline_edge":
        warnings.append("intraday_15m_currently_diagnostic_not_primary_edge")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_small_account_high_yield_near_miss_safety_status_v1",
        "status": "research_only",
        "watchlist_count": len(report.get("high_yield_near_miss_research_watchlist", [])),
        "blockers": list(report.get("blockers", [])),
        **_gate(),
    }


def _gate() -> dict[str, Any]:
    return {
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "strategy_skeleton_generated": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "reason": "near-miss and v2 high-yield variants are research-only diagnostics; they cannot unlock paper or live",
    }


def _guardrails() -> dict[str, Any]:
    return {
        "research_only": True,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "real_order_submitted": False,
    }


def render_btc_small_account_high_yield_near_miss_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("near_miss_summary", {})
    gate = report.get("gate", {})
    lines = [
        "# BTC 高收益 Near-Miss 复核包",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策边界：`{report.get('decision')}`",
        f"- Top10 复核数：`{summary.get('top10_review_count')}`",
        f"- v2 窄网格候选数：`{summary.get('v2_candidate_count')}`",
        f"- v2 研究短名单数：`{summary.get('v2_watchlist_count')}`",
        f"- v2 最佳候选：`{summary.get('best_v2_variant_id')}`",
        f"- v2 最佳年化：`{summary.get('best_v2_annual_return_pct')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 三个问题的回答",
        "",
    ]
    top = (report.get("top10_near_miss_review") or [{}])[0]
    lines.extend(
        [
            f"- 57.19% 到 60% 的差距：最佳候选差距约 `{top.get('gap_to_60_pct')}` 个百分点；成本拖累约 `{top.get('cost_drag_annual_pct')}`，回撤闸门拖累约 `{top.get('drawdown_gate_drag_annual_pct')}`，连亏降仓拖累约 `{top.get('consecutive_loss_derisk_drag_annual_pct')}`，强平缓冲降仓拖累约 `{top.get('liquidation_buffer_derisk_drag_annual_pct')}`，剩余低暴露/无趋势差距约 `{top.get('trendless_or_low_exposure_gap_pct')}`。",
            f"- vol_target_120 vs fixed_3x：`{(report.get('vol_target_120_vs_fixed_3x') or {}).get('diagnosis')}`。",
            f"- 15m intraday：`{(report.get('intraday_contribution') or {}).get('diagnosis')}`；本轮没有把 intraday 并入 v2 网格。",
            "",
            "## Top v2",
            "",
            "| 排名 | 候选 | 年化 | 回撤 | PF | 2x成本收益 | 结论 |",
            "|---:|---|---:|---:|---:|---:|---|",
        ]
    )
    for idx, row in enumerate((report.get("v2_narrow_grid_rows") or [])[:10], start=1):
        lines.append(
            f"| {idx} | `{row.get('variant_id')}` | {row.get('annual_return_pct')} | "
            f"{row.get('max_drawdown_abs_pct')} | {row.get('profit_factor')} | "
            f"{row.get('cost_2x_total_return_pct')} | `{row.get('retention_decision')}` |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 本报告只做 near-miss 复核和 v2 窄范围研究，不写 paper 队列，不解锁 live。",
            "- 杠杆、强平缓冲、funding 和成本均为研究近似，不能作为实盘证据。",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(str(key))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bars_per_year(interval: str) -> float:
    if interval == "15m":
        return 365.0 * 24.0 * 4.0
    return 365.0 * 6.0


def _round(value: Any, digits: int = 6) -> float:
    if value is None:
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return round(number, digits)


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _git_commit() -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True)
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"
