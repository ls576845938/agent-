#!/usr/bin/env python3
"""Robustness validation for top1_higher_vol under original ETF rotation semantics."""

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

from quant_us.research.us_etf_macro_momentum_rotation import performance_summary  # noqa: E402
from scripts.build_us_etf_original_semantics_optimization_report import (  # noqa: E402
    _apply_params,
    _load_original_environment,
    _metric_block,
    _run_candidate,
)


DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_etf_macro_rotation/latest")
DEFAULT_MARKDOWN = Path("学习资料/量化交易业务闭环/系统评估/US ETF top1_higher_vol 稳健性验证.md")
PRIMARY_PARAMS = {"TOP_N": 1, "TARGET_VOL": 0.25, "TARGET_VOL_INVERTED": 0.18}
COST_MULTIPLIERS = (0.0, 1.0, 2.0, 3.0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--markdown-path", default=str(DEFAULT_MARKDOWN))
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    report = build_top1_higher_vol_validation_report()

    output_root = root / Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "us_etf_top1_higher_vol_validation_report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    markdown_path = root / Path(args.markdown_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(json_path), "markdown": str(markdown_path)}, indent=2, sort_keys=True))


def build_top1_higher_vol_validation_report() -> dict[str, Any]:
    env = _load_original_environment()
    baseline = _run_with_params(env, {}, "original_v8_2_semantics")
    primary = _run_with_params(env, PRIMARY_PARAMS, "top1_higher_vol")
    years = _yearly_breakdown(primary["returns"], env["prices"], primary["weights"])
    costs = _cost_stress(env, PRIMARY_PARAMS)
    neighborhood = _parameter_neighborhood(env)
    walk_forward = _walk_forward(env)
    decision = _decision(baseline, primary, costs, neighborhood, walk_forward)
    return {
        "schema_version": "us_etf_top1_higher_vol_validation_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "research_only_validation",
        "live_ready": False,
        "paper_ready": False,
        "strategy_id": "top1_higher_vol",
        "baseline_id": "original_v8_2_semantics",
        "rebalance_semantics": "calendar_month_end_only_skip_if_not_trading_day",
        "primary_parameters": PRIMARY_PARAMS,
        "baseline_metrics": baseline["metrics"],
        "primary_metrics": primary["metrics"],
        "yearly_breakdown": years,
        "cost_stress": costs,
        "parameter_neighborhood": neighborhood,
        "walk_forward": walk_forward,
        "decision": decision,
        "methodology": {
            "goal": "Check whether top1_higher_vol survives validation rather than merely fitting the full 2018-2026 sample.",
            "walk_forward": "For each test year from 2021 onward, choose best parameters on all prior available years, then evaluate the next year out of sample.",
            "cost_stress": "Re-run the same strategy at 0x, 1x, 2x, and 3x original cost.",
            "parameter_neighborhood": "TOP_N in {1,2}, TARGET_VOL in {0.20,0.25,0.30}, TARGET_VOL_INVERTED in {0.15,0.18,0.20}.",
            "constraint": "Original skipped-month rebalance semantics are preserved; no paper/live unlock.",
        },
    }


def _run_with_params(env: dict[str, Any], params: dict[str, Any], candidate_id: str, *, cost_multiplier: float = 1.0) -> dict[str, Any]:
    cfg = deepcopy(env["base_cfg"])
    _apply_params(cfg, params)
    cfg.COST_BPS = float(cfg.COST_BPS) * cost_multiplier
    result = _run_candidate(cfg, env)
    signals = env["calculate_signals"](env["prices"], env["macro"], cfg)
    returns, _macro, _exposure, weights = env["run_backtest"](
        env["prices"],
        signals[5],
        signals[0],
        signals[1],
        signals[2],
        signals[3],
        signals[4],
        signals[6],
        cfg,
    )
    return {
        "candidate_id": candidate_id,
        "parameters": params,
        "metrics": result["metrics"],
        "returns": returns.dropna(),
        "weights": weights,
    }


def _yearly_breakdown(returns: pd.Series, prices: pd.DataFrame, weights: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    spy_returns = prices["SPY"].pct_change(fill_method=None).reindex(returns.index).fillna(0.0)
    qqq_returns = prices["QQQ"].pct_change(fill_method=None).reindex(returns.index).fillna(0.0)
    for year, group in returns.groupby(returns.index.year):
        mask = returns.index.year == year
        strategy = _compound(group)
        spy = _compound(spy_returns.loc[mask])
        qqq = _compound(qqq_returns.loc[mask])
        drawdown = _max_drawdown(group)
        rows.append(
            {
                "year": int(year),
                "strategy_return": strategy,
                "SPY_return": spy,
                "QQQ_return": qqq,
                "excess_vs_SPY": strategy - spy,
                "excess_vs_QQQ": strategy - qqq,
                "max_drawdown": drawdown,
                "turnover": float(weights.loc[mask].diff().abs().sum(axis=1).fillna(0.0).sum()),
                "beats_SPY": strategy > spy,
                "beats_QQQ": strategy > qqq,
            }
        )
    return rows


def _cost_stress(env: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for multiplier in COST_MULTIPLIERS:
        row = _run_with_params(env, params, f"top1_higher_vol_cost_{multiplier:g}x", cost_multiplier=multiplier)
        rows[f"{multiplier:g}x"] = {
            "cost_multiplier": multiplier,
            "metrics": row["metrics"],
        }
    return rows


def _parameter_neighborhood(env: dict[str, Any]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for top_n in (1, 2):
        for target_vol in (0.20, 0.25, 0.30):
            for inverted_vol in (0.15, 0.18, 0.20):
                params = {"TOP_N": top_n, "TARGET_VOL": target_vol, "TARGET_VOL_INVERTED": inverted_vol}
                row = _run_with_params(env, params, f"top{top_n}_vol{target_vol:g}_{inverted_vol:g}")
                metrics = row["metrics"]["strategy"]
                candidates.append(
                    {
                        "parameters": params,
                        "metrics": row["metrics"],
                        "alive": metrics["true_cagr"] > 0.08 and metrics["max_drawdown"] > -0.35,
                        "score": metrics["true_cagr"] * 3.0 + metrics["sharpe_no_risk_free"] * 0.25 - abs(metrics["max_drawdown"]) * 0.20,
                    }
                )
    sorted_candidates = sorted(candidates, key=lambda item: item["score"], reverse=True)
    alive = [row for row in candidates if row["alive"]]
    cagr_values = [row["metrics"]["strategy"]["true_cagr"] for row in candidates]
    return {
        "candidate_count": len(candidates),
        "alive_count": len(alive),
        "alive_rate": len(alive) / len(candidates),
        "median_cagr": float(np.median(cagr_values)),
        "best": sorted_candidates[0],
        "top_candidates": sorted_candidates[:10],
        "all_candidates": candidates,
    }


def _walk_forward(env: dict[str, Any]) -> dict[str, Any]:
    base_index = env["prices"].index
    test_years = list(range(2021, int(base_index.max().year) + 1))
    parameter_rows = _parameter_neighborhood(env)["all_candidates"]
    candidate_returns: list[dict[str, Any]] = []
    for row in parameter_rows:
        result = _run_with_params(env, row["parameters"], "wf_candidate")
        candidate_returns.append({**row, "returns": result["returns"], "weights": result["weights"]})
    folds: list[dict[str, Any]] = []
    stitched_returns: list[pd.Series] = []
    stitched_weights: list[pd.DataFrame] = []
    for test_year in test_years:
        train_years = [year for year in range(2018, test_year)]
        train_mask = pd.Series(base_index.year, index=base_index).isin(train_years)
        test_mask = pd.Series(base_index.year, index=base_index).isin([test_year])
        if not bool(train_mask.any()) or not bool(test_mask.any()):
            continue
        selected = max(
            candidate_returns,
            key=lambda row: _period_score(row["returns"].loc[row["returns"].index.year < test_year], env["prices"]),
        )
        test_returns = selected["returns"].loc[selected["returns"].index.year == test_year]
        if test_returns.empty:
            continue
        folds.append(
            {
                "test_year": test_year,
                "train_years": train_years,
                "selected_parameters": selected["parameters"],
                "test_return": _compound(test_returns),
                "test_max_drawdown": _max_drawdown(test_returns),
                "test_metrics": _period_metrics(test_returns, env["prices"]),
            }
        )
        stitched_returns.append(test_returns)
        stitched_weights.append(selected["weights"].loc[selected["weights"].index.year == test_year])
    if stitched_returns:
        combined_returns = pd.concat(stitched_returns).sort_index()
        combined_weights = pd.concat(stitched_weights).sort_index()
        aggregate = {
            "metrics": _period_metrics(combined_returns, env["prices"]),
            "turnover": float(combined_weights.diff().abs().sum(axis=1).fillna(0.0).sum()),
        }
    else:
        aggregate = {"metrics": {}, "turnover": 0.0}
    return {
        "fold_count": len(folds),
        "folds": folds,
        "aggregate_oos": aggregate,
    }


def _period_score(returns: pd.Series, prices: pd.DataFrame) -> float:
    metrics = _period_metrics(returns, prices)["strategy"]
    return metrics["true_cagr"] * 3.0 + metrics["sharpe_no_risk_free"] * 0.25 - abs(metrics["max_drawdown"]) * 0.20


def _period_metrics(returns: pd.Series, prices: pd.DataFrame) -> dict[str, Any]:
    clean = returns.dropna()
    aligned = prices.reindex(clean.index).ffill()
    spy = aligned["SPY"].pct_change(fill_method=None).fillna(0.0)
    qqq = aligned["QQQ"].pct_change(fill_method=None).fillna(0.0)
    return {
        "strategy": _metric_block(clean, aligned["SPY"]),
        "SPY": _metric_block(spy, aligned["SPY"]),
        "QQQ": _metric_block(qqq, aligned["SPY"]),
    }


def _decision(
    baseline: dict[str, Any],
    primary: dict[str, Any],
    costs: dict[str, Any],
    neighborhood: dict[str, Any],
    walk_forward: dict[str, Any],
) -> dict[str, Any]:
    base_cagr = baseline["metrics"]["strategy"]["true_cagr"]
    primary_cagr = primary["metrics"]["strategy"]["true_cagr"]
    oos_cagr = walk_forward["aggregate_oos"]["metrics"].get("strategy", {}).get("true_cagr", 0.0)
    pass_research = (
        primary_cagr > base_cagr
        and neighborhood["alive_rate"] >= 0.60
        and costs["3x"]["metrics"]["strategy"]["true_cagr"] > base_cagr
        and oos_cagr > 0.0
    )
    return {
        "status": "manual_review_candidate" if pass_research else "validation_concerns",
        "live_ready": False,
        "paper_ready": False,
        "primary_improves_baseline": primary_cagr > base_cagr,
        "neighborhood_alive_rate": neighborhood["alive_rate"],
        "oos_cagr": oos_cagr,
        "reason": "Requires manual review because full-sample improvement may still be regime-dependent and does not beat QQQ.",
    }


def _compound(returns: pd.Series) -> float:
    return float((1.0 + returns.fillna(0.0)).prod() - 1.0)


def _max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _markdown(report: dict[str, Any]) -> str:
    primary = report["primary_metrics"]["strategy"]
    baseline = report["baseline_metrics"]["strategy"]
    oos = report["walk_forward"]["aggregate_oos"]["metrics"].get("strategy", {})
    lines = [
        "# US ETF top1_higher_vol 稳健性验证",
        "",
        "## 结论",
        "",
        f"- 状态：`{report['decision']['status']}`。",
        f"- 原始基线 true CAGR：{_pct(baseline['true_cagr'])}；top1_higher_vol true CAGR：{_pct(primary['true_cagr'])}。",
        f"- 参数邻域存活率：{report['parameter_neighborhood']['alive_rate']:.1%}。",
        f"- Walk-forward OOS CAGR：{_pct(oos.get('true_cagr', 0.0))}；MDD：{_pct(oos.get('max_drawdown', 0.0))}。",
        "- 不解锁纸盘或实盘，仍需人工复核年份贡献和参数稳定性。",
        "",
        "## 年度拆解",
        "",
        "| Year | Strategy | SPY | QQQ | Excess vs SPY | MDD | Turnover |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["yearly_breakdown"]:
        lines.append(
            f"| {row['year']} | {_pct(row['strategy_return'])} | {_pct(row['SPY_return'])} | {_pct(row['QQQ_return'])} | {_pct(row['excess_vs_SPY'])} | {_pct(row['max_drawdown'])} | {row['turnover']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## 成本压力",
            "",
            "| Cost | CAGR | Sharpe | MDD | Total Return |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for key, row in report["cost_stress"].items():
        metrics = row["metrics"]["strategy"]
        lines.append(f"| {key} | {_pct(metrics['true_cagr'])} | {metrics['sharpe_no_risk_free']:.3f} | {_pct(metrics['max_drawdown'])} | {_pct(metrics['total_return'])} |")
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
    return "\n".join(lines)


if __name__ == "__main__":
    main()
