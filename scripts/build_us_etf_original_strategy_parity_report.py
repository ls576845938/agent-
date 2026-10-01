#!/usr/bin/env python3
"""Compare the user's original ETF rotation script with the integrated research backtest."""

from __future__ import annotations

import argparse
import contextlib
import io
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
DEFAULT_MARKDOWN = Path("学习资料/量化交易业务闭环/系统评估/US ETF 轮动 原始策略口径差异诊断.md")
ORIGINAL_PROJECT = REPO_ROOT / "legacy_strategies/us_etf_rotation_original"
ORIGINAL_DATA_LAKE = Path("D:/Trading/PythonApplication1/data_cache_lake")
START_DATE = "2018-01-01"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--markdown-path", default=str(DEFAULT_MARKDOWN))
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    report = build_original_strategy_parity_report(repo_root=root)

    output_root = root / Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "us_etf_original_strategy_parity_report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    markdown_path = root / Path(args.markdown_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(json_path), "markdown": str(markdown_path)}, indent=2, sort_keys=True))


def build_original_strategy_parity_report(*, repo_root: Path) -> dict[str, Any]:
    original = _run_original_external_strategy()
    integrated = _run_integrated_strategy(repo_root)
    return {
        "schema_version": "us_etf_original_strategy_parity_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "diagnostic_research_only",
        "live_ready": False,
        "paper_ready": False,
        "canonical_original_baseline": {
            "baseline_id": "original_v8_2_semantics",
            "strategy_family": "us_etf_macro_momentum_rotation",
            "rebalance_semantics": "calendar_month_end_only_skip_if_not_trading_day",
            "metric_basis": "true_cagr_and_arithmetic_annualized_both_reported",
            "eligible_for_direct_comparison_with_integrated_candidates": False,
            "reason": (
                "The original baseline intentionally preserves the source script's skipped-month rebalance behavior; "
                "it must not be ranked against actual-last-trading-day candidates without an explicit semantics label."
            ),
        },
        "original_project": str(ORIGINAL_PROJECT),
        "original_data_lake": str(ORIGINAL_DATA_LAKE),
        "start_date": START_DATE,
        "original_external_v8_2": original,
        "integrated_research_backtest": integrated,
        "diagnosis": {
            "primary_reason": "The original script uses calendar month-end dates and skips months when the calendar month-end is not a trading day; the integrated backtest uses the actual last trading day of every month.",
            "metric_label_issue": "The original analysis labels mean_daily_return*252 as CAGR. This is arithmetic annualized return, not compound annual growth rate.",
            "benchmark_issue": "The original report compares mainly with SPY; the stricter gate also compares with QQQ, which strongly outperformed in the 2018-2026 sample.",
            "data_issue": "Earlier local data had SPY/QQQ quality issues; current reports use repaired external ETF data.",
            "conclusion": "The original strategy can look better than the integrated version under its original rebalance semantics, but on the current 2018-2026 data it still does not beat buy-and-hold SPY or QQQ on CAGR.",
            "next_action": "Use original_v8_2_semantics as the protected baseline for future limited improvements; report all changes against this baseline and against SPY/QQQ separately.",
        },
    }


def _run_original_external_strategy() -> dict[str, Any]:
    if not ORIGINAL_PROJECT.exists():
        return {"status": "missing_original_project"}
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
    signals = calculate_signals(prices, macro, cfg)
    returns, _macro, _exposure, weights = run_backtest(
        prices,
        signals[5],
        signals[0],
        signals[1],
        signals[2],
        signals[3],
        signals[4],
        signals[6],
        cfg,
    )
    calendar_month_ends = prices.resample("ME").last().index
    used_month_ends = [date for date in calendar_month_ends if date in prices.index]
    return {
        "status": "available",
        "metrics": _strategy_and_benchmarks(returns, prices, weights),
        "rebalance_calendar": {
            "calendar_month_end_count": len(calendar_month_ends),
            "used_by_original_count": len(used_month_ends),
            "skipped_month_count": len(calendar_month_ends) - len(used_month_ends),
            "first_skipped_month_ends": [str(date.date()) for date in calendar_month_ends if date not in prices.index][:20],
        },
    }


def _run_integrated_strategy(repo_root: Path) -> dict[str, Any]:
    cfg = UsEtfMacroMomentumRotationConfig()
    bars, available_symbols, _coverage = _load_external_data_lake_bars(DEFAULT_EXTERNAL_DATA_LAKE, cfg.required_symbols())
    missing = sorted(set(cfg.required_symbols()) - set(available_symbols))
    if missing:
        return {"status": "missing_symbols", "missing": missing}
    prices = build_price_matrix_from_bars(bars, cfg.required_symbols())
    macro, _macro_status, _macro_path = _load_macro_data(repo_root, None, external_data_lake=DEFAULT_EXTERNAL_DATA_LAKE)
    inputs = calculate_rotation_inputs(prices, macro, cfg)
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
    result = _run_experiment(
        context=context,
        spec=ExperimentSpec("integrated_v1", "Integrated research backtest", {"cost_per_turnover": cfg.cost_per_turnover}),
    )
    mask = result.daily_returns.index >= pd.Timestamp(START_DATE, tz="UTC")
    return {
        "status": "available",
        "metrics": _strategy_and_benchmarks(result.daily_returns.loc[mask], prices.loc[result.daily_returns.loc[mask].index], result.daily_weights.loc[mask]),
        "rebalance_calendar": {
            "last_trading_month_count": int(prices.loc[mask].groupby([prices.loc[mask].index.year, prices.loc[mask].index.month]).tail(1).shape[0]),
            "semantics": "actual_last_trading_day_each_month",
        },
    }


def _strategy_and_benchmarks(returns: pd.Series, prices: pd.DataFrame, weights: pd.DataFrame) -> dict[str, Any]:
    clean = returns.dropna()
    prices = prices.reindex(clean.index).ffill()
    strategy = _metric_block(clean, prices["SPY"])
    spy_returns = prices["SPY"].pct_change(fill_method=None).fillna(0.0)
    qqq_returns = prices["QQQ"].pct_change(fill_method=None).fillna(0.0)
    return {
        "sample_start": str(clean.index.min().date()),
        "sample_end": str(clean.index.max().date()),
        "rows": int(len(clean)),
        "strategy": strategy,
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


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _markdown(report: dict[str, Any]) -> str:
    original = report["original_external_v8_2"]
    integrated = report["integrated_research_backtest"]
    lines = [
        "# US ETF 轮动 原始策略口径差异诊断",
        "",
        "## 结论",
        "",
        f"- 受控保留的原始基线：`{report['canonical_original_baseline']['baseline_id']}`。",
        f"- 原始 V8.2 口径状态：`{original['status']}`。",
        f"- 集成研究口径状态：`{integrated['status']}`。",
        f"- 主因：{report['diagnosis']['primary_reason']}",
        f"- 指标标签问题：{report['diagnosis']['metric_label_issue']}",
        f"- 结论：{report['diagnosis']['conclusion']}",
        f"- 下一步：{report['diagnosis']['next_action']}",
        "",
    ]
    if original["status"] == "available":
        om = original["metrics"]
        lines.extend(
            [
                "## 原始 V8.2 口径",
                "",
                f"- 策略 true CAGR：{_pct(om['strategy']['true_cagr'])}；原脚本标成 CAGR 的算术年化：{_pct(om['strategy']['arithmetic_annualized_return'])}。",
                f"- 策略 MDD：{_pct(om['strategy']['max_drawdown'])}；Turnover：{om['turnover']:.2f}。",
                f"- SPY true CAGR：{_pct(om['SPY']['true_cagr'])}；QQQ true CAGR：{_pct(om['QQQ']['true_cagr'])}。",
                f"- 自然月末数量：{original['rebalance_calendar']['calendar_month_end_count']}；实际调仓数量：{original['rebalance_calendar']['used_by_original_count']}；跳过月份：{original['rebalance_calendar']['skipped_month_count']}。",
                "",
            ]
        )
    if integrated["status"] == "available":
        im = integrated["metrics"]
        lines.extend(
            [
                "## 集成研究口径",
                "",
                f"- 策略 true CAGR：{_pct(im['strategy']['true_cagr'])}；算术年化：{_pct(im['strategy']['arithmetic_annualized_return'])}。",
                f"- 策略 MDD：{_pct(im['strategy']['max_drawdown'])}；Turnover：{im['turnover']:.2f}。",
                f"- SPY true CAGR：{_pct(im['SPY']['true_cagr'])}；QQQ true CAGR：{_pct(im['QQQ']['true_cagr'])}。",
                f"- 调仓语义：{integrated['rebalance_calendar']['semantics']}。",
                "",
            ]
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
