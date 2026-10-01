#!/usr/bin/env python3
"""Book-inspired optimization experiments for the US ETF macro rotation strategy."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.research.us_etf_macro_momentum_rotation import (  # noqa: E402
    UsEtfMacroMomentumRotationConfig,
    build_price_matrix_from_bars,
    calculate_rotation_inputs,
    performance_summary,
)
from scripts.build_us_etf_macro_rotation_optimization_report import (  # noqa: E402
    ExperimentSpec,
    FOCUS_YEARS,
    _focus_years,
    _run_experiment,
)
from scripts.build_us_etf_macro_rotation_research_report import (  # noqa: E402
    DEFAULT_EXTERNAL_DATA_LAKE,
    _load_external_data_lake_bars,
    _load_macro_data,
)


DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_etf_macro_rotation/latest")
DEFAULT_MARKDOWN = Path("学习资料/量化交易业务闭环/系统评估/US ETF 轮动 书籍启发优化.md")
STRESS_COST_BPS = (10, 25, 50)
BASELINE_PARAMETERS = {
    "max_monthly_turnover": 0.75,
    "min_hold_months": 4,
    "rebalance_blend": 0.75,
    "turnover_threshold": 0.35,
}
LOW_TURNOVER_PARAMETERS = {
    "max_monthly_turnover": 0.50,
    "min_hold_months": 5,
    "rebalance_blend": 0.75,
    "turnover_threshold": 0.55,
}
AGGRESSIVE_PARAMETERS = {
    "turnover_profile": "aggressive_no_turnover_guard",
}
SECTOR_ASSETS = ("XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "SOXX", "IGV", "XBI")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--markdown-path", default=str(DEFAULT_MARKDOWN))
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    report = build_book_inspired_optimization_report(repo_root=root)

    output_root = root / Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "us_etf_macro_rotation_book_inspired_optimization_report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    markdown_path = root / Path(args.markdown_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(json_path), "markdown": str(markdown_path)}, indent=2, sort_keys=True))


def build_book_inspired_optimization_report(*, repo_root: Path) -> dict[str, Any]:
    cfg = UsEtfMacroMomentumRotationConfig()
    bars, available_symbols, _coverage = _load_external_data_lake_bars(DEFAULT_EXTERNAL_DATA_LAKE, cfg.required_symbols())
    missing = sorted(set(cfg.required_symbols()) - set(available_symbols))
    if missing:
        raise SystemExit(f"missing external ETF symbols: {missing}")
    prices = build_price_matrix_from_bars(bars, cfg.required_symbols())
    macro_df, macro_status, macro_path = _load_macro_data(repo_root, None, external_data_lake=DEFAULT_EXTERNAL_DATA_LAKE)
    base_context = _build_base_context(prices=prices, macro_df=macro_df, cfg=cfg)

    baseline = _evaluate_candidate(
        family="baseline_v2_turnover_guard",
        description="Current cost-robust turnover-guard baseline.",
        source_idea="Prior internal optimization baseline.",
        context=base_context,
        parameters=BASELINE_PARAMETERS,
    )

    evaluated: list[dict[str, Any]] = [baseline]
    for family, family_context, source_idea in _book_inspired_contexts(base_context).values():
        for params in _cost_control_grid(family):
            evaluated.append(
                _evaluate_candidate(
                    family=family,
                    description=_family_description(family),
                    source_idea=source_idea,
                    context=family_context,
                    parameters=params,
                )
            )

    ranked = sorted(evaluated, key=lambda row: row["score_50bps"], reverse=True)
    ranked_by_cagr = sorted(evaluated, key=lambda row: row["stress"]["50bps"]["metrics"]["cagr"], reverse=True)
    families: dict[str, Any] = {}
    for row in evaluated:
        families.setdefault(row["family"], []).append(row)
    family_summary = {
        family: {
            "candidate_count": len(rows),
            "best": sorted(rows, key=lambda item: item["score_50bps"], reverse=True)[0],
            "top_candidates": sorted(rows, key=lambda item: item["score_50bps"], reverse=True)[:5],
        }
        for family, rows in sorted(families.items())
    }

    best_non_baseline = next(row for row in ranked if row["family"] != "baseline_v2_turnover_guard")
    return {
        "schema_version": "us_etf_macro_rotation_book_inspired_optimization_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "research_only",
        "live_ready": False,
        "paper_ready": False,
        "price_source": str(DEFAULT_EXTERNAL_DATA_LAKE),
        "macro_status": macro_status,
        "macro_path": str(macro_path) if macro_path else None,
        "stress_cost_bps": list(STRESS_COST_BPS),
        "baseline": baseline,
        "best_overall": ranked[0],
        "highest_cagr_candidate": ranked_by_cagr[0],
        "best_non_baseline": best_non_baseline,
        "families": family_summary,
        "ranking": ranked,
        "book_sources": _book_sources(),
        "strategy_inventory_151": _extract_151_inventory(repo_root),
        "deferred_ideas": [
            {
                "idea": "carry plus momentum",
                "reason": "Expected Returns and 151 Trading Strategies support carry/momentum blends, but this ETF data set has no reliable futures roll yield, funding, or term-structure carry fields yet.",
            },
            {
                "idea": "residual momentum after multi-factor risk model",
                "reason": "Active Portfolio Management supports residual forecast construction, but the current ETF universe has only ETF prices and coarse macro data; a factor exposure model should be added before testing it.",
            },
        ],
        "methodology": {
            "goal": "Convert local markdown book notes into testable rotation variants, then compare them with the existing cost-robust baseline.",
            "primary_cost_bps": 50,
            "cost_stress": "Each candidate is evaluated at 10bps, 25bps, and 50bps turnover cost.",
            "score_50bps": "0.25*50bps_sharpe + 3.0*50bps_cagr - 0.10*abs(50bps_mdd) + 0.05*mean_focus_year_excess; turnover is reported but no longer penalized in the primary score.",
            "constraint": "Research-only; no paper/live unlock; same repaired ETF data and FRED macro data as prior reports.",
        },
    }


def _build_base_context(*, prices: pd.DataFrame, macro_df: pd.DataFrame, cfg: UsEtfMacroMomentumRotationConfig) -> dict[str, Any]:
    inputs = calculate_rotation_inputs(prices, macro_df, cfg)
    return {
        "prices": prices,
        "mom_score": inputs[0],
        "volatility": inputs[1],
        "trend_filter": inputs[2],
        "macro_regime": inputs[3],
        "yield_curve_inverted": inputs[4],
        "asset_rets": inputs[5],
        "defense_mom": inputs[6],
        "cfg": cfg,
    }


def _book_inspired_contexts(base_context: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any], str]]:
    cfg: UsEtfMacroMomentumRotationConfig = base_context["cfg"]
    prices: pd.DataFrame = base_context["prices"]
    asset_rets: pd.DataFrame = base_context["asset_rets"]
    assets = list(cfg.offensive_assets)
    sector_assets = [asset for asset in SECTOR_ASSETS if asset in prices.columns]

    dual_score = _annual_relative_to_cash_score(prices, assets)
    quality_score = _quality_momentum_score(prices, asset_rets, assets)
    multi_speed_score = _multi_speed_trend_score(prices, asset_rets, assets)
    ensemble_score = _zscore(base_context["mom_score"]) * 0.35 + _zscore(quality_score) * 0.30 + _zscore(multi_speed_score) * 0.35
    sector_momentum = _weighted_return_score(prices, sector_assets, ((63, 0.25), (126, 0.35), (252, 0.40)))
    sector_dual = _annual_relative_to_cash_score(prices, sector_assets)
    alpha_rotation = _residual_alpha_score(prices, asset_rets, assets, cfg.benchmark)
    r_squared_trend = _r_squared_trend_score(prices, assets)
    mean_reversion = _mean_reversion_score(prices, assets)
    low_volatility = _low_volatility_score(asset_rets, assets)
    multi_factor = _zscore(multi_speed_score) * 0.45 + _zscore(low_volatility) * 0.25 + _zscore(r_squared_trend) * 0.30
    single_ma = _single_ma_score(prices, assets, 200)
    dual_ma = _dual_ma_score(prices, assets, 50, 200)
    triple_ma = _triple_ma_score(prices, assets, 50, 100, 200)
    support_resistance = _breakout_score(prices, assets, 63)
    channel_breakout = _breakout_score(prices, assets, 126)
    multi_asset_tsmom = _weighted_return_score(prices, assets, ((63, 0.20), (126, 0.30), (252, 0.50)))

    annual_abs = prices[assets].pct_change(252, fill_method=None)
    ma200 = prices[assets].rolling(200).mean()
    positive_long_trend = (annual_abs > 0.0) & (prices[assets] > ma200)
    sector_positive_long_trend = positive_long_trend.reindex(columns=sector_assets)
    spy_vol = asset_rets[cfg.benchmark].rolling(63).std() * np.sqrt(252)
    macro_vol_scaler = (0.16 / spy_vol.replace(0.0, np.nan)).clip(lower=0.35, upper=1.0).fillna(1.0)

    return {
        "sector_price_momentum_rotation_151": (
            "sector_price_momentum_rotation_151",
            _with_context(
                base_context,
                cfg=replace(cfg, offensive_assets=tuple(sector_assets), top_n=3),
                mom_score=sector_momentum,
                trend_filter=sector_momentum > 0.0,
            ),
            "151 ETF chapter: sector momentum rotation maps directly to sector ETF ranking.",
        ),
        "sector_momentum_ma_filter_151": (
            "sector_momentum_ma_filter_151",
            _with_context(
                base_context,
                cfg=replace(cfg, offensive_assets=tuple(sector_assets), top_n=3),
                mom_score=sector_momentum,
                trend_filter=(sector_momentum > 0.0) & sector_positive_long_trend,
            ),
            "151 ETF chapter: sector momentum rotation with a moving-average filter.",
        ),
        "sector_dual_momentum_151": (
            "sector_dual_momentum_151",
            _with_context(
                base_context,
                cfg=replace(cfg, offensive_assets=tuple(sector_assets), top_n=2),
                mom_score=sector_dual,
                trend_filter=sector_dual > 0.0,
            ),
            "151 ETF chapter: dual-momentum sector rotation uses relative rank plus absolute/cash hurdle.",
        ),
        "alpha_rotation_residual_151": (
            "alpha_rotation_residual_151",
            _with_context(
                base_context,
                cfg=replace(cfg, top_n=2),
                mom_score=alpha_rotation,
                trend_filter=(alpha_rotation > 0.0) & positive_long_trend,
            ),
            "151 ETF and stock chapters: alpha/residual momentum after removing broad market beta.",
        ),
        "r_squared_trend_quality_151": (
            "r_squared_trend_quality_151",
            _with_context(
                base_context,
                cfg=replace(cfg, top_n=2),
                mom_score=r_squared_trend,
                trend_filter=(r_squared_trend > 0.0) & positive_long_trend,
            ),
            "151 ETF chapter: R-squared trend quality favors assets with cleaner trend fits.",
        ),
        "etf_mean_reversion_151": (
            "etf_mean_reversion_151",
            _with_context(
                base_context,
                cfg=replace(cfg, top_n=2),
                mom_score=mean_reversion,
                trend_filter=(mean_reversion > 0.0) & positive_long_trend,
            ),
            "151 ETF and futures chapters: mean reversion tested only inside positive long-term trend.",
        ),
        "low_volatility_anomaly_151": (
            "low_volatility_anomaly_151",
            _with_context(
                base_context,
                cfg=replace(cfg, top_n=3),
                mom_score=low_volatility,
                trend_filter=positive_long_trend,
            ),
            "151 stock chapter: low-volatility anomaly mapped to ETF selection.",
        ),
        "multifactor_portfolio_151": (
            "multifactor_portfolio_151",
            _with_context(
                base_context,
                cfg=replace(cfg, top_n=3),
                mom_score=multi_factor,
                trend_filter=(multi_factor > 0.0) & positive_long_trend,
            ),
            "151 stock chapter: multifactor portfolio combines momentum, low volatility, and trend quality.",
        ),
        "single_moving_average_151": (
            "single_moving_average_151",
            _with_context(
                base_context,
                cfg=replace(cfg, top_n=3),
                mom_score=single_ma,
                trend_filter=single_ma > 0.0,
            ),
            "151 stock chapter: single moving-average timing converted into ETF cross-sectional ranking.",
        ),
        "two_moving_averages_151": (
            "two_moving_averages_151",
            _with_context(
                base_context,
                cfg=replace(cfg, top_n=3),
                mom_score=dual_ma,
                trend_filter=dual_ma > 0.0,
            ),
            "151 stock chapter: two moving averages become a trend-strength forecast.",
        ),
        "three_moving_averages_151": (
            "three_moving_averages_151",
            _with_context(
                base_context,
                cfg=replace(cfg, top_n=3),
                mom_score=triple_ma,
                trend_filter=triple_ma > 0.0,
            ),
            "151 stock chapter: three moving averages require short, medium, and long trend alignment.",
        ),
        "support_resistance_breakout_151": (
            "support_resistance_breakout_151",
            _with_context(
                base_context,
                cfg=replace(cfg, top_n=2),
                mom_score=support_resistance,
                trend_filter=support_resistance > 0.0,
            ),
            "151 stock chapter: support/resistance translated into 63-day breakout strength.",
        ),
        "channel_breakout_151": (
            "channel_breakout_151",
            _with_context(
                base_context,
                cfg=replace(cfg, top_n=2),
                mom_score=channel_breakout,
                trend_filter=channel_breakout > 0.0,
            ),
            "151 stock chapter: channel strategy translated into 126-day Donchian-style breakout.",
        ),
        "multi_asset_tsmom_151": (
            "multi_asset_tsmom_151",
            _with_context(
                base_context,
                cfg=replace(cfg, top_n=3),
                mom_score=multi_asset_tsmom,
                trend_filter=(multi_asset_tsmom > 0.0) & positive_long_trend,
            ),
            "151 ETF and futures chapters: multi-asset trend following / time-series momentum.",
        ),
        "dual_momentum_absolute_relative": (
            "dual_momentum_absolute_relative",
            _with_context(
                base_context,
                cfg=replace(cfg, top_n=1),
                mom_score=dual_score,
                trend_filter=positive_long_trend & (dual_score > 0.0),
            ),
            "Dual Momentum Investing and 151 Trading Strategies: rank by relative strength only after absolute momentum clears cash/defensive return.",
        ),
        "quality_momentum_12_1": (
            "quality_momentum_12_1",
            _with_context(
                base_context,
                cfg=replace(cfg, top_n=2),
                mom_score=quality_score,
                trend_filter=(quality_score > 0.0) & positive_long_trend,
            ),
            "Quantitative Momentum: use 12-1 momentum, path quality, and volatility adjustment instead of raw recent strength.",
        ),
        "multi_speed_trend_forecast": (
            "multi_speed_trend_forecast",
            _with_context(
                base_context,
                cfg=replace(cfg, top_n=2),
                mom_score=multi_speed_score,
                trend_filter=(multi_speed_score > 0.0) & positive_long_trend,
            ),
            "Systematic Trading and trend-following notes: blend several trend horizons into a capped forecast before position construction.",
        ),
        "macro_vol_scaled_overlay": (
            "macro_vol_scaled_overlay",
            _with_context(
                base_context,
                macro_regime=(base_context["macro_regime"] * macro_vol_scaler).clip(lower=0.0, upper=1.0),
            ),
            "Systematic Trading and volatility-targeting strategies: reduce offensive budget when market volatility is elevated.",
        ),
        "ensemble_forecast_blend": (
            "ensemble_forecast_blend",
            _with_context(
                base_context,
                cfg=replace(cfg, top_n=2),
                mom_score=ensemble_score,
                trend_filter=(ensemble_score > 0.0) & positive_long_trend,
            ),
            "Active Portfolio Management and Systematic Trading: combine forecasts, then let portfolio construction and cost controls translate forecast into weight.",
        ),
    }


def _with_context(base_context: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    next_context = dict(base_context)
    next_context.update(overrides)
    return next_context


def _annual_relative_to_cash_score(prices: pd.DataFrame, assets: list[str]) -> pd.DataFrame:
    annual_ret = prices[assets].pct_change(252, fill_method=None)
    cash_ret = prices["SHV"].pct_change(252, fill_method=None)
    return _clean_score(annual_ret.sub(cash_ret, axis=0))


def _quality_momentum_score(prices: pd.DataFrame, asset_rets: pd.DataFrame, assets: list[str]) -> pd.DataFrame:
    twelve_minus_one = prices[assets].shift(21) / prices[assets].shift(252) - 1.0
    six_month_positive_share = asset_rets[assets].gt(0.0).rolling(126).mean()
    realized_vol = asset_rets[assets].rolling(126).std() * np.sqrt(252)
    score = twelve_minus_one / realized_vol.replace(0.0, np.nan)
    return _clean_score(score * (0.50 + six_month_positive_share))


def _multi_speed_trend_score(prices: pd.DataFrame, asset_rets: pd.DataFrame, assets: list[str]) -> pd.DataFrame:
    score = pd.DataFrame(0.0, index=prices.index, columns=assets)
    for lookback, weight in ((63, 0.25), (126, 0.35), (252, 0.40)):
        trend = prices[assets].pct_change(lookback, fill_method=None)
        vol = asset_rets[assets].rolling(lookback).std() * np.sqrt(252)
        score += (trend / vol.replace(0.0, np.nan)).clip(lower=-3.0, upper=3.0) * weight
    return _clean_score(score)


def _weighted_return_score(
    prices: pd.DataFrame,
    assets: list[str],
    lookbacks: tuple[tuple[int, float], ...],
) -> pd.DataFrame:
    score = pd.DataFrame(0.0, index=prices.index, columns=assets)
    for lookback, weight in lookbacks:
        score += prices[assets].pct_change(lookback, fill_method=None) * weight
    return _clean_score(score)


def _residual_alpha_score(
    prices: pd.DataFrame,
    asset_rets: pd.DataFrame,
    assets: list[str],
    benchmark: str,
) -> pd.DataFrame:
    market_ret = asset_rets[benchmark]
    market_var = market_ret.rolling(63).var()
    residual = pd.DataFrame(index=prices.index, columns=assets, dtype=float)
    for asset in assets:
        beta = asset_rets[asset].rolling(63).cov(market_ret) / market_var.replace(0.0, np.nan)
        residual[asset] = asset_rets[asset] - beta.shift(1).fillna(0.0) * market_ret
    score = pd.DataFrame(0.0, index=prices.index, columns=assets)
    for lookback, weight in ((63, 0.25), (126, 0.35), (252, 0.40)):
        ret = np.expm1(np.log1p(residual.clip(lower=-0.9999)).rolling(lookback).sum())
        vol = residual.rolling(lookback).std() * np.sqrt(252)
        score += (ret / vol.replace(0.0, np.nan)).clip(lower=-3.0, upper=3.0) * weight
    return _clean_score(score)


def _r_squared_trend_score(prices: pd.DataFrame, assets: list[str], window: int = 252) -> pd.DataFrame:
    log_ret = np.log(prices[assets]).diff()
    mean_ret = log_ret.rolling(window).mean()
    vol_ret = log_ret.rolling(window).std()
    t_stat = mean_ret / vol_ret.replace(0.0, np.nan) * np.sqrt(window)
    r2_proxy = t_stat.pow(2) / (t_stat.pow(2) + max(window - 2, 1))
    trend = prices[assets].pct_change(window, fill_method=None)
    return _clean_score(trend * r2_proxy)


def _mean_reversion_score(prices: pd.DataFrame, assets: list[str], window: int = 63) -> pd.DataFrame:
    deviation = prices[assets] / prices[assets].rolling(window).mean() - 1.0
    realized_vol = prices[assets].pct_change(fill_method=None).rolling(window).std() * np.sqrt(252)
    score = -deviation / realized_vol.replace(0.0, np.nan)
    return _clean_score(score.where(deviation < 0.0, -999.0))


def _low_volatility_score(asset_rets: pd.DataFrame, assets: list[str], window: int = 126) -> pd.DataFrame:
    realized_vol = asset_rets[assets].rolling(window).std() * np.sqrt(252)
    return _clean_score(-realized_vol)


def _single_ma_score(prices: pd.DataFrame, assets: list[str], window: int) -> pd.DataFrame:
    return _clean_score(prices[assets] / prices[assets].rolling(window).mean() - 1.0)


def _dual_ma_score(prices: pd.DataFrame, assets: list[str], fast: int, slow: int) -> pd.DataFrame:
    return _clean_score(prices[assets].rolling(fast).mean() / prices[assets].rolling(slow).mean() - 1.0)


def _triple_ma_score(prices: pd.DataFrame, assets: list[str], fast: int, medium: int, slow: int) -> pd.DataFrame:
    fast_ma = prices[assets].rolling(fast).mean()
    medium_ma = prices[assets].rolling(medium).mean()
    slow_ma = prices[assets].rolling(slow).mean()
    score = (fast_ma / medium_ma - 1.0) + (medium_ma / slow_ma - 1.0)
    return _clean_score(score.where((fast_ma > medium_ma) & (medium_ma > slow_ma), -999.0))


def _breakout_score(prices: pd.DataFrame, assets: list[str], window: int) -> pd.DataFrame:
    previous_high = prices[assets].rolling(window).max().shift(1)
    return _clean_score(prices[assets] / previous_high - 1.0)


def _zscore(frame: pd.DataFrame) -> pd.DataFrame:
    centered = frame.sub(frame.mean(axis=1), axis=0)
    scaled = centered.div(frame.std(axis=1).replace(0.0, np.nan), axis=0)
    return _clean_score(scaled)


def _clean_score(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.replace([np.inf, -np.inf], np.nan).fillna(-999.0)


def _cost_control_grid(family: str) -> list[dict[str, Any]]:
    del family
    return [
        dict(AGGRESSIVE_PARAMETERS),
        dict(BASELINE_PARAMETERS),
        dict(LOW_TURNOVER_PARAMETERS),
    ]


def _family_description(family: str) -> str:
    return {
        "sector_price_momentum_rotation_151": "151 ETF sector momentum rotation mapped to sector/thematic ETF ranks.",
        "sector_momentum_ma_filter_151": "151 sector momentum with moving-average filter.",
        "sector_dual_momentum_151": "151 dual-momentum sector rotation with cash hurdle.",
        "alpha_rotation_residual_151": "151 alpha rotation using residual momentum after broad-market beta.",
        "r_squared_trend_quality_151": "151 R-squared trend quality mapped to ETF trend selection.",
        "etf_mean_reversion_151": "151 ETF mean-reversion tested under positive long-term trend.",
        "low_volatility_anomaly_151": "151 low-volatility anomaly mapped to ETFs.",
        "multifactor_portfolio_151": "151 multifactor blend of momentum, low volatility, and trend quality.",
        "single_moving_average_151": "151 single moving-average timing.",
        "two_moving_averages_151": "151 two moving-average trend timing.",
        "three_moving_averages_151": "151 three moving-average trend alignment.",
        "support_resistance_breakout_151": "151 support/resistance breakout.",
        "channel_breakout_151": "151 channel breakout.",
        "multi_asset_tsmom_151": "151 multi-asset trend following / time-series momentum.",
        "dual_momentum_absolute_relative": "Absolute-plus-relative dual momentum with cash hurdle.",
        "quality_momentum_12_1": "12-1 month quality momentum with path consistency and volatility scaling.",
        "multi_speed_trend_forecast": "Multi-horizon trend forecast blended across 3, 6, and 12 months.",
        "macro_vol_scaled_overlay": "Existing signal with volatility-scaled macro offensive budget.",
        "ensemble_forecast_blend": "Blend existing residual momentum, quality momentum, and multi-speed trend forecast.",
    }[family]


def _evaluate_candidate(
    *,
    family: str,
    description: str,
    source_idea: str,
    context: dict[str, Any],
    parameters: dict[str, Any],
) -> dict[str, Any]:
    cfg: UsEtfMacroMomentumRotationConfig = context["cfg"]
    base_params = dict(parameters)
    base_params["cost_per_turnover"] = 0.0
    result = _run_experiment(
        context=context,
        spec=ExperimentSpec(family, description, base_params),
    )
    turnover = result.daily_weights.diff().abs().sum(axis=1).fillna(0.0)
    gross_returns = (result.daily_weights * context["asset_rets"][result.daily_weights.columns]).sum(axis=1)
    stress: dict[str, Any] = {}
    for bps in STRESS_COST_BPS:
        returns = gross_returns - turnover * (bps / 10_000.0)
        metrics = performance_summary(returns, context["prices"][cfg.benchmark])
        focus = _focus_years(returns, context["prices"][cfg.benchmark], result.daily_weights, cfg)
        stress[f"{bps}bps"] = {
            "metrics": {
                "total_return": float(metrics.get("total_return", 0.0)),
                "cagr": float(metrics.get("cagr", 0.0)),
                "sharpe": float(metrics.get("sharpe", 0.0)),
                "max_drawdown": float(metrics.get("max_drawdown", 0.0)),
                "benchmark_total_return": float(metrics.get("benchmark_total_return", 0.0)),
                "turnover": float(turnover.sum()),
                "avg_rebalance_turnover": float(turnover[turnover > 0].mean()) if (turnover > 0).any() else 0.0,
            },
            "focus_years": focus,
            "diagnostics": {
                **result.diagnostics,
                "cost_per_turnover": bps / 10_000.0,
                "top_n": int(cfg.top_n),
            },
        }
    m50 = stress["50bps"]["metrics"]
    focus_excess = [row["excess_return"] for row in stress["50bps"]["focus_years"].values()]
    score = (
        0.25 * float(m50["sharpe"])
        + 3.0 * float(m50["cagr"])
        - 0.10 * abs(float(m50["max_drawdown"]))
        + 0.05 * (float(np.mean(focus_excess)) if focus_excess else 0.0)
    )
    return {
        "family": family,
        "description": description,
        "source_idea": source_idea,
        "parameters": parameters,
        "stress": stress,
        "score_50bps": float(score),
        "survives_50bps": _survives(stress["50bps"]),
    }


def _survives(row: dict[str, Any]) -> bool:
    metrics = row["metrics"]
    return (
        float(metrics["cagr"]) > 0.0
        and float(metrics["sharpe"]) > 0.0
        and float(metrics["max_drawdown"]) > -0.40
        and float(metrics["turnover"]) < 140.0
    )


def _book_sources() -> list[dict[str, str]]:
    return [
        {
            "path": "学习资料/量化交易业务闭环/书籍/Dual Momentum Investing - Gary Antonacci.md",
            "usable_idea": "relative strength plus absolute momentum gate; defensive asset when risk asset momentum is not positive.",
        },
        {
            "path": "学习资料/量化交易业务闭环/书籍/Quantitative Momentum - Gray and Vogel.md",
            "usable_idea": "avoid chasing only the latest month; prefer 12-1 momentum and smoother momentum paths.",
        },
        {
            "path": "学习资料/量化交易业务闭环/书籍/Systematic Trading - Robert Carver.md",
            "usable_idea": "forecast first, then convert forecast into position with risk and cost controls.",
        },
        {
            "path": "学习资料/量化交易业务闭环/书籍/Active Portfolio Management - Grinold and Kahn.md",
            "usable_idea": "combine signals as forecasts and evaluate contribution after costs.",
        },
        {
            "path": "学习资料/量化交易业务闭环/书籍/Expected Returns - Antti Ilmanen.md",
            "usable_idea": "momentum, low-risk, and macro environments are distinct premia; do not mix them without attribution.",
        },
        {
            "path": "学习资料/量化交易业务闭环/书籍/151 Trading Strategies - Zura Kakushadze and Juan Andres Serur - 原文.md",
            "usable_idea": "sector rotation, dual momentum, multi-asset trend following, and volatility targeting can be tested as rotation variants.",
        },
    ]


def _extract_151_inventory(repo_root: Path) -> dict[str, Any]:
    candidates = [
        repo_root / "学习资料/量化交易业务闭环/书籍原文MD/151 Trading Strategies - Zura Kakushadze and Juan Andres Serur - 原文.md",
        repo_root.parent / "学习资料/量化交易业务闭环/书籍原文MD/151 Trading Strategies - Zura Kakushadze and Juan Andres Serur - 原文.md",
    ]
    path = next((candidate for candidate in candidates if candidate.exists()), None)
    if path is None:
        return {
            "source_found": False,
            "total_strategy_entries": None,
            "chapter_counts": {},
            "directly_tested_families": _tested_151_families(),
            "notes": "151 markdown source was not found from the current repo root; tested families are still encoded in this script.",
        }
    entries = _parse_151_toc(path)
    chapter_counts = Counter(chapter for chapter, _name in entries)
    return {
        "source_found": True,
        "source_path": str(path),
        "total_strategy_entries": len(entries),
        "chapter_counts": dict(sorted(chapter_counts.items())),
        "directly_tested_families": _tested_151_families(),
        "directly_tested_count": len(_tested_151_families()),
        "deferred_groups": {
            "options": "Need option chains, strikes, expiries, greeks, and volatility surface data.",
            "volatility": "Need VIX futures/ETN and option-implied volatility data.",
            "fixed_income_curve": "Need a full Treasury curve, futures, swaps, or bond-level data for most curve trades.",
            "credit_structured_tax_distressed": "Need CDS, tranche, MBS, tax, or distressed-security data not present in the ETF lake.",
            "intraday_arbitrage_market_making": "Need intraday quotes, spreads, order-book, and execution data.",
        },
    }


def _parse_151_toc(path: Path) -> list[tuple[str, str]]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    entries: list[tuple[str, str]] = []
    chapter = ""
    in_contents = False
    for line_number, line in enumerate(lines, start=1):
        if "### Contents" in line:
            in_contents = True
        if not in_contents:
            continue
        if line_number > 1480:
            break
        chapter_match = re.search(r"\[(\d+)\s+([^\]]+)\]", line)
        if chapter_match and "Strategy" not in chapter_match.group(2):
            chapter = chapter_match.group(2).replace("\u200b", "").strip()
        if "Strategy" not in line and "Mean-Reversion" not in line:
            continue
        name = re.sub(r".*?Strategy:\u200b|.*?Strategy:\s*", "", line)
        name = re.sub(r"\]\(.*", "", name).strip(" []")
        name = name.replace("\u200b", "").strip()
        if name and len(name) < 140:
            entries.append((chapter, name))
    return entries


def _tested_151_families() -> list[str]:
    return [
        "sector_price_momentum_rotation_151",
        "sector_momentum_ma_filter_151",
        "sector_dual_momentum_151",
        "alpha_rotation_residual_151",
        "r_squared_trend_quality_151",
        "etf_mean_reversion_151",
        "low_volatility_anomaly_151",
        "multifactor_portfolio_151",
        "single_moving_average_151",
        "two_moving_averages_151",
        "three_moving_averages_151",
        "support_resistance_breakout_151",
        "channel_breakout_151",
        "multi_asset_tsmom_151",
    ]


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _markdown(report: dict[str, Any]) -> str:
    best = report["best_overall"]
    highest_cagr = report["highest_cagr_candidate"]
    best_non_baseline = report["best_non_baseline"]
    baseline = report["baseline"]
    b50 = baseline["stress"]["50bps"]["metrics"]
    best50 = best["stress"]["50bps"]["metrics"]
    high50 = highest_cagr["stress"]["50bps"]["metrics"]
    nb50 = best_non_baseline["stress"]["50bps"]["metrics"]

    lines = [
        "# US ETF 轮动 书籍启发优化",
        "",
        "## 结论",
        "",
        f"- 当前全体最优：`{best['family']}`，50bps CAGR {_pct(best50['cagr'])}，Sharpe {best50['sharpe']:.3f}，MDD {_pct(best50['max_drawdown'])}，Turnover {best50['turnover']:.2f}。",
        f"- 最高 CAGR 候选：`{highest_cagr['family']}`，参数 `{json.dumps(highest_cagr['parameters'], ensure_ascii=False, sort_keys=True)}`，50bps CAGR {_pct(high50['cagr'])}，Sharpe {high50['sharpe']:.3f}，MDD {_pct(high50['max_drawdown'])}，Turnover {high50['turnover']:.2f}。",
        f"- 书籍启发最优：`{best_non_baseline['family']}`，参数 `{json.dumps(best_non_baseline['parameters'], ensure_ascii=False, sort_keys=True)}`。",
        f"- 书籍启发最优 50bps：CAGR {_pct(nb50['cagr'])}，Sharpe {nb50['sharpe']:.3f}，MDD {_pct(nb50['max_drawdown'])}，Turnover {nb50['turnover']:.2f}。",
        f"- 当前成本鲁棒基线 50bps：CAGR {_pct(b50['cagr'])}，Sharpe {b50['sharpe']:.3f}，MDD {_pct(b50['max_drawdown'])}，Turnover {b50['turnover']:.2f}。",
        "- 本报告只做研究优化，不解锁纸盘或实盘。",
        "",
        "## 151 策略覆盖",
        "",
    ]
    inventory = report.get("strategy_inventory_151", {})
    if inventory.get("source_found"):
        chapter_counts = inventory.get("chapter_counts", {})
        lines.extend(
            [
                f"- 已从《151 Trading Strategies》目录解析出 `{inventory['total_strategy_entries']}` 个策略条目。",
                f"- 本轮直接映射并回测 `{inventory['directly_tested_count']}` 个 151 启发策略族；其余大多需要期权链、VIX 期货、债券曲线、CDS/MBS、税务/困境证券或盘口级数据。",
                "- 这不是说其他策略没价值，而是当前 ETF 日线 + FRED 宏观数据无法严谨验证那些策略。",
                "",
                "| Chapter | Strategy Count |",
                "|---|---:|",
            ]
        )
        for chapter, count in chapter_counts.items():
            lines.append(f"| {chapter} | {count} |")
    else:
        lines.append("- 未在当前路径找到 151 原文 MD，报告使用脚本内置的可测策略映射。")
    lines.extend(
        [
            "",
            "## 收益和夏普偏低的原因",
            "",
            "- 当前目标函数偏向 `50bps 成本后仍存活 + 低换手 + 低回撤`，不是最大化 CAGR。",
            "- 策略是月度长-only ETF 轮动，不能做空、不能杠杆，也没有期权/波动率/期货 carry 等收益源。",
            "- 2018 以后 SPY/QQQ 牛市很强，任何带宏观防守和现金/债券残余仓位的策略都会牺牲部分上行收益。",
            "- 高成本压力会惩罚高换手策略，所以很多看似高收益的动量切换会被主动压下去。",
            "- 本轮已加入 `aggressive_no_turnover_guard`；它不主动压换手，但 50bps 后换手普遍约 300，收益和回撤明显恶化，所以不能简单理解为“换手越高收益越高”。",
            "",
        ]
    )
    lines.extend(
        [
        "## 书籍启发方向",
        "",
        "| 方向 | 本轮实现 | 主要启发 |",
        "|---|---|---|",
        ]
    )
    for family, summary in report["families"].items():
        if family == "baseline_v2_turnover_guard":
            continue
        row = summary["best"]
        metrics = row["stress"]["50bps"]["metrics"]
        lines.append(
            "| "
            + " | ".join(
                [
                    family,
                    f"50bps CAGR {_pct(metrics['cagr'])}, Sharpe {metrics['sharpe']:.3f}, MDD {_pct(metrics['max_drawdown'])}, Turnover {metrics['turnover']:.2f}",
                    row["source_idea"],
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Top 15",
            "",
            "| Rank | Family | Params | 10bps CAGR | 25bps CAGR | 50bps CAGR | 50bps Sharpe | 50bps MDD | Turnover | Survives |",
            "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for rank, row in enumerate(report["ranking"][:15], start=1):
        m10 = row["stress"]["10bps"]["metrics"]
        m25 = row["stress"]["25bps"]["metrics"]
        m50 = row["stress"]["50bps"]["metrics"]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(rank),
                    row["family"],
                    f"`{json.dumps(row['parameters'], ensure_ascii=False, sort_keys=True)}`",
                    _pct(m10["cagr"]),
                    _pct(m25["cagr"]),
                    _pct(m50["cagr"]),
                    f"{m50['sharpe']:.3f}",
                    _pct(m50["max_drawdown"]),
                    f"{m50['turnover']:.2f}",
                    "yes" if row["survives_50bps"] else "no",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 暂缓方向",
            "",
        ]
    )
    for item in report["deferred_ideas"]:
        lines.append(f"- `{item['idea']}`：{item['reason']}")
    lines.extend(
        [
            "",
            "## 方法",
            "",
            f"- {report['methodology']['goal']}",
            f"- 成本压力：{report['methodology']['cost_stress']}",
            f"- 评分：{report['methodology']['score_50bps']}",
            f"- 约束：{report['methodology']['constraint']}",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
