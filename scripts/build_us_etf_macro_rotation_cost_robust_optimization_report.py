#!/usr/bin/env python3
"""Second-stage cost-robust optimization for US ETF macro rotation."""

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
DEFAULT_MARKDOWN = Path("学习资料/量化交易业务闭环/系统评估/US ETF 轮动 成本鲁棒二次优化.md")
STRESS_COST_BPS = (10, 25, 50)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--markdown-path", default=str(DEFAULT_MARKDOWN))
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    report = build_cost_robust_optimization_report(repo_root=root)

    output_root = root / Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "us_etf_macro_rotation_cost_robust_optimization_report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    markdown_path = root / Path(args.markdown_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(json_path), "markdown": str(markdown_path)}, indent=2, sort_keys=True))


def build_cost_robust_optimization_report(*, repo_root: Path) -> dict[str, Any]:
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

    baseline_specs = [
        ExperimentSpec("v1_turnover_guard", "上一轮最优换手约束方案", {"min_hold_months": 3, "turnover_threshold": 0.35}),
        ExperimentSpec(
            "v1_combined_conservative",
            "上一轮组合保守方案",
            {
                "defense_cap_when_spy_trend": 0.65,
                "drawdown_penalty": 1.0,
                "macro_floor": 0.5,
                "macro_floor_requires_spy_trend": True,
                "min_hold_months": 2,
                "reversal_filter_20d": 0.15,
                "risky_asset_cap": 0.25,
                "turnover_threshold": 0.25,
            },
        ),
    ]
    candidate_specs = _second_stage_grid()
    evaluated = [_evaluate_cost_robust(spec, context) for spec in [*baseline_specs, *candidate_specs]]
    ranked = sorted(evaluated, key=lambda item: item["score_50bps"], reverse=True)
    grouped: dict[str, Any] = {}
    for row in evaluated:
        family = row["family"]
        grouped.setdefault(family, []).append(row)
    families = {
        family: {
            "candidate_count": len(rows),
            "best": sorted(rows, key=lambda item: item["score_50bps"], reverse=True)[0],
            "top_candidates": sorted(rows, key=lambda item: item["score_50bps"], reverse=True)[:5],
        }
        for family, rows in grouped.items()
    }
    return {
        "schema_version": "us_etf_macro_rotation_cost_robust_optimization_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "research_only",
        "live_ready": False,
        "paper_ready": False,
        "price_source": str(DEFAULT_EXTERNAL_DATA_LAKE),
        "macro_status": macro_status,
        "macro_path": str(macro_path) if macro_path else None,
        "stress_cost_bps": list(STRESS_COST_BPS),
        "families": families,
        "ranking": ranked,
        "best_overall": ranked[0],
        "methodology": {
            "scope": "Second-stage search around turnover_guard and combined_conservative because those survived 50bps in the prior stress report.",
            "new_controls": ["max_monthly_turnover", "rebalance_blend"],
            "score_50bps": "50bps_sharpe + 50bps_cagr - 0.5*abs(50bps_mdd) - 0.003*turnover + 0.25*mean_focus_excess_50bps",
            "constraint": "Research-only; no paper/live unlock.",
        },
    }


def _second_stage_grid() -> list[ExperimentSpec]:
    specs: list[ExperimentSpec] = []
    for threshold, hold, cap, blend in itertools.product(
        (0.35, 0.45, 0.55),
        (3, 4),
        (0.75, 1.00),
        (1.0, 0.75),
    ):
        specs.append(
            ExperimentSpec(
                "v2_turnover_guard_refined",
                "围绕上一轮 turnover_guard 做更强换手控制。",
                {
                    "turnover_threshold": threshold,
                    "min_hold_months": hold,
                    "max_monthly_turnover": cap,
                    "rebalance_blend": blend,
                },
            )
        )
    for macro_floor, threshold, hold, risky_cap, defense_cap, monthly_cap in itertools.product(
        (0.35, 0.50),
        (0.35,),
        (3,),
        (0.25, 0.30),
        (0.50, 0.65),
        (0.75,),
    ):
        specs.append(
            ExperimentSpec(
                "v2_cost_robust_combined",
                "组合保守版叠加更强换手控制，面向 50bps 成本鲁棒性。",
                {
                    "macro_floor": macro_floor,
                    "macro_floor_requires_spy_trend": True,
                    "turnover_threshold": threshold,
                    "min_hold_months": hold,
                    "risky_asset_cap": risky_cap,
                    "drawdown_penalty": 1.0,
                    "reversal_filter_20d": 0.15,
                    "defense_cap_when_spy_trend": defense_cap,
                    "max_monthly_turnover": monthly_cap,
                },
            )
        )
    return specs


def _evaluate_cost_robust(spec: ExperimentSpec, context: dict[str, Any]) -> dict[str, Any]:
    cfg: UsEtfMacroMomentumRotationConfig = context["cfg"]
    base_params = dict(spec.parameters)
    base_params["cost_per_turnover"] = 0.0
    base_result = _run_experiment(context=context, spec=ExperimentSpec(spec.scheme_id, spec.description, base_params))
    turnover = base_result.daily_weights.diff().abs().sum(axis=1).fillna(0.0)
    gross_returns = (base_result.daily_weights * context["asset_rets"][base_result.daily_weights.columns]).sum(axis=1)
    stress: dict[str, Any] = {}
    for bps in STRESS_COST_BPS:
        daily_returns = gross_returns - turnover * (bps / 10_000.0)
        metrics = performance_summary(daily_returns, context["prices"][cfg.benchmark])
        focus = _focus_years(daily_returns, context["prices"][cfg.benchmark], base_result.daily_weights, cfg)
        stress[f"{bps}bps"] = {
            "metrics": {
                "total_return": float(metrics.get("total_return", 0.0)),
                "cagr": float(metrics.get("cagr", 0.0)),
                "sharpe": float(metrics.get("sharpe", 0.0)),
                "max_drawdown": float(metrics.get("max_drawdown", 0.0)),
                "benchmark_total_return": float(metrics.get("benchmark_total_return", 0.0)),
                "turnover": float(base_result.diagnostics["turnover"]),
                "avg_rebalance_turnover": float(base_result.diagnostics["avg_rebalance_turnover"]),
            },
            "focus_years": focus,
            "diagnostics": {**base_result.diagnostics, "cost_per_turnover": bps / 10_000.0},
        }
    m50 = stress["50bps"]["metrics"]
    focus_excess = [row["excess_return"] for row in stress["50bps"]["focus_years"].values()]
    score = (
        float(m50["sharpe"])
        + float(m50["cagr"])
        - 0.5 * abs(float(m50["max_drawdown"]))
        - 0.003 * float(m50["turnover"])
        + 0.25 * (float(np.mean(focus_excess)) if focus_excess else 0.0)
    )
    return {
        "family": spec.scheme_id,
        "description": spec.description,
        "parameters": spec.parameters,
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
    )


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _markdown(report: dict[str, Any]) -> str:
    best = report["best_overall"]
    m50 = best["stress"]["50bps"]["metrics"]
    lines = [
        "# US ETF 轮动 成本鲁棒二次优化",
        "",
        "## 结论",
        "",
        f"- 二次优化最优：`{best['family']}`，参数 `{json.dumps(best['parameters'], ensure_ascii=False, sort_keys=True)}`。",
        f"- 50bps：CAGR {_pct(m50['cagr'])}；Sharpe {m50['sharpe']:.3f}；MDD {_pct(m50['max_drawdown'])}；Turnover {m50['turnover']:.2f}。",
        "- 这一步只说明成本鲁棒性更强，仍然是 research-only。",
        "",
        "## 家族最优",
        "",
        "| 家族 | 参数 | 10bps CAGR | 25bps CAGR | 50bps CAGR | 50bps Sharpe | 50bps MDD | Turnover |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for family, payload in report["families"].items():
        row = payload["best"]
        s10 = row["stress"]["10bps"]["metrics"]
        s25 = row["stress"]["25bps"]["metrics"]
        s50 = row["stress"]["50bps"]["metrics"]
        lines.append(
            "| "
            + " | ".join(
                [
                    family,
                    f"`{json.dumps(row['parameters'], ensure_ascii=False, sort_keys=True)}`",
                    _pct(s10["cagr"]),
                    _pct(s25["cagr"]),
                    _pct(s50["cagr"]),
                    f"{s50['sharpe']:.3f}",
                    _pct(s50["max_drawdown"]),
                    f"{s50['turnover']:.2f}",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 方法",
            "",
            f"- 范围：{report['methodology']['scope']}",
            f"- 新控制项：{', '.join(report['methodology']['new_controls'])}",
            f"- 评分：{report['methodology']['score_50bps']}",
            f"- 约束：{report['methodology']['constraint']}",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
