#!/usr/bin/env python3
"""Build focused attribution for selected US ETF macro rotation years."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.research.us_etf_macro_momentum_rotation import (  # noqa: E402
    UsEtfMacroMomentumRotationConfig,
    _base_equity_weight,
    build_price_matrix_from_bars,
    calculate_rotation_inputs,
    run_us_etf_macro_momentum_rotation,
)
from scripts.build_us_etf_macro_rotation_research_report import (  # noqa: E402
    DEFAULT_EXTERNAL_DATA_LAKE,
    _load_external_data_lake_bars,
    _load_macro_data,
)


DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_etf_macro_rotation/latest")
DEFAULT_MARKDOWN = Path("学习资料/量化交易业务闭环/系统评估/US ETF 轮动 2015-2024 归因.md")
DEFAULT_YEARS = (2015, 2022, 2023, 2024)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--markdown-path", default=str(DEFAULT_MARKDOWN))
    parser.add_argument("--years", default=",".join(str(year) for year in DEFAULT_YEARS))
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    years = tuple(int(item.strip()) for item in args.years.split(",") if item.strip())
    report = build_attribution_report(repo_root=root, years=years)

    output_root = root / Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "us_etf_macro_rotation_year_attribution_report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    markdown_path = root / Path(args.markdown_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(json_path), "markdown": str(markdown_path)}, indent=2, sort_keys=True))


def build_attribution_report(*, repo_root: Path, years: tuple[int, ...]) -> dict[str, Any]:
    cfg = UsEtfMacroMomentumRotationConfig()
    bars, available_symbols, coverage = _load_external_data_lake_bars(DEFAULT_EXTERNAL_DATA_LAKE, cfg.required_symbols())
    missing = sorted(set(cfg.required_symbols()) - set(available_symbols))
    if missing:
        raise SystemExit(f"missing external ETF symbols: {missing}")
    prices = build_price_matrix_from_bars(bars, cfg.required_symbols())
    macro_df, macro_status, macro_path = _load_macro_data(repo_root, None, external_data_lake=DEFAULT_EXTERNAL_DATA_LAKE)
    inputs = calculate_rotation_inputs(prices, macro_df, cfg)
    result = run_us_etf_macro_momentum_rotation(prices, macro_df, cfg)

    daily_ret = prices[list(cfg.required_symbols())].pct_change(fill_method=None).fillna(0.0)
    weights = result.daily_weights.reindex(daily_ret.index).fillna(0.0)
    benchmark_ret = daily_ret[cfg.benchmark]
    # GLD exists in both config lists. For role attribution, classify overlaps
    # as defense so group weights are mutually exclusive and sum cleanly.
    defense_assets = list(cfg.defense_assets)
    offensive_assets = [asset for asset in cfg.offensive_assets if asset not in defense_assets]
    offensive_weight = weights[offensive_assets].sum(axis=1)
    defense_weight = weights[defense_assets].sum(axis=1)
    total_weight = weights.sum(axis=1)
    turnover = weights.diff().abs().sum(axis=1).fillna(0.0)
    costs = turnover * cfg.cost_per_turnover

    offensive_raw = (weights[offensive_assets] * daily_ret[offensive_assets]).sum(axis=1)
    offensive_selection = (weights[offensive_assets] * daily_ret[offensive_assets].sub(benchmark_ret, axis=0)).sum(axis=1)
    defense_raw = (weights[defense_assets] * daily_ret[defense_assets]).sum(axis=1)
    macro_equity_exposure = (offensive_weight - 1.0) * benchmark_ret
    cash_residual = (total_weight - offensive_weight - defense_weight) * benchmark_ret
    strategy = offensive_raw + defense_raw - costs
    excess = strategy - benchmark_ret
    additive_reconstructed_excess = macro_equity_exposure + offensive_selection + defense_raw + cash_residual - costs

    macro_regime = inputs[3].reindex(daily_ret.index).ffill().fillna(1.0)
    base_equity_weight = macro_regime.map(lambda value: _base_equity_weight(float(value), cfg))
    yield_curve_inverted = inputs[4].reindex(daily_ret.index).ffill().fillna(False)
    monthly_reasons = _infer_monthly_reasons(weights, base_equity_weight, offensive_weight, cfg)
    asset_contrib = weights.multiply(daily_ret, axis=0)

    by_year: dict[str, Any] = {}
    for year in years:
        mask = daily_ret.index.year == year
        if not bool(mask.any()):
            continue
        year_key = str(year)
        yearly_asset_contrib = asset_contrib.loc[mask].sum().sort_values()
        by_year[year_key] = {
            "strategy_return": _compound(strategy.loc[mask]),
            "benchmark_return": _compound(benchmark_ret.loc[mask]),
            "excess_return": _compound(strategy.loc[mask]) - _compound(benchmark_ret.loc[mask]),
            "additive_excess": float(excess.loc[mask].sum()),
            "attribution_additive": {
                "macro_equity_exposure_effect": float(macro_equity_exposure.loc[mask].sum()),
                "momentum_selection_effect": float(offensive_selection.loc[mask].sum()),
                "defense_asset_contribution": float(defense_raw.loc[mask].sum()),
                "cash_residual_effect": float(cash_residual.loc[mask].sum()),
                "cost_effect": float(-costs.loc[mask].sum()),
                "reconstructed_excess": float(additive_reconstructed_excess.loc[mask].sum()),
            },
            "exposure": {
                "avg_macro_score": float(macro_regime.loc[mask].mean()),
                "avg_base_equity_weight": float(base_equity_weight.loc[mask].mean()),
                "avg_actual_offensive_weight": float(offensive_weight.loc[mask].mean()),
                "avg_defense_weight": float(defense_weight.loc[mask].mean()),
                "avg_total_weight": float(total_weight.loc[mask].mean()),
                "risk_off_days": int((base_equity_weight.loc[mask] <= 0).sum()),
                "inverted_curve_days": int(yield_curve_inverted.loc[mask].sum()),
                "turnover": float(turnover.loc[mask].sum()),
            },
            "asset_contribution": {
                "worst": {symbol: float(value) for symbol, value in yearly_asset_contrib.head(8).items() if abs(value) > 1e-12},
                "best": {symbol: float(value) for symbol, value in yearly_asset_contrib.tail(8).sort_values(ascending=False).items() if abs(value) > 1e-12},
            },
            "rebalance_reason_counts": _year_reason_counts(monthly_reasons, year),
            "diagnosis": _diagnose_year(
                strategy_return=_compound(strategy.loc[mask]),
                benchmark_return=_compound(benchmark_ret.loc[mask]),
                attribution={
                    "macro": float(macro_equity_exposure.loc[mask].sum()),
                    "momentum": float(offensive_selection.loc[mask].sum()),
                    "defense": float(defense_raw.loc[mask].sum()),
                    "cost": float(-costs.loc[mask].sum()),
                },
            ),
        }

    return {
        "schema_version": "us_etf_macro_rotation_year_attribution_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy_id": cfg.strategy_id,
        "price_source": str(DEFAULT_EXTERNAL_DATA_LAKE),
        "macro_status": macro_status,
        "macro_path": str(macro_path) if macro_path else None,
        "years": by_year,
        "methodology": {
            "benchmark": cfg.benchmark,
            "additive_excess_formula": (
                "excess ~= (offensive_weight - 1) * SPY_return "
                "+ offensive_weighted(asset_return - SPY_return) "
                "+ defense_weighted(asset_return) + cash_residual - turnover_cost"
            ),
            "notes": [
                "Additive attribution is summed daily and will not exactly equal compounded excess return.",
                "Macro effect is measured as equity under/over-exposure versus always holding SPY.",
                "Momentum selection effect measures selected offensive ETFs versus SPY on the days they were held.",
                "Assets that appear in both offensive and defense lists are classified as defense for role attribution.",
                "Defense contribution is absolute defensive asset return; its SPY opportunity cost is captured mainly by macro equity exposure.",
            ],
        },
    }


def _infer_monthly_reasons(
    weights: pd.DataFrame,
    base_equity_weight: pd.Series,
    offensive_weight: pd.Series,
    cfg: UsEtfMacroMomentumRotationConfig,
) -> pd.Series:
    period_index = weights.index.tz_convert(None).to_period("M") if weights.index.tz is not None else weights.index.to_period("M")
    month_end_dates = pd.DatetimeIndex(
        [group.iloc[-1] for _, group in pd.Series(weights.index, index=weights.index).groupby(period_index)]
    )
    reasons: dict[pd.Timestamp, str] = {}
    for date in month_end_dates:
        if float(base_equity_weight.loc[date]) <= 0:
            reasons[date] = "macro_risk_off_defense_only"
        elif float(offensive_weight.loc[date]) <= 1e-9:
            reasons[date] = "no_positive_trend_defense_only"
        else:
            reasons[date] = "offensive_rotation_with_defense_residual"
    return pd.Series(reasons)


def _year_reason_counts(reasons: pd.Series, year: int) -> dict[str, int]:
    selected = reasons[reasons.index.year == year]
    counts = selected.value_counts()
    return {str(reason): int(count) for reason, count in counts.items()}


def _compound(returns: pd.Series) -> float:
    return float((1.0 + returns.fillna(0.0)).prod() - 1.0)


def _diagnose_year(*, strategy_return: float, benchmark_return: float, attribution: dict[str, float]) -> str:
    if strategy_return < 0:
        target = "亏损"
    elif strategy_return < benchmark_return:
        target = "跑输"
    else:
        target = "跑赢"
    drag_items = sorted(
        ((name, value) for name, value in attribution.items() if value < 0),
        key=lambda item: item[1],
    )
    if not drag_items:
        return f"{target}: no negative additive attribution bucket dominated."
    primary = drag_items[0][0]
    labels = {
        "macro": "宏观开关/低权益暴露",
        "momentum": "动量选择",
        "defense": "防御资产收益",
        "cost": "换手成本",
    }
    return f"{target}：主要拖累来自{labels.get(primary, primary)}。"


def _pct(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value * 100:.2f}%"


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# US ETF 轮动 2015/2022/2023/2024 归因",
        "",
        "## 结论",
        "",
    ]
    for year, row in report["years"].items():
        attr = row["attribution_additive"]
        exp = row["exposure"]
        lines.extend(
            [
                f"### {year}",
                "",
                f"- 策略收益：{_pct(row['strategy_return'])}；SPY：{_pct(row['benchmark_return'])}；超额：{_pct(row['excess_return'])}。",
                f"- 主要判断：{row['diagnosis']}",
                f"- 宏观/权益暴露效应：{_pct(attr['macro_equity_exposure_effect'])}；动量选择效应：{_pct(attr['momentum_selection_effect'])}；防御资产贡献：{_pct(attr['defense_asset_contribution'])}；成本：{_pct(attr['cost_effect'])}。",
                f"- 平均宏观分数：{exp['avg_macro_score']:.3f}；平均实际进攻仓位：{_pct(exp['avg_actual_offensive_weight'])}；平均防御仓位：{_pct(exp['avg_defense_weight'])}；risk-off 天数：{exp['risk_off_days']}。",
                f"- 调仓原因：{json.dumps(row['rebalance_reason_counts'], ensure_ascii=False, sort_keys=True)}。",
                "",
                "资产贡献最差：",
                "",
                *[f"- {symbol}: {_pct(value)}" for symbol, value in row["asset_contribution"]["worst"].items()],
                "",
                "资产贡献最好：",
                "",
                *[f"- {symbol}: {_pct(value)}" for symbol, value in row["asset_contribution"]["best"].items()],
                "",
            ]
        )
    lines.extend(
        [
            "## 方法",
            "",
            report["methodology"]["additive_excess_formula"],
            "",
            *[f"- {note}" for note in report["methodology"]["notes"]],
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
