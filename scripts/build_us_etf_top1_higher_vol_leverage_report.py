#!/usr/bin/env python3
"""Leverage and volatility-targeting research for top1_higher_vol."""

from __future__ import annotations

import argparse
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

from quant_us.research.us_etf_macro_momentum_rotation import performance_summary  # noqa: E402
from scripts.build_us_etf_original_semantics_optimization_report import (  # noqa: E402
    _load_original_environment,
)
from scripts.build_us_etf_top1_higher_vol_validation_report import (  # noqa: E402
    PRIMARY_PARAMS,
    _run_with_params,
)


DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_etf_macro_rotation/latest")
DEFAULT_MARKDOWN = Path("学习资料/量化交易业务闭环/系统评估/US ETF top1_higher_vol 杠杆与波动目标研究.md")
FINANCING_RATE = 0.045
TRADING_DAYS = 252


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--markdown-path", default=str(DEFAULT_MARKDOWN))
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    report = build_top1_higher_vol_leverage_report()

    output_root = root / Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "us_etf_top1_higher_vol_leverage_report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    markdown_path = root / Path(args.markdown_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(json_path), "markdown": str(markdown_path)}, indent=2, sort_keys=True))


def build_top1_higher_vol_leverage_report() -> dict[str, Any]:
    env = _load_original_environment()
    base = _run_with_params(env, PRIMARY_PARAMS, "top1_higher_vol")
    returns = base["returns"].copy()
    prices = env["prices"].reindex(returns.index).ffill()
    benchmark_returns = {
        "SPY": prices["SPY"].pct_change(fill_method=None).fillna(0.0),
        "QQQ": prices["QQQ"].pct_change(fill_method=None).fillna(0.0),
    }
    variants = _evaluate_variants(returns, benchmark_returns)
    ranked = sorted(variants, key=lambda row: _score(row), reverse=True)
    return {
        "schema_version": "us_etf_top1_higher_vol_leverage_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "research_only_no_live_or_paper",
        "live_ready": False,
        "paper_ready": False,
        "strategy_id": "top1_higher_vol",
        "primary_parameters": PRIMARY_PARAMS,
        "financing_rate": FINANCING_RATE,
        "leverage_model": "portfolio_return_overlay_no_asset_selection_changes",
        "asset_selection_bias_guard": "No QQQ/sector/technology preference was added; leverage is applied only to the strategy return stream.",
        "benchmarks": {
            key: _metrics(value, benchmark_returns["SPY"])
            for key, value in benchmark_returns.items()
        },
        "base_unlevered": _variant("base_unlevered", returns, pd.Series(1.0, index=returns.index), benchmark_returns),
        "ranking": ranked,
        "variants": variants,
        "decision": _decision(ranked),
        "methodology": {
            "fixed_leverage": "Test 1.2x, 1.5x, and 2.0x overlays with financing cost above 1x exposure.",
            "vol_target": "Use rolling 63-day realized volatility with target vol 15%, 20%, and 25%, capped at max leverage.",
            "drawdown_deleveraging": "When strategy equity drawdown exceeds 10%, halve leverage until recovery.",
            "constraint": "Research only; leveraged variants require financing, margin, and manual risk review before any paper/live consideration.",
        },
    }


def _evaluate_variants(returns: pd.Series, benchmarks: dict[str, pd.Series]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for leverage in (1.2, 1.5, 2.0):
        exposure = pd.Series(leverage, index=returns.index)
        rows.append(_variant(f"fixed_{leverage:g}x", returns, exposure, benchmarks))
        rows.append(
            _variant(
                f"fixed_{leverage:g}x_dd_delever",
                returns,
                _drawdown_deleveraged_exposure(returns, base_leverage=leverage, drawdown_threshold=0.10, cut=0.50),
                benchmarks,
            )
        )
    for target_vol in (0.15, 0.20, 0.25):
        for max_lev in (1.5, 2.0):
            exposure = _vol_target_exposure(returns, target_vol=target_vol, max_leverage=max_lev)
            rows.append(_variant(f"vol_target_{int(target_vol*100)}pct_cap{max_lev:g}x", returns, exposure, benchmarks))
            rows.append(
                _variant(
                    f"vol_target_{int(target_vol*100)}pct_cap{max_lev:g}x_dd_delever",
                    returns,
                    _drawdown_deleveraged_exposure(returns, base_exposure=exposure, drawdown_threshold=0.10, cut=0.50),
                    benchmarks,
                )
            )
    return rows


def _variant(
    variant_id: str,
    returns: pd.Series,
    exposure: pd.Series,
    benchmarks: dict[str, pd.Series],
) -> dict[str, Any]:
    exposure = exposure.reindex(returns.index).ffill().fillna(1.0).clip(lower=0.0)
    financing = (exposure - 1.0).clip(lower=0.0) * (FINANCING_RATE / TRADING_DAYS)
    levered_returns = returns * exposure.shift(1).fillna(exposure.iloc[0]) - financing
    metrics = _metrics(levered_returns, benchmarks["SPY"])
    spy = _metrics(benchmarks["SPY"].reindex(levered_returns.index).fillna(0.0), benchmarks["SPY"])
    qqq = _metrics(benchmarks["QQQ"].reindex(levered_returns.index).fillna(0.0), benchmarks["SPY"])
    return {
        "variant_id": variant_id,
        "metrics": metrics,
        "exposure": {
            "average": float(exposure.mean()),
            "max": float(exposure.max()),
            "min": float(exposure.min()),
            "days_above_1x": int((exposure > 1.0).sum()),
        },
        "financing_cost_total_return_drag": float((1.0 + financing).prod() - 1.0),
        "beats_SPY_cagr": metrics["true_cagr"] > spy["true_cagr"],
        "beats_QQQ_cagr": metrics["true_cagr"] > qqq["true_cagr"],
        "beats_QQQ_with_lower_drawdown": metrics["true_cagr"] > qqq["true_cagr"] and metrics["max_drawdown"] > qqq["max_drawdown"],
        "excess_vs_SPY": _excess(metrics, spy),
        "excess_vs_QQQ": _excess(metrics, qqq),
    }


def _vol_target_exposure(returns: pd.Series, *, target_vol: float, max_leverage: float) -> pd.Series:
    realized = returns.rolling(63).std() * np.sqrt(TRADING_DAYS)
    exposure = target_vol / realized.replace(0.0, np.nan)
    return exposure.clip(lower=0.0, upper=max_leverage).fillna(1.0)


def _drawdown_deleveraged_exposure(
    returns: pd.Series,
    *,
    base_leverage: float | None = None,
    base_exposure: pd.Series | None = None,
    drawdown_threshold: float,
    cut: float,
) -> pd.Series:
    if base_exposure is None:
        exposure = pd.Series(float(base_leverage or 1.0), index=returns.index)
    else:
        exposure = base_exposure.reindex(returns.index).ffill().fillna(1.0).copy()
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    exposure.loc[drawdown <= -abs(drawdown_threshold)] *= cut
    return exposure


def _metrics(returns: pd.Series, benchmark_prices_or_returns: pd.Series) -> dict[str, float]:
    if (benchmark_prices_or_returns <= 0).any():
        benchmark_prices = (1.0 + benchmark_prices_or_returns.fillna(0.0)).cumprod()
    else:
        benchmark_prices = benchmark_prices_or_returns
    summary = performance_summary(returns, benchmark_prices)
    arithmetic_annualized = float(returns.mean() * TRADING_DAYS)
    annual_vol = float(returns.std(ddof=0) * np.sqrt(TRADING_DAYS))
    calmar = float(summary.get("cagr", 0.0)) / abs(float(summary.get("max_drawdown", 0.0))) if summary.get("max_drawdown", 0.0) else 0.0
    return {
        "true_cagr": float(summary.get("cagr", 0.0)),
        "arithmetic_annualized_return": arithmetic_annualized,
        "annualized_volatility": annual_vol,
        "sharpe_no_risk_free": float(arithmetic_annualized / annual_vol) if annual_vol > 0 else 0.0,
        "max_drawdown": float(summary.get("max_drawdown", 0.0)),
        "calmar": calmar,
        "total_return": float(summary.get("total_return", 0.0)),
    }


def _excess(metrics: dict[str, float], benchmark: dict[str, float]) -> dict[str, float]:
    return {
        "true_cagr": metrics["true_cagr"] - benchmark["true_cagr"],
        "max_drawdown_improvement": metrics["max_drawdown"] - benchmark["max_drawdown"],
        "sharpe": metrics["sharpe_no_risk_free"] - benchmark["sharpe_no_risk_free"],
    }


def _score(row: dict[str, Any]) -> float:
    metrics = row["metrics"]
    return (
        metrics["true_cagr"] * 3.0
        + metrics["sharpe_no_risk_free"] * 0.20
        + metrics["calmar"] * 0.15
        - abs(metrics["max_drawdown"]) * 0.10
    )


def _decision(ranked: list[dict[str, Any]]) -> dict[str, Any]:
    best = ranked[0]
    qqq_beaters = [row for row in ranked if row["beats_QQQ_with_lower_drawdown"]]
    if qqq_beaters:
        status = "leveraged_candidate_manual_review_required"
    elif best["beats_QQQ_cagr"]:
        status = "beats_qqq_cagr_but_risk_review_required"
    elif best["beats_SPY_cagr"]:
        status = "beats_spy_not_qqq_manual_review"
    else:
        status = "no_leveraged_variant_clears_benchmark"
    return {
        "status": status,
        "live_ready": False,
        "paper_ready": False,
        "best_variant_id": best["variant_id"],
        "qqq_beater_count": len(qqq_beaters),
        "reason": "Leverage is a research overlay only; financing, margin, gap risk, and behavior under stress require manual review.",
    }


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _markdown(report: dict[str, Any]) -> str:
    best = report["ranking"][0]
    base = report["base_unlevered"]
    lines = [
        "# US ETF top1_higher_vol 杠杆与波动目标研究",
        "",
        "## 结论",
        "",
        f"- 状态：`{report['decision']['status']}`。",
        f"- 未杠杆 true CAGR：{_pct(base['metrics']['true_cagr'])}，MDD：{_pct(base['metrics']['max_drawdown'])}。",
        f"- 最优杠杆/波动目标变体：`{best['variant_id']}`，CAGR {_pct(best['metrics']['true_cagr'])}，MDD {_pct(best['metrics']['max_drawdown'])}，Sharpe {best['metrics']['sharpe_no_risk_free']:.3f}。",
        f"- QQQ CAGR：{_pct(report['benchmarks']['QQQ']['true_cagr'])}，MDD：{_pct(report['benchmarks']['QQQ']['max_drawdown'])}。",
        "- 本报告不改变资产选择规则，不给 QQQ 或科技资产特权，只在组合收益层面研究杠杆。",
        "",
        "## 排名",
        "",
        "| Rank | Variant | CAGR | Vol | Sharpe | MDD | Calmar | Avg Lev | Max Lev | Beats QQQ Lower DD |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, row in enumerate(report["ranking"], start=1):
        metrics = row["metrics"]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(rank),
                    row["variant_id"],
                    _pct(metrics["true_cagr"]),
                    _pct(metrics["annualized_volatility"]),
                    f"{metrics['sharpe_no_risk_free']:.3f}",
                    _pct(metrics["max_drawdown"]),
                    f"{metrics['calmar']:.3f}",
                    f"{row['exposure']['average']:.2f}",
                    f"{row['exposure']['max']:.2f}",
                    "yes" if row["beats_QQQ_with_lower_drawdown"] else "no",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 方法",
            "",
            f"- 融资成本：{report['financing_rate']:.2%}/年，仅对超过 1x 的暴露扣除。",
            f"- 约束：{report['methodology']['constraint']}",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
