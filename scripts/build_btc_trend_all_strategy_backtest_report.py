#!/usr/bin/env python3
"""Build a BTC trend all-candidate backtest report.

This is a broad research pass over every BTC spot daily strategy candidate
that can be evaluated with the current OKX daily bundle. It deliberately
keeps multi-asset, futures curve, ETF, equity and ML-overlay ideas blocked
until the corresponding data and validation pipeline exist.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_btc_only_trend_v0_report import _load_daily_bars  # noqa: E402
from scripts.build_btc_trend_priority_strategy_backtest_report import (  # noqa: E402
    COST_BPS_GRID,
    DELAY_DAYS_GRID,
    FORECAST_CAP,
    MAX_EXPOSURE,
    MIN_MEANINGFUL_AVERAGE_EXPOSURE,
    TARGET_VOLS,
    VOL_WINDOWS,
    CandidateSpec,
    _float,
    _guardrails,
    _mapping,
    _optimization_objective,
    _performance,
    _relpath,
    _resolve,
    _round,
    _score,
    _timestamp_text,
)


SCHEMA_VERSION = "btc_trend_all_strategy_backtest_report_v1"
SYMBOL = "BTCUSDT"
DEFAULT_BUNDLE_DIR = Path("data/external/btc_spot/okx/bundles/btc_okx_spot_btcusdt_daily_5y_v1")
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_all_strategy_backtest_report.json")
DEFAULT_GRID_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_all_strategy_grid.csv")
DEFAULT_LEDGER_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_all_strategy_position_ledger.csv")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/BTC 趋势策略全集回测报告.md")
MIN_DAILY_ROWS = 1095

BASELINE_FAMILY = "baseline"
BTC_FAMILIES = [
    "t01_twelve_month_momentum",
    "t02_long_ma_trend",
    "t03_ewmac_forecast",
    "t04_donchian_20_10",
    "t05_donchian_55_20",
    "t06_atr_channel_breakout",
    "t07_bollinger_breakout",
    "t08_price_atr_buffer",
    "t09_dual_ma_system",
    "t10_triple_ma_filter",
    "t11_donchian_time_exit",
    "oth_t01_range_position_breakout",
    "oth_t02_ewmac_acceleration",
]
BLOCKED_FAMILIES = [
    {
        "family_id": "m01_multi_asset_tsmom",
        "status": "blocked_missing_data",
        "reason": "requires multi-asset futures or ETF proxy data; current run has BTC spot daily only",
        "required_data": ["multi_asset_daily_prices", "instrument_metadata"],
    },
    {
        "family_id": "m02_multi_asset_ewmac_forecast",
        "status": "blocked_missing_data",
        "reason": "requires multi-asset price universe and instrument diversification model",
        "required_data": ["multi_asset_daily_prices", "instrument_diversification_model"],
    },
    {
        "family_id": "m03_dual_momentum_etf_rotation",
        "status": "blocked_missing_data",
        "reason": "requires ETF universe and defensive asset data",
        "required_data": ["etf_adjusted_prices", "defensive_asset_prices"],
    },
    {
        "family_id": "m04_stock_cross_sectional_momentum",
        "status": "blocked_missing_data",
        "reason": "requires equity universe, survivorship controls and factor pipeline",
        "required_data": ["equity_universe", "survivorship_controls", "factor_pipeline"],
    },
    {
        "family_id": "oth_t04_trend_carry_funding_filter",
        "status": "blocked_missing_data",
        "reason": "requires futures basis or perpetual funding data; not part of BTC spot v0",
        "required_data": ["perpetual_funding_rates", "futures_basis_or_mark_premium"],
    },
    {
        "family_id": "oth_rv_calendar_or_cross_instrument_spread",
        "status": "blocked_missing_data",
        "reason": "requires multi-leg futures curve and spread execution model",
        "required_data": ["futures_curve", "multi_leg_execution_model"],
    },
    {
        "family_id": "oth_v01_meta_labeling_overlay",
        "status": "blocked_pending_baseline",
        "reason": "requires frozen primary rules, event labeling and purged validation; not a standalone first-pass strategy",
        "required_data": ["frozen_primary_rules", "event_labels", "purged_validation_pipeline"],
    },
    {
        "family_id": "oth_f01_safer_fast_mean_reversion",
        "status": "blocked_out_of_scope",
        "reason": "short-horizon mean reversion is not the current daily trend strategy scope and must not unfreeze 5m HFT",
        "required_data": ["intraday_research_scope_approval", "separate_non_hft_validation_gate"],
    },
]


@dataclass
class EvaluatedCandidate:
    spec: CandidateSpec
    raw_signal: pd.Series
    exposure: pd.Series
    turnover: pd.Series
    cost: pd.Series
    strategy_returns: pd.Series
    equity: pd.Series
    metrics: dict[str, Any]


def build_btc_trend_all_strategy_backtest_report(
    *,
    repo_root: Path | None = None,
    bundle_dir: Path = DEFAULT_BUNDLE_DIR,
    output: Path = DEFAULT_OUTPUT,
    grid_output: Path = DEFAULT_GRID_OUTPUT,
    ledger_output: Path = DEFAULT_LEDGER_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    initial_capital: float = 25_000.0,
    default_cost_bps: float = 5.0,
    default_delay_days: int = 1,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    bundle_abs = _resolve(root, bundle_dir)
    output_abs = _resolve(root, output)
    grid_abs = _resolve(root, grid_output)
    ledger_abs = _resolve(root, ledger_output)
    markdown_abs = _resolve(root, markdown_output)

    daily = _load_daily_bars(bundle_abs)
    rows = int(len(daily))
    if rows < MIN_DAILY_ROWS:
        payload = _insufficient_payload(
            generated=generated,
            root=root,
            bundle_abs=bundle_abs,
            daily=daily,
            grid_abs=grid_abs,
            ledger_abs=ledger_abs,
        )
        _write_csv(grid_abs, _grid_fieldnames(), [])
        _write_csv(ledger_abs, _ledger_fieldnames(), [])
        _write_json(output_abs, payload)
        _write_text(markdown_abs, _markdown(payload))
        return payload

    close = daily["close"].astype(float)
    high = daily["high"].astype(float)
    low = daily["low"].astype(float)
    returns = close.pct_change().fillna(0.0)
    atr = _atr(high=high, low=low, close=close, window=20)
    specs = _candidate_specs()
    baselines = _baseline_specs()
    baseline_evaluated = [
        _evaluate_spec(
            spec,
            close=close,
            high=high,
            low=low,
            returns=returns,
            atr=atr,
            initial_capital=initial_capital,
            cost_bps=default_cost_bps,
            delay_days=default_delay_days,
        )
        for spec in baselines
    ]
    buy_hold_metrics = baseline_evaluated[0].metrics
    evaluated = [
        _evaluate_spec(
            spec,
            close=close,
            high=high,
            low=low,
            returns=returns,
            atr=atr,
            initial_capital=initial_capital,
            cost_bps=default_cost_bps,
            delay_days=default_delay_days,
        )
        for spec in specs
    ]

    grid_rows = [_grid_row(candidate, buy_hold_metrics=buy_hold_metrics) for candidate in evaluated]
    _write_csv(grid_abs, _grid_fieldnames(), grid_rows)
    family_summaries = _family_summaries(evaluated, buy_hold_metrics=buy_hold_metrics)
    selected_ids = {str(_mapping(summary.get("selected_candidate")).get("candidate_id", "")) for summary in family_summaries}
    selected = [candidate for candidate in evaluated if candidate.spec.candidate_id in selected_ids]
    ledger_rows = _position_ledger_rows(
        selected_candidates=selected,
        baselines=baseline_evaluated,
        close=close,
        returns=returns,
        cost_bps=default_cost_bps,
        delay_days=default_delay_days,
    )
    _write_csv(ledger_abs, _ledger_fieldnames(), ledger_rows)
    cost_stress = _cost_stress(
        selected_candidates=selected,
        close=close,
        high=high,
        low=low,
        returns=returns,
        atr=atr,
        initial_capital=initial_capital,
        delay_days=default_delay_days,
    )
    delay_stress = _delay_stress(
        selected_candidates=selected,
        close=close,
        high=high,
        low=low,
        returns=returns,
        atr=atr,
        initial_capital=initial_capital,
        cost_bps=default_cost_bps,
    )
    yearly = _yearly_performance(
        selected_candidates=selected,
        baselines=baseline_evaluated,
        initial_capital=initial_capital,
    )
    ranking = sorted(
        [_result_row(candidate, buy_hold_metrics=buy_hold_metrics) for candidate in evaluated],
        key=lambda row: (-float(row["score"]), str(row["candidate_id"])),
    )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "research_only_all_backtest_complete",
        "decision": "btc_spot_daily_candidate_sweep_complete_manual_review_required",
        "asset": "btc",
        "symbol": SYMBOL,
        "bundle_dir": _relpath(bundle_abs, root),
        "data": _data_section(daily),
        "btc_families": BTC_FAMILIES,
        "blocked_families": BLOCKED_FAMILIES,
        "parameters": _parameters(default_cost_bps=default_cost_bps, default_delay_days=default_delay_days),
        "optimization_objective": _optimization_objective(),
        "guardrails": _guardrails(),
        "baseline_performance": [_result_row(candidate, buy_hold_metrics=buy_hold_metrics) for candidate in baseline_evaluated],
        "family_summaries": family_summaries,
        "overall_ranking": ranking[:50],
        "cost_stress": cost_stress,
        "delay_stress": delay_stress,
        "yearly_performance": yearly,
        "grid_output": {"path": _relpath(grid_abs, root), "row_count": len(grid_rows)},
        "position_ledger": {
            "path": _relpath(ledger_abs, root),
            "row_count": len(ledger_rows),
            "complete": _ledger_complete(ledger_rows),
            "delay_rule": "signal generated after T close; exposure effective T+1 or later",
        },
        "recommendations": _recommendations(family_summaries),
        "blockers": [],
    }
    _write_json(output_abs, payload)
    _write_text(markdown_abs, _markdown(payload))
    return payload


def _candidate_specs() -> list[CandidateSpec]:
    specs: list[CandidateSpec] = []
    specs.extend(_momentum_specs())
    specs.extend(_long_ma_specs())
    specs.extend(_ewmac_specs())
    specs.extend(_donchian_specs("t04_donchian_20_10", "t04_donchian", [20, 40], [10, 20]))
    specs.extend(_donchian_specs("t05_donchian_55_20", "t05_donchian", [50, 55, 80], [20, 30]))
    specs.extend(_atr_channel_specs())
    specs.extend(_bollinger_specs())
    specs.extend(_price_atr_buffer_specs())
    specs.extend(_dual_ma_specs())
    specs.extend(_triple_ma_specs())
    specs.extend(_donchian_time_exit_specs())
    specs.extend(_range_position_specs())
    specs.extend(_acceleration_specs())
    return specs


def _baseline_specs() -> list[CandidateSpec]:
    return [
        CandidateSpec(BASELINE_FAMILY, "buy_hold_btc", "Buy and hold BTC", {"signal_type": "buy_hold"}),
        CandidateSpec(BASELINE_FAMILY, "fixed_50pct_btc", "Fixed 50% BTC exposure", {"signal_type": "fixed_50pct"}),
    ]


def _momentum_specs() -> list[CandidateSpec]:
    specs = []
    for window in [300, 365, 420]:
        specs.append(
            CandidateSpec(
                "t01_twelve_month_momentum",
                "t01_momentum_binary",
                "T01 12-month momentum binary exposure",
                {"signal_type": "momentum", "momentum_window": window, "position_mode": "binary"},
            )
        )
        specs.extend(_vol_target_variants("t01_twelve_month_momentum", "t01_momentum_vol_target", "T01 12-month momentum vol target", {"signal_type": "momentum", "momentum_window": window}))
    return specs


def _long_ma_specs() -> list[CandidateSpec]:
    specs = []
    for fast in [60, 100, 120, 150]:
        for slow in [180, 200, 240, 300, 350]:
            if fast >= slow:
                continue
            base = {"signal_type": "long_ma", "ma_fast": fast, "ma_slow": slow}
            specs.append(CandidateSpec("t02_long_ma_trend", "t02_ma_binary", "T02 long MA trend binary", {**base, "position_mode": "binary"}))
            specs.extend(_vol_target_variants("t02_long_ma_trend", "t02_ma_vol_target", "T02 long MA trend vol target", base))
    return specs


def _ewmac_specs() -> list[CandidateSpec]:
    specs = []
    for fast, slow in [(8, 32), (16, 64), (21, 84), (32, 128), (64, 256)]:
        for vol_window in [20, 35, 60]:
            for scalar in [25.0, 50.0, 100.0, 200.0, 400.0]:
                base = {
                    "signal_type": "ewmac",
                    "ewmac_fast": fast,
                    "ewmac_slow": slow,
                    "forecast_scalar": scalar,
                    "vol_window": vol_window,
                    "forecast_cap": FORECAST_CAP,
                }
                specs.append(CandidateSpec("t03_ewmac_forecast", "t03_ewmac_fraction", "T03 EWMAC continuous forecast", {**base, "position_mode": "forecast_fraction"}))
                for target_vol in [0.15, 0.25, 0.35]:
                    specs.append(CandidateSpec("t03_ewmac_forecast", "t03_ewmac_vol_target", "T03 EWMAC forecast vol target", {**base, "position_mode": "forecast_vol_target", "target_vol": target_vol}))
    return specs


def _donchian_specs(family: str, variant: str, entry_windows: list[int], exit_windows: list[int]) -> list[CandidateSpec]:
    specs = []
    for entry in entry_windows:
        for exit_window in exit_windows:
            if exit_window >= entry:
                continue
            base = {"signal_type": "donchian", "entry_window": entry, "exit_window": exit_window}
            specs.append(CandidateSpec(family, f"{variant}_binary", f"{variant} binary", {**base, "position_mode": "binary"}))
            specs.extend(_vol_target_variants(family, f"{variant}_vol_target", f"{variant} vol target", base, compact=True))
    return specs


def _atr_channel_specs() -> list[CandidateSpec]:
    specs = []
    for ma_window in [200, 300, 350]:
        for atr_window in [20, 40]:
            for k_up in [3.0, 5.0, 7.0]:
                for k_down in [2.0, 3.0, 5.0]:
                    for exit_mode in ["mid_cross", "lower_band"]:
                        specs.append(
                            CandidateSpec(
                                "t06_atr_channel_breakout",
                                "t06_atr_channel_binary",
                                "T06 ATR channel breakout",
                                {
                                    "signal_type": "atr_channel",
                                    "ma_window": ma_window,
                                    "atr_window": atr_window,
                                    "k_up": k_up,
                                    "k_down": k_down,
                                    "exit_mode": exit_mode,
                                    "position_mode": "binary",
                                },
                            )
                        )
    return specs


def _bollinger_specs() -> list[CandidateSpec]:
    specs = []
    for window in [100, 200, 250]:
        for k in [2.0, 2.5, 3.0]:
            for exit_mode in ["mid_cross", "lower_band"]:
                specs.append(
                    CandidateSpec(
                        "t07_bollinger_breakout",
                        "t07_bollinger_binary",
                        "T07 Bollinger breakout",
                        {
                            "signal_type": "bollinger",
                            "window": window,
                            "k": k,
                            "exit_mode": exit_mode,
                            "position_mode": "binary",
                        },
                    )
                )
    return specs


def _price_atr_buffer_specs() -> list[CandidateSpec]:
    specs = []
    for lookback in [50, 100, 200]:
        for atr_window in [20, 30]:
            for k in [1.0, 2.0, 3.0]:
                specs.append(
                    CandidateSpec(
                        "t08_price_atr_buffer",
                        "t08_price_atr_binary",
                        "T08 price lookback ATR buffer",
                        {
                            "signal_type": "price_atr_buffer",
                            "lookback": lookback,
                            "atr_window": atr_window,
                            "k": k,
                            "position_mode": "binary",
                        },
                    )
                )
    return specs


def _dual_ma_specs() -> list[CandidateSpec]:
    specs = []
    for fast, slow in [(50, 200), (100, 350), (150, 350)]:
        base = {"signal_type": "dual_ma", "ma_fast": fast, "ma_slow": slow}
        specs.append(CandidateSpec("t09_dual_ma_system", "t09_dual_ma_binary", "T09 dual MA binary", {**base, "position_mode": "binary"}))
        specs.extend(_vol_target_variants("t09_dual_ma_system", "t09_dual_ma_vol_target", "T09 dual MA vol target", base, compact=True))
    return specs


def _triple_ma_specs() -> list[CandidateSpec]:
    specs = []
    for fast in [100, 150]:
        for medium in [200, 250]:
            for slow in [300, 350]:
                if fast < medium < slow:
                    specs.append(
                        CandidateSpec(
                            "t10_triple_ma_filter",
                            "t10_triple_ma_binary",
                            "T10 triple MA filter",
                            {
                                "signal_type": "triple_ma",
                                "ma_fast": fast,
                                "ma_medium": medium,
                                "ma_slow": slow,
                                "position_mode": "binary",
                            },
                        )
                    )
    return specs


def _donchian_time_exit_specs() -> list[CandidateSpec]:
    specs = []
    for entry in [20, 40, 55]:
        for hold_days in [40, 80, 120]:
            specs.append(
                CandidateSpec(
                    "t11_donchian_time_exit",
                    "t11_donchian_time_exit_binary",
                    "T11 Donchian breakout time exit",
                    {"signal_type": "donchian_time_exit", "entry_window": entry, "time_exit_days": hold_days, "position_mode": "binary"},
                )
            )
    return specs


def _range_position_specs() -> list[CandidateSpec]:
    specs = []
    for horizon in [20, 40, 80, 160, 320]:
        for scalar in [0.5, 0.75, 1.0, 1.25]:
            base = {"signal_type": "range_position", "horizon": horizon, "forecast_scalar": scalar, "forecast_cap": FORECAST_CAP}
            specs.append(CandidateSpec("oth_t01_range_position_breakout", "oth_t01_range_fraction", "OTH-T01 range-position breakout forecast", {**base, "position_mode": "forecast_fraction"}))
            specs.extend(_vol_target_variants("oth_t01_range_position_breakout", "oth_t01_range_vol_target", "OTH-T01 range-position vol target", base, compact=True, mode="forecast_vol_target"))
    return specs


def _acceleration_specs() -> list[CandidateSpec]:
    specs = []
    for fast, slow in [(8, 32), (16, 64), (32, 128), (64, 256)]:
        for scalar in [0.5, 1.0, 2.0, 4.0]:
            base = {
                "signal_type": "ewmac_acceleration",
                "ewmac_fast": fast,
                "ewmac_slow": slow,
                "base_forecast_scalar": 100.0,
                "acceleration_scalar": scalar,
                "forecast_cap": FORECAST_CAP,
            }
            specs.append(CandidateSpec("oth_t02_ewmac_acceleration", "oth_t02_acceleration_fraction", "OTH-T02 EWMAC acceleration", {**base, "position_mode": "forecast_fraction"}))
            specs.extend(_vol_target_variants("oth_t02_ewmac_acceleration", "oth_t02_acceleration_vol_target", "OTH-T02 acceleration vol target", base, compact=True, mode="forecast_vol_target"))
    return specs


def _vol_target_variants(
    family: str,
    variant: str,
    label: str,
    base: Mapping[str, Any],
    *,
    compact: bool = False,
    mode: str = "vol_target",
) -> list[CandidateSpec]:
    windows = [30] if compact else VOL_WINDOWS
    targets = [0.25, 0.35] if compact else TARGET_VOLS
    return [
        CandidateSpec(
            family,
            variant,
            label,
            {**dict(base), "position_mode": mode, "vol_window": vol_window, "target_vol": target_vol},
        )
        for vol_window in windows
        for target_vol in targets
    ]


def _evaluate_spec(
    spec: CandidateSpec,
    *,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    returns: pd.Series,
    atr: pd.Series,
    initial_capital: float,
    cost_bps: float,
    delay_days: int,
) -> EvaluatedCandidate:
    raw_signal = _raw_signal(spec, close=close, high=high, low=low, returns=returns, atr=atr)
    exposure = raw_signal.shift(int(delay_days)).fillna(0.0).clip(0.0, MAX_EXPOSURE)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    cost = turnover * (float(cost_bps) / 10_000.0)
    strategy_returns = (exposure * returns - cost).fillna(0.0)
    equity = float(initial_capital) * (1.0 + strategy_returns).cumprod()
    metrics = _performance(
        strategy_returns=strategy_returns,
        equity=equity,
        exposure=exposure,
        turnover=turnover,
        cost=cost,
    )
    return EvaluatedCandidate(
        spec=spec,
        raw_signal=raw_signal,
        exposure=exposure,
        turnover=turnover,
        cost=cost,
        strategy_returns=strategy_returns,
        equity=equity,
        metrics=metrics,
    )


def _raw_signal(
    spec: CandidateSpec,
    *,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    returns: pd.Series,
    atr: pd.Series,
) -> pd.Series:
    params = spec.params
    signal_type = str(params.get("signal_type", ""))
    if signal_type == "buy_hold":
        return pd.Series(1.0, index=close.index)
    if signal_type == "fixed_50pct":
        return pd.Series(0.5, index=close.index)
    if signal_type == "momentum":
        base = (close.pct_change(int(params["momentum_window"])) > 0.0).astype(float)
        return _apply_position_mode(base, returns=returns, params=params)
    if signal_type in {"long_ma", "dual_ma"}:
        fast = close.rolling(int(params["ma_fast"])).mean()
        slow = close.rolling(int(params["ma_slow"])).mean()
        base = ((fast > slow) & (close > slow)).astype(float) if signal_type == "long_ma" else (fast > slow).astype(float)
        return _apply_position_mode(base, returns=returns, params=params)
    if signal_type == "ewmac":
        return _ewmac_fraction(close=close, returns=returns, params=params)
    if signal_type == "donchian":
        return _donchian_signal(high=high, low=low, entry_window=int(params["entry_window"]), exit_window=int(params["exit_window"]))
    if signal_type == "atr_channel":
        return _atr_channel_signal(close=close, atr=atr, params=params)
    if signal_type == "bollinger":
        return _bollinger_signal(close=close, params=params)
    if signal_type == "price_atr_buffer":
        return _price_atr_buffer_signal(close=close, atr=atr, params=params)
    if signal_type == "triple_ma":
        fast = close.rolling(int(params["ma_fast"])).mean()
        medium = close.rolling(int(params["ma_medium"])).mean()
        slow = close.rolling(int(params["ma_slow"])).mean()
        return ((fast > medium) & (fast > slow) & (medium > slow)).astype(float)
    if signal_type == "donchian_time_exit":
        return _donchian_time_exit_signal(high=high, entry_window=int(params["entry_window"]), time_exit_days=int(params["time_exit_days"]))
    if signal_type == "range_position":
        return _range_position_signal(close=close, returns=returns, params=params)
    if signal_type == "ewmac_acceleration":
        return _acceleration_signal(close=close, returns=returns, params=params)
    raise ValueError(f"Unsupported BTC trend candidate signal_type: {signal_type}")


def _apply_position_mode(base: pd.Series, *, returns: pd.Series, params: Mapping[str, Any]) -> pd.Series:
    mode = str(params.get("position_mode", "binary"))
    base = base.fillna(0.0).clip(0.0, 1.0)
    if mode in {"vol_target", "forecast_vol_target"}:
        realized_vol = returns.rolling(int(params.get("vol_window", 30))).std(ddof=0) * math.sqrt(365.0)
        scalar = (float(params.get("target_vol", 0.25)) / realized_vol).replace([math.inf, -math.inf], 0.0).fillna(0.0)
        return (base * scalar).clip(0.0, MAX_EXPOSURE)
    return base


def _ewmac_fraction(*, close: pd.Series, returns: pd.Series, params: Mapping[str, Any]) -> pd.Series:
    fast_span = int(params["ewmac_fast"])
    slow_span = int(params["ewmac_slow"])
    vol_window = int(params.get("vol_window", 35))
    forecast_cap = float(params.get("forecast_cap", FORECAST_CAP))
    fast = close.ewm(span=fast_span, adjust=False, min_periods=fast_span).mean()
    slow = close.ewm(span=slow_span, adjust=False, min_periods=slow_span).mean()
    price_vol = returns.rolling(vol_window).std(ddof=0) * math.sqrt(365.0) * close
    raw_forecast = ((fast - slow) / price_vol).replace([math.inf, -math.inf], 0.0).fillna(0.0)
    forecast = (raw_forecast * float(params["forecast_scalar"])).clip(-forecast_cap, forecast_cap)
    fraction = (forecast.clip(lower=0.0) / forecast_cap).clip(0.0, 1.0)
    return _apply_position_mode(fraction, returns=returns, params=params)


def _donchian_signal(*, high: pd.Series, low: pd.Series, entry_window: int, exit_window: int) -> pd.Series:
    entry = high > high.shift(1).rolling(entry_window).max()
    exit_ = low < low.shift(1).rolling(exit_window).min()
    return _stateful_long_flat(entry=entry, exit_=exit_)


def _atr_channel_signal(*, close: pd.Series, atr: pd.Series, params: Mapping[str, Any]) -> pd.Series:
    mid = close.rolling(int(params["ma_window"])).mean()
    atr_local = _atr_rewindow(atr, int(params.get("atr_window", 20)))
    upper = mid + float(params["k_up"]) * atr_local
    lower = mid - float(params["k_down"]) * atr_local
    entry = close > upper
    exit_ = close < mid if str(params.get("exit_mode", "mid_cross")) == "mid_cross" else close < lower
    return _stateful_long_flat(entry=entry, exit_=exit_)


def _bollinger_signal(*, close: pd.Series, params: Mapping[str, Any]) -> pd.Series:
    window = int(params["window"])
    mid = close.rolling(window).mean()
    std = close.rolling(window).std(ddof=0)
    upper = mid + float(params["k"]) * std
    lower = mid - float(params["k"]) * std
    entry = close > upper
    exit_ = close < mid if str(params.get("exit_mode", "mid_cross")) == "mid_cross" else close < lower
    return _stateful_long_flat(entry=entry, exit_=exit_)


def _price_atr_buffer_signal(*, close: pd.Series, atr: pd.Series, params: Mapping[str, Any]) -> pd.Series:
    lookback = int(params["lookback"])
    atr_local = _atr_rewindow(atr, int(params.get("atr_window", 20)))
    ref = close.shift(lookback)
    entry = close > ref + float(params["k"]) * atr_local
    exit_ = close < ref - float(params["k"]) * atr_local
    return _stateful_long_flat(entry=entry, exit_=exit_)


def _donchian_time_exit_signal(*, high: pd.Series, entry_window: int, time_exit_days: int) -> pd.Series:
    entry = high > high.shift(1).rolling(entry_window).max()
    out = []
    in_pos = False
    held = 0
    for ent in entry.fillna(False).astype(bool):
        if in_pos:
            held += 1
            if held >= time_exit_days:
                in_pos = False
                held = 0
        if not in_pos and ent:
            in_pos = True
            held = 0
        out.append(1.0 if in_pos else 0.0)
    return pd.Series(out, index=high.index)


def _range_position_signal(*, close: pd.Series, returns: pd.Series, params: Mapping[str, Any]) -> pd.Series:
    horizon = int(params["horizon"])
    low_range = close.rolling(horizon).min()
    high_range = close.rolling(horizon).max()
    width = (high_range - low_range).replace(0.0, math.nan)
    raw = 40.0 * ((close - low_range) / width - 0.5)
    smooth = raw.ewm(span=max(2, int(horizon / 4)), adjust=False, min_periods=max(2, int(horizon / 4))).mean()
    forecast = (smooth.fillna(0.0) * float(params.get("forecast_scalar", 1.0))).clip(-FORECAST_CAP, FORECAST_CAP)
    fraction = (forecast.clip(lower=0.0) / FORECAST_CAP).clip(0.0, 1.0)
    return _apply_position_mode(fraction, returns=returns, params=params)


def _acceleration_signal(*, close: pd.Series, returns: pd.Series, params: Mapping[str, Any]) -> pd.Series:
    base_params = {
        "ewmac_fast": int(params["ewmac_fast"]),
        "ewmac_slow": int(params["ewmac_slow"]),
        "forecast_scalar": float(params.get("base_forecast_scalar", 100.0)),
        "vol_window": 35,
        "forecast_cap": FORECAST_CAP,
        "position_mode": "forecast_fraction",
    }
    base_fraction = _ewmac_fraction(close=close, returns=returns, params=base_params)
    base_forecast = base_fraction * FORECAST_CAP
    accel = (base_forecast - base_forecast.shift(int(params["ewmac_fast"]))) * float(params.get("acceleration_scalar", 1.0))
    fraction = accel.clip(lower=0.0, upper=FORECAST_CAP).fillna(0.0) / FORECAST_CAP
    return _apply_position_mode(fraction, returns=returns, params=params)


def _stateful_long_flat(*, entry: pd.Series, exit_: pd.Series) -> pd.Series:
    out = []
    in_pos = False
    for ent, ex in zip(entry.fillna(False).astype(bool), exit_.fillna(False).astype(bool)):
        if in_pos and ex:
            in_pos = False
        if not in_pos and ent:
            in_pos = True
        out.append(1.0 if in_pos else 0.0)
    return pd.Series(out, index=entry.index)


def _atr(*, high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def _atr_rewindow(atr20: pd.Series, window: int) -> pd.Series:
    if window == 20:
        return atr20
    return atr20.rolling(window).mean()


def _result_row(candidate: EvaluatedCandidate, *, buy_hold_metrics: Mapping[str, Any]) -> dict[str, Any]:
    metrics = candidate.metrics
    return {
        "candidate_id": candidate.spec.candidate_id,
        "family_id": candidate.spec.family_id,
        "variant_id": candidate.spec.variant_id,
        "label": candidate.spec.label,
        "params": candidate.spec.params,
        "score": _score(metrics, buy_hold_metrics=buy_hold_metrics),
        "metrics": metrics,
        "drawdown_reduction_vs_buy_hold_pct": _round(
            _float(buy_hold_metrics, "max_drawdown_abs_pct") - _float(metrics, "max_drawdown_abs_pct")
        ),
        "return_diff_vs_buy_hold_pct": _round(_float(metrics, "total_return_pct") - _float(buy_hold_metrics, "total_return_pct")),
    }


def _grid_row(candidate: EvaluatedCandidate, *, buy_hold_metrics: Mapping[str, Any]) -> dict[str, Any]:
    row = _result_row(candidate, buy_hold_metrics=buy_hold_metrics)
    metrics = _mapping(row.get("metrics"))
    return {
        "candidate_id": row["candidate_id"],
        "family_id": row["family_id"],
        "variant_id": row["variant_id"],
        "score": row["score"],
        "params_json": json.dumps(row["params"], sort_keys=True, ensure_ascii=False),
        "total_return_pct": metrics["total_return_pct"],
        "annual_return_pct": metrics["annual_return_pct"],
        "annual_volatility_pct": metrics["annual_volatility_pct"],
        "sharpe_ratio": metrics["sharpe_ratio"],
        "sortino_ratio": metrics["sortino_ratio"],
        "max_drawdown_abs_pct": metrics["max_drawdown_abs_pct"],
        "calmar_ratio": metrics["calmar_ratio"],
        "turnover": metrics["turnover"],
        "exposure_change_count": metrics["exposure_change_count"],
        "fee_return_pct": metrics["fee_return_pct"],
        "average_exposure": metrics["average_exposure"],
        "drawdown_reduction_vs_buy_hold_pct": row["drawdown_reduction_vs_buy_hold_pct"],
    }


def _family_summaries(evaluated: list[EvaluatedCandidate], *, buy_hold_metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    summaries = []
    for family_id in BTC_FAMILIES:
        family_candidates = [candidate for candidate in evaluated if candidate.spec.family_id == family_id]
        ranked = sorted(
            [_result_row(candidate, buy_hold_metrics=buy_hold_metrics) for candidate in family_candidates],
            key=lambda row: (-float(row["score"]), str(row["candidate_id"])),
        )
        positive = sum(1 for row in ranked if _float(_mapping(row.get("metrics")), "total_return_pct") > 0.0)
        dd_better = sum(
            1
            for row in ranked
            if _float(_mapping(row.get("metrics")), "max_drawdown_abs_pct") < _float(buy_hold_metrics, "max_drawdown_abs_pct")
        )
        meaningful = sum(
            1
            for row in ranked
            if _float(_mapping(row.get("metrics")), "average_exposure") >= MIN_MEANINGFUL_AVERAGE_EXPOSURE
            and _float(_mapping(row.get("metrics")), "total_return_pct") >= 5.0
        )
        summaries.append(
            {
                "family_id": family_id,
                "status": "tested",
                "candidate_count": len(ranked),
                "selected_candidate": ranked[0] if ranked else {},
                "top_5": ranked[:5],
                "positive_total_return_share": _round(positive / len(ranked)) if ranked else 0.0,
                "drawdown_below_buy_hold_share": _round(dd_better / len(ranked)) if ranked else 0.0,
                "meaningful_candidate_share": _round(meaningful / len(ranked)) if ranked else 0.0,
            }
        )
    return summaries


def _cost_stress(
    *,
    selected_candidates: list[EvaluatedCandidate],
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    returns: pd.Series,
    atr: pd.Series,
    initial_capital: float,
    delay_days: int,
) -> list[dict[str, Any]]:
    rows = []
    for selected in selected_candidates:
        for cost_bps in COST_BPS_GRID:
            evaluated = _evaluate_spec(
                selected.spec,
                close=close,
                high=high,
                low=low,
                returns=returns,
                atr=atr,
                initial_capital=initial_capital,
                cost_bps=cost_bps,
                delay_days=delay_days,
            )
            rows.append(
                {
                    "family_id": selected.spec.family_id,
                    "candidate_id": selected.spec.candidate_id,
                    "cost_bps": cost_bps,
                    "metrics": evaluated.metrics,
                }
            )
    return rows


def _delay_stress(
    *,
    selected_candidates: list[EvaluatedCandidate],
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    returns: pd.Series,
    atr: pd.Series,
    initial_capital: float,
    cost_bps: float,
) -> list[dict[str, Any]]:
    rows = []
    for selected in selected_candidates:
        for delay_days in DELAY_DAYS_GRID:
            evaluated = _evaluate_spec(
                selected.spec,
                close=close,
                high=high,
                low=low,
                returns=returns,
                atr=atr,
                initial_capital=initial_capital,
                cost_bps=cost_bps,
                delay_days=delay_days,
            )
            rows.append(
                {
                    "family_id": selected.spec.family_id,
                    "candidate_id": selected.spec.candidate_id,
                    "delay_days": delay_days,
                    "metrics": evaluated.metrics,
                }
            )
    return rows


def _yearly_performance(
    *,
    selected_candidates: list[EvaluatedCandidate],
    baselines: list[EvaluatedCandidate],
    initial_capital: float,
) -> list[dict[str, Any]]:
    rows = []
    for candidate in baselines + selected_candidates:
        years = sorted({int(ts.year) for ts in candidate.strategy_returns.index})
        for year in years:
            index = candidate.strategy_returns.index[candidate.strategy_returns.index.year == year]
            if len(index) == 0:
                continue
            returns = candidate.strategy_returns.loc[index].fillna(0.0)
            equity = float(initial_capital) * (1.0 + returns).cumprod()
            rows.append(
                {
                    "year": year,
                    "segment": f"{year} partial" if len(index) < 365 else str(year),
                    "candidate_id": candidate.spec.candidate_id,
                    "family_id": candidate.spec.family_id,
                    "variant_id": candidate.spec.variant_id,
                    "params": candidate.spec.params,
                    "day_count": len(index),
                    "metrics": _performance(
                        strategy_returns=returns,
                        equity=equity,
                        exposure=candidate.exposure.loc[index].fillna(0.0),
                        turnover=candidate.turnover.loc[index].fillna(0.0),
                        cost=candidate.cost.loc[index].fillna(0.0),
                    ),
                }
            )
    return rows


def _position_ledger_rows(
    *,
    selected_candidates: list[EvaluatedCandidate],
    baselines: list[EvaluatedCandidate],
    close: pd.Series,
    returns: pd.Series,
    cost_bps: float,
    delay_days: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    index = list(close.index)
    for candidate in baselines + selected_candidates:
        for i, timestamp in enumerate(index):
            source_i = i - int(delay_days)
            source_ts = index[source_i] if source_i >= 0 else None
            raw_value = float(candidate.raw_signal.iloc[source_i]) if source_i >= 0 else 0.0
            exposure = float(candidate.exposure.iloc[i])
            turnover = float(candidate.turnover.iloc[i])
            rows.append(
                {
                    "timestamp": _timestamp_text(timestamp),
                    "candidate_id": candidate.spec.candidate_id,
                    "family_id": candidate.spec.family_id,
                    "variant_id": candidate.spec.variant_id,
                    "close": _round(float(close.iloc[i])),
                    "daily_return": _round(float(returns.iloc[i])),
                    "raw_signal": _round(raw_value, 10),
                    "signal_timestamp": _timestamp_text(source_ts) if source_ts is not None else "",
                    "effective_timestamp": _timestamp_text(timestamp),
                    "exposure": _round(exposure, 10),
                    "turnover": _round(turnover, 10),
                    "cost_bps": float(cost_bps),
                    "strategy_daily_return": _round(float(candidate.strategy_returns.iloc[i]), 10),
                    "equity": _round(float(candidate.equity.iloc[i])),
                    "reason": _ledger_reason(source_ts=source_ts, turnover=turnover, exposure=exposure),
                    "params_json": json.dumps(candidate.spec.params, sort_keys=True, ensure_ascii=False),
                }
            )
    return rows


def _ledger_reason(*, source_ts: pd.Timestamp | None, turnover: float, exposure: float) -> str:
    if source_ts is None:
        return "warming_up_no_effective_signal"
    if turnover > 1e-12:
        return "exposure_changed_from_prior_effective_signal"
    if exposure > 0.0:
        return "hold_prior_effective_signal"
    return "flat_prior_effective_signal"


def _ledger_complete(rows: list[Mapping[str, Any]]) -> bool:
    if not rows:
        return False
    required = set(_ledger_fieldnames())
    return all(required.issubset(row.keys()) and str(row.get("reason", "")).strip() for row in rows)


def _recommendations(family_summaries: list[Mapping[str, Any]]) -> list[str]:
    ranked = sorted(
        family_summaries,
        key=lambda item: -float(_mapping(_mapping(item).get("selected_candidate")).get("score", -9999.0) or -9999.0),
    )
    if not ranked:
        return ["没有可排名候选。"]
    top = _mapping(ranked[0])
    selected = _mapping(top.get("selected_candidate"))
    metrics = _mapping(selected.get("metrics"))
    return [
        f"全集回测已完成；当前全样本评分最高策略族是 `{top.get('family_id', '')}`。",
        f"最高候选参数为 `{json.dumps(selected.get('params', {}), ensure_ascii=False, sort_keys=True)}`。",
        f"最高候选总收益 {metrics.get('total_return_pct', 0)}%，最大回撤 {metrics.get('max_drawdown_abs_pct', 0)}%，Sharpe {metrics.get('sharpe_ratio', 0)}。",
        "这仍是全样本研究排名，不是 strategy_validation_gate 通过结论；下一步应对排名前列策略单独做 walk-forward 参数选择验证。",
    ]


def _insufficient_payload(
    *,
    generated: str,
    root: Path,
    bundle_abs: Path,
    daily: pd.DataFrame,
    grid_abs: Path,
    ledger_abs: Path,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "insufficient_history",
        "decision": "do_not_rank_all_candidates",
        "asset": "btc",
        "symbol": SYMBOL,
        "bundle_dir": _relpath(bundle_abs, root),
        "data": _data_section(daily),
        "btc_families": BTC_FAMILIES,
        "blocked_families": BLOCKED_FAMILIES,
        "parameters": _parameters(default_cost_bps=5.0, default_delay_days=1),
        "optimization_objective": _optimization_objective(),
        "guardrails": _guardrails(),
        "baseline_performance": [],
        "family_summaries": [],
        "overall_ranking": [],
        "cost_stress": [],
        "delay_stress": [],
        "yearly_performance": [],
        "grid_output": {"path": _relpath(grid_abs, root), "row_count": 0},
        "position_ledger": {"path": _relpath(ledger_abs, root), "row_count": 0, "complete": False},
        "recommendations": ["历史长度不足，不做全集参数优化。"],
        "blockers": ["btc_trend_all_strategy_validation_requires_at_least_1095_daily_rows"],
    }


def _parameters(*, default_cost_bps: float, default_delay_days: int) -> dict[str, Any]:
    return {
        "minimum_daily_rows": MIN_DAILY_ROWS,
        "default_cost_bps": float(default_cost_bps),
        "default_delay_days": int(default_delay_days),
        "cost_bps_grid": COST_BPS_GRID,
        "delay_days_grid": DELAY_DAYS_GRID,
        "minimum_meaningful_average_exposure": MIN_MEANINGFUL_AVERAGE_EXPOSURE,
        "max_exposure": MAX_EXPOSURE,
        "forecast_cap": FORECAST_CAP,
    }


def _data_section(daily: pd.DataFrame) -> dict[str, Any]:
    return {
        "daily_rows": int(len(daily)),
        "start": _timestamp_text(daily.index.min()) if len(daily) else "",
        "end": _timestamp_text(daily.index.max()) if len(daily) else "",
        "source": "OKX public local spot daily bundle",
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    data = _mapping(payload.get("data"))
    lines = [
        "# BTC 趋势策略全集回测报告",
        "",
        f"生成时间：{payload.get('generated_at', '')}",
        "",
        "## 结论",
        "",
        f"状态：`{payload.get('status', '')}`",
        "",
    ]
    if payload.get("status") == "insufficient_history":
        lines += [
            f"当前日线行数 {data.get('daily_rows', 0)}，不足 1095 行，不做全集排名。",
            "",
        ]
        return "\n".join(lines)
    lines += [
        "本报告把当前 BTC-only 日线可测策略候选全部跑了一遍。它只支持研究排序，不解锁纸盘或实盘。",
        "",
        "## 数据",
        "",
        "| 项目 | 数值 |",
        "| --- | ---: |",
        f"| 日线行数 | {data.get('daily_rows', 0)} |",
        f"| 开始 | {data.get('start', '')} |",
        f"| 结束 | {data.get('end', '')} |",
        "",
        "## 入选策略族",
        "",
        "| 策略族 | 参数数 | 入选候选 | 入选参数 | 分数 | 总收益 | 最大回撤 | Sharpe | 平均仓位 | 换仓次数 |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for summary in payload.get("family_summaries", []):
        item = _mapping(summary)
        selected = _mapping(item.get("selected_candidate"))
        metrics = _mapping(selected.get("metrics"))
        lines.append(
            f"| {item.get('family_id', '')} | {item.get('candidate_count', 0)} | "
            f"`{selected.get('candidate_id', '')}` | `{json.dumps(selected.get('params', {}), ensure_ascii=False, sort_keys=True)}` | "
            f"{selected.get('score', 0)} | {metrics.get('total_return_pct', 0)}% | "
            f"{metrics.get('max_drawdown_abs_pct', 0)}% | {metrics.get('sharpe_ratio', 0)} | "
            f"{metrics.get('average_exposure', 0)} | {metrics.get('exposure_change_count', 0)} |"
        )
    lines += [
        "",
        "## 总排名 Top 20",
        "",
        "| 排名 | 策略族 | 候选 | 总收益 | 最大回撤 | Sharpe | 参数 |",
        "| ---: | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for i, row in enumerate(payload.get("overall_ranking", [])[:20], start=1):
        item = _mapping(row)
        metrics = _mapping(item.get("metrics"))
        lines.append(
            f"| {i} | {item.get('family_id', '')} | `{item.get('candidate_id', '')}` | "
            f"{metrics.get('total_return_pct', 0)}% | {metrics.get('max_drawdown_abs_pct', 0)}% | "
            f"{metrics.get('sharpe_ratio', 0)} | `{json.dumps(item.get('params', {}), ensure_ascii=False, sort_keys=True)}` |"
        )
    lines += [
        "",
        "## 暂不回测策略族",
        "",
        "| 策略族 | 状态 | 原因 |",
        "| --- | --- | --- |",
    ]
    for row in payload.get("blocked_families", []):
        item = _mapping(row)
        lines.append(f"| {item.get('family_id', '')} | `{item.get('status', '')}` | {item.get('reason', '')} |")
    lines += [
        "",
        "## 输出",
        "",
        f"- 参数网格：`{_mapping(payload.get('grid_output')).get('path', '')}`",
        f"- 仓位 ledger：`{_mapping(payload.get('position_ledger')).get('path', '')}`",
        "",
        "## 下一步",
        "",
    ]
    for note in payload.get("recommendations", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_csv(path: Path, fieldnames: list[str], rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in fieldnames})
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _grid_fieldnames() -> list[str]:
    return [
        "candidate_id",
        "family_id",
        "variant_id",
        "score",
        "params_json",
        "total_return_pct",
        "annual_return_pct",
        "annual_volatility_pct",
        "sharpe_ratio",
        "sortino_ratio",
        "max_drawdown_abs_pct",
        "calmar_ratio",
        "turnover",
        "exposure_change_count",
        "fee_return_pct",
        "average_exposure",
        "drawdown_reduction_vs_buy_hold_pct",
    ]


def _ledger_fieldnames() -> list[str]:
    return [
        "timestamp",
        "candidate_id",
        "family_id",
        "variant_id",
        "close",
        "daily_return",
        "raw_signal",
        "signal_timestamp",
        "effective_timestamp",
        "exposure",
        "turnover",
        "cost_bps",
        "strategy_daily_return",
        "equity",
        "reason",
        "params_json",
    ]


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC all trend strategy backtest report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--grid-output", default=str(DEFAULT_GRID_OUTPUT))
    parser.add_argument("--ledger-output", default=str(DEFAULT_LEDGER_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--initial-capital", type=float, default=25_000.0)
    parser.add_argument("--default-cost-bps", type=float, default=5.0)
    parser.add_argument("--default-delay-days", type=int, default=1)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_btc_trend_all_strategy_backtest_report(
        repo_root=Path(args.repo_root),
        bundle_dir=Path(args.bundle_dir),
        output=Path(args.output),
        grid_output=Path(args.grid_output),
        ledger_output=Path(args.ledger_output),
        markdown_output=Path(args.markdown_output),
        initial_capital=float(args.initial_capital),
        default_cost_bps=float(args.default_cost_bps),
        default_delay_days=int(args.default_delay_days),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
