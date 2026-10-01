from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research import high_octane_attack_sleeve_lab as high_octane
from quant_crypto.research import pyramiding_sleeve_lab as pyramiding
from quant_crypto.research.bankroll_rollover_lab import _frozen_v3_direction
from quant_crypto.research.simple_trend_rule_lab import (
    BASE_COST_BPS,
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    INITIAL_CAPITAL,
)
from quant_crypto.research.small_account_high_yield_near_miss_review import _prepare_market_context


SCHEMA_VERSION = "btc_attack_followup_review_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_attack_followup_review/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_attack_followup_review_report.json"
DEFAULT_STRICT_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_attack_followup_high_octane_strict_rows.csv"
DEFAULT_COMPARISON_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_attack_followup_5x_vs_10x_comparison.csv"
DEFAULT_ROLLING_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_attack_followup_5x_vs_10x_rolling_start.csv"
DEFAULT_SUMMARY_CN_PATH = DEFAULT_OUTPUT_DIR / "btc_attack_followup_review_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_HIGH_OCTANE_REPORT_PATH = high_octane.DEFAULT_OUTPUT_DIR / "btc_high_octane_attack_sleeve_lab_report.json"
DEFAULT_HIGH_OCTANE_ROLLING_PATH = high_octane.DEFAULT_OUTPUT_DIR / "btc_high_octane_attack_sleeve_lab_rolling_start.csv"
DEFAULT_RISK_STRESS_MATRIX_PATH = Path(
    "artifacts/btc_attack_sleeve_risk_stress_review/latest/btc_attack_sleeve_risk_stress_review_matrix.csv"
)
DEFAULT_RISK_STRESS_REPORT_PATH = Path(
    "artifacts/btc_attack_sleeve_risk_stress_review/latest/btc_attack_sleeve_risk_stress_review_report.json"
)
DEFAULT_PYRAMIDING_REPORT_PATH = pyramiding.DEFAULT_OUTPUT_DIR / "btc_pyramiding_sleeve_lab_report.json"

STRICT_POLICY_ORDER = (
    "base_strict_next_bar",
    "mark_adverse_100bps",
    "mark_adverse_200bps",
    "funding_2x_adverse",
    "funding_5x_adverse",
    "slippage_2x",
    "slippage_5x",
    "taker_fee_2x",
    "combined_adverse_5x",
)


def build_btc_attack_followup_review(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    high_octane_report_path: Path = DEFAULT_HIGH_OCTANE_REPORT_PATH,
    high_octane_rolling_path: Path = DEFAULT_HIGH_OCTANE_ROLLING_PATH,
    risk_stress_matrix_path: Path = DEFAULT_RISK_STRESS_MATRIX_PATH,
    risk_stress_report_path: Path = DEFAULT_RISK_STRESS_REPORT_PATH,
    pyramiding_report_path: Path = DEFAULT_PYRAMIDING_REPORT_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
    run_rolling_comparison: bool = True,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    strict_csv_path = output_dir / DEFAULT_STRICT_CSV_PATH.name
    comparison_csv_path = output_dir / DEFAULT_COMPARISON_CSV_PATH.name
    rolling_csv_path = output_dir / DEFAULT_ROLLING_CSV_PATH.name
    summary_path = output_dir / DEFAULT_SUMMARY_CN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    blockers: list[str] = []
    high_report = _read_json(high_octane_report_path, blockers, "missing_high_octane_report")
    risk_report = _read_json(risk_stress_report_path, blockers, "missing_risk_stress_report")
    pyramiding_report = _read_json(pyramiding_report_path, blockers, "missing_pyramiding_report")
    strict_matrix_rows = _read_csv(risk_stress_matrix_path, blockers, "missing_risk_stress_matrix")
    high_rolling_rows = _read_csv(high_octane_rolling_path, blockers, "missing_high_octane_rolling")

    high_summary = _mapping(high_report.get("summary"))
    best_high_id = str(high_summary.get("best_scenario_id") or "")
    strict_rows = _strict_rows_for_best(best_high_id, strict_matrix_rows)
    high_rolling_summary = _high_octane_rolling_summary(best_high_id, high_rolling_rows)
    comparison_rows = _comparison_rows(pyramiding_report)
    rolling_rows: list[dict[str, Any]] = []
    rolling_summary: dict[str, Any] = {"rolling_start_count": 0, "status": "not_run"}
    if run_rolling_comparison and not blockers:
        try:
            rolling_rows = _run_pyramiding_rolling_comparison(
                market_db_path=market_db_path,
                derivatives_rows_path=derivatives_rows_path,
                pyramiding_report=pyramiding_report,
                initial_capital=initial_capital,
                base_cost_bps=base_cost_bps,
            )
            rolling_summary = _comparison_rolling_summary(rolling_rows)
        except Exception as exc:  # pragma: no cover - defensive report boundary
            blockers.append(f"btc_attack_followup_rolling_failed:{type(exc).__name__}:{exc}")
            rolling_summary = {"rolling_start_count": 0, "status": "failed", "error": str(exc)}
    elif not run_rolling_comparison:
        rolling_summary = {"rolling_start_count": 0, "status": "disabled_for_test_or_dry_run"}

    summary = _summary(
        high_summary=high_summary,
        risk_summary=_mapping(risk_report.get("summary")),
        strict_rows=strict_rows,
        high_rolling_summary=high_rolling_summary,
        comparison_rows=comparison_rows,
        rolling_summary=rolling_summary,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": _decision(blockers=blockers, summary=summary),
        "scope": "high_octane_strict_followup_and_5x_vs_actual_10x_same_window_comparison_research_only",
        "code_commit": _git(["rev-parse", "--short", "HEAD"]),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "high_octane_report_path": _portable_path(high_octane_report_path),
            "high_octane_rolling_path": _portable_path(high_octane_rolling_path),
            "risk_stress_matrix_path": _portable_path(risk_stress_matrix_path),
            "risk_stress_report_path": _portable_path(risk_stress_report_path),
            "pyramiding_report_path": _portable_path(pyramiding_report_path),
        },
        "research_design": {
            "high_octane_review": "Reuse strict next-bar risk-stress rows plus existing High-Octane rolling-start rows for the current best candidate.",
            "comparison_review": "Compare fixed best 5x spike-defense sleeve candidate against fixed best actual 10x limited-exposure candidate on the same market window and rolling starts.",
            "rolling_start_step_days": high_octane.ROLLING_START_STEP_DAYS,
            "rolling_min_remaining_days": high_octane.ROLLING_MIN_REMAINING_DAYS,
            "stress_policies": list(STRICT_POLICY_ORDER),
            "paper_live_boundary": "Research-only review. No paper queue write, no strategy skeleton, no OMS/broker/live unlock.",
        },
        "summary": summary,
        "high_octane_strict_rows": strict_rows,
        "high_octane_rolling_summary": high_rolling_summary,
        "same_window_comparison_rows": comparison_rows,
        "rolling_comparison_summary": rolling_summary,
        "rolling_comparison_rows_sample": rolling_rows[:20],
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(blockers=blockers, summary=summary),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "high_octane_strict_csv": _portable_path(strict_csv_path),
            "comparison_csv": _portable_path(comparison_csv_path),
            "rolling_start_csv": _portable_path(rolling_csv_path),
            "summary_cn": _portable_path(summary_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(strict_csv_path, strict_rows)
    _write_csv(comparison_csv_path, comparison_rows)
    _write_csv(rolling_csv_path, rolling_rows)
    _write_text(summary_path, render_btc_attack_followup_review_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_attack_followup_review_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    lines = [
        "# BTC High-Octane 严格复核 + 5x/10x 限暴露对比",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        "- 边界：research-only，不写 paper 队列，不生成策略骨架，不接 broker/OMS/order，不解锁 live。",
        "",
        "## High-Octane v2 严格复核",
        "",
        f"- 当前最佳：`{summary.get('high_octane_best_scenario_id')}`",
        f"- 原始年化 / 总收益 / 回撤：`{summary.get('high_octane_source_annual_return_pct')}` / `{summary.get('high_octane_source_total_return_pct')}` / `{summary.get('high_octane_source_max_drawdown_abs_pct')}`",
        f"- 严格 base 年化 / 总收益 / 回撤：`{summary.get('high_octane_strict_base_annual_return_pct')}` / `{summary.get('high_octane_strict_base_total_return_pct')}` / `{summary.get('high_octane_strict_base_max_drawdown_abs_pct')}`",
        f"- 严格压力最差 -10% 后剩余本金：`{summary.get('high_octane_strict_min_remaining_after_10pct_spike')}`",
        f"- rolling-start 中位总收益：`{summary.get('high_octane_rolling_median_total_return_pct')}`，最差总收益：`{summary.get('high_octane_rolling_min_total_return_pct')}`",
        "",
        "| policy | 年化 | 总收益 | 回撤 | -10%后剩余 | 强平 | 全灭 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in _list_of_mappings(report.get("high_octane_strict_rows")):
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(row.get("policy_id")),
                    _md(_pct(row.get("annual_return_pct"))),
                    _md(_pct(row.get("total_return_pct"))),
                    _md(_pct(row.get("max_drawdown_abs_pct"))),
                    _md(_pct(row.get("min_remaining_capital_pct_after_10pct_spike"))),
                    _md(row.get("normal_liquidation_count")),
                    _md(row.get("full_wipeout")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 5x 防插针 vs 实际 10x 限暴露",
            "",
            f"- 同窗口结论：`{summary.get('comparison_verdict')}`",
            f"- rolling-start 结论：`{summary.get('rolling_comparison_verdict')}`",
            "",
            "| 策略 | 年化 | 总收益 | 回撤 | -10%后剩余 | rolling中位收益 | rolling最差收益 | 正收益率 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    rolling_by_id = {
        str(row.get("line_id")): row for row in _list_of_mappings(_nested(report, "rolling_comparison_summary", "by_line"))
    }
    for row in _list_of_mappings(report.get("same_window_comparison_rows")):
        rolling = rolling_by_id.get(str(row.get("line_id")), {})
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(row.get("display_name_cn")),
                    _md(_pct(row.get("annual_return_pct"))),
                    _md(_pct(row.get("total_return_pct"))),
                    _md(_pct(row.get("max_drawdown_abs_pct"))),
                    _md(_pct(row.get("min_remaining_capital_pct_after_10pct_spike"))),
                    _md(_pct(rolling.get("rolling_median_total_return_pct"))),
                    _md(_pct(rolling.get("rolling_min_total_return_pct"))),
                    _md(_pct_rate(rolling.get("rolling_positive_rate"))),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 当前解释",
            "",
            "- High-Octane v2 在严格 base next-bar 下收益大幅低于原始同根代理口径，但仍为正；压力后本金余量仍贴近 40% 档，不能视为稳健。",
            "- 5x 防插针线更像本金保护基线；实际 10x 限暴露线收益低很多，但验证了限暴露、提本金和错峰的纪律价值。",
            "- 下一步不应扩大策略空间，而应继续做真实 mark/index、盘口深度、funding 结算和 forward observation。",
        ]
    )
    return "\n".join(lines) + "\n"


def _strict_rows_for_best(best_high_id: str, matrix_rows: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in matrix_rows if row.get("scenario_id") == best_high_id]
    order = {policy: idx for idx, policy in enumerate(STRICT_POLICY_ORDER)}
    rows = sorted(rows, key=lambda row: (order.get(str(row.get("policy_id")), 999), str(row.get("policy_id"))))
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                "policy_id": row.get("policy_id"),
                "scenario_id": row.get("scenario_id"),
                "annual_return_pct": _num(row.get("annual_return_pct")),
                "total_return_pct": _num(row.get("total_return_pct")),
                "max_drawdown_abs_pct": _num(row.get("max_drawdown_abs_pct")),
                "min_remaining_capital_pct_after_10pct_spike": _num(row.get("min_remaining_capital_pct_after_10pct_spike")),
                "normal_liquidation_count": _int(row.get("normal_liquidation_count")),
                "spike_liquidation_max_count": _int(row.get("spike_liquidation_max_count")),
                "max_concurrent_exposed_sleeves_observed": _int(row.get("max_concurrent_exposed_sleeves_observed")),
                "mark_adverse_offset_bps": _num(row.get("mark_adverse_offset_bps")),
                "funding_adverse_multiplier": _num(row.get("funding_adverse_multiplier")),
                "slippage_bps": _num(row.get("slippage_bps")),
                "taker_fee_multiplier": _num(row.get("taker_fee_multiplier")),
                "hard_wipeout": _bool(row.get("hard_wipeout")),
                "full_wipeout": _bool(row.get("full_wipeout")),
                "strict_next_bar_execution": _bool(row.get("strict_next_bar_execution")),
                "same_bar_profit_allowed": _bool(row.get("same_bar_profit_allowed")),
                "stress_decision": row.get("stress_decision"),
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        )
    return normalized


def _high_octane_rolling_summary(best_high_id: str, rolling_rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    rows = [row for row in rolling_rows if row.get("scenario_id") == best_high_id]
    returns = [_num(row.get("total_return_pct"), 0.0) or 0.0 for row in rows]
    annuals = [_num(row.get("annual_return_pct"), 0.0) or 0.0 for row in rows]
    remaining = [_num(row.get("min_remaining_capital_pct_after_10pct_spike"), 0.0) or 0.0 for row in rows]
    return {
        "scenario_id": best_high_id,
        "rolling_start_count": len(rows),
        "rolling_median_total_return_pct": _round(median(returns)) if returns else 0.0,
        "rolling_min_total_return_pct": _round(min(returns)) if returns else 0.0,
        "rolling_positive_rate": _round(sum(1 for value in returns if value > 0.0) / max(1, len(rows))),
        "rolling_median_annual_return_pct": _round(median(annuals)) if annuals else 0.0,
        "rolling_median_remaining_after_10pct_spike": _round(median(remaining)) if remaining else 0.0,
        "rolling_full_wipeout_rate": _round(
            sum(1 for row in rows if _bool(row.get("full_wipeout"))) / max(1, len(rows))
        ),
    }


def _comparison_rows(pyramiding_report: Mapping[str, Any]) -> list[dict[str, Any]]:
    top_defense = _first_mapping(pyramiding_report.get("top_watchlist"))
    top_attack = _first_mapping(pyramiding_report.get("top_actual_attack_watchlist"))
    return [
        _comparison_row("defensive_5x_spike_sleeve", "5x 防插针/分仓版", top_defense),
        _comparison_row("actual_10x_limited_attack", "实际 10x attack 限暴露版", top_attack),
    ]


def _comparison_row(line_id: str, display_name: str, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "line_id": line_id,
        "display_name_cn": display_name,
        "scenario_id": row.get("scenario_id"),
        "annual_return_pct": _num(row.get("annual_return_pct")),
        "total_return_pct": _num(row.get("total_return_pct")),
        "max_drawdown_abs_pct": _num(row.get("max_drawdown_abs_pct")),
        "min_remaining_capital_pct_after_10pct_spike": _num(row.get("min_remaining_capital_pct_after_10pct_spike")),
        "max_concurrent_exposed_sleeves_observed": _int(row.get("max_concurrent_exposed_sleeves_observed")),
        "max_attack_exposed_sleeves_observed": _int(row.get("max_attack_exposed_sleeves_observed")),
        "extract_count": _int(row.get("extract_count")),
        "reserve_cash_pct_of_initial": _num(row.get("reserve_cash_pct_of_initial")),
        "normal_liquidation_count": _int(row.get("normal_liquidation_count")),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _run_pyramiding_rolling_comparison(
    *,
    market_db_path: Path,
    derivatives_rows_path: Path,
    pyramiding_report: Mapping[str, Any],
    initial_capital: float,
    base_cost_bps: float,
) -> list[dict[str, Any]]:
    comparison = _comparison_rows(pyramiding_report)
    wanted = {str(row.get("scenario_id")): str(row.get("line_id")) for row in comparison if row.get("scenario_id")}
    scenario_map = {scenario.scenario_id: scenario for scenario in pyramiding._scenario_grid()}
    selected = {scenario_id: scenario_map[scenario_id] for scenario_id in wanted if scenario_id in scenario_map}
    if not selected:
        return []
    market = _prepare_market_context(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    direction = _frozen_v3_direction(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    starts = high_octane._rolling_start_times(direction.index)
    rows: list[dict[str, Any]] = []
    for scenario_id, scenario in selected.items():
        for start_time in starts:
            direction_slice = direction.loc[direction.index >= start_time]
            if direction_slice.empty:
                continue
            market_slice = dict(market)
            market_slice["bars_4h"] = market["bars_4h"].loc[market["bars_4h"].index >= start_time]
            market_slice["derivatives_4h"] = market["derivatives_4h"].loc[market["derivatives_4h"].index >= start_time]
            result = pyramiding._simulate_pyramid_sleeves(
                scenario,
                market=market_slice,
                direction=direction_slice,
                initial_capital=initial_capital,
                base_cost_bps=base_cost_bps,
            )
            row = pyramiding._result_row(result)
            row["line_id"] = wanted[scenario_id]
            row["rolling_start_time"] = _ts(start_time)
            row["hard_wipeout"] = bool(float(row.get("final_equity", 0.0)) <= initial_capital * 0.25)
            row["full_wipeout"] = bool(float(row.get("final_equity", 0.0)) <= 1e-9)
            row["paper_queue_write_allowed"] = False
            row["live_unlock_allowed"] = False
            rows.append(row)
    return rows


def _comparison_rolling_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_line: list[dict[str, Any]] = []
    for line_id in sorted({str(row.get("line_id")) for row in rows if row.get("line_id")}):
        line_rows = [row for row in rows if str(row.get("line_id")) == line_id]
        returns = [_num(row.get("total_return_pct"), 0.0) or 0.0 for row in line_rows]
        remaining = [_num(row.get("min_remaining_capital_pct_after_10pct_spike"), 0.0) or 0.0 for row in line_rows]
        by_line.append(
            {
                "line_id": line_id,
                "rolling_start_count": len(line_rows),
                "rolling_median_total_return_pct": _round(median(returns)) if returns else 0.0,
                "rolling_min_total_return_pct": _round(min(returns)) if returns else 0.0,
                "rolling_positive_rate": _round(sum(1 for value in returns if value > 0.0) / max(1, len(line_rows))),
                "rolling_median_remaining_after_10pct_spike": _round(median(remaining)) if remaining else 0.0,
                "rolling_min_remaining_after_10pct_spike": _round(min(remaining)) if remaining else 0.0,
                "rolling_full_wipeout_rate": _round(
                    sum(1 for row in line_rows if bool(row.get("full_wipeout"))) / max(1, len(line_rows))
                ),
                "rolling_normal_liquidation_count": sum(_int(row.get("normal_liquidation_count")) for row in line_rows),
            }
        )
    return {
        "status": "complete" if rows else "empty",
        "rolling_start_count": max((row["rolling_start_count"] for row in by_line), default=0),
        "by_line": by_line,
    }


def _summary(
    *,
    high_summary: Mapping[str, Any],
    risk_summary: Mapping[str, Any],
    strict_rows: Sequence[Mapping[str, Any]],
    high_rolling_summary: Mapping[str, Any],
    comparison_rows: Sequence[Mapping[str, Any]],
    rolling_summary: Mapping[str, Any],
) -> dict[str, Any]:
    strict_base = _find_row(strict_rows, "policy_id", "base_strict_next_bar")
    strict_min_remaining = min(
        (_num(row.get("min_remaining_capital_pct_after_10pct_spike"), 100.0) or 100.0 for row in strict_rows),
        default=0.0,
    )
    defensive = _find_row(comparison_rows, "line_id", "defensive_5x_spike_sleeve")
    attack = _find_row(comparison_rows, "line_id", "actual_10x_limited_attack")
    by_line = _list_of_mappings(rolling_summary.get("by_line"))
    defense_roll = _find_row(by_line, "line_id", "defensive_5x_spike_sleeve")
    attack_roll = _find_row(by_line, "line_id", "actual_10x_limited_attack")
    return {
        "high_octane_best_scenario_id": high_summary.get("best_scenario_id"),
        "high_octane_source_annual_return_pct": _num(high_summary.get("best_annual_return_pct")),
        "high_octane_source_total_return_pct": _num(high_summary.get("best_total_return_pct")),
        "high_octane_source_max_drawdown_abs_pct": _num(high_summary.get("best_max_drawdown_abs_pct")),
        "high_octane_source_min_remaining_after_10pct_spike": _num(high_summary.get("best_min_remaining_after_10pct_spike")),
        "high_octane_strict_base_annual_return_pct": _num(strict_base.get("annual_return_pct")),
        "high_octane_strict_base_total_return_pct": _num(strict_base.get("total_return_pct")),
        "high_octane_strict_base_max_drawdown_abs_pct": _num(strict_base.get("max_drawdown_abs_pct")),
        "high_octane_strict_min_remaining_after_10pct_spike": _round(strict_min_remaining),
        "high_octane_risk_stress_not_forward_observation_ready": bool(risk_summary.get("not_forward_observation_ready")),
        "high_octane_rolling_median_total_return_pct": _num(high_rolling_summary.get("rolling_median_total_return_pct")),
        "high_octane_rolling_min_total_return_pct": _num(high_rolling_summary.get("rolling_min_total_return_pct")),
        "high_octane_rolling_positive_rate": _num(high_rolling_summary.get("rolling_positive_rate")),
        "comparison_verdict": _comparison_verdict(defensive, attack),
        "rolling_comparison_verdict": _rolling_verdict(defense_roll, attack_roll),
        "defensive_5x_total_return_pct": _num(defensive.get("total_return_pct")),
        "actual_10x_limited_total_return_pct": _num(attack.get("total_return_pct")),
        "defensive_5x_min_remaining_after_10pct_spike": _num(defensive.get("min_remaining_capital_pct_after_10pct_spike")),
        "actual_10x_limited_min_remaining_after_10pct_spike": _num(attack.get("min_remaining_capital_pct_after_10pct_spike")),
        "defensive_5x_rolling_median_total_return_pct": _num(defense_roll.get("rolling_median_total_return_pct")),
        "actual_10x_limited_rolling_median_total_return_pct": _num(attack_roll.get("rolling_median_total_return_pct")),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _comparison_verdict(defensive: Mapping[str, Any], attack: Mapping[str, Any]) -> str:
    defense_return = _num(defensive.get("total_return_pct"), 0.0) or 0.0
    attack_return = _num(attack.get("total_return_pct"), 0.0) or 0.0
    defense_remaining = _num(defensive.get("min_remaining_capital_pct_after_10pct_spike"), 0.0) or 0.0
    attack_remaining = _num(attack.get("min_remaining_capital_pct_after_10pct_spike"), 0.0) or 0.0
    if defense_return > attack_return and defense_remaining >= attack_remaining:
        return "defensive_5x_dominates_same_window_return_and_spike_survival"
    if attack_remaining >= 80.0:
        return "actual_10x_limited_is_discipline_module_not_return_leader"
    return "mixed_result_requires_manual_review"


def _rolling_verdict(defense_roll: Mapping[str, Any], attack_roll: Mapping[str, Any]) -> str:
    defense_median = _num(defense_roll.get("rolling_median_total_return_pct"), 0.0) or 0.0
    attack_median = _num(attack_roll.get("rolling_median_total_return_pct"), 0.0) or 0.0
    defense_remaining = _num(defense_roll.get("rolling_median_remaining_after_10pct_spike"), 0.0) or 0.0
    attack_remaining = _num(attack_roll.get("rolling_median_remaining_after_10pct_spike"), 0.0) or 0.0
    if defense_median > attack_median and defense_remaining >= attack_remaining:
        return "defensive_5x_has_better_rolling_median_and_spike_survival"
    if attack_remaining >= 80.0:
        return "actual_10x_limited_survives_but_underperforms_rolling_return"
    return "rolling_result_mixed"


def _decision(*, blockers: Sequence[str], summary: Mapping[str, Any]) -> str:
    if blockers:
        return "btc_attack_followup_review_blocked_research_only_no_paper_no_live"
    if bool(summary.get("high_octane_risk_stress_not_forward_observation_ready")):
        return "btc_attack_followup_review_complete_not_forward_ready_no_paper_no_live"
    return "btc_attack_followup_review_complete_manual_review_required_no_paper_no_live"


def _warnings(*, blockers: Sequence[str], summary: Mapping[str, Any]) -> list[str]:
    warnings = ["btc_attack_followup_review_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_attack_followup_review_blocked")
    if bool(summary.get("high_octane_risk_stress_not_forward_observation_ready")):
        warnings.append("high_octane_strict_review_not_forward_observation_ready")
    warnings.append("funding_mark_index_liquidation_are_research_approximations")
    return warnings


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "strategy_skeleton_generated": False,
        "reason": "Attack follow-up review is diagnostic only.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_attack_followup_review_safety_status_v1",
        "status": "research_only",
        "decision": report.get("decision"),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "strategy_skeleton_generated": False,
        "reason": "BTC attack follow-up review cannot promote strategies.",
    }


def _read_json(path: Path, blockers: list[str], blocker: str) -> dict[str, Any]:
    if not path.exists():
        blockers.append(blocker)
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        blockers.append(f"{blocker}_invalid_json")
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_csv(path: Path, blockers: list[str], blocker: str) -> list[dict[str, str]]:
    if not path.exists():
        blockers.append(blocker)
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _find_row(rows: Sequence[Mapping[str, Any]], key: str, value: str) -> dict[str, Any]:
    for row in rows:
        if str(row.get(key)) == value:
            return dict(row)
    return {}


def _first_mapping(value: Any) -> Mapping[str, Any]:
    rows = _list_of_mappings(value)
    return rows[0] if rows else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nested(payload: Mapping[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _num(value: Any, fallback: float | None = None) -> float | None:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return _round(float(value))
    if isinstance(value, str):
        try:
            return _round(float(value))
        except ValueError:
            return fallback
    return fallback


def _int(value: Any, fallback: int = 0) -> int:
    number = _num(value)
    return fallback if number is None else int(number)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "是"}
    return bool(value)


def _round(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def _pct(value: Any) -> str:
    number = _num(value)
    return "-" if number is None else f"{number:.2f}%"


def _pct_rate(value: Any) -> str:
    number = _num(value)
    return "-" if number is None else f"{number * 100.0:.2f}%"


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _ts(value: Any) -> str:
    return pd.Timestamp(value).isoformat()


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _git(args: Sequence[str]) -> str | None:
    try:
        completed = subprocess.run(["git", *args], text=True, capture_output=True, check=False)
    except OSError:
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None
