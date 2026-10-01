#!/usr/bin/env python3
"""Run turnover-cost stress tests for optimized US ETF rotation variants."""

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
    build_price_matrix_from_bars,
    calculate_rotation_inputs,
    performance_summary,
)
from scripts.build_us_etf_macro_rotation_optimization_report import (  # noqa: E402
    ExperimentSpec,
    _focus_years,
    _run_experiment,
)
from scripts.build_us_etf_macro_rotation_research_report import (  # noqa: E402
    DEFAULT_EXTERNAL_DATA_LAKE,
    _load_external_data_lake_bars,
    _load_macro_data,
)


DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_etf_macro_rotation/latest")
DEFAULT_OPTIMIZATION_REPORT = DEFAULT_OUTPUT_ROOT / "us_etf_macro_rotation_optimization_report.json"
DEFAULT_MARKDOWN = Path("学习资料/量化交易业务闭环/系统评估/US ETF 轮动 成本压力测试.md")
STRESS_COST_BPS = (10, 25, 50)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--optimization-report", default=str(DEFAULT_OPTIMIZATION_REPORT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--markdown-path", default=str(DEFAULT_MARKDOWN))
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    report = build_cost_stress_report(repo_root=root, optimization_report=root / Path(args.optimization_report))

    output_root = root / Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "us_etf_macro_rotation_cost_stress_report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    markdown_path = root / Path(args.markdown_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(json_path), "markdown": str(markdown_path)}, indent=2, sort_keys=True))


def build_cost_stress_report(*, repo_root: Path, optimization_report: Path) -> dict[str, Any]:
    optimization = json.loads(optimization_report.read_text(encoding="utf-8"))
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

    specs = [ExperimentSpec("baseline_current", "当前原始策略", {})]
    for scheme_id, scheme in optimization["schemes"].items():
        best = scheme["best"]
        specs.append(ExperimentSpec(scheme_id, best["description"], dict(best["parameters"])))

    rows: dict[str, Any] = {}
    for spec in specs:
        by_cost: dict[str, Any] = {}
        for bps in STRESS_COST_BPS:
            params = dict(spec.parameters)
            params["cost_per_turnover"] = bps / 10_000.0
            stressed = ExperimentSpec(spec.scheme_id, spec.description, params)
            result = _run_experiment(context=context, spec=stressed)
            metrics = performance_summary(result.daily_returns, prices[cfg.benchmark])
            focus = _focus_years(result.daily_returns, prices[cfg.benchmark], result.daily_weights, cfg)
            by_cost[f"{bps}bps"] = {
                "cost_bps": bps,
                "metrics": {
                    "total_return": float(metrics.get("total_return", 0.0)),
                    "cagr": float(metrics.get("cagr", 0.0)),
                    "sharpe": float(metrics.get("sharpe", 0.0)),
                    "max_drawdown": float(metrics.get("max_drawdown", 0.0)),
                    "benchmark_total_return": float(metrics.get("benchmark_total_return", 0.0)),
                    "turnover": float(result.diagnostics["turnover"]),
                    "cost_drag_estimate": float(result.diagnostics["turnover"]) * (bps / 10_000.0),
                },
                "focus_years": focus,
                "diagnostics": result.diagnostics,
            }
        rows[spec.scheme_id] = {
            "description": spec.description,
            "base_parameters": spec.parameters,
            "stress": by_cost,
            "survives_50bps": _survives_50bps(by_cost["50bps"]),
        }

    ranking_50bps = sorted(
        (
            {
                "scheme_id": scheme_id,
                "cagr": row["stress"]["50bps"]["metrics"]["cagr"],
                "sharpe": row["stress"]["50bps"]["metrics"]["sharpe"],
                "max_drawdown": row["stress"]["50bps"]["metrics"]["max_drawdown"],
                "turnover": row["stress"]["50bps"]["metrics"]["turnover"],
                "survives_50bps": row["survives_50bps"],
            }
            for scheme_id, row in rows.items()
        ),
        key=lambda item: (item["survives_50bps"], item["sharpe"], item["cagr"]),
        reverse=True,
    )
    return {
        "schema_version": "us_etf_macro_rotation_cost_stress_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "research_only",
        "live_ready": False,
        "paper_ready": False,
        "stress_cost_bps": list(STRESS_COST_BPS),
        "source_optimization_report": str(optimization_report),
        "price_source": str(DEFAULT_EXTERNAL_DATA_LAKE),
        "macro_status": macro_status,
        "macro_path": str(macro_path) if macro_path else None,
        "schemes": rows,
        "ranking_50bps": ranking_50bps,
        "best_50bps": ranking_50bps[0],
        "methodology": {
            "cost_model": "strategy_daily_return = gross_weighted_asset_return - turnover * cost_per_turnover",
            "survival_rule": "50bps survives when CAGR > 0, Sharpe > 0, and max drawdown is better than -40%.",
            "note": "This is a research-only stress test. Passing it does not unlock paper or live trading.",
        },
    }


def _survives_50bps(row: dict[str, Any]) -> bool:
    metrics = row["metrics"]
    return (
        float(metrics["cagr"]) > 0.0
        and float(metrics["sharpe"]) > 0.0
        and float(metrics["max_drawdown"]) > -0.40
    )


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# US ETF 轮动 成本压力测试",
        "",
        "## 结论",
        "",
        f"- 50bps 下排名第一：`{report['best_50bps']['scheme_id']}`，CAGR {_pct(report['best_50bps']['cagr'])}，Sharpe {report['best_50bps']['sharpe']:.3f}，MDD {_pct(report['best_50bps']['max_drawdown'])}。",
        "- 成本压力只验证高换手脆弱性，不代表可纸盘或实盘。",
        "",
        "## 成本压力表",
        "",
        "| 方案 | 成本 | CAGR | Sharpe | MDD | Turnover | 成本拖累估算 | 50bps通过 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scheme_id, row in report["schemes"].items():
        for cost_key, stressed in row["stress"].items():
            metrics = stressed["metrics"]
            lines.append(
                "| "
                + " | ".join(
                    [
                        scheme_id,
                        cost_key,
                        _pct(metrics["cagr"]),
                        f"{metrics['sharpe']:.3f}",
                        _pct(metrics["max_drawdown"]),
                        f"{metrics['turnover']:.2f}",
                        _pct(metrics["cost_drag_estimate"]),
                        "是" if row["survives_50bps"] else "否",
                    ]
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## 方法",
            "",
            f"- 成本模型：{report['methodology']['cost_model']}",
            f"- 50bps 生存规则：{report['methodology']['survival_rule']}",
            f"- 说明：{report['methodology']['note']}",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
