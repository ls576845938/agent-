#!/usr/bin/env python3
"""Limited optimization under the user's original ETF rotation rebalance semantics."""

from __future__ import annotations

import argparse
import contextlib
import io
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
from scripts.build_us_etf_original_strategy_parity_report import (  # noqa: E402
    ORIGINAL_DATA_LAKE,
    ORIGINAL_PROJECT,
)


DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_etf_macro_rotation/latest")
DEFAULT_MARKDOWN = Path("学习资料/量化交易业务闭环/系统评估/US ETF 轮动 原始语义有限优化.md")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--markdown-path", default=str(DEFAULT_MARKDOWN))
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    report = build_original_semantics_optimization_report()

    output_root = root / Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "us_etf_original_semantics_optimization_report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    markdown_path = root / Path(args.markdown_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(json_path), "markdown": str(markdown_path)}, indent=2, sort_keys=True))


def build_original_semantics_optimization_report() -> dict[str, Any]:
    env = _load_original_environment()
    candidates = []
    for spec in _candidate_specs():
        cfg = _clone_config(env["base_cfg"])
        _apply_params(cfg, spec["parameters"])
        result = _run_candidate(cfg, env)
        candidates.append({**spec, **result})
    ranked_by_value = sorted(candidates, key=_value_score, reverse=True)
    ranked_by_cagr = sorted(candidates, key=lambda row: row["metrics"]["strategy"]["true_cagr"], reverse=True)
    baseline = next(row for row in candidates if row["candidate_id"] == "original_v8_2_semantics")
    best_value = ranked_by_value[0]
    best_cagr = ranked_by_cagr[0]
    return {
        "schema_version": "us_etf_original_semantics_optimization_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "research_only_original_semantics",
        "live_ready": False,
        "paper_ready": False,
        "baseline_id": "original_v8_2_semantics",
        "rebalance_semantics": "calendar_month_end_only_skip_if_not_trading_day",
        "data_lake": str(ORIGINAL_DATA_LAKE),
        "candidate_count": len(candidates),
        "baseline": baseline,
        "best_value_candidate": best_value,
        "highest_cagr_candidate": best_cagr,
        "ranking": ranked_by_value,
        "all_candidates": candidates,
        "benchmarks": {
            "SPY": baseline["metrics"]["SPY"],
            "QQQ": baseline["metrics"]["QQQ"],
        },
        "decision": _decision(baseline, best_value, best_cagr),
        "methodology": {
            "goal": "Try limited parameter improvements without changing the user's original rebalance semantics.",
            "allowed_changes": ["TOP_N", "TARGET_VOL", "TARGET_VOL_INVERTED", "MOM_WEIGHTS", "MACRO_MODE"],
            "forbidden_changes": ["rebalance semantics", "benchmark data", "cost model", "lookahead behavior", "live/paper unlock"],
            "score": "true_cagr improvement vs original + drawdown control + Sharpe, with SPY/QQQ shown separately.",
        },
    }


def _load_original_environment() -> dict[str, Any]:
    if not ORIGINAL_PROJECT.exists():
        raise SystemExit(f"missing original project: {ORIGINAL_PROJECT}")
    sys.path.insert(0, str(ORIGINAL_PROJECT))
    from 配置参数 import Config  # type: ignore  # noqa: PLC0415
    from 数据拼接 import build_macro_matrix, build_price_matrix  # type: ignore  # noqa: PLC0415
    from 策略逻辑 import calculate_signals, run_backtest  # type: ignore  # noqa: PLC0415
    from 量化引擎 import QuantDataStore  # type: ignore  # noqa: PLC0415

    cfg = Config()
    cfg.DB_DIR = str(ORIGINAL_DATA_LAKE)
    store = QuantDataStore(base_dir=cfg.DB_DIR)
    with contextlib.redirect_stdout(io.StringIO()):
        prices = build_price_matrix(store, cfg.UNIQUE_ASSETS, cfg.START_DATE)
        macro = build_macro_matrix(store, cfg.START_DATE)
    return {
        "base_cfg": cfg,
        "prices": prices,
        "macro": macro,
        "calculate_signals": calculate_signals,
        "run_backtest": run_backtest,
    }


def _clone_config(cfg: Any) -> Any:
    cloned = deepcopy(cfg)
    cloned.DB_DIR = str(ORIGINAL_DATA_LAKE)
    return cloned


def _candidate_specs() -> list[dict[str, Any]]:
    return [
        {"candidate_id": "original_v8_2_semantics", "description": "Original V8.2 parameters and original skipped-month rebalance semantics.", "parameters": {}},
        {"candidate_id": "top1_concentrated", "description": "Hold only the strongest offensive ETF when signal is active.", "parameters": {"TOP_N": 1}},
        {"candidate_id": "top3_diversified", "description": "Hold three offensive ETFs to reduce single-selection error.", "parameters": {"TOP_N": 3}},
        {"candidate_id": "higher_target_vol_25", "description": "Raise target volatility moderately to reduce defensive drag.", "parameters": {"TARGET_VOL": 0.25, "TARGET_VOL_INVERTED": 0.18}},
        {"candidate_id": "higher_target_vol_30", "description": "Raise target volatility aggressively to test whether upside capture improves.", "parameters": {"TARGET_VOL": 0.30, "TARGET_VOL_INVERTED": 0.20}},
        {"candidate_id": "long_horizon_momentum", "description": "Emphasize 6-12 month momentum more heavily.", "parameters": {"MOM_WEIGHTS": [0.05, 0.15, 0.30, 0.50]}},
        {"candidate_id": "medium_horizon_momentum", "description": "Emphasize 3-6 month momentum and reduce 1-year lag.", "parameters": {"MOM_WEIGHTS": [0.10, 0.35, 0.35, 0.20]}},
        {"candidate_id": "step_macro_gate", "description": "Use original STEP macro gate instead of continuous scaling.", "parameters": {"MACRO_MODE": "STEP", "MACRO_THRESHOLD": 0.4}},
        {"candidate_id": "top1_higher_vol", "description": "Combine concentration with moderately higher target volatility.", "parameters": {"TOP_N": 1, "TARGET_VOL": 0.25, "TARGET_VOL_INVERTED": 0.18}},
        {"candidate_id": "top3_higher_vol", "description": "Combine diversification with moderately higher target volatility.", "parameters": {"TOP_N": 3, "TARGET_VOL": 0.25, "TARGET_VOL_INVERTED": 0.18}},
    ]


def _apply_params(cfg: Any, params: dict[str, Any]) -> None:
    for key, value in params.items():
        setattr(cfg, key, value)


def _run_candidate(cfg: Any, env: dict[str, Any]) -> dict[str, Any]:
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
    metrics = _strategy_and_benchmarks(returns, env["prices"], weights)
    return {
        "metrics": metrics,
        "excess_vs_original": {},
        "beats_spy_cagr": metrics["strategy"]["true_cagr"] > metrics["SPY"]["true_cagr"],
        "beats_qqq_cagr": metrics["strategy"]["true_cagr"] > metrics["QQQ"]["true_cagr"],
    }


def _strategy_and_benchmarks(returns: pd.Series, prices: pd.DataFrame, weights: pd.DataFrame) -> dict[str, Any]:
    clean = returns.dropna()
    prices = prices.reindex(clean.index).ffill()
    spy_returns = prices["SPY"].pct_change(fill_method=None).fillna(0.0)
    qqq_returns = prices["QQQ"].pct_change(fill_method=None).fillna(0.0)
    return {
        "sample_start": str(clean.index.min().date()),
        "sample_end": str(clean.index.max().date()),
        "rows": int(len(clean)),
        "strategy": _metric_block(clean, prices["SPY"]),
        "SPY": _metric_block(spy_returns, prices["SPY"]),
        "QQQ": _metric_block(qqq_returns, prices["SPY"]),
        "turnover": float(weights.diff().abs().sum(axis=1).fillna(0.0).sum()),
    }


def _metric_block(returns: pd.Series, benchmark_prices: pd.Series) -> dict[str, float]:
    summary = performance_summary(returns, benchmark_prices)
    arithmetic_annualized = float(returns.mean() * 252)
    annual_vol = float(returns.std(ddof=0) * np.sqrt(252))
    return {
        "true_cagr": float(summary.get("cagr", 0.0)),
        "arithmetic_annualized_return": arithmetic_annualized,
        "sharpe_no_risk_free": float(arithmetic_annualized / annual_vol) if annual_vol > 0 else 0.0,
        "max_drawdown": float(summary.get("max_drawdown", 0.0)),
        "total_return": float(summary.get("total_return", 0.0)),
    }


def _value_score(row: dict[str, Any]) -> float:
    metrics = row["metrics"]["strategy"]
    return (
        float(metrics["true_cagr"]) * 3.0
        + float(metrics["sharpe_no_risk_free"]) * 0.25
        - abs(float(metrics["max_drawdown"])) * 0.20
    )


def _decision(baseline: dict[str, Any], best_value: dict[str, Any], best_cagr: dict[str, Any]) -> dict[str, Any]:
    base_cagr = baseline["metrics"]["strategy"]["true_cagr"]
    best_cagr_value = best_cagr["metrics"]["strategy"]["true_cagr"]
    materially_improved = best_cagr_value >= base_cagr + 0.015
    if best_cagr["beats_spy_cagr"] or best_cagr["beats_qqq_cagr"]:
        status = "offensive_candidate_for_manual_review"
    elif materially_improved:
        status = "improved_vs_original_but_not_buy_hold_replacement"
    else:
        status = "no_material_improvement_vs_original"
    return {
        "status": status,
        "live_ready": False,
        "paper_ready": False,
        "best_value_candidate_id": best_value["candidate_id"],
        "highest_cagr_candidate_id": best_cagr["candidate_id"],
        "highest_cagr_improvement_vs_original": best_cagr_value - base_cagr,
        "reason": "No candidate may proceed unless it improves the protected original baseline and is separately judged against SPY/QQQ.",
    }


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _markdown(report: dict[str, Any]) -> str:
    baseline = report["baseline"]
    best = report["best_value_candidate"]
    high = report["highest_cagr_candidate"]
    lines = [
        "# US ETF 轮动 原始语义有限优化",
        "",
        "## 结论",
        "",
        f"- 决策：`{report['decision']['status']}`。",
        f"- 受保护基线：`{report['baseline_id']}`，调仓语义 `{report['rebalance_semantics']}`。",
        f"- 原始基线 true CAGR：{_pct(baseline['metrics']['strategy']['true_cagr'])}，MDD：{_pct(baseline['metrics']['strategy']['max_drawdown'])}。",
        f"- 最高 CAGR 候选：`{high['candidate_id']}`，true CAGR {_pct(high['metrics']['strategy']['true_cagr'])}，MDD {_pct(high['metrics']['strategy']['max_drawdown'])}。",
        f"- 价值评分第一：`{best['candidate_id']}`，true CAGR {_pct(best['metrics']['strategy']['true_cagr'])}，MDD {_pct(best['metrics']['strategy']['max_drawdown'])}。",
        f"- 同期 SPY true CAGR：{_pct(report['benchmarks']['SPY']['true_cagr'])}；QQQ true CAGR：{_pct(report['benchmarks']['QQQ']['true_cagr'])}。",
        "",
        "## 候选排名",
        "",
        "| Rank | Candidate | true CAGR | Arithmetic Ann. | Sharpe | MDD | Turnover | Beats SPY | Beats QQQ |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, row in enumerate(report["ranking"], start=1):
        metrics = row["metrics"]["strategy"]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(rank),
                    row["candidate_id"],
                    _pct(metrics["true_cagr"]),
                    _pct(metrics["arithmetic_annualized_return"]),
                    f"{metrics['sharpe_no_risk_free']:.3f}",
                    _pct(metrics["max_drawdown"]),
                    f"{row['metrics']['turnover']:.2f}",
                    "yes" if row["beats_spy_cagr"] else "no",
                    "yes" if row["beats_qqq_cagr"] else "no",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 方法",
            "",
            f"- 允许改动：{', '.join(report['methodology']['allowed_changes'])}。",
            f"- 禁止改动：{', '.join(report['methodology']['forbidden_changes'])}。",
            "- 本报告只做研究，不解锁纸盘或实盘。",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
