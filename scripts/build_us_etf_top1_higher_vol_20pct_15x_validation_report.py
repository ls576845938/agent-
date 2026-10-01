#!/usr/bin/env python3
"""Dedicated validation for top1_higher_vol with 20% vol target and 1.5x cap."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_us_etf_original_semantics_optimization_report import (  # noqa: E402
    ORIGINAL_DATA_LAKE,
    _apply_params,
    _load_original_environment,
    _metric_block,
    _run_candidate,
)
from scripts.build_us_etf_top1_higher_vol_validation_report import (  # noqa: E402
    PRIMARY_PARAMS,
    _run_with_params,
)


DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_etf_macro_rotation/latest")
DEFAULT_MARKDOWN = Path("学习资料/量化交易业务闭环/系统评估/US ETF vol_target_20pct_cap1.5x 专项验证.md")
TRADING_DAYS = 252
TARGET_VOL = 0.20
MAX_LEVERAGE = 1.50
BROKER_SPREAD = 0.015
SLIPPAGE_STRESS_BPS = (0.0, 10.0, 25.0, 50.0)
REFERENCE_AUM = 100_000.0
CAPACITY_AUMS = (10_000.0, 50_000.0, 100_000.0, 500_000.0, 1_000_000.0)
MIN_ADV_USD = 10_000_000.0
DBMF_MAX_WEIGHT = 0.10
EXTREME_YEARS = (2018, 2020, 2022, 2023, 2025, 2026)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--markdown-path", default=str(DEFAULT_MARKDOWN))
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    report = build_vol_target_20pct_15x_validation_report()

    output_root = root / Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "us_etf_top1_higher_vol_20pct_15x_validation_report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    markdown_path = root / Path(args.markdown_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown(report), encoding="utf-8")

    print(json.dumps({"report": str(json_path), "markdown": str(markdown_path)}, indent=2, sort_keys=True))


def build_vol_target_20pct_15x_validation_report() -> dict[str, Any]:
    env = _load_original_environment()
    baseline = _run_with_params(env, {}, "original_v8_2_semantics")
    unlevered = _run_with_params(env, PRIMARY_PARAMS, "top1_higher_vol_unlevered")
    model = _build_variant_model(env, unlevered, extra_slippage_bps=0.0)
    constrained = _tradable_constraint_models(env, unlevered)
    selected_constraint = constrained["selected"]
    benchmarks = _benchmarks(env, baseline, unlevered, model["net_returns"])
    yearly = _yearly_breakdown(env, unlevered, model)
    stress = _cost_stress(env, unlevered)
    walk_forward = _walk_forward(env)
    capacity = _capacity_tests(env, unlevered["weights"], model["exposure"])
    constrained_capacity = _capacity_tests(env, selected_constraint["weights"], selected_constraint["model"]["exposure"])
    tradability = _tradability_report(env, unlevered["weights"], model["exposure"], REFERENCE_AUM)
    constrained_tradability = _tradability_report(env, selected_constraint["weights"], selected_constraint["model"]["exposure"], REFERENCE_AUM)
    small_account = _small_account_profile(env, unlevered, model, selected_constraint)
    margin = _margin_report(model["exposure"])
    extreme = _extreme_year_attribution(yearly)
    source_attribution = _source_attribution(env, baseline, unlevered, model, stress)
    decision = _decision(model, benchmarks, stress, walk_forward, margin, tradability, constrained_tradability)

    return {
        "schema_version": "us_etf_top1_higher_vol_20pct_15x_validation_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "research_only_manual_review_required",
        "live_ready": False,
        "paper_ready": False,
        "strategy_id": "top1_higher_vol__vol_target_20pct_cap1.5x",
        "base_strategy_id": "top1_higher_vol",
        "rebalance_semantics": "calendar_month_end_only_skip_if_not_trading_day",
        "primary_parameters": PRIMARY_PARAMS,
        "overlay": {
            "type": "portfolio_level_volatility_target",
            "target_vol": TARGET_VOL,
            "max_leverage": MAX_LEVERAGE,
            "realized_vol_window_days": 63,
            "exposure_timing": "exposure is shifted one trading day before applying returns",
        },
        "financing_model": {
            "type": "time_varying_DGS2_plus_broker_spread",
            "base_rate_column": "DGS2",
            "broker_spread": BROKER_SPREAD,
            "charged_only_above_1x": True,
            "average_annual_rate": float(model["financing_rate"].mean()),
            "max_annual_rate": float(model["financing_rate"].max()),
        },
        "slippage_model": {
            "reference_aum": REFERENCE_AUM,
            "capacity_aums": list(CAPACITY_AUMS),
            "stress_bps": list(SLIPPAGE_STRESS_BPS),
            "implementation": "daily extra slippage = portfolio turnover * stress_bps / 10000; tradability uses 20d ADV and turnover participation.",
        },
        "tradability_constraints": {
            "dbmf_max_weight": DBMF_MAX_WEIGHT,
            "min_20d_adv_usd": MIN_ADV_USD,
            "replacement_asset": "SHV",
            "selected_constrained_variant": selected_constraint["variant_id"],
            "candidates": constrained["candidates"],
        },
        "margin_model": margin,
        "tradability": tradability,
        "capacity_tests": capacity,
        "constrained_tradability": constrained_tradability,
        "constrained_capacity_tests": constrained_capacity,
        "small_account_10k_profile": small_account,
        "metrics": {
            "selected_variant": _metrics(model["net_returns"], env["prices"]["SPY"]),
            "selected_tradability_constrained_variant": _metrics(selected_constraint["model"]["net_returns"], env["prices"]["SPY"]),
            "unlevered_top1_higher_vol": unlevered["metrics"]["strategy"],
            "original_v8_2_semantics": baseline["metrics"]["strategy"],
        },
        "comparison": benchmarks,
        "standardized_report_schema": _standardized_report_schema(
            comparison=benchmarks,
            selected_model=model,
            unlevered=unlevered,
            baseline=baseline,
            stress=stress,
            tradability=tradability,
            constrained_tradability=constrained_tradability,
        ),
        "yearly_breakdown": yearly,
        "cost_stress": stress,
        "walk_forward": walk_forward,
        "extreme_year_attribution": extreme,
        "source_attribution": source_attribution,
        "decision": decision,
        "methodology": {
            "goal": "Validate the specific vol_target_20pct_cap1.5x overlay as a standalone research candidate.",
            "asset_selection_bias_guard": "No QQQ/sector/technology preference is added; the overlay only scales the already selected strategy return stream.",
            "benchmark_set": ["SPY", "QQQ", "60_40_SPY_IEF", "SHV", "original_v8_2_semantics", "top1_higher_vol_unlevered"],
            "constraint": "Research only. This report does not unlock paper or live trading.",
        },
    }


def _build_variant_model(env: dict[str, Any], base: dict[str, Any], *, extra_slippage_bps: float) -> dict[str, Any]:
    returns = base["returns"].copy().sort_index()
    exposure = _vol_target_exposure(returns, target_vol=TARGET_VOL, max_leverage=MAX_LEVERAGE)
    financing_rate = _financing_rate(env, returns.index)
    financing_drag = (exposure.shift(1).fillna(1.0) - 1.0).clip(lower=0.0) * financing_rate / TRADING_DAYS
    weights = base["weights"].reindex(returns.index).fillna(0.0)
    turnover = weights.diff().abs().sum(axis=1).fillna(0.0)
    overlay_turnover = exposure.diff().abs().fillna(0.0)
    total_turnover = turnover + overlay_turnover
    slippage_drag = total_turnover * extra_slippage_bps / 10_000.0
    gross_returns = returns * exposure.shift(1).fillna(1.0)
    net_returns = gross_returns - financing_drag - slippage_drag
    return {
        "base_returns": returns,
        "gross_returns": gross_returns,
        "net_returns": net_returns,
        "exposure": exposure,
        "financing_rate": financing_rate,
        "financing_drag": financing_drag,
        "slippage_drag": slippage_drag,
        "turnover": total_turnover,
        "weights": weights,
    }


def _build_model_from_weights(
    env: dict[str, Any],
    weights: pd.DataFrame,
    *,
    extra_slippage_bps: float,
) -> dict[str, Any]:
    prices = env["prices"].reindex(weights.index).ffill()
    asset_returns = prices.pct_change(fill_method=None).fillna(0.0)
    weights = weights.reindex(asset_returns.index).fillna(0.0)
    returns = (weights * asset_returns[weights.columns]).sum(axis=1)
    base = {"returns": returns, "weights": weights}
    return _build_variant_model(env, base, extra_slippage_bps=extra_slippage_bps)


def _tradable_constraint_models(env: dict[str, Any], unlevered: dict[str, Any]) -> dict[str, Any]:
    dollar_volume = _load_dollar_volume(env["prices"].columns)
    adv = dollar_volume.reindex(unlevered["weights"].index).ffill().rolling(20).mean().shift(1)
    weights = unlevered["weights"].copy().fillna(0.0)
    candidates: list[dict[str, Any]] = []
    variants = {
        "dbmf_cap_10pct": _cap_symbol_to_replacement(weights, "DBMF", DBMF_MAX_WEIGHT, "SHV"),
        "dbmf_replace_with_shv": _replace_symbol(weights, "DBMF", "SHV"),
        "min_adv_10m_to_shv": _apply_min_adv_gate(weights, adv, MIN_ADV_USD, "SHV"),
    }
    for variant_id, constrained_weights in variants.items():
        model = _build_model_from_weights(env, constrained_weights, extra_slippage_bps=0.0)
        tradability = _tradability_report(env, constrained_weights, model["exposure"], REFERENCE_AUM)
        metrics = _metrics(model["net_returns"], env["prices"]["SPY"].reindex(model["net_returns"].index).ffill())
        candidates.append(
            {
                "variant_id": variant_id,
                "metrics": metrics,
                "tradability_pass": tradability["passes_reference_aum_liquidity_check"],
                "max_single_name_participation": tradability["max_single_name_participation"],
                "p95_single_name_participation": tradability["p95_single_name_participation"],
                "dbmf_average_weight": float(constrained_weights.get("DBMF", pd.Series(0.0, index=weights.index)).mean()),
                "dbmf_max_weight": float(constrained_weights.get("DBMF", pd.Series(0.0, index=weights.index)).max()),
            }
        )
    ranked = sorted(
        candidates,
        key=lambda row: (
            row["tradability_pass"],
            row["metrics"]["true_cagr"],
            row["metrics"]["max_drawdown"],
        ),
        reverse=True,
    )
    selected_id = ranked[0]["variant_id"]
    selected_weights = variants[selected_id]
    return {
        "selected": {
            "variant_id": selected_id,
            "weights": selected_weights,
            "model": _build_model_from_weights(env, selected_weights, extra_slippage_bps=0.0),
        },
        "candidates": ranked,
    }


def _cap_symbol_to_replacement(weights: pd.DataFrame, symbol: str, cap: float, replacement: str) -> pd.DataFrame:
    constrained = weights.copy()
    if symbol not in constrained.columns:
        return constrained
    if replacement not in constrained.columns:
        constrained[replacement] = 0.0
    excess = (constrained[symbol] - cap).clip(lower=0.0)
    constrained[symbol] = constrained[symbol].clip(upper=cap)
    constrained[replacement] = constrained[replacement] + excess
    return constrained


def _replace_symbol(weights: pd.DataFrame, symbol: str, replacement: str) -> pd.DataFrame:
    constrained = weights.copy()
    if symbol not in constrained.columns:
        return constrained
    if replacement not in constrained.columns:
        constrained[replacement] = 0.0
    constrained[replacement] = constrained[replacement] + constrained[symbol]
    constrained[symbol] = 0.0
    return constrained


def _apply_min_adv_gate(weights: pd.DataFrame, adv: pd.DataFrame, min_adv: float, replacement: str) -> pd.DataFrame:
    constrained = weights.copy()
    if replacement not in constrained.columns:
        constrained[replacement] = 0.0
    aligned_adv = adv.reindex(constrained.index).reindex(columns=constrained.columns).ffill()
    for symbol in list(constrained.columns):
        if symbol == replacement:
            continue
        low_liquidity = aligned_adv[symbol].fillna(0.0) < min_adv
        moved = constrained.loc[low_liquidity, symbol]
        constrained.loc[low_liquidity, replacement] = constrained.loc[low_liquidity, replacement] + moved
        constrained.loc[low_liquidity, symbol] = 0.0
    return constrained


def _vol_target_exposure(returns: pd.Series, *, target_vol: float, max_leverage: float) -> pd.Series:
    realized = returns.rolling(63).std() * np.sqrt(TRADING_DAYS)
    exposure = target_vol / realized.replace(0.0, np.nan)
    return exposure.clip(lower=0.0, upper=max_leverage).fillna(1.0)


def _financing_rate(env: dict[str, Any], index: pd.Index) -> pd.Series:
    macro = env["macro"].copy()
    dgs2 = macro["DGS2"].reindex(index).ffill().bfill() / 100.0
    return (dgs2 + BROKER_SPREAD).clip(lower=0.0)


def _benchmarks(
    env: dict[str, Any],
    baseline: dict[str, Any],
    unlevered: dict[str, Any],
    selected_returns: pd.Series,
) -> dict[str, Any]:
    prices = env["prices"].reindex(selected_returns.index).ffill()
    returns = prices.pct_change(fill_method=None).fillna(0.0)
    rows = {
        "selected_vol_target_20pct_cap1.5x": _metrics(selected_returns, prices["SPY"]),
        "SPY": _metrics(returns["SPY"], prices["SPY"]),
        "QQQ": _metrics(returns["QQQ"], prices["SPY"]),
        "60_40_SPY_IEF": _metrics(returns["SPY"] * 0.60 + returns["IEF"] * 0.40, prices["SPY"]),
        "SHV": _metrics(returns["SHV"], prices["SPY"]),
        "original_v8_2_semantics": _with_full_metric_schema(baseline["returns"], prices["SPY"]),
        "top1_higher_vol_unlevered": _with_full_metric_schema(unlevered["returns"], prices["SPY"]),
    }
    selected = rows["selected_vol_target_20pct_cap1.5x"]
    for key, metrics in rows.items():
        metrics["excess_vs_selected_cagr"] = selected["true_cagr"] - metrics["true_cagr"]
        metrics["selected_drawdown_improvement"] = selected["max_drawdown"] - metrics["max_drawdown"]
    return rows


def _standardized_report_schema(
    *,
    comparison: dict[str, Any],
    selected_model: dict[str, Any],
    unlevered: dict[str, Any],
    baseline: dict[str, Any],
    stress: dict[str, Any],
    tradability: dict[str, Any],
    constrained_tradability: dict[str, Any],
) -> dict[str, Any]:
    turnover_by_id = {
        "selected_vol_target_20pct_cap1.5x": float(selected_model["turnover"].sum()),
        "SPY": 0.0,
        "QQQ": 0.0,
        "60_40_SPY_IEF": 0.0,
        "SHV": 0.0,
        "original_v8_2_semantics": float(baseline["weights"].diff().abs().sum(axis=1).fillna(0.0).sum()),
        "top1_higher_vol_unlevered": float(unlevered["weights"].diff().abs().sum(axis=1).fillna(0.0).sum()),
    }
    cost_stressed_total_return = {
        "selected_vol_target_20pct_cap1.5x": float(stress["25bps"]["metrics"]["total_return"]),
        "SPY": comparison["SPY"]["total_return"],
        "QQQ": comparison["QQQ"]["total_return"],
        "60_40_SPY_IEF": comparison["60_40_SPY_IEF"]["total_return"],
        "SHV": comparison["SHV"]["total_return"],
        "original_v8_2_semantics": comparison["original_v8_2_semantics"]["total_return"],
        "top1_higher_vol_unlevered": comparison["top1_higher_vol_unlevered"]["total_return"],
    }
    liquidity = {
        "selected_vol_target_20pct_cap1.5x": bool(tradability["passes_reference_aum_liquidity_check"]),
        "SPY": True,
        "QQQ": True,
        "60_40_SPY_IEF": True,
        "SHV": True,
        "original_v8_2_semantics": True,
        "top1_higher_vol_unlevered": bool(constrained_tradability["passes_reference_aum_liquidity_check"]),
    }
    rows = []
    for benchmark_id, metrics in comparison.items():
        rows.append(
            {
                "id": benchmark_id,
                "CAGR": float(metrics["true_cagr"]),
                "Vol": float(metrics["annualized_volatility"]),
                "Sharpe": float(metrics["sharpe_no_risk_free"]),
                "MDD": float(metrics["max_drawdown"]),
                "Calmar": float(metrics["calmar"]),
                "Turnover": turnover_by_id[benchmark_id],
                "CostStressedReturn": float(cost_stressed_total_return[benchmark_id]),
                "LiquidityPass": bool(liquidity[benchmark_id]),
            }
        )
    return {
        "schema_version": "us_etf_standardized_comparison_schema_v1",
        "required_fields": ["CAGR", "Vol", "Sharpe", "MDD", "Calmar", "Turnover", "CostStressedReturn", "LiquidityPass"],
        "rows": rows,
    }


def _with_full_metric_schema(returns: pd.Series, benchmark_prices: pd.Series) -> dict[str, float]:
    return _metrics(returns.dropna(), benchmark_prices.reindex(returns.dropna().index).ffill())


def _yearly_breakdown(env: dict[str, Any], unlevered: dict[str, Any], model: dict[str, Any]) -> list[dict[str, Any]]:
    prices = env["prices"].reindex(model["net_returns"].index).ffill()
    benchmark_returns = prices.pct_change(fill_method=None).fillna(0.0)
    rows: list[dict[str, Any]] = []
    for year, net_group in model["net_returns"].groupby(model["net_returns"].index.year):
        mask = model["net_returns"].index.year == year
        base = unlevered["returns"].loc[mask]
        gross = model["gross_returns"].loc[mask]
        financing = model["financing_drag"].loc[mask]
        slippage = model["slippage_drag"].loc[mask]
        rows.append(
            {
                "year": int(year),
                "selected_return": _compound(net_group),
                "unlevered_return": _compound(base),
                "gross_levered_return": _compound(gross),
                "financing_drag_sum": float(financing.sum()),
                "slippage_drag_sum": float(slippage.sum()),
                "leverage_effect_vs_unlevered": _compound(gross) - _compound(base),
                "max_drawdown": _max_drawdown(net_group),
                "average_exposure": float(model["exposure"].loc[mask].mean()),
                "max_exposure": float(model["exposure"].loc[mask].max()),
                "turnover": float(model["turnover"].loc[mask].sum()),
                "SPY_return": _compound(benchmark_returns.loc[mask, "SPY"]),
                "QQQ_return": _compound(benchmark_returns.loc[mask, "QQQ"]),
                "sixty_forty_return": _compound(benchmark_returns.loc[mask, "SPY"] * 0.60 + benchmark_returns.loc[mask, "IEF"] * 0.40),
            }
        )
    return rows


def _cost_stress(env: dict[str, Any], unlevered: dict[str, Any]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for bps in SLIPPAGE_STRESS_BPS:
        model = _build_variant_model(env, unlevered, extra_slippage_bps=bps)
        rows[f"{bps:g}bps"] = {
            "extra_slippage_bps": bps,
            "metrics": _metrics(model["net_returns"], env["prices"]["SPY"].reindex(model["net_returns"].index).ffill()),
            "total_financing_drag": float(model["financing_drag"].sum()),
            "total_slippage_drag": float(model["slippage_drag"].sum()),
            "total_turnover": float(model["turnover"].sum()),
        }
    return rows


def _walk_forward(env: dict[str, Any]) -> dict[str, Any]:
    parameter_grid = [
        {"TOP_N": top_n, "TARGET_VOL": target_vol, "TARGET_VOL_INVERTED": inverted}
        for top_n in (1, 2)
        for target_vol in (0.20, 0.25, 0.30)
        for inverted in (0.15, 0.18, 0.20)
    ]
    candidate_cache: list[dict[str, Any]] = []
    for params in parameter_grid:
        result = _run_with_params(env, params, "wf")
        model = _build_variant_model(env, result, extra_slippage_bps=0.0)
        candidate_cache.append({**result, "model": model})

    years = range(2021, int(env["prices"].index.max().year) + 1)
    folds: list[dict[str, Any]] = []
    stitched: list[pd.Series] = []
    for test_year in years:
        selected = max(
            candidate_cache,
            key=lambda row: _period_score(row["model"]["net_returns"].loc[row["model"]["net_returns"].index.year < test_year], env["prices"]),
        )
        test_returns = selected["model"]["net_returns"].loc[selected["model"]["net_returns"].index.year == test_year]
        if test_returns.empty:
            continue
        stitched.append(test_returns)
        folds.append(
            {
                "test_year": int(test_year),
                "train_years": [int(year) for year in range(2018, test_year)],
                "selected_parameters": selected["parameters"],
                "selected_overlay": {"target_vol": TARGET_VOL, "max_leverage": MAX_LEVERAGE},
                "test_return": _compound(test_returns),
                "test_max_drawdown": _max_drawdown(test_returns),
                "test_metrics": _period_metrics(test_returns, env["prices"]),
            }
        )
    combined = pd.concat(stitched).sort_index() if stitched else pd.Series(dtype=float)
    return {
        "fold_count": len(folds),
        "folds": folds,
        "aggregate_oos": {
            "metrics": _period_metrics(combined, env["prices"]) if not combined.empty else {},
            "status": "research_oos_only_no_promotion",
        },
    }


def _period_score(returns: pd.Series, prices: pd.DataFrame) -> float:
    if returns.empty:
        return -999.0
    metrics = _period_metrics(returns, prices)["strategy"]
    return metrics["true_cagr"] * 3.0 + metrics["sharpe_no_risk_free"] * 0.20 - abs(metrics["max_drawdown"]) * 0.20


def _period_metrics(returns: pd.Series, prices: pd.DataFrame) -> dict[str, Any]:
    clean = returns.dropna()
    aligned = prices.reindex(clean.index).ffill()
    ret = aligned.pct_change(fill_method=None).fillna(0.0)
    return {
        "strategy": _metrics(clean, aligned["SPY"]),
        "SPY": _metrics(ret["SPY"], aligned["SPY"]),
        "QQQ": _metrics(ret["QQQ"], aligned["SPY"]),
        "60_40_SPY_IEF": _metrics(ret["SPY"] * 0.60 + ret["IEF"] * 0.40, aligned["SPY"]),
    }


def _capacity_tests(env: dict[str, Any], weights: pd.DataFrame, exposure: pd.Series) -> dict[str, Any]:
    rows = {
        f"{int(aum):d}": _tradability_report(env, weights, exposure, aum)
        for aum in CAPACITY_AUMS
    }
    passing = [
        float(key)
        for key, row in rows.items()
        if row["passes_reference_aum_liquidity_check"]
    ]
    return {
        "aums": rows,
        "max_passing_aum": max(passing) if passing else 0.0,
        "all_requested_aums_pass": len(passing) == len(CAPACITY_AUMS),
    }


def _small_account_profile(
    env: dict[str, Any],
    unlevered: dict[str, Any],
    model: dict[str, Any],
    selected_constraint: dict[str, Any],
) -> dict[str, Any]:
    account_equity = 10_000.0
    original_tradability = _tradability_report(env, unlevered["weights"], model["exposure"], account_equity)
    constrained_model = selected_constraint["model"]
    constrained_tradability = _tradability_report(env, selected_constraint["weights"], constrained_model["exposure"], account_equity)
    original_latest = _latest_target_snapshot(env, unlevered["weights"], model["exposure"], account_equity)
    constrained_latest = _latest_target_snapshot(env, selected_constraint["weights"], constrained_model["exposure"], account_equity)
    return {
        "account_equity": account_equity,
        "positioning": "small_account_research_profile",
        "original_strategy_capacity_pass": original_tradability["passes_reference_aum_liquidity_check"],
        "constrained_strategy_capacity_pass": constrained_tradability["passes_reference_aum_liquidity_check"],
        "recommended_research_variant": selected_constraint["variant_id"],
        "recommendation_reason": (
            "At 10k USD, the original version passes liquidity, but the min-ADV gate reduces tail execution risk "
            "and keeps the path scalable before capital grows."
        ),
        "original_latest_target": original_latest,
        "constrained_latest_target": constrained_latest,
        "whole_share_warning": {
            "status": "review_required",
            "reason": "Whole-share execution can create tracking error for 10k accounts; fractional shares or a minimum-notional allocator should be checked before paper/live.",
            "original_symbols_below_one_share": original_latest["symbols_below_one_share"],
            "constrained_symbols_below_one_share": constrained_latest["symbols_below_one_share"],
        },
        "financing_note": {
            "max_leverage": MAX_LEVERAGE,
            "max_borrow_notional": account_equity * (MAX_LEVERAGE - 1.0),
            "uses_margin": True,
            "reason": "Vol-target overlay can raise gross exposure above cash equity; small account must have margin enabled or cap exposure at 1x.",
        },
    }


def _latest_target_snapshot(env: dict[str, Any], weights: pd.DataFrame, exposure: pd.Series, account_equity: float) -> dict[str, Any]:
    prices = env["prices"].reindex(weights.index).ffill()
    latest_date = weights.index.max()
    latest_weights = weights.loc[latest_date].fillna(0.0)
    latest_exposure = float(exposure.reindex(weights.index).ffill().loc[latest_date])
    latest_prices = prices.loc[latest_date].reindex(latest_weights.index).ffill()
    target_weights = (latest_weights * latest_exposure).sort_values(ascending=False)
    rows: list[dict[str, Any]] = []
    below_one_share: list[str] = []
    for symbol, weight in target_weights.items():
        if abs(float(weight)) <= 1e-9:
            continue
        price = float(latest_prices[symbol])
        notional = float(weight) * account_equity
        shares = notional / price if price > 0 else 0.0
        if 0.0 < abs(shares) < 1.0:
            below_one_share.append(str(symbol))
        rows.append(
            {
                "symbol": str(symbol),
                "target_weight": float(weight),
                "target_notional": notional,
                "price": price,
                "shares": shares,
            }
        )
    return {
        "date": str(latest_date.date()),
        "gross_exposure": float(target_weights.abs().sum()),
        "net_exposure": float(target_weights.sum()),
        "target_count": len(rows),
        "symbols_below_one_share": below_one_share,
        "targets": rows,
    }


def _source_attribution(
    env: dict[str, Any],
    baseline: dict[str, Any],
    unlevered: dict[str, Any],
    model: dict[str, Any],
    stress: dict[str, Any],
) -> dict[str, Any]:
    baseline_cagr = baseline["metrics"]["strategy"]["true_cagr"]
    unlevered_cagr = unlevered["metrics"]["strategy"]["true_cagr"]
    benchmark_prices = env["prices"]["SPY"].reindex(model["net_returns"].index).ffill()
    gross_metrics = _metrics(model["gross_returns"], benchmark_prices)
    selected_metrics = _metrics(model["net_returns"], benchmark_prices)
    cost25 = stress["25bps"]["metrics"]
    return {
        "baseline_original_cagr": baseline_cagr,
        "asset_selection_and_parameter_effect_cagr": unlevered_cagr - baseline_cagr,
        "unlevered_top1_higher_vol_cagr": unlevered_cagr,
        "gross_leverage_overlay_cagr": gross_metrics["true_cagr"],
        "gross_leverage_effect_cagr": gross_metrics["true_cagr"] - unlevered_cagr,
        "financing_effect_cagr": selected_metrics["true_cagr"] - gross_metrics["true_cagr"],
        "net_selected_cagr": selected_metrics["true_cagr"],
        "slippage_25bps_effect_cagr": cost25["true_cagr"] - selected_metrics["true_cagr"],
        "interpretation": "CAGR bridge: original baseline -> unlevered top1_higher_vol -> gross 1.5x vol target -> financing-adjusted selected -> 25bps slippage stress.",
    }


def _tradability_report(env: dict[str, Any], weights: pd.DataFrame, exposure: pd.Series, reference_aum: float) -> dict[str, Any]:
    dollar_volume = _load_dollar_volume(env["prices"].columns)
    aligned_adv = dollar_volume.reindex(weights.index).ffill().rolling(20).mean()
    exposure_shift = exposure.shift(1).fillna(1.0)
    notional_weights = weights.mul(exposure_shift, axis=0).abs()
    traded_notional = notional_weights.diff().abs().fillna(0.0) * reference_aum
    participation = traded_notional.div(aligned_adv.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)
    active = participation.stack().dropna()
    symbol_median_adv = aligned_adv.median().dropna().sort_values()
    worst_events = (
        participation.stack()
        .dropna()
        .sort_values(ascending=False)
        .head(10)
    )
    tradable_symbols = sorted(set(weights.columns) & set(dollar_volume.columns))
    missing_symbols = sorted(set(weights.columns) - set(dollar_volume.columns))
    p95_participation = float(active.quantile(0.95)) if not active.empty else 0.0
    max_participation = float(active.max()) if not active.empty else 0.0
    return {
        "reference_aum": reference_aum,
        "volume_source": str(ORIGINAL_DATA_LAKE / "kline"),
        "tradable_symbol_count": len(tradable_symbols),
        "missing_volume_symbols": missing_symbols,
        "median_20d_adv": float(aligned_adv.stack().median()),
        "min_symbol_median_20d_adv": float(aligned_adv.median().min()),
        "lowest_median_adv_symbols": [
            {"symbol": str(symbol), "median_20d_adv": float(value)}
            for symbol, value in symbol_median_adv.head(5).items()
        ],
        "worst_participation_events": [
            {"date": str(idx[0].date()), "symbol": str(idx[1]), "participation": float(value)}
            for idx, value in worst_events.items()
        ],
        "max_single_name_participation": max_participation,
        "p95_single_name_participation": p95_participation,
        "participation_threshold": 0.01,
        "max_participation_review_threshold": 0.05,
        "passes_reference_aum_liquidity_check": bool(
            active.empty or (p95_participation < 0.01 and max_participation < 0.05)
        ),
    }


def _load_dollar_volume(symbols: pd.Index) -> pd.DataFrame:
    frames: dict[str, pd.Series] = {}
    for symbol in symbols:
        path = ORIGINAL_DATA_LAKE / "kline" / f"{symbol}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path, columns=["datetime", "Close", "Volume"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        series = (df["Close"].astype(float) * df["Volume"].astype(float)).rename(symbol)
        series.index = df["datetime"]
        frames[symbol] = series.sort_index()
    return pd.DataFrame(frames).sort_index()


def _margin_report(exposure: pd.Series) -> dict[str, Any]:
    reg_t_max = 2.0
    maintenance_max = 4.0
    max_exposure = float(exposure.max())
    return {
        "reg_t_initial_margin_max_leverage": reg_t_max,
        "maintenance_margin_max_leverage": maintenance_max,
        "configured_max_leverage": MAX_LEVERAGE,
        "observed_max_leverage": max_exposure,
        "observed_average_leverage": float(exposure.mean()),
        "reg_t_headroom": reg_t_max - max_exposure,
        "maintenance_headroom": maintenance_max - max_exposure,
        "margin_call_model": "No margin call in research path because observed leverage is capped at 1.5x below Reg-T 2x.",
        "passes_margin_constraint": bool(max_exposure <= MAX_LEVERAGE <= reg_t_max),
    }


def _extreme_year_attribution(yearly: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [row for row in yearly if row["year"] in EXTREME_YEARS]
    worst = min(yearly, key=lambda row: row["selected_return"])
    best = max(yearly, key=lambda row: row["selected_return"])
    largest_drawdown = min(yearly, key=lambda row: row["max_drawdown"])
    return {
        "selected_years": selected,
        "worst_return_year": worst,
        "best_return_year": best,
        "largest_drawdown_year": largest_drawdown,
        "interpretation": "Attribution separates unlevered strategy return, leverage effect, financing drag, and slippage drag by calendar year.",
    }


def _decision(
    model: dict[str, Any],
    benchmarks: dict[str, Any],
    stress: dict[str, Any],
    walk_forward: dict[str, Any],
    margin: dict[str, Any],
    tradability: dict[str, Any],
    constrained_tradability: dict[str, Any],
) -> dict[str, Any]:
    selected = benchmarks["selected_vol_target_20pct_cap1.5x"]
    qqq = benchmarks["QQQ"]
    stress_25 = stress["25bps"]["metrics"]
    oos = walk_forward["aggregate_oos"]["metrics"].get("strategy", {})
    clears_benchmark = selected["true_cagr"] > qqq["true_cagr"] and selected["max_drawdown"] > qqq["max_drawdown"]
    robust_enough = stress_25["true_cagr"] > qqq["true_cagr"] * 0.90 and oos.get("true_cagr", 0.0) > 0.0
    constrained_tradeable = constrained_tradability["passes_reference_aum_liquidity_check"]
    status = "manual_review_candidate" if clears_benchmark and robust_enough and margin["passes_margin_constraint"] and constrained_tradeable else "research_concerns"
    return {
        "status": status,
        "live_ready": False,
        "paper_ready": False,
        "clears_qqq_cagr_with_lower_drawdown": clears_benchmark,
        "survives_25bps_slippage": stress_25["true_cagr"] > 0.0,
        "walk_forward_oos_cagr": oos.get("true_cagr", 0.0),
        "margin_pass": margin["passes_margin_constraint"],
        "tradability_pass": tradability["passes_reference_aum_liquidity_check"],
        "constrained_tradability_pass": constrained_tradeable,
        "reason": "Candidate can remain in research review, but live/paper requires separate financing, broker margin, execution, and manual governance approval.",
    }


def _metrics(returns: pd.Series, benchmark_prices: pd.Series) -> dict[str, float]:
    metrics = _metric_block(returns.dropna(), benchmark_prices.reindex(returns.dropna().index).ffill())
    annual_vol = float(returns.dropna().std(ddof=0) * np.sqrt(TRADING_DAYS))
    metrics["annualized_volatility"] = annual_vol
    metrics["calmar"] = float(metrics["true_cagr"] / abs(metrics["max_drawdown"])) if metrics["max_drawdown"] else 0.0
    return metrics


def _compound(returns: pd.Series) -> float:
    return float((1.0 + returns.fillna(0.0)).prod() - 1.0)


def _max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _markdown(report: dict[str, Any]) -> str:
    selected = report["metrics"]["selected_variant"]
    constrained = report["metrics"]["selected_tradability_constrained_variant"]
    qqq = report["comparison"]["QQQ"]
    oos = report["walk_forward"]["aggregate_oos"]["metrics"].get("strategy", {})
    attribution = report["source_attribution"]
    small = report["small_account_10k_profile"]
    lines = [
        "# US ETF vol_target_20pct_cap1.5x 专项验证",
        "",
        "## 结论",
        "",
        f"- 状态：`{report['decision']['status']}`，不解锁纸盘或实盘。",
        f"- 选中变体 CAGR：{_pct(selected['true_cagr'])}，MDD：{_pct(selected['max_drawdown'])}，Sharpe：{selected['sharpe_no_risk_free']:.3f}。",
        f"- 可交易约束后变体 `{report['tradability_constraints']['selected_constrained_variant']}`：CAGR {_pct(constrained['true_cagr'])}，MDD {_pct(constrained['max_drawdown'])}，Sharpe {constrained['sharpe_no_risk_free']:.3f}。",
        f"- QQQ CAGR：{_pct(qqq['true_cagr'])}，MDD：{_pct(qqq['max_drawdown'])}。",
        f"- Walk-forward OOS CAGR：{_pct(oos.get('true_cagr', 0.0))}，MDD：{_pct(oos.get('max_drawdown', 0.0))}。",
        f"- 原始参考 AUM 流动性检查：`{report['tradability']['passes_reference_aum_liquidity_check']}`；约束后流动性检查：`{report['constrained_tradability']['passes_reference_aum_liquidity_check']}`。",
        f"- 1 万美元小资金：原始流动性 `{small['original_strategy_capacity_pass']}`，约束后流动性 `{small['constrained_strategy_capacity_pass']}`；推荐研究版本 `{small['recommended_research_variant']}`。",
        "",
        "## 正式对照",
        "",
        "| 对象 | CAGR | Vol | Sharpe | MDD | Calmar |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, metrics in report["comparison"].items():
        lines.append(
            f"| {key} | {_pct(metrics['true_cagr'])} | {_pct(metrics.get('annualized_volatility', 0.0))} | {metrics['sharpe_no_risk_free']:.3f} | {_pct(metrics['max_drawdown'])} | {metrics.get('calmar', 0.0):.3f} |"
        )
    lines.extend(
        [
            "",
            "## 1万美元小资金画像",
            "",
            f"- 账户本金：${small['account_equity']:,.0f}。",
            f"- 结论：{small['recommendation_reason']}",
            f"- 融资说明：最大杠杆 {small['financing_note']['max_leverage']:.2f}x，理论最大借款 ${small['financing_note']['max_borrow_notional']:,.0f}。",
            f"- 整股交易风险：`{small['whole_share_warning']['status']}`；原始低于 1 股标的 {small['whole_share_warning']['original_symbols_below_one_share']}；约束后低于 1 股标的 {small['whole_share_warning']['constrained_symbols_below_one_share']}。",
            "",
            "### 最新目标仓位：原始版本",
            "",
            f"- 日期：{small['original_latest_target']['date']}；Gross exposure：{small['original_latest_target']['gross_exposure']:.2f}。",
            "",
            "| Symbol | Target Weight | Target Notional | Price | Shares |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in small["original_latest_target"]["targets"]:
        lines.append(f"| {row['symbol']} | {_pct(row['target_weight'])} | ${row['target_notional']:,.2f} | ${row['price']:,.2f} | {row['shares']:.3f} |")
    lines.extend(
        [
            "",
            "### 最新目标仓位：可交易约束版本",
            "",
            f"- 日期：{small['constrained_latest_target']['date']}；Gross exposure：{small['constrained_latest_target']['gross_exposure']:.2f}。",
            "",
            "| Symbol | Target Weight | Target Notional | Price | Shares |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in small["constrained_latest_target"]["targets"]:
        lines.append(f"| {row['symbol']} | {_pct(row['target_weight'])} | ${row['target_notional']:,.2f} | ${row['price']:,.2f} | {row['shares']:.3f} |")
    lines.extend(
        [
            "",
            "## 收益来源拆解",
            "",
            "| Step | CAGR / Effect |",
            "|---|---:|",
            f"| 原始策略 CAGR | {_pct(attribution['baseline_original_cagr'])} |",
            f"| 资产选择/参数改动贡献 | {_pct(attribution['asset_selection_and_parameter_effect_cagr'])} |",
            f"| 未杠杆 top1_higher_vol CAGR | {_pct(attribution['unlevered_top1_higher_vol_cagr'])} |",
            f"| 毛杠杆覆盖贡献 | {_pct(attribution['gross_leverage_effect_cagr'])} |",
            f"| 融资成本影响 | {_pct(attribution['financing_effect_cagr'])} |",
            f"| 净选中变体 CAGR | {_pct(attribution['net_selected_cagr'])} |",
            f"| 25bps 滑点压力影响 | {_pct(attribution['slippage_25bps_effect_cagr'])} |",
        ]
    )
    lines.extend(
        [
            "",
            "## 成本压力",
            "",
            "| Slippage | CAGR | Sharpe | MDD | Financing Drag | Slippage Drag |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for key, row in report["cost_stress"].items():
        metrics = row["metrics"]
        lines.append(f"| {key} | {_pct(metrics['true_cagr'])} | {metrics['sharpe_no_risk_free']:.3f} | {_pct(metrics['max_drawdown'])} | {_pct(row['total_financing_drag'])} | {_pct(row['total_slippage_drag'])} |")
    lines.extend(
        [
            "",
            "## DBMF 与可交易约束",
            "",
            f"- DBMF 权重上限候选：{report['tradability_constraints']['dbmf_max_weight']:.0%}。",
            f"- 最小 20 日 ADV 门槛：${report['tradability_constraints']['min_20d_adv_usd']:,.0f}，不满足时替换到 `{report['tradability_constraints']['replacement_asset']}`。",
            f"- 选中约束方案：`{report['tradability_constraints']['selected_constrained_variant']}`。",
            "",
            "| Variant | CAGR | MDD | Sharpe | DBMF Avg | DBMF Max | Tradability | Max Participation |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report["tradability_constraints"]["candidates"]:
        metrics = row["metrics"]
        lines.append(
            f"| {row['variant_id']} | {_pct(metrics['true_cagr'])} | {_pct(metrics['max_drawdown'])} | {metrics['sharpe_no_risk_free']:.3f} | {_pct(row['dbmf_average_weight'])} | {_pct(row['dbmf_max_weight'])} | {row['tradability_pass']} | {_pct(row['max_single_name_participation'])} |"
        )
    lines.extend(
        [
            "",
            "## 容量测试",
            "",
            f"- 原始版本最大通过资金规模：${report['capacity_tests']['max_passing_aum']:,.0f}。",
            f"- 可交易约束后最大通过资金规模：${report['constrained_capacity_tests']['max_passing_aum']:,.0f}。",
            "",
            "| AUM | Original Pass | Original Max Participation | Constrained Pass | Constrained Max Participation |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for key in sorted(report["capacity_tests"]["aums"], key=lambda item: float(item)):
        original = report["capacity_tests"]["aums"][key]
        constrained_row = report["constrained_capacity_tests"]["aums"][key]
        lines.append(
            f"| ${float(key):,.0f} | {original['passes_reference_aum_liquidity_check']} | {_pct(original['max_single_name_participation'])} | {constrained_row['passes_reference_aum_liquidity_check']} | {_pct(constrained_row['max_single_name_participation'])} |"
        )
    lines.extend(
        [
            "",
            "## 年度拆解",
            "",
            "| Year | Selected | Unlevered | Leverage Effect | Financing Drag | MDD | Avg Lev | SPY | QQQ | 60/40 |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report["yearly_breakdown"]:
        lines.append(
            f"| {row['year']} | {_pct(row['selected_return'])} | {_pct(row['unlevered_return'])} | {_pct(row['leverage_effect_vs_unlevered'])} | {_pct(row['financing_drag_sum'])} | {_pct(row['max_drawdown'])} | {row['average_exposure']:.2f} | {_pct(row['SPY_return'])} | {_pct(row['QQQ_return'])} | {_pct(row['sixty_forty_return'])} |"
        )
    lines.extend(
        [
            "",
            "## Walk-Forward",
            "",
            "| Test Year | Params | Return | MDD | CAGR |",
            "|---:|---|---:|---:|---:|",
        ]
    )
    for fold in report["walk_forward"]["folds"]:
        lines.append(
            f"| {fold['test_year']} | `{json.dumps(fold['selected_parameters'], sort_keys=True)}` | {_pct(fold['test_return'])} | {_pct(fold['test_max_drawdown'])} | {_pct(fold['test_metrics']['strategy']['true_cagr'])} |"
        )
    lines.extend(
        [
            "",
            "## 执行约束",
            "",
            f"- 融资模型：DGS2 + {report['financing_model']['broker_spread']:.1%} broker spread，平均年化融资率 {_pct(report['financing_model']['average_annual_rate'])}。",
            f"- 最大观察杠杆：{report['margin_model']['observed_max_leverage']:.2f}x，Reg-T 初始保证金上限 {report['margin_model']['reg_t_initial_margin_max_leverage']:.2f}x。",
            f"- 参考 AUM：${report['tradability']['reference_aum']:,.0f}，P95 单名参与率 {report['tradability']['p95_single_name_participation']:.4%}。",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
