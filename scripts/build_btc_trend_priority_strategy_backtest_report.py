#!/usr/bin/env python3
"""Build a BTC trend first-priority strategy backtest report.

The report is research-only. It optimizes parameters for the first-priority
trend families, validates the optimization with walk-forward folds, writes a
position ledger, and produces an Obsidian-ready professional review note.
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


SCHEMA_VERSION = "btc_trend_priority_strategy_backtest_report_v1"
SYMBOL = "BTCUSDT"
DEFAULT_BUNDLE_DIR = Path("data/external/btc_spot/okx/bundles/btc_okx_spot_btcusdt_daily_5y_v1")
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_priority_strategy_backtest_report.json")
DEFAULT_GRID_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_priority_strategy_grid.csv")
DEFAULT_LEDGER_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_priority_position_ledger.csv")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/BTC 趋势第一优先级策略回测报告.md")

MIN_DAILY_ROWS = 1095
COST_BPS_GRID = [0.0, 5.0, 10.0, 25.0]
DELAY_DAYS_GRID = [1, 2, 3]
MOMENTUM_WINDOWS = [300, 365, 420]
MA_FAST_WINDOWS = [60, 100, 120, 150]
MA_SLOW_WINDOWS = [180, 200, 240, 300, 350]
EWMAC_PAIRS = [(8, 32), (16, 64), (21, 84), (32, 128), (64, 256)]
EWMAC_VOL_WINDOWS = [20, 35, 60]
EWMAC_FORECAST_SCALARS = [25.0, 50.0, 100.0, 200.0, 400.0]
VOL_WINDOWS = [14, 20, 30]
TARGET_VOLS = [0.15, 0.25, 0.35]
FORECAST_CAP = 20.0
MAX_EXPOSURE = 1.0
MIN_MEANINGFUL_AVERAGE_EXPOSURE = 0.10
BASELINES = ["buy_hold_btc", "fixed_50pct_btc"]
FIRST_PRIORITY_FAMILIES = [
    "t01_twelve_month_momentum",
    "t02_long_ma_trend",
    "t03_ewmac_forecast",
]


@dataclass(frozen=True)
class CandidateSpec:
    family_id: str
    variant_id: str
    label: str
    params: dict[str, Any]

    @property
    def candidate_id(self) -> str:
        digest = hashlib.sha1(json.dumps(self.params, sort_keys=True).encode("utf-8")).hexdigest()[:10]
        return f"{self.variant_id}_{digest}"


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


def build_btc_trend_priority_strategy_backtest_report(
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
    parameters = _parameters(default_cost_bps=default_cost_bps, default_delay_days=default_delay_days)
    if rows < MIN_DAILY_ROWS:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated,
            "status": "insufficient_history",
            "decision": "do_not_rank_or_optimize_first_priority_strategies",
            "asset": "btc",
            "symbol": SYMBOL,
            "bundle_dir": _relpath(bundle_abs, root),
            "data": _data_section(daily),
            "first_priority_families": FIRST_PRIORITY_FAMILIES,
            "parameters": parameters,
            "optimization_objective": _optimization_objective(),
            "guardrails": _guardrails(),
            "baseline_performance": [],
            "family_summaries": [],
            "overall_ranking": [],
            "walk_forward": {"folds": [], "summary": _empty_walk_forward_summary()},
            "cost_stress": [],
            "delay_stress": [],
            "yearly_performance": [],
            "grid_output": {"path": _relpath(grid_abs, root), "row_count": 0},
            "position_ledger": {"path": _relpath(ledger_abs, root), "row_count": 0, "complete": False},
            "blockers": ["btc_trend_priority_validation_requires_at_least_1095_daily_rows"],
        }
        _write_csv(grid_abs, _grid_fieldnames(), [])
        _write_csv(ledger_abs, _ledger_fieldnames(), [])
        _write_json(output_abs, payload)
        _write_text(markdown_abs, _markdown(payload))
        return payload

    close = daily["close"].astype(float)
    returns = close.pct_change().fillna(0.0)
    specs = _candidate_specs()
    baseline_specs = _baseline_specs()
    baseline_evaluated = [
        _evaluate_spec(
            spec,
            close=close,
            returns=returns,
            initial_capital=initial_capital,
            cost_bps=default_cost_bps,
            delay_days=default_delay_days,
        )
        for spec in baseline_specs
    ]
    buy_hold_metrics = _metrics_by_candidate_id(baseline_evaluated)["buy_hold_btc"]["metrics"]

    evaluated = [
        _evaluate_spec(
            spec,
            close=close,
            returns=returns,
            initial_capital=initial_capital,
            cost_bps=default_cost_bps,
            delay_days=default_delay_days,
        )
        for spec in specs
    ]
    grid_rows = [_grid_row(candidate, buy_hold_metrics=buy_hold_metrics) for candidate in evaluated]
    _write_csv(grid_abs, _grid_fieldnames(), grid_rows)

    family_summaries = _family_summaries(evaluated, buy_hold_metrics=buy_hold_metrics)
    selected_by_family = {
        str(summary["family_id"]): str(summary["selected_candidate"]["candidate_id"])
        for summary in family_summaries
        if summary.get("selected_candidate")
    }
    selected_candidates = [candidate for candidate in evaluated if candidate.spec.candidate_id in set(selected_by_family.values())]
    baseline_rows = [_result_row(candidate, buy_hold_metrics=buy_hold_metrics) for candidate in baseline_evaluated]
    overall_ranking = sorted(
        [_result_row(candidate, buy_hold_metrics=buy_hold_metrics) for candidate in evaluated],
        key=lambda row: (-float(row["score"]), str(row["candidate_id"])),
    )
    walk_forward = _walk_forward(
        specs=specs,
        close=close,
        returns=returns,
        initial_capital=initial_capital,
        cost_bps=default_cost_bps,
        delay_days=default_delay_days,
    )
    cost_stress = _cost_stress(
        selected_candidates=selected_candidates,
        close=close,
        returns=returns,
        initial_capital=initial_capital,
        delay_days=default_delay_days,
    )
    delay_stress = _delay_stress(
        selected_candidates=selected_candidates,
        close=close,
        returns=returns,
        initial_capital=initial_capital,
        cost_bps=default_cost_bps,
    )
    yearly = _yearly_performance(
        selected_candidates=selected_candidates,
        baselines=baseline_evaluated,
        initial_capital=initial_capital,
    )
    ledger_rows = _position_ledger_rows(
        selected_candidates=selected_candidates,
        baselines=baseline_evaluated,
        close=close,
        returns=returns,
        cost_bps=default_cost_bps,
        delay_days=default_delay_days,
    )
    _write_csv(ledger_abs, _ledger_fieldnames(), ledger_rows)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "research_only_backtest_complete",
        "decision": "first_priority_backtest_flow_complete_manual_review_required",
        "asset": "btc",
        "symbol": SYMBOL,
        "bundle_dir": _relpath(bundle_abs, root),
        "data": _data_section(daily),
        "first_priority_families": FIRST_PRIORITY_FAMILIES,
        "parameters": parameters,
        "optimization_objective": _optimization_objective(),
        "guardrails": _guardrails(),
        "baseline_performance": baseline_rows,
        "family_summaries": family_summaries,
        "overall_ranking": overall_ranking[:25],
        "walk_forward": walk_forward,
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
        "recommendations": _recommendations(family_summaries, walk_forward),
        "blockers": [],
    }
    _write_json(output_abs, payload)
    _write_text(markdown_abs, _markdown(payload))
    return payload


def _candidate_specs() -> list[CandidateSpec]:
    specs: list[CandidateSpec] = []
    for window in MOMENTUM_WINDOWS:
        specs.append(
            CandidateSpec(
                family_id="t01_twelve_month_momentum",
                variant_id="t01_momentum_binary",
                label="T01 12-month momentum binary exposure",
                params={"momentum_window": window, "position_mode": "binary"},
            )
        )
        for vol_window in VOL_WINDOWS:
            for target_vol in TARGET_VOLS:
                specs.append(
                    CandidateSpec(
                        family_id="t01_twelve_month_momentum",
                        variant_id="t01_momentum_vol_target",
                        label="T01 12-month momentum with volatility target",
                        params={
                            "momentum_window": window,
                            "position_mode": "vol_target",
                            "vol_window": vol_window,
                            "target_vol": target_vol,
                        },
                    )
                )
    for fast in MA_FAST_WINDOWS:
        for slow in MA_SLOW_WINDOWS:
            if fast >= slow:
                continue
            specs.append(
                CandidateSpec(
                    family_id="t02_long_ma_trend",
                    variant_id="t02_ma_binary",
                    label="T02 long MA trend binary exposure",
                    params={"ma_fast": fast, "ma_slow": slow, "position_mode": "binary"},
                )
            )
            for vol_window in VOL_WINDOWS:
                for target_vol in TARGET_VOLS:
                    specs.append(
                        CandidateSpec(
                            family_id="t02_long_ma_trend",
                            variant_id="t02_ma_vol_target",
                            label="T02 long MA trend with volatility target",
                            params={
                                "ma_fast": fast,
                                "ma_slow": slow,
                                "position_mode": "vol_target",
                                "vol_window": vol_window,
                                "target_vol": target_vol,
                            },
                        )
                    )
    for fast, slow in EWMAC_PAIRS:
        for vol_window in EWMAC_VOL_WINDOWS:
            for scalar in EWMAC_FORECAST_SCALARS:
                specs.append(
                    CandidateSpec(
                        family_id="t03_ewmac_forecast",
                        variant_id="t03_ewmac_fraction",
                        label="T03 EWMAC continuous forecast exposure",
                        params={
                            "ewmac_fast": fast,
                            "ewmac_slow": slow,
                            "forecast_scalar": scalar,
                            "position_mode": "forecast_fraction",
                            "vol_window": vol_window,
                            "forecast_cap": FORECAST_CAP,
                        },
                    )
                )
                for target_vol in TARGET_VOLS:
                    specs.append(
                        CandidateSpec(
                            family_id="t03_ewmac_forecast",
                            variant_id="t03_ewmac_vol_target",
                            label="T03 EWMAC continuous forecast with volatility target",
                            params={
                                "ewmac_fast": fast,
                                "ewmac_slow": slow,
                                "forecast_scalar": scalar,
                                "position_mode": "forecast_vol_target",
                                "vol_window": vol_window,
                                "target_vol": target_vol,
                                "forecast_cap": FORECAST_CAP,
                            },
                        )
                    )
    return specs


def _baseline_specs() -> list[CandidateSpec]:
    return [
        CandidateSpec("baseline", "buy_hold_btc", "Buy and hold BTC", {"position_mode": "buy_hold"}),
        CandidateSpec("baseline", "fixed_50pct_btc", "Fixed 50% BTC exposure", {"position_mode": "fixed_50pct"}),
    ]


def _evaluate_spec(
    spec: CandidateSpec,
    *,
    close: pd.Series,
    returns: pd.Series,
    initial_capital: float,
    cost_bps: float,
    delay_days: int,
) -> EvaluatedCandidate:
    raw_signal = _raw_signal_for_spec(spec, close=close, returns=returns)
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


def _raw_signal_for_spec(spec: CandidateSpec, *, close: pd.Series, returns: pd.Series) -> pd.Series:
    params = spec.params
    mode = str(params.get("position_mode", ""))
    if mode == "buy_hold":
        return pd.Series(1.0, index=close.index)
    if mode == "fixed_50pct":
        return pd.Series(0.5, index=close.index)
    if spec.family_id == "t01_twelve_month_momentum":
        signal = (close.pct_change(int(params["momentum_window"])) > 0.0).astype(float)
        return _apply_position_mode(signal, returns=returns, params=params)
    if spec.family_id == "t02_long_ma_trend":
        fast = close.rolling(int(params["ma_fast"])).mean()
        slow = close.rolling(int(params["ma_slow"])).mean()
        signal = ((fast > slow) & (close > slow)).astype(float)
        return _apply_position_mode(signal, returns=returns, params=params)
    if spec.family_id == "t03_ewmac_forecast":
        fast_span = int(params["ewmac_fast"])
        slow_span = int(params["ewmac_slow"])
        vol_window = int(params["vol_window"])
        forecast_cap = float(params.get("forecast_cap", FORECAST_CAP))
        fast = close.ewm(span=fast_span, adjust=False, min_periods=fast_span).mean()
        slow = close.ewm(span=slow_span, adjust=False, min_periods=slow_span).mean()
        price_vol = returns.rolling(vol_window).std(ddof=0) * math.sqrt(365.0) * close
        raw_forecast = ((fast - slow) / price_vol).replace([math.inf, -math.inf], 0.0).fillna(0.0)
        forecast = (raw_forecast * float(params["forecast_scalar"])).clip(-forecast_cap, forecast_cap)
        fraction = (forecast.clip(lower=0.0) / forecast_cap).clip(0.0, 1.0)
        if mode == "forecast_vol_target":
            return _apply_vol_target(fraction, returns=returns, params=params)
        return fraction
    raise ValueError(f"Unsupported first priority strategy family: {spec.family_id}")


def _apply_position_mode(signal: pd.Series, *, returns: pd.Series, params: Mapping[str, Any]) -> pd.Series:
    mode = str(params.get("position_mode", "binary"))
    if mode == "vol_target":
        return _apply_vol_target(signal, returns=returns, params=params)
    return signal.fillna(0.0).clip(0.0, 1.0)


def _apply_vol_target(signal: pd.Series, *, returns: pd.Series, params: Mapping[str, Any]) -> pd.Series:
    vol_window = int(params.get("vol_window", 20))
    target_vol = float(params.get("target_vol", 0.25))
    realized_vol = returns.rolling(vol_window).std(ddof=0) * math.sqrt(365.0)
    scalar = (target_vol / realized_vol).replace([math.inf, -math.inf], 0.0).fillna(0.0)
    return (signal.fillna(0.0) * scalar).clip(0.0, MAX_EXPOSURE)


def _performance(
    *,
    strategy_returns: pd.Series,
    equity: pd.Series,
    exposure: pd.Series,
    turnover: pd.Series,
    cost: pd.Series,
) -> dict[str, Any]:
    if strategy_returns.empty or equity.empty:
        return _empty_metrics()
    first = float(equity.iloc[0])
    total_return = float(equity.iloc[-1] / first - 1.0) if first else 0.0
    days = max(1, int((equity.index.max() - equity.index.min()).days))
    annual_return = (1.0 + total_return) ** (365.0 / days) - 1.0 if total_return > -1.0 else -1.0
    std = float(strategy_returns.std(ddof=0))
    annual_vol = std * math.sqrt(365.0)
    downside = strategy_returns[strategy_returns < 0.0]
    downside_std = float(downside.std(ddof=0)) if len(downside) else 0.0
    downside_vol = downside_std * math.sqrt(365.0)
    sharpe = float(strategy_returns.mean() / std * math.sqrt(365.0)) if std > 0 else 0.0
    sortino = float(strategy_returns.mean() / downside_std * math.sqrt(365.0)) if downside_std > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
    dd_end = drawdown.idxmin() if len(drawdown) else None
    dd_start = equity.loc[:dd_end].idxmax() if dd_end is not None else None
    dd_days = int((pd.Timestamp(dd_end) - pd.Timestamp(dd_start)).days) if dd_end is not None and dd_start is not None else 0
    calmar = float(annual_return / abs(max_drawdown)) if max_drawdown < 0 else 0.0
    nonzero = strategy_returns[exposure > 0.0]
    return {
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "annual_volatility_pct": _round(annual_vol * 100.0),
        "downside_volatility_pct": _round(downside_vol * 100.0),
        "sharpe_ratio": _round(sharpe),
        "sortino_ratio": _round(sortino),
        "calmar_ratio": _round(calmar),
        "max_drawdown_pct": _round(max_drawdown * 100.0),
        "max_drawdown_abs_pct": _round(abs(max_drawdown) * 100.0),
        "max_drawdown_start": _timestamp_text(dd_start) if dd_start is not None else "",
        "max_drawdown_end": _timestamp_text(dd_end) if dd_end is not None else "",
        "max_drawdown_days": dd_days,
        "final_equity": _round(float(equity.iloc[-1])),
        "average_exposure": _round(float(exposure.mean())) if len(exposure) else 0.0,
        "max_exposure": _round(float(exposure.max())) if len(exposure) else 0.0,
        "days_with_exposure": int((exposure > 0.0).sum()),
        "turnover": _round(float(turnover.sum())),
        "exposure_change_count": int((turnover > 1e-12).sum()),
        "fee_return_pct": _round(float(cost.sum()) * 100.0),
        "winning_day_pct": _round(float((nonzero > 0.0).mean()) * 100.0) if len(nonzero) else 0.0,
    }


def _score(metrics: Mapping[str, Any], *, buy_hold_metrics: Mapping[str, Any]) -> float:
    annual_return = _float(metrics, "annual_return_pct")
    sharpe = _float(metrics, "sharpe_ratio")
    drawdown = _float(metrics, "max_drawdown_abs_pct")
    turnover = _float(metrics, "turnover")
    fee = _float(metrics, "fee_return_pct")
    average_exposure = _float(metrics, "average_exposure")
    total_return = _float(metrics, "total_return_pct")
    drawdown_reduction = _float(buy_hold_metrics, "max_drawdown_abs_pct") - drawdown
    low_exposure_penalty = 100.0 if average_exposure < MIN_MEANINGFUL_AVERAGE_EXPOSURE else 0.0
    low_return_penalty = 50.0 if total_return < 5.0 else 0.0
    return round(
        annual_return
        + 10.0 * sharpe
        + 0.25 * drawdown_reduction
        - 0.75 * drawdown
        - 0.05 * turnover
        - fee
        - low_exposure_penalty
        - low_return_penalty,
        6,
    )


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
    metrics = row["metrics"]
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


def _family_summaries(
    evaluated: list[EvaluatedCandidate],
    *,
    buy_hold_metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    summaries = []
    for family_id in FIRST_PRIORITY_FAMILIES:
        rows = [candidate for candidate in evaluated if candidate.spec.family_id == family_id]
        ranked = sorted(
            [_result_row(candidate, buy_hold_metrics=buy_hold_metrics) for candidate in rows],
            key=lambda row: (-float(row["score"]), str(row["candidate_id"])),
        )
        default = _default_candidate_for_family(family_id, ranked)
        selected = ranked[0] if ranked else {}
        positive = sum(1 for row in ranked if _float(row["metrics"], "total_return_pct") > 0.0)
        dd_better = sum(
            1
            for row in ranked
            if _float(row["metrics"], "max_drawdown_abs_pct") < _float(buy_hold_metrics, "max_drawdown_abs_pct")
        )
        summaries.append(
            {
                "family_id": family_id,
                "candidate_count": len(ranked),
                "selected_candidate": selected,
                "default_candidate": default,
                "top_5": ranked[:5],
                "positive_total_return_share": _round(positive / len(ranked)) if ranked else 0.0,
                "drawdown_below_buy_hold_share": _round(dd_better / len(ranked)) if ranked else 0.0,
            }
        )
    return summaries


def _default_candidate_for_family(family_id: str, ranked: list[Mapping[str, Any]]) -> dict[str, Any]:
    for row in ranked:
        params = _mapping(row.get("params"))
        if family_id == "t01_twelve_month_momentum" and params == {"momentum_window": 365, "position_mode": "binary"}:
            return dict(row)
        if family_id == "t02_long_ma_trend" and params == {"ma_fast": 120, "ma_slow": 200, "position_mode": "binary"}:
            return dict(row)
        if family_id == "t03_ewmac_forecast" and params == {
            "ewmac_fast": 16,
            "ewmac_slow": 64,
            "forecast_cap": 20.0,
            "forecast_scalar": 100.0,
            "position_mode": "forecast_fraction",
            "vol_window": 20,
        }:
            return dict(row)
    return {}


def _walk_forward(
    *,
    specs: list[CandidateSpec],
    close: pd.Series,
    returns: pd.Series,
    initial_capital: float,
    cost_bps: float,
    delay_days: int,
    train_days: int = 1095,
    test_days: int = 180,
    step_days: int = 180,
) -> dict[str, Any]:
    folds = []
    n = len(close)
    fold_id = 1
    test_start = train_days
    while test_start < n:
        test_end = min(test_start + test_days, n)
        if test_end - test_start < 90:
            break
        train_start = max(0, test_start - train_days)
        train_index = close.index[train_start:test_start]
        test_index = close.index[test_start:test_end]
        if len(train_index) < 365 or len(test_index) < 90:
            test_start += step_days
            continue
        baseline_train = _evaluate_period(
            _evaluate_spec(
                _baseline_specs()[0],
                close=close,
                returns=returns,
                initial_capital=initial_capital,
                cost_bps=cost_bps,
                delay_days=delay_days,
            ),
            train_index,
            initial_capital=initial_capital,
        )
        baseline_test = _evaluate_period(
            _evaluate_spec(
                _baseline_specs()[0],
                close=close,
                returns=returns,
                initial_capital=initial_capital,
                cost_bps=cost_bps,
                delay_days=delay_days,
            ),
            test_index,
            initial_capital=initial_capital,
        )
        fold_rows = []
        for family_id in FIRST_PRIORITY_FAMILIES:
            family_specs = [spec for spec in specs if spec.family_id == family_id]
            train_rank = []
            evaluated_by_id: dict[str, EvaluatedCandidate] = {}
            for spec in family_specs:
                candidate = _evaluate_spec(
                    spec,
                    close=close,
                    returns=returns,
                    initial_capital=initial_capital,
                    cost_bps=cost_bps,
                    delay_days=delay_days,
                )
                evaluated_by_id[spec.candidate_id] = candidate
                train_metrics = _evaluate_period(candidate, train_index, initial_capital=initial_capital)
                train_rank.append(
                    {
                        "candidate_id": spec.candidate_id,
                        "params": spec.params,
                        "score": _score(train_metrics, buy_hold_metrics=baseline_train),
                        "metrics": train_metrics,
                    }
                )
            selected = max(train_rank, key=lambda row: (float(row["score"]), str(row["candidate_id"])))
            selected_candidate = evaluated_by_id[str(selected["candidate_id"])]
            test_metrics = _evaluate_period(selected_candidate, test_index, initial_capital=initial_capital)
            acceptable = (
                _float(test_metrics, "max_drawdown_abs_pct") <= _float(baseline_test, "max_drawdown_abs_pct") + 5.0
                and _float(test_metrics, "total_return_pct") >= -25.0
            )
            fold_rows.append(
                {
                    "family_id": family_id,
                    "selected_candidate_id": selected["candidate_id"],
                    "selected_params": selected["params"],
                    "train_metrics": selected["metrics"],
                    "test_metrics": test_metrics,
                    "buy_hold_test_metrics": baseline_test,
                    "acceptable": bool(acceptable),
                }
            )
        folds.append(
            {
                "fold_id": fold_id,
                "train_start": _timestamp_text(train_index.min()),
                "train_end": _timestamp_text(train_index.max()),
                "test_start": _timestamp_text(test_index.min()),
                "test_end": _timestamp_text(test_index.max()),
                "families": fold_rows,
            }
        )
        fold_id += 1
        test_start += step_days
    family_summary = {}
    for family_id in FIRST_PRIORITY_FAMILIES:
        family_rows = [row for fold in folds for row in fold["families"] if row["family_id"] == family_id]
        acceptable = sum(1 for row in family_rows if row["acceptable"])
        family_summary[family_id] = {
            "fold_count": len(family_rows),
            "acceptable_fold_count": acceptable,
            "pass": bool(len(family_rows) >= 3 and acceptable >= max(2, math.ceil(len(family_rows) * 0.5))),
        }
    return {
        "folds": folds,
        "summary": {
            "fold_count": len(folds),
            "family_summary": family_summary,
            "all_first_priority_families_have_walk_forward": all(
                data["fold_count"] >= 3 for data in family_summary.values()
            )
            if family_summary
            else False,
        },
    }


def _evaluate_period(candidate: EvaluatedCandidate, index: pd.Index, *, initial_capital: float) -> dict[str, Any]:
    returns = candidate.strategy_returns.loc[index].fillna(0.0)
    exposure = candidate.exposure.loc[index].fillna(0.0)
    turnover = candidate.turnover.loc[index].fillna(0.0)
    cost = candidate.cost.loc[index].fillna(0.0)
    equity = float(initial_capital) * (1.0 + returns).cumprod()
    return _performance(strategy_returns=returns, equity=equity, exposure=exposure, turnover=turnover, cost=cost)


def _cost_stress(
    *,
    selected_candidates: list[EvaluatedCandidate],
    close: pd.Series,
    returns: pd.Series,
    initial_capital: float,
    delay_days: int,
) -> list[dict[str, Any]]:
    rows = []
    for selected in selected_candidates:
        for cost_bps in COST_BPS_GRID:
            evaluated = _evaluate_spec(
                selected.spec,
                close=close,
                returns=returns,
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
    returns: pd.Series,
    initial_capital: float,
    cost_bps: float,
) -> list[dict[str, Any]]:
    rows = []
    for selected in selected_candidates:
        for delay_days in DELAY_DAYS_GRID:
            evaluated = _evaluate_spec(
                selected.spec,
                close=close,
                returns=returns,
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
    candidates = baselines + selected_candidates
    years = sorted({int(ts.year) for candidate in candidates for ts in candidate.strategy_returns.index})
    for year in years:
        for candidate in candidates:
            mask_index = candidate.strategy_returns.index[candidate.strategy_returns.index.year == year]
            if len(mask_index) == 0:
                continue
            rows.append(
                {
                    "year": year,
                    "segment": f"{year} partial" if len(mask_index) < 365 else str(year),
                    "candidate_id": candidate.spec.candidate_id,
                    "family_id": candidate.spec.family_id,
                    "variant_id": candidate.spec.variant_id,
                    "params": candidate.spec.params,
                    "day_count": len(mask_index),
                    "metrics": _evaluate_period(candidate, mask_index, initial_capital=initial_capital),
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


def _recommendations(family_summaries: list[Mapping[str, Any]], walk_forward: Mapping[str, Any]) -> list[str]:
    if not family_summaries:
        return ["历史长度不足，不做参数优化，也不输出候选排名。"]
    wf_summary = _mapping(walk_forward.get("summary"))
    family_wf = _mapping(wf_summary.get("family_summary"))
    ranked = sorted(
        family_summaries,
        key=lambda item: -float(_mapping(_mapping(item).get("selected_candidate")).get("score", -9999.0) or -9999.0),
    )
    top = _mapping(ranked[0])
    top_family = str(top.get("family_id", ""))
    top_selected = _mapping(top.get("selected_candidate"))
    notes = [
        f"第一优先级验证流程已跑通；当前全样本评分最高的策略族是 `{top_family}`。",
        "不要把本报告当成 live-ready 结论；下一步应人工审阅 walk-forward、成本压力和年度分段。",
    ]
    wf_top = _mapping(family_wf.get(top_family))
    if not bool(wf_top.get("pass", False)):
        notes.append(f"`{top_family}` 未通过 walk-forward 接受规则，必须保持 research-only。")
    if _float(_mapping(top_selected.get("metrics")), "exposure_change_count") <= 5:
        notes.append(f"`{top_family}` 换仓次数很低，应明确它是日线趋势暴露管理，不是高频策略。")
    return notes


def _parameters(*, default_cost_bps: float, default_delay_days: int) -> dict[str, Any]:
    return {
        "minimum_daily_rows": MIN_DAILY_ROWS,
        "default_cost_bps": float(default_cost_bps),
        "default_delay_days": int(default_delay_days),
        "cost_bps_grid": COST_BPS_GRID,
        "delay_days_grid": DELAY_DAYS_GRID,
        "momentum_windows": MOMENTUM_WINDOWS,
        "ma_fast_windows": MA_FAST_WINDOWS,
        "ma_slow_windows": MA_SLOW_WINDOWS,
        "ewmac_pairs": [list(pair) for pair in EWMAC_PAIRS],
        "ewmac_vol_windows": EWMAC_VOL_WINDOWS,
        "ewmac_forecast_scalars": EWMAC_FORECAST_SCALARS,
        "vol_windows": VOL_WINDOWS,
        "target_vols": TARGET_VOLS,
        "forecast_cap": FORECAST_CAP,
        "max_exposure": MAX_EXPOSURE,
        "minimum_meaningful_average_exposure": MIN_MEANINGFUL_AVERAGE_EXPOSURE,
    }


def _optimization_objective() -> dict[str, Any]:
    return {
        "name": "cost_adjusted_return_risk_score",
        "formula": "annual_return_pct + 10*sharpe + 0.25*drawdown_reduction_vs_buy_hold - 0.75*max_drawdown_abs_pct - 0.05*turnover - fee_return_pct - low_exposure_penalty - low_return_penalty",
        "minimum_meaningful_average_exposure": MIN_MEANINGFUL_AVERAGE_EXPOSURE,
        "notes": [
            "optimization uses cost-adjusted returns at the default cost model",
            "score penalizes drawdown, turnover and fees; it is not Sharpe-only optimization",
            "score penalizes candidates that avoid risk by holding near-cash exposure or producing negligible total return",
            "walk-forward results are reported separately and must be reviewed before strategy claims",
        ],
    }


def _data_section(daily: pd.DataFrame) -> dict[str, Any]:
    return {
        "daily_rows": int(len(daily)),
        "start": _timestamp_text(daily.index.min()) if len(daily) else "",
        "end": _timestamp_text(daily.index.max()) if len(daily) else "",
        "source": "OKX public local spot daily bundle",
    }


def _guardrails() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_candidate_ready": False,
        "live_order_allowed": False,
        "broker_calls_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "all_exposures_use_t_plus_1_or_later_signal": True,
        "does_not_unlock_paper_or_live": True,
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    data = _mapping(payload.get("data"))
    lines = [
        "# BTC 趋势第一优先级策略回测报告",
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
            f"当前日线行数 {data.get('daily_rows', 0)}，不足 1095 行。第一优先级策略不输出排名，不做参数优化。",
            "",
            "## 阻断项",
            "",
        ]
        for blocker in payload.get("blockers", []):
            lines.append(f"- {blocker}")
        lines.append("")
        return "\n".join(lines)

    lines += [
        "本报告完成第一优先级趋势策略的参数网格、成本压力、执行延迟、walk-forward 和年度分段验证。它只支持研究判断，不解锁纸盘或实盘。",
        "",
        "## 数据",
        "",
        "| 项目 | 数值 |",
        "| --- | ---: |",
        f"| 日线行数 | {data.get('daily_rows', 0)} |",
        f"| 开始 | {data.get('start', '')} |",
        f"| 结束 | {data.get('end', '')} |",
        "",
        "## 基准",
        "",
        "| 基准 | 总收益 | 年化收益 | 年化波动 | 最大回撤 | Sharpe |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("baseline_performance", []):
        item = _mapping(row)
        metrics = _mapping(item.get("metrics"))
        lines.append(
            f"| {item.get('label', item.get('candidate_id', ''))} | {metrics.get('total_return_pct', 0)}% | "
            f"{metrics.get('annual_return_pct', 0)}% | {metrics.get('annual_volatility_pct', 0)}% | "
            f"{metrics.get('max_drawdown_abs_pct', 0)}% | {metrics.get('sharpe_ratio', 0)} |"
        )

    lines += [
        "",
        "## 优化目标",
        "",
        "本轮没有用 Sharpe 单指标选参数，而是使用成本调整后的收益/风险综合分数：",
        "",
        "```text",
        str(_mapping(payload.get("optimization_objective")).get("formula", "")),
        "```",
        "",
        f"最低有效平均仓位约束：`{_mapping(payload.get('optimization_objective')).get('minimum_meaningful_average_exposure', 0)}`。低暴露或几乎无收益的候选会被惩罚，避免选出“躲在现金里”的假优胜者。",
        "",
        "## 第一优先级策略优化结果",
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
            f"{selected.get('score', 0)} | "
            f"{metrics.get('total_return_pct', 0)}% | {metrics.get('max_drawdown_abs_pct', 0)}% | "
            f"{metrics.get('sharpe_ratio', 0)} | {metrics.get('average_exposure', 0)} | {metrics.get('exposure_change_count', 0)} |"
        )

    wf_summary = _mapping(_mapping(payload.get("walk_forward")).get("summary"))
    family_wf = _mapping(wf_summary.get("family_summary"))
    lines += [
        "",
        "## Walk-forward",
        "",
        "| 策略族 | Fold 数 | 可接受 Fold | 通过 |",
        "| --- | ---: | ---: | --- |",
    ]
    for family_id, wf in family_wf.items():
        wf_map = _mapping(wf)
        lines.append(
            f"| {family_id} | {wf_map.get('fold_count', 0)} | "
            f"{wf_map.get('acceptable_fold_count', 0)} | `{wf_map.get('pass', False)}` |"
        )

    lines += [
        "",
        "## 成本压力",
        "",
        "| 策略族 | 成本 bps | 总收益 | 最大回撤 | Sharpe |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("cost_stress", []):
        item = _mapping(row)
        metrics = _mapping(item.get("metrics"))
        lines.append(
            f"| {item.get('family_id', '')} | {item.get('cost_bps', 0)} | "
            f"{metrics.get('total_return_pct', 0)}% | {metrics.get('max_drawdown_abs_pct', 0)}% | "
            f"{metrics.get('sharpe_ratio', 0)} |"
        )

    lines += [
        "",
        "## 执行延迟压力",
        "",
        "| 策略族 | 延迟天数 | 总收益 | 最大回撤 | Sharpe |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("delay_stress", []):
        item = _mapping(row)
        metrics = _mapping(item.get("metrics"))
        lines.append(
            f"| {item.get('family_id', '')} | T+{item.get('delay_days', 0)} | "
            f"{metrics.get('total_return_pct', 0)}% | {metrics.get('max_drawdown_abs_pct', 0)}% | "
            f"{metrics.get('sharpe_ratio', 0)} |"
        )

    lines += [
        "",
        "## 年度分段",
        "",
        "| 年度 | 策略族 | 总收益 | 最大回撤 | Sharpe |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in payload.get("yearly_performance", []):
        item = _mapping(row)
        if item.get("family_id") == "baseline":
            continue
        metrics = _mapping(item.get("metrics"))
        lines.append(
            f"| {item.get('segment', item.get('year', ''))} | {item.get('family_id', '')} | "
            f"{metrics.get('total_return_pct', 0)}% | {metrics.get('max_drawdown_abs_pct', 0)}% | "
            f"{metrics.get('sharpe_ratio', 0)} |"
        )

    lines += [
        "",
        "## 输出",
        "",
        f"- 参数网格：`{_mapping(payload.get('grid_output')).get('path', '')}`",
        f"- 仓位 ledger：`{_mapping(payload.get('position_ledger')).get('path', '')}`",
        "",
        "## 研究结论限制",
        "",
        "- 这是单资产 BTC 日线趋势研究，不是多品种 CTA。",
        "- 参数优化结果不能直接当作策略有效证明，必须结合 walk-forward、成本压力和年度分段。",
        "- 本报告不调用 broker、不使用 private/order endpoint、不允许实盘。",
        "",
        "## 下一步",
        "",
    ]
    for note in payload.get("recommendations", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def _metrics_by_candidate_id(candidates: list[EvaluatedCandidate]) -> dict[str, dict[str, Any]]:
    return {
        candidate.spec.variant_id: {
            "candidate_id": candidate.spec.candidate_id,
            "metrics": candidate.metrics,
            "params": candidate.spec.params,
        }
        for candidate in candidates
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "total_return_pct": 0.0,
        "annual_return_pct": 0.0,
        "annual_volatility_pct": 0.0,
        "downside_volatility_pct": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "calmar_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "max_drawdown_abs_pct": 0.0,
        "max_drawdown_start": "",
        "max_drawdown_end": "",
        "max_drawdown_days": 0,
        "final_equity": 0.0,
        "average_exposure": 0.0,
        "max_exposure": 0.0,
        "days_with_exposure": 0,
        "turnover": 0.0,
        "exposure_change_count": 0,
        "fee_return_pct": 0.0,
        "winning_day_pct": 0.0,
    }


def _empty_walk_forward_summary() -> dict[str, Any]:
    return {
        "fold_count": 0,
        "family_summary": {},
        "all_first_priority_families_have_walk_forward": False,
    }


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


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _timestamp_text(value: object) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _float(metrics: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(metrics.get(key, default))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _round(value: float, digits: int = 6) -> float:
    if not math.isfinite(float(value)):
        return 0.0
    return round(float(value), digits)


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC first-priority trend strategy backtest report.")
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
    payload = build_btc_trend_priority_strategy_backtest_report(
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
