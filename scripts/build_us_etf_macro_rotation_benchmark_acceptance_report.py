#!/usr/bin/env python3
"""Benchmark acceptance gate for US ETF macro rotation candidates."""

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
    performance_summary,
)
from scripts.build_us_etf_macro_rotation_research_report import (  # noqa: E402
    DEFAULT_EXTERNAL_DATA_LAKE,
    _load_external_data_lake_bars,
)


DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_etf_macro_rotation/latest")
DEFAULT_SOURCE_REPORT = DEFAULT_OUTPUT_ROOT / "us_etf_macro_rotation_book_inspired_optimization_report.json"
DEFAULT_ORIGINAL_PARITY_REPORT = DEFAULT_OUTPUT_ROOT / "us_etf_original_strategy_parity_report.json"
DEFAULT_MARKDOWN = Path("学习资料/量化交易业务闭环/系统评估/US ETF 轮动 基准替代价值评估.md")
PRIMARY_COST_KEY = "50bps"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-report", default=str(DEFAULT_SOURCE_REPORT))
    parser.add_argument("--original-parity-report", default=str(DEFAULT_ORIGINAL_PARITY_REPORT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--markdown-path", default=str(DEFAULT_MARKDOWN))
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    report = build_benchmark_acceptance_report(
        repo_root=root,
        source_report=root / Path(args.source_report),
        original_parity_report=root / Path(args.original_parity_report),
    )

    output_root = root / Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "us_etf_macro_rotation_benchmark_acceptance_report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    markdown_path = root / Path(args.markdown_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(json_path), "markdown": str(markdown_path)}, indent=2, sort_keys=True))


def build_benchmark_acceptance_report(*, repo_root: Path, source_report: Path, original_parity_report: Path | None = None) -> dict[str, Any]:
    source = json.loads(source_report.read_text(encoding="utf-8"))
    cfg = UsEtfMacroMomentumRotationConfig()
    bars, available_symbols, _coverage = _load_external_data_lake_bars(DEFAULT_EXTERNAL_DATA_LAKE, cfg.required_symbols())
    missing = sorted(set(cfg.required_symbols()) - set(available_symbols))
    if missing:
        raise SystemExit(f"missing external ETF symbols: {missing}")
    prices = build_price_matrix_from_bars(bars, cfg.required_symbols())
    benchmark_returns = _benchmark_returns(prices, cfg)
    benchmarks = {
        benchmark_id: _metrics(returns, prices[cfg.benchmark])
        for benchmark_id, returns in benchmark_returns.items()
    }
    evaluated = [_acceptance_row(row, benchmarks) for row in source["ranking"]]
    ranked_offensive = sorted(evaluated, key=lambda row: row["offensive_score"], reverse=True)
    ranked_defensive = sorted(evaluated, key=lambda row: row["defensive_score"], reverse=True)
    summary = _summary(evaluated)
    protected_original = _protected_original_baseline(original_parity_report)
    return {
        "schema_version": "us_etf_macro_rotation_benchmark_acceptance_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "research_only",
        "live_ready": False,
        "paper_ready": False,
        "source_report": str(source_report),
        "source_schema_version": source.get("schema_version"),
        "protected_original_baseline": protected_original,
        "primary_cost_key": PRIMARY_COST_KEY,
        "benchmarks": benchmarks,
        "acceptance_rules": _acceptance_rules(),
        "summary": summary,
        "best_offensive_candidate": ranked_offensive[0],
        "best_defensive_candidate": ranked_defensive[0],
        "candidates": evaluated,
        "ranking": {
            "offensive": ranked_offensive,
            "defensive": ranked_defensive,
        },
        "decision": _decision(summary),
        "methodology": {
            "goal": "Decide whether any ETF rotation candidate deserves to replace buy-and-hold SPY/QQQ, or should only be treated as a defensive allocation candidate.",
            "constraint": "Research-only; this gate does not unlock paper/live trading.",
            "original_semantics_boundary": "original_v8_2_semantics is reported as a protected baseline but not mixed into rankings because it uses skipped calendar-month-end rebalance semantics.",
            "benchmark_set": ["SPY", "QQQ", "60_40_SPY_IEF", "equal_offensive_etf"],
        },
    }


def _protected_original_baseline(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"status": "missing", "included_in_candidate_ranking": False}
    payload = json.loads(path.read_text(encoding="utf-8"))
    baseline = payload.get("canonical_original_baseline", {})
    original = payload.get("original_external_v8_2", {})
    metrics = original.get("metrics", {})
    strategy = metrics.get("strategy", {})
    spy = metrics.get("SPY", {})
    qqq = metrics.get("QQQ", {})
    return {
        "status": "available",
        "baseline_id": baseline.get("baseline_id", "original_v8_2_semantics"),
        "included_in_candidate_ranking": False,
        "rebalance_semantics": baseline.get("rebalance_semantics"),
        "metrics": {
            "strategy_true_cagr": strategy.get("true_cagr"),
            "strategy_arithmetic_annualized_return": strategy.get("arithmetic_annualized_return"),
            "strategy_max_drawdown": strategy.get("max_drawdown"),
            "strategy_total_return": strategy.get("total_return"),
            "SPY_true_cagr": spy.get("true_cagr"),
            "QQQ_true_cagr": qqq.get("true_cagr"),
            "turnover": metrics.get("turnover"),
        },
        "decision": "protected_baseline_for_future_original_semantics_improvements",
    }


def _benchmark_returns(prices: pd.DataFrame, cfg: UsEtfMacroMomentumRotationConfig) -> dict[str, pd.Series]:
    returns = prices.pct_change(fill_method=None).fillna(0.0)
    return {
        "SPY": returns["SPY"],
        "QQQ": returns["QQQ"],
        "60_40_SPY_IEF": returns["SPY"] * 0.60 + returns["IEF"] * 0.40,
        "equal_offensive_etf": returns[list(cfg.offensive_assets)].mean(axis=1),
    }


def _metrics(returns: pd.Series, benchmark_prices: pd.Series) -> dict[str, Any]:
    summary = performance_summary(returns, benchmark_prices)
    return {
        "total_return": float(summary.get("total_return", 0.0)),
        "cagr": float(summary.get("cagr", 0.0)),
        "sharpe": float(summary.get("sharpe", 0.0)),
        "max_drawdown": float(summary.get("max_drawdown", 0.0)),
    }


def _acceptance_row(candidate: dict[str, Any], benchmarks: dict[str, Any]) -> dict[str, Any]:
    metrics = candidate["stress"][PRIMARY_COST_KEY]["metrics"]
    spy = benchmarks["SPY"]
    qqq = benchmarks["QQQ"]
    equal = benchmarks["equal_offensive_etf"]
    best_growth_cagr = max(float(spy["cagr"]), float(qqq["cagr"]))
    best_growth_sharpe = max(float(spy["sharpe"]), float(qqq["sharpe"]))

    offensive_pass = (
        float(metrics["cagr"]) > best_growth_cagr
        and float(metrics["sharpe"]) >= best_growth_sharpe
        and float(metrics["max_drawdown"]) >= min(float(spy["max_drawdown"]), float(qqq["max_drawdown"]))
    )
    defensive_pass = (
        float(metrics["cagr"]) >= float(spy["cagr"]) * 0.75
        and float(metrics["sharpe"]) > float(spy["sharpe"])
        and float(metrics["max_drawdown"]) > float(spy["max_drawdown"]) * 0.65
        and float(metrics["max_drawdown"]) > float(qqq["max_drawdown"]) * 0.50
    )
    equal_pool_pass = (
        float(metrics["cagr"]) > float(equal["cagr"])
        and float(metrics["sharpe"]) > float(equal["sharpe"])
    )
    if offensive_pass:
        gate_status = "offensive_replacement_pass"
    elif defensive_pass:
        gate_status = "defensive_candidate_only"
    else:
        gate_status = "rejected_vs_buy_hold"
    offensive_score = (
        (float(metrics["cagr"]) - best_growth_cagr) * 4.0
        + (float(metrics["sharpe"]) - best_growth_sharpe)
        + (float(metrics["max_drawdown"]) - min(float(spy["max_drawdown"]), float(qqq["max_drawdown"]))) * 0.25
    )
    defensive_score = (
        (float(metrics["sharpe"]) - float(spy["sharpe"]))
        + (float(metrics["max_drawdown"]) - float(spy["max_drawdown"])) * 0.75
        + (float(metrics["cagr"]) - float(spy["cagr"])) * 2.0
    )
    return {
        "family": candidate["family"],
        "parameters": candidate["parameters"],
        "metrics_50bps": metrics,
        "gate_status": gate_status,
        "offensive_replacement_pass": offensive_pass,
        "defensive_candidate_pass": defensive_pass,
        "beats_equal_offensive_pool": equal_pool_pass,
        "excess_vs_spy": _excess(metrics, spy),
        "excess_vs_qqq": _excess(metrics, qqq),
        "excess_vs_equal_offensive_etf": _excess(metrics, equal),
        "offensive_score": float(offensive_score),
        "defensive_score": float(defensive_score),
    }


def _excess(metrics: dict[str, Any], benchmark: dict[str, Any]) -> dict[str, float]:
    return {
        "cagr": float(metrics["cagr"]) - float(benchmark["cagr"]),
        "sharpe": float(metrics["sharpe"]) - float(benchmark["sharpe"]),
        "max_drawdown_improvement": float(metrics["max_drawdown"]) - float(benchmark["max_drawdown"]),
        "total_return": float(metrics["total_return"]) - float(benchmark["total_return"]),
    }


def _summary(evaluated: list[dict[str, Any]]) -> dict[str, Any]:
    offensive = [row for row in evaluated if row["offensive_replacement_pass"]]
    defensive = [row for row in evaluated if row["defensive_candidate_pass"]]
    rejected = [row for row in evaluated if row["gate_status"] == "rejected_vs_buy_hold"]
    return {
        "candidate_count": len(evaluated),
        "offensive_replacement_pass_count": len(offensive),
        "defensive_candidate_pass_count": len(defensive),
        "rejected_vs_buy_hold_count": len(rejected),
        "has_offensive_replacement": bool(offensive),
        "has_defensive_candidate": bool(defensive),
    }


def _decision(summary: dict[str, Any]) -> dict[str, Any]:
    if summary["has_offensive_replacement"]:
        status = "offensive_replacement_candidate_for_manual_review"
    elif summary["has_defensive_candidate"]:
        status = "defensive_candidate_only_not_spy_qqq_replacement"
    else:
        status = "rejected_vs_buy_hold"
    return {
        "status": status,
        "live_order_allowed": False,
        "paper_promotion_allowed": False,
        "reason": (
            "No candidate may replace SPY/QQQ unless it passes the offensive replacement rule. "
            "Defensive candidates can only be studied as drawdown-control allocations."
        ),
    }


def _acceptance_rules() -> dict[str, str]:
    return {
        "offensive_replacement_pass": "50bps candidate CAGR must exceed max(SPY, QQQ), Sharpe must exceed max(SPY, QQQ), and drawdown must not be worse than the harsher SPY/QQQ drawdown.",
        "defensive_candidate_only": "50bps candidate CAGR must be at least 75% of SPY CAGR, Sharpe must exceed SPY, and drawdown must be at least materially lower than SPY and QQQ.",
        "rejected_vs_buy_hold": "Candidate is neither an offensive replacement nor a defensive allocation candidate.",
    }


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _markdown(report: dict[str, Any]) -> str:
    decision = report["decision"]
    best_off = report["best_offensive_candidate"]
    best_def = report["best_defensive_candidate"]
    lines = [
        "# US ETF 轮动 基准替代价值评估",
        "",
        "## 结论",
        "",
        f"- Gate 状态：`{decision['status']}`。",
        f"- 进攻型替代通过数：`{report['summary']['offensive_replacement_pass_count']}` / `{report['summary']['candidate_count']}`。",
        f"- 防守型候选通过数：`{report['summary']['defensive_candidate_pass_count']}` / `{report['summary']['candidate_count']}`。",
        "- 本报告不允许纸盘或实盘晋级，只判断是否值得替代长持基准。",
        "",
        "## 基准表现",
        "",
        "| Benchmark | CAGR | Sharpe | MDD | Total Return |",
        "|---|---:|---:|---:|---:|",
    ]
    protected = report.get("protected_original_baseline", {})
    if protected.get("status") == "available":
        protected_metrics = protected["metrics"]
        lines.insert(12, "")
        lines.insert(12, f"- 同期 SPY true CAGR：{_pct(protected_metrics['SPY_true_cagr'])}；同期 QQQ true CAGR：{_pct(protected_metrics['QQQ_true_cagr'])}。")
        lines.insert(12, f"- true CAGR：{_pct(protected_metrics['strategy_true_cagr'])}；算术年化：{_pct(protected_metrics['strategy_arithmetic_annualized_return'])}；MDD：{_pct(protected_metrics['strategy_max_drawdown'])}；Turnover：{protected_metrics['turnover']:.2f}。")
        lines.insert(12, f"- 调仓语义：`{protected['rebalance_semantics']}`。")
        lines.insert(12, f"- Baseline：`{protected['baseline_id']}`，不混入当前候选排名。")
        lines.insert(12, "")
        lines.insert(12, "## 受保护原始基线")
        lines.insert(12, "")

    for benchmark_id, metrics in report["benchmarks"].items():
        lines.append(
            f"| {benchmark_id} | {_pct(metrics['cagr'])} | {metrics['sharpe']:.3f} | {_pct(metrics['max_drawdown'])} | {_pct(metrics['total_return'])} |"
        )
    lines.extend(
        [
            "",
            "## 最优候选",
            "",
            f"- 进攻排序第一：`{best_off['family']}`，CAGR {_pct(best_off['metrics_50bps']['cagr'])}，Sharpe {best_off['metrics_50bps']['sharpe']:.3f}，MDD {_pct(best_off['metrics_50bps']['max_drawdown'])}，状态 `{best_off['gate_status']}`。",
            f"- 防守排序第一：`{best_def['family']}`，CAGR {_pct(best_def['metrics_50bps']['cagr'])}，Sharpe {best_def['metrics_50bps']['sharpe']:.3f}，MDD {_pct(best_def['metrics_50bps']['max_drawdown'])}，状态 `{best_def['gate_status']}`。",
            "",
            "## 候选排名",
            "",
            "| Rank | Family | Status | CAGR | Sharpe | MDD | Excess CAGR vs SPY | Excess CAGR vs QQQ | MDD Improvement vs SPY |",
            "|---:|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for rank, row in enumerate(report["ranking"]["defensive"][:20], start=1):
        metrics = row["metrics_50bps"]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(rank),
                    row["family"],
                    row["gate_status"],
                    _pct(metrics["cagr"]),
                    f"{metrics['sharpe']:.3f}",
                    _pct(metrics["max_drawdown"]),
                    _pct(row["excess_vs_spy"]["cagr"]),
                    _pct(row["excess_vs_qqq"]["cagr"]),
                    _pct(row["excess_vs_spy"]["max_drawdown_improvement"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 规则",
            "",
            f"- 进攻型替代：{report['acceptance_rules']['offensive_replacement_pass']}",
            f"- 防守型候选：{report['acceptance_rules']['defensive_candidate_only']}",
            f"- 淘汰：{report['acceptance_rules']['rejected_vs_buy_hold']}",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
