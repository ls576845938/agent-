#!/usr/bin/env python3
"""Walk-forward and parameter-neighborhood stability for US ETF rotation."""

from __future__ import annotations

import argparse
import itertools
import json
import sys
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
    _run_experiment,
)
from scripts.build_us_etf_macro_rotation_research_report import (  # noqa: E402
    DEFAULT_EXTERNAL_DATA_LAKE,
    _load_external_data_lake_bars,
    _load_macro_data,
)


DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_etf_macro_rotation/latest")
DEFAULT_MARKDOWN = Path("学习资料/量化交易业务闭环/系统评估/US ETF 轮动 Walk-Forward 与参数稳定性.md")
PRIMARY_COST_BPS = 50
STRESS_COST_BPS = (10, 25, 50)
TEST_YEARS = tuple(range(2015, 2026))
TRAIN_YEARS = 5
BASE_PARAMETERS = {
    "max_monthly_turnover": 0.75,
    "min_hold_months": 4,
    "rebalance_blend": 0.75,
    "turnover_threshold": 0.35,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--markdown-path", default=str(DEFAULT_MARKDOWN))
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    report = build_walk_forward_stability_report(repo_root=root)

    output_root = root / Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "us_etf_macro_rotation_walk_forward_stability_report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    markdown_path = root / Path(args.markdown_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(json_path), "markdown": str(markdown_path)}, indent=2, sort_keys=True))


def build_walk_forward_stability_report(*, repo_root: Path) -> dict[str, Any]:
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

    evaluated = [_evaluate_parameters(params, context) for params in _parameter_neighborhood()]
    primary_rows = [row["stress"][f"{PRIMARY_COST_BPS}bps"] for row in evaluated]
    stability = _stability_summary(evaluated, primary_cost_key=f"{PRIMARY_COST_BPS}bps")
    walk_forward = _walk_forward(evaluated, prices[cfg.benchmark])
    base_row = next(row for row in evaluated if row["parameters"] == BASE_PARAMETERS)
    best_full_sample = max(evaluated, key=lambda row: row["stress"][f"{PRIMARY_COST_BPS}bps"]["score"])

    return {
        "schema_version": "us_etf_macro_rotation_walk_forward_stability_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "research_only",
        "live_ready": False,
        "paper_ready": False,
        "price_source": str(DEFAULT_EXTERNAL_DATA_LAKE),
        "macro_status": macro_status,
        "macro_path": str(macro_path) if macro_path else None,
        "primary_cost_bps": PRIMARY_COST_BPS,
        "stress_cost_bps": list(STRESS_COST_BPS),
        "train_years": TRAIN_YEARS,
        "test_years": list(TEST_YEARS),
        "parameter_grid": {
            "candidate_count": len(evaluated),
            "base_parameters": BASE_PARAMETERS,
            "dimensions": {
                "turnover_threshold": [0.35, 0.45, 0.55],
                "min_hold_months": [3, 4, 5],
                "max_monthly_turnover": [0.50, 0.75],
                "rebalance_blend": [0.75, 1.00],
            },
        },
        "stability": stability,
        "walk_forward": walk_forward,
        "base_candidate": _compact_candidate(base_row),
        "best_full_sample": _compact_candidate(best_full_sample),
        "top_full_sample": [_compact_candidate(row) for row in sorted(evaluated, key=lambda row: row["stress"][f"{PRIMARY_COST_BPS}bps"]["score"], reverse=True)[:10]],
        "all_candidates": [_compact_candidate(row) for row in evaluated],
        "methodology": {
            "goal": "Verify that a parameter neighborhood survives; do not rely on a single pretty parameter set.",
            "walk_forward": "For each test year, pick the best parameter on the prior 5 calendar years at 50bps, then evaluate the next calendar year out of sample.",
            "alive_rule": "Alive at 50bps when CAGR > 0, Sharpe > 0, max drawdown > -40%, and total turnover < 140.",
            "score": "sharpe + cagr - 0.5*abs(max_drawdown) - 0.003*turnover",
            "constraint": "Research-only; no paper/live unlock.",
        },
    }


def _parameter_neighborhood() -> list[dict[str, Any]]:
    params: list[dict[str, Any]] = []
    for threshold, hold, monthly_cap, blend in itertools.product(
        (0.35, 0.45, 0.55),
        (3, 4, 5),
        (0.50, 0.75),
        (0.75, 1.00),
    ):
        params.append(
            {
                "turnover_threshold": threshold,
                "min_hold_months": hold,
                "max_monthly_turnover": monthly_cap,
                "rebalance_blend": blend,
            }
        )
    return params


def _evaluate_parameters(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    cfg: UsEtfMacroMomentumRotationConfig = context["cfg"]
    base_params = dict(params)
    base_params["cost_per_turnover"] = 0.0
    result = _run_experiment(
        context=context,
        spec=ExperimentSpec("v2_turnover_guard_neighborhood", "parameter-neighborhood candidate", base_params),
    )
    turnover = result.daily_weights.diff().abs().sum(axis=1).fillna(0.0)
    gross_returns = (result.daily_weights * context["asset_rets"][result.daily_weights.columns]).sum(axis=1)
    stress: dict[str, Any] = {}
    for bps in STRESS_COST_BPS:
        returns = gross_returns - turnover * (bps / 10_000.0)
        metrics = _metrics(returns, context["prices"][cfg.benchmark], turnover)
        stress[f"{bps}bps"] = {
            "metrics": metrics,
            "score": _score(metrics),
            "alive": _alive(metrics),
            "daily_returns": returns,
            "turnover": turnover,
        }
    return {
        "parameters": params,
        "stress": stress,
        "diagnostics": {
            "t_plus_1_execution": bool(result.diagnostics["t_plus_1_execution"]),
            "rebalance_reason_counts": result.diagnostics.get("rebalance_reason_counts", {}),
        },
    }


def _metrics(returns: pd.Series, benchmark_prices: pd.Series, turnover: pd.Series) -> dict[str, Any]:
    summary = performance_summary(returns, benchmark_prices)
    return {
        "total_return": float(summary.get("total_return", 0.0)),
        "cagr": float(summary.get("cagr", 0.0)),
        "sharpe": float(summary.get("sharpe", 0.0)),
        "max_drawdown": float(summary.get("max_drawdown", 0.0)),
        "benchmark_total_return": float(summary.get("benchmark_total_return", 0.0)),
        "turnover": float(turnover.reindex(returns.index).fillna(0.0).sum()),
    }


def _score(metrics: dict[str, Any]) -> float:
    return (
        float(metrics["sharpe"])
        + float(metrics["cagr"])
        - 0.5 * abs(float(metrics["max_drawdown"]))
        - 0.003 * float(metrics["turnover"])
    )


def _alive(metrics: dict[str, Any]) -> bool:
    return (
        float(metrics["cagr"]) > 0.0
        and float(metrics["sharpe"]) > 0.0
        and float(metrics["max_drawdown"]) > -0.40
        and float(metrics["turnover"]) < 140.0
    )


def _stability_summary(evaluated: list[dict[str, Any]], *, primary_cost_key: str) -> dict[str, Any]:
    rows = [row["stress"][primary_cost_key]["metrics"] for row in evaluated]
    alive_count = sum(1 for row in evaluated if row["stress"][primary_cost_key]["alive"])
    return {
        "candidate_count": len(evaluated),
        "alive_count": alive_count,
        "alive_rate": alive_count / max(len(evaluated), 1),
        "median": _distribution(rows, "median"),
        "p25": _distribution(rows, "p25"),
        "p75": _distribution(rows, "p75"),
        "min": _distribution(rows, "min"),
        "max": _distribution(rows, "max"),
        "stable_enough_for_next_research_stage": bool(alive_count / max(len(evaluated), 1) >= 0.60 and _quantile(rows, "sharpe", 0.50) > 0.45),
    }


def _distribution(rows: list[dict[str, Any]], mode: str) -> dict[str, float]:
    q = {"min": 0.0, "p25": 0.25, "median": 0.50, "p75": 0.75, "max": 1.0}[mode]
    return {
        key: _quantile(rows, key, q)
        for key in ("cagr", "sharpe", "max_drawdown", "turnover")
    }


def _quantile(rows: list[dict[str, Any]], key: str, q: float) -> float:
    values = [float(row[key]) for row in rows]
    if q == 0.0:
        return float(min(values))
    if q == 1.0:
        return float(max(values))
    return float(np.quantile(values, q))


def _walk_forward(evaluated: list[dict[str, Any]], benchmark_prices: pd.Series) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    stitched_returns: list[pd.Series] = []
    stitched_turnover: list[pd.Series] = []
    for test_year in TEST_YEARS:
        train_years = tuple(range(test_year - TRAIN_YEARS, test_year))
        train_mask = _year_mask(evaluated[0]["stress"][f"{PRIMARY_COST_BPS}bps"]["daily_returns"].index, train_years)
        test_mask = _year_mask(evaluated[0]["stress"][f"{PRIMARY_COST_BPS}bps"]["daily_returns"].index, (test_year,))
        if not bool(train_mask.any()) or not bool(test_mask.any()):
            continue
        selected = max(
            evaluated,
            key=lambda row: _period_score(
                row["stress"][f"{PRIMARY_COST_BPS}bps"]["daily_returns"].loc[train_mask],
                benchmark_prices.loc[train_mask],
                row["stress"][f"{PRIMARY_COST_BPS}bps"]["turnover"].loc[train_mask],
            ),
        )
        test_returns = selected["stress"][f"{PRIMARY_COST_BPS}bps"]["daily_returns"].loc[test_mask]
        test_turnover = selected["stress"][f"{PRIMARY_COST_BPS}bps"]["turnover"].loc[test_mask]
        test_metrics = _metrics(test_returns, benchmark_prices.loc[test_mask], test_turnover)
        folds.append(
            {
                "train_years": list(train_years),
                "test_year": test_year,
                "selected_parameters": selected["parameters"],
                "test_metrics": test_metrics,
                "test_alive": _alive(test_metrics),
            }
        )
        stitched_returns.append(test_returns)
        stitched_turnover.append(test_turnover)
    if stitched_returns:
        returns = pd.concat(stitched_returns).sort_index()
        turnover = pd.concat(stitched_turnover).sort_index()
        aggregate = _metrics(returns, benchmark_prices.loc[returns.index], turnover)
    else:
        aggregate = {}
    return {
        "fold_count": len(folds),
        "folds": folds,
        "aggregate_oos_metrics": aggregate,
        "oos_alive_rate": sum(1 for fold in folds if fold["test_alive"]) / max(len(folds), 1),
        "stable_enough_for_next_research_stage": bool(aggregate and aggregate["cagr"] > 0 and aggregate["sharpe"] > 0.45 and aggregate["max_drawdown"] > -0.40),
    }


def _period_score(returns: pd.Series, benchmark_prices: pd.Series, turnover: pd.Series) -> float:
    metrics = _metrics(returns, benchmark_prices, turnover)
    return _score(metrics)


def _year_mask(index: pd.Index, years: tuple[int, ...]) -> pd.Series:
    return pd.Series(index.year, index=index).isin(years)


def _compact_candidate(row: dict[str, Any]) -> dict[str, Any]:
    key = f"{PRIMARY_COST_BPS}bps"
    return {
        "parameters": row["parameters"],
        "metrics": row["stress"][key]["metrics"],
        "score": row["stress"][key]["score"],
        "alive": row["stress"][key]["alive"],
        "t_plus_1_execution": row["diagnostics"]["t_plus_1_execution"],
    }


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _markdown(report: dict[str, Any]) -> str:
    stability = report["stability"]
    wf = report["walk_forward"]
    best = report["best_full_sample"]
    base = report["base_candidate"]
    lines = [
        "# US ETF 轮动 Walk-Forward 与参数稳定性",
        "",
        "## 结论",
        "",
        f"- 参数邻域数量：{stability['candidate_count']}；50bps 存活率：{stability['alive_rate']:.1%}。",
        f"- 邻域中位数：CAGR {_pct(stability['median']['cagr'])}；Sharpe {stability['median']['sharpe']:.3f}；MDD {_pct(stability['median']['max_drawdown'])}；Turnover {stability['median']['turnover']:.2f}。",
        f"- Walk-forward OOS：CAGR {_pct(wf['aggregate_oos_metrics']['cagr'])}；总收益 {_pct(wf['aggregate_oos_metrics']['total_return'])}；SPY {_pct(wf['aggregate_oos_metrics']['benchmark_total_return'])}；Sharpe {wf['aggregate_oos_metrics']['sharpe']:.3f}；MDD {_pct(wf['aggregate_oos_metrics']['max_drawdown'])}；存活率 {wf['oos_alive_rate']:.1%}。",
        f"- 当前基准参数 50bps：CAGR {_pct(base['metrics']['cagr'])}；Sharpe {base['metrics']['sharpe']:.3f}；MDD {_pct(base['metrics']['max_drawdown'])}；Turnover {base['metrics']['turnover']:.2f}。",
        f"- 全样本最优参数：`{json.dumps(best['parameters'], ensure_ascii=False, sort_keys=True)}`。",
        "- 结论：这一步只验证参数邻域和 walk-forward 是否站得住，仍然不解锁纸盘或实盘。",
        "",
        "## Walk-Forward Folds",
        "",
        "| Test Year | Selected Params | Return | SPY | Sharpe | MDD | Alive |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for fold in wf["folds"]:
        metrics = fold["test_metrics"]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(fold["test_year"]),
                    f"`{json.dumps(fold['selected_parameters'], ensure_ascii=False, sort_keys=True)}`",
                    _pct(metrics["total_return"]),
                    _pct(metrics["benchmark_total_return"]),
                    f"{metrics['sharpe']:.3f}",
                    _pct(metrics["max_drawdown"]),
                    "是" if fold["test_alive"] else "否",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 方法",
            "",
            f"- {report['methodology']['walk_forward']}",
            f"- 存活规则：{report['methodology']['alive_rule']}",
            f"- 评分：{report['methodology']['score']}",
            f"- 约束：{report['methodology']['constraint']}",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
