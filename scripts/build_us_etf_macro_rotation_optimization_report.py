#!/usr/bin/env python3
"""Run constrained optimization experiments for the US ETF macro rotation strategy."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from dataclasses import dataclass
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
    _base_equity_weight,
    _defense_allocations,
    _last_trading_dates_by_month,
    build_price_matrix_from_bars,
    calculate_rotation_inputs,
    performance_summary,
)
from scripts.build_us_etf_macro_rotation_research_report import (  # noqa: E402
    DEFAULT_EXTERNAL_DATA_LAKE,
    _load_external_data_lake_bars,
    _load_macro_data,
)


DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_etf_macro_rotation/latest")
DEFAULT_MARKDOWN = Path("学习资料/量化交易业务闭环/系统评估/US ETF 轮动 5方案优化报告.md")
FOCUS_YEARS = (2015, 2022, 2023, 2024)
RISKY_ASSETS = ("BITO", "USO", "XBI", "SOXX", "IGV")


@dataclass(frozen=True)
class ExperimentSpec:
    scheme_id: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class BacktestResult:
    daily_returns: pd.Series
    daily_weights: pd.DataFrame
    diagnostics: dict[str, Any]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--markdown-path", default=str(DEFAULT_MARKDOWN))
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    report = build_optimization_report(repo_root=root)

    output_root = root / Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "us_etf_macro_rotation_optimization_report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    markdown_path = root / Path(args.markdown_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(json_path), "markdown": str(markdown_path)}, indent=2, sort_keys=True))


def build_optimization_report(*, repo_root: Path) -> dict[str, Any]:
    cfg = UsEtfMacroMomentumRotationConfig()
    bars, available_symbols, _coverage = _load_external_data_lake_bars(DEFAULT_EXTERNAL_DATA_LAKE, cfg.required_symbols())
    missing = sorted(set(cfg.required_symbols()) - set(available_symbols))
    if missing:
        raise SystemExit(f"missing external ETF symbols: {missing}")
    prices = build_price_matrix_from_bars(bars, cfg.required_symbols())
    macro_df, macro_status, macro_path = _load_macro_data(repo_root, None, external_data_lake=DEFAULT_EXTERNAL_DATA_LAKE)
    inputs = calculate_rotation_inputs(prices, macro_df, cfg)
    context = {
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

    baseline = _evaluate_experiment(
        ExperimentSpec("baseline_current", "当前原始策略", {}),
        context,
    )
    schemes: dict[str, Any] = {}
    for scheme_id, candidates in _experiment_grid().items():
        evaluated = [_evaluate_experiment(spec, context, baseline=baseline) for spec in candidates]
        ranked = sorted(evaluated, key=lambda row: row["optimization_score"], reverse=True)
        best = ranked[0]
        schemes[scheme_id] = {
            "best": best,
            "candidate_count": len(ranked),
            "top_candidates": ranked[:5],
            "all_candidates": ranked,
        }

    best_overall = max((scheme["best"] for scheme in schemes.values()), key=lambda row: row["optimization_score"])
    return {
        "schema_version": "us_etf_macro_rotation_optimization_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy_id": cfg.strategy_id,
        "status": "research_only",
        "live_ready": False,
        "paper_ready": False,
        "price_source": str(DEFAULT_EXTERNAL_DATA_LAKE),
        "macro_status": macro_status,
        "macro_path": str(macro_path) if macro_path else None,
        "focus_years": list(FOCUS_YEARS),
        "baseline": baseline,
        "schemes": schemes,
        "best_overall": best_overall,
        "methodology": {
            "optimization_score": (
                "sharpe + cagr - 0.5*abs(max_drawdown) - 0.01*turnover "
                "+ 0.5*mean_focus_year_excess_improvement"
            ),
            "constraint": "All experiments remain research-only and reuse the same repaired external ETF/FRED data.",
            "schemes": [
                "v1_macro_floor: keep a minimum offensive allocation when SPY is above its 200-day average.",
                "v1_turnover_guard: add no-trade threshold and minimum holding period to reduce churn.",
                "v1_risk_capped_selection: penalize drawdown and cap high-volatility thematic ETFs.",
                "v1_defense_regime_cap: cap defensive allocation while SPY is above its 200-day average.",
                "v1_combined_conservative: combine the strongest conservative settings from the above ideas.",
            ],
        },
    }


def _experiment_grid() -> dict[str, list[ExperimentSpec]]:
    return {
        "v1_macro_floor": [
            ExperimentSpec(
                "v1_macro_floor",
                "趋势为多头时设置最低进攻仓位，避免牛市中过度防御。",
                {"macro_floor": floor, "macro_floor_requires_spy_trend": True},
            )
            for floor in (0.35, 0.50, 0.65)
        ],
        "v1_turnover_guard": [
            ExperimentSpec(
                "v1_turnover_guard",
                "设置换仓阈值和最短持有期，降低月度轮动噪音。",
                {"turnover_threshold": threshold, "min_hold_months": hold}
            )
            for threshold, hold in itertools.product((0.15, 0.25, 0.35), (2, 3))
        ],
        "v1_risk_capped_selection": [
            ExperimentSpec(
                "v1_risk_capped_selection",
                "对高波动主题 ETF 做仓位上限，并对近期回撤较大的资产扣分。",
                {"risky_asset_cap": cap, "drawdown_penalty": penalty, "reversal_filter_20d": reversal},
            )
            for cap, penalty, reversal in itertools.product((0.20, 0.30), (1.0, 2.0), (0.10, 0.15))
        ],
        "v1_defense_regime_cap": [
            ExperimentSpec(
                "v1_defense_regime_cap",
                "SPY 长期趋势向上时限制防御仓位，把防御从开关改成缓冲。",
                {"defense_cap_when_spy_trend": cap},
            )
            for cap in (0.35, 0.50, 0.65)
        ],
        "v1_combined_conservative": [
            ExperimentSpec(
                "v1_combined_conservative",
                "组合保守版：最低进攻仓位、换手阈值、风险封顶、防御上限同时启用。",
                {
                    "macro_floor": macro_floor,
                    "macro_floor_requires_spy_trend": True,
                    "turnover_threshold": turnover_threshold,
                    "min_hold_months": hold,
                    "risky_asset_cap": risky_cap,
                    "drawdown_penalty": 1.0,
                    "reversal_filter_20d": 0.15,
                    "defense_cap_when_spy_trend": defense_cap,
                },
            )
            for macro_floor, turnover_threshold, hold, risky_cap, defense_cap in itertools.product(
                (0.35, 0.50),
                (0.15, 0.25),
                (2,),
                (0.25, 0.30),
                (0.50, 0.65),
            )
        ],
    }


def _evaluate_experiment(
    spec: ExperimentSpec,
    context: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg: UsEtfMacroMomentumRotationConfig = context["cfg"]
    result = _run_experiment(context=context, spec=spec)
    metrics = performance_summary(result.daily_returns, context["prices"][cfg.benchmark])
    turnover = float(result.diagnostics["turnover"])
    focus = _focus_years(result.daily_returns, context["prices"][cfg.benchmark], result.daily_weights, cfg)
    focus_excess_values = [row["excess_return"] for row in focus.values()]
    baseline_improvement = 0.0
    if baseline:
        baseline_focus = baseline["focus_years"]
        improvements = [
            focus[str(year)]["excess_return"] - baseline_focus[str(year)]["excess_return"]
            for year in FOCUS_YEARS
            if str(year) in focus and str(year) in baseline_focus
        ]
        baseline_improvement = float(np.mean(improvements)) if improvements else 0.0
    score = (
        float(metrics.get("sharpe", 0.0))
        + float(metrics.get("cagr", 0.0))
        - 0.5 * abs(float(metrics.get("max_drawdown", 0.0)))
        - 0.01 * turnover
        + 0.5 * baseline_improvement
    )
    return {
        "scheme_id": spec.scheme_id,
        "description": spec.description,
        "parameters": spec.parameters,
        "metrics": {
            "total_return": float(metrics.get("total_return", 0.0)),
            "cagr": float(metrics.get("cagr", 0.0)),
            "sharpe": float(metrics.get("sharpe", 0.0)),
            "max_drawdown": float(metrics.get("max_drawdown", 0.0)),
            "benchmark_total_return": float(metrics.get("benchmark_total_return", 0.0)),
            "turnover": turnover,
            "avg_rebalance_turnover": float(result.diagnostics["avg_rebalance_turnover"]),
        },
        "focus_years": focus,
        "mean_focus_excess_return": float(np.mean(focus_excess_values)) if focus_excess_values else 0.0,
        "mean_focus_excess_improvement_vs_baseline": baseline_improvement,
        "optimization_score": float(score),
        "diagnostics": result.diagnostics,
    }


def _run_experiment(*, context: dict[str, Any], spec: ExperimentSpec) -> BacktestResult:
    cfg: UsEtfMacroMomentumRotationConfig = context["cfg"]
    prices: pd.DataFrame = context["prices"]
    asset_rets: pd.DataFrame = context["asset_rets"]
    mom_score: pd.DataFrame = context["mom_score"].copy()
    volatility: pd.DataFrame = context["volatility"]
    trend_filter: pd.DataFrame = context["trend_filter"]
    macro_regime: pd.Series = context["macro_regime"]
    yield_curve_inverted: pd.Series = context["yield_curve_inverted"]
    defense_mom: pd.DataFrame = context["defense_mom"]
    params = spec.parameters

    if "drawdown_penalty" in params:
        recent_peak = prices[list(cfg.offensive_assets)].rolling(63).max()
        recent_drawdown = prices[list(cfg.offensive_assets)] / recent_peak - 1.0
        mom_score = mom_score + recent_drawdown.fillna(0.0) * float(params["drawdown_penalty"])

    rebalance_dates = _last_trading_dates_by_month(prices.index)
    columns = list(_unique([*cfg.offensive_assets, *cfg.defense_assets]))
    weights_monthly = pd.DataFrame(0.0, index=rebalance_dates, columns=columns)
    reasons: dict[str, str] = {}
    spy_trend = prices[cfg.benchmark] > prices[cfg.benchmark].rolling(200).mean()
    last_change_index = -999

    for month_index, date in enumerate(rebalance_dates):
        target, reason = _monthly_target(
            date=date,
            prices=prices,
            asset_rets=asset_rets,
            mom_score=mom_score,
            volatility=volatility,
            trend_filter=trend_filter,
            macro_regime=macro_regime,
            yield_curve_inverted=yield_curve_inverted,
            defense_mom=defense_mom,
            cfg=cfg,
            params=params,
            columns=columns,
            spy_trend=spy_trend,
        )

        if _turnover_guard_active(params) and month_index > 0:
            previous = weights_monthly.iloc[month_index - 1].copy()
            turnover_to_target = float((target - previous).abs().sum())
            months_since_change = month_index - last_change_index
            hard_risk_off = reason == "macro_risk_off_defense_only" and not bool(spy_trend.loc[date])
            if not hard_risk_off and turnover_to_target < float(params.get("turnover_threshold", 0.0)):
                target = previous
                reason = "turnover_guard_kept_previous"
            elif not hard_risk_off and months_since_change < int(params.get("min_hold_months", 1)):
                target = previous
                reason = "min_hold_kept_previous"

        if month_index > 0:
            previous = weights_monthly.iloc[month_index - 1].copy()
            hard_risk_off = reason == "macro_risk_off_defense_only" and not bool(spy_trend.loc[date])
            if "rebalance_blend" in params and not hard_risk_off:
                blend = min(1.0, max(0.0, float(params["rebalance_blend"])))
                target = previous * (1.0 - blend) + target * blend
                reason = f"{reason}_blended" if blend < 1.0 else reason
            if "max_monthly_turnover" in params and not hard_risk_off:
                delta = target - previous
                turnover_to_target = float(delta.abs().sum())
                cap = max(0.0, float(params["max_monthly_turnover"]))
                if cap > 0 and turnover_to_target > cap:
                    target = previous + delta * (cap / turnover_to_target)
                    reason = f"{reason}_turnover_capped"
            target = _normalize_target(target)

        if month_index == 0 or float((target - weights_monthly.iloc[month_index - 1]).abs().sum()) > 1e-12:
            last_change_index = month_index
        weights_monthly.loc[date] = target
        reasons[str(date)] = reason

    daily_weights = weights_monthly.reindex(prices.index).ffill().shift(1).fillna(0.0)
    turnover = daily_weights.diff().abs().sum(axis=1).fillna(0.0)
    cost_per_turnover = float(params.get("cost_per_turnover", cfg.cost_per_turnover))
    returns = (daily_weights * asset_rets[daily_weights.columns]).sum(axis=1) - turnover * cost_per_turnover
    reason_counts: dict[str, int] = {}
    for reason in reasons.values():
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    diagnostics = {
        "rebalance_count": int(len(weights_monthly)),
        "turnover": float(turnover.sum()),
        "avg_rebalance_turnover": float(turnover[turnover > 0].mean()) if (turnover > 0).any() else 0.0,
        "rebalance_reason_counts": reason_counts,
        "t_plus_1_execution": _check_t_plus_1(weights_monthly, daily_weights),
        "cost_per_turnover": cost_per_turnover,
    }
    return BacktestResult(daily_returns=returns, daily_weights=daily_weights, diagnostics=diagnostics)


def _monthly_target(
    *,
    date: pd.Timestamp,
    prices: pd.DataFrame,
    asset_rets: pd.DataFrame,
    mom_score: pd.DataFrame,
    volatility: pd.DataFrame,
    trend_filter: pd.DataFrame,
    macro_regime: pd.Series,
    yield_curve_inverted: pd.Series,
    defense_mom: pd.DataFrame,
    cfg: UsEtfMacroMomentumRotationConfig,
    params: dict[str, Any],
    columns: list[str],
    spy_trend: pd.Series,
) -> tuple[pd.Series, str]:
    target = pd.Series(0.0, index=columns)
    base = _base_equity_weight(float(macro_regime.loc[date]), cfg)
    if "macro_floor" in params:
        requires_trend = bool(params.get("macro_floor_requires_spy_trend", False))
        if not requires_trend or bool(spy_trend.loc[date]):
            base = max(base, float(params["macro_floor"]))
    defense_allocations = _defense_allocations(date, asset_rets, volatility, defense_mom, cfg)

    if base <= 0.0:
        for asset in cfg.defense_assets:
            target[asset] += defense_allocations.get(asset, 0.0)
        return _normalize_target(target), "macro_risk_off_defense_only"

    selected = _select_assets_for_experiment(date, prices, asset_rets, mom_score, trend_filter, cfg, params)
    if not selected:
        for asset in cfg.defense_assets:
            target[asset] += defense_allocations.get(asset, 0.0)
        return _normalize_target(target), "no_positive_trend_defense_only"

    selected_vols = volatility.loc[date, selected].replace(0.0, 0.0001)
    inv_vols = 1.0 / selected_vols
    risk_parity_weights = inv_vols / inv_vols.sum()
    hist_rets = asset_rets.loc[:date, selected].tail(cfg.cov_lookback)
    vol_scaler = 1.0
    if len(hist_rets) > 10:
        cov_matrix = hist_rets.cov() * 252
        variance = float(np.dot(risk_parity_weights.values.T, np.dot(cov_matrix.values, risk_parity_weights.values)))
        expected_vol = float(np.sqrt(max(variance, 0.0)))
        current_target_vol = cfg.target_vol_inverted if bool(yield_curve_inverted.loc[date]) else cfg.target_vol
        vol_scaler = min(1.0, current_target_vol / expected_vol) if expected_vol > 0 else 1.0
    final_equity_weight = float(base * vol_scaler)
    offensive_weights = risk_parity_weights.astype(float) * final_equity_weight
    if "risky_asset_cap" in params:
        offensive_weights, capped_excess = _cap_risky_weights(offensive_weights, float(params["risky_asset_cap"]))
        final_equity_weight = float(offensive_weights.sum())
    else:
        capped_excess = 0.0

    for asset, weight in offensive_weights.items():
        target[asset] += float(weight)
    defense_total_weight = max(0.0, 1.0 - final_equity_weight)
    defense_total_weight += capped_excess
    if "defense_cap_when_spy_trend" in params and bool(spy_trend.loc[date]):
        cap = float(params["defense_cap_when_spy_trend"])
        if defense_total_weight > cap:
            excess = defense_total_weight - cap
            defense_total_weight = cap
            if offensive_weights.sum() > 0:
                uplift = offensive_weights / offensive_weights.sum() * excess
                for asset, weight in uplift.items():
                    target[asset] += float(weight)
            else:
                target["QQQ"] += excess
    for asset in cfg.defense_assets:
        target[asset] += defense_allocations.get(asset, 0.0) * defense_total_weight
    return _normalize_target(target), "offensive_rotation_with_defense_residual"


def _select_assets_for_experiment(
    date: pd.Timestamp,
    prices: pd.DataFrame,
    asset_rets: pd.DataFrame,
    mom_score: pd.DataFrame,
    trend_filter: pd.DataFrame,
    cfg: UsEtfMacroMomentumRotationConfig,
    params: dict[str, Any],
) -> list[str]:
    current_mom = mom_score.loc[date].copy()
    current_trend = trend_filter.loc[date]
    valid_mom = current_mom.where(current_trend, -999.0)
    if "reversal_filter_20d" in params:
        recent_ret = prices[list(cfg.offensive_assets)].pct_change(20, fill_method=None).loc[date]
        valid_mom = valid_mom.where(recent_ret >= -float(params["reversal_filter_20d"]), -999.0)
    valid_assets = valid_mom.sort_values(ascending=False)
    valid_assets = valid_assets[valid_assets != -999.0].index.tolist()
    selected: list[str] = []
    corr_hist = asset_rets.loc[:date, valid_assets].tail(cfg.cov_lookback)
    current_corr = corr_hist.corr() if len(corr_hist) > 10 else pd.DataFrame()
    for asset in valid_assets:
        if not selected:
            selected.append(asset)
        else:
            too_correlated = False
            if not current_corr.empty:
                for picked in selected:
                    if float(current_corr.loc[asset, picked]) > 0.80:
                        too_correlated = True
                        break
            if not too_correlated:
                selected.append(asset)
        if len(selected) >= cfg.top_n:
            break
    if len(selected) < cfg.top_n:
        for asset in valid_assets:
            if asset not in selected:
                selected.append(asset)
            if len(selected) >= cfg.top_n:
                break
    return selected


def _cap_risky_weights(weights: pd.Series, cap: float) -> tuple[pd.Series, float]:
    capped = weights.copy()
    excess = 0.0
    for asset in list(capped.index):
        if asset in RISKY_ASSETS and float(capped[asset]) > cap:
            excess += float(capped[asset] - cap)
            capped[asset] = cap
    return capped, excess


def _normalize_target(target: pd.Series) -> pd.Series:
    target = target.clip(lower=0.0)
    total = float(target.sum())
    if total > 1.0:
        target = target / total
    return target


def _turnover_guard_active(params: dict[str, Any]) -> bool:
    return "turnover_threshold" in params or "min_hold_months" in params


def _focus_years(
    returns: pd.Series,
    benchmark_prices: pd.Series,
    weights: pd.DataFrame,
    cfg: UsEtfMacroMomentumRotationConfig,
) -> dict[str, Any]:
    benchmark_ret = benchmark_prices.pct_change(fill_method=None).reindex(returns.index).fillna(0.0)
    defense_assets = list(cfg.defense_assets)
    offensive_assets = [asset for asset in cfg.offensive_assets if asset not in defense_assets]
    result: dict[str, Any] = {}
    for year in FOCUS_YEARS:
        mask = returns.index.year == year
        if not bool(mask.any()):
            continue
        strategy_return = _compound(returns.loc[mask])
        benchmark_return = _compound(benchmark_ret.loc[mask])
        result[str(year)] = {
            "strategy_return": strategy_return,
            "benchmark_return": benchmark_return,
            "excess_return": strategy_return - benchmark_return,
            "avg_offensive_weight": float(weights.loc[mask, offensive_assets].sum(axis=1).mean()),
            "avg_defense_weight": float(weights.loc[mask, defense_assets].sum(axis=1).mean()),
            "turnover": float(weights.loc[mask].diff().abs().sum(axis=1).fillna(0.0).sum()),
        }
    return result


def _compound(returns: pd.Series) -> float:
    return float((1.0 + returns.fillna(0.0)).prod() - 1.0)


def _check_t_plus_1(weights_monthly: pd.DataFrame, daily_weights: pd.DataFrame) -> bool:
    for rebalance_date in weights_monthly.index:
        if rebalance_date not in daily_weights.index:
            continue
        previous_dates = daily_weights.index[daily_weights.index < rebalance_date]
        if len(previous_dates) == 0:
            continue
        current = daily_weights.loc[rebalance_date].fillna(0.0)
        previous = daily_weights.loc[previous_dates[-1]].fillna(0.0)
        if not np.allclose(current, previous):
            return False
    return True


def _unique(items: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        symbol = str(item).upper()
        if symbol not in seen:
            seen.add(symbol)
            result.append(symbol)
    return result


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _markdown(report: dict[str, Any]) -> str:
    baseline = report["baseline"]
    best = report["best_overall"]
    lines = [
        "# US ETF 轮动 5方案优化报告",
        "",
        "## 结论",
        "",
        f"- 当前最优实验：`{best['scheme_id']}`，参数 `{json.dumps(best['parameters'], ensure_ascii=False, sort_keys=True)}`。",
        f"- 最优实验 CAGR：{_pct(best['metrics']['cagr'])}；Sharpe：{best['metrics']['sharpe']:.3f}；最大回撤：{_pct(best['metrics']['max_drawdown'])}；换手：{best['metrics']['turnover']:.2f}。",
        f"- baseline CAGR：{_pct(baseline['metrics']['cagr'])}；Sharpe：{baseline['metrics']['sharpe']:.3f}；最大回撤：{_pct(baseline['metrics']['max_drawdown'])}；换手：{baseline['metrics']['turnover']:.2f}。",
        "",
        "## 方案排名",
        "",
        "| 方案 | 最优参数 | CAGR | Sharpe | MDD | Turnover | 2015超额 | 2022超额 | 2023超额 | 2024超额 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scheme_id, scheme in report["schemes"].items():
        row = scheme["best"]
        fy = row["focus_years"]
        lines.append(
            "| "
            + " | ".join(
                [
                    scheme_id,
                    f"`{json.dumps(row['parameters'], ensure_ascii=False, sort_keys=True)}`",
                    _pct(row["metrics"]["cagr"]),
                    f"{row['metrics']['sharpe']:.3f}",
                    _pct(row["metrics"]["max_drawdown"]),
                    f"{row['metrics']['turnover']:.2f}",
                    _pct(fy["2015"]["excess_return"]),
                    _pct(fy["2022"]["excess_return"]),
                    _pct(fy["2023"]["excess_return"]),
                    _pct(fy["2024"]["excess_return"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Baseline",
            "",
            f"- CAGR：{_pct(baseline['metrics']['cagr'])}；Sharpe：{baseline['metrics']['sharpe']:.3f}；MDD：{_pct(baseline['metrics']['max_drawdown'])}；换手：{baseline['metrics']['turnover']:.2f}。",
            "",
            "## 方法",
            "",
            f"- 优化评分：{report['methodology']['optimization_score']}",
            f"- 约束：{report['methodology']['constraint']}",
            "- 所有方案仍为 research-only，不允许直接纸盘或实盘。",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
