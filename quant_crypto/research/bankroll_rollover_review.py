from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.bankroll_rollover_lab import (
    INITIAL_SLEEVE_COUNT,
    MAX_SLEEVE_COUNT,
    ROLL_MULTIPLE,
    _frozen_v3_direction,
)
from quant_crypto.research.simple_trend_rule_lab import BASE_COST_BPS, DEFAULT_DERIVATIVES_ROWS, DEFAULT_MARKET_DB, INITIAL_CAPITAL
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path, _prepare_market_context, _round


SCHEMA_VERSION = "btc_bankroll_rollover_review_v1"
DEFAULT_SOURCE_REPORT_PATH = Path("artifacts/btc_bankroll_rollover_lab/latest/btc_bankroll_rollover_lab_report.json")
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_bankroll_rollover_review/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_rollover_review_report.json"
DEFAULT_SOURCE_ATTRIBUTION_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_rollover_review_source_attribution.csv"
DEFAULT_LIQUIDATION_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_rollover_review_liquidation_sensitivity.csv"
DEFAULT_COST_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_rollover_review_funding_cost_stress.csv"
DEFAULT_SEGMENT_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_rollover_review_segment_rolling_start.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_rollover_review_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

CORE_SOURCE_SCENARIOS = (
    ("br_review_no_rollover_lev1p0", "no_rollover", 1.0),
    ("br_review_no_rollover_lev3p0", "no_rollover", 3.0),
    ("br_review_no_rollover_lev5p0", "no_rollover", 5.0),
    ("br_review_no_rollover_lev10p0", "no_rollover", 10.0),
    ("br_review_split_2_on_double_lev10p0", "split_2_on_double", 10.0),
    ("br_review_extract_principal_roll_profit_lev10p0", "extract_principal_roll_profit", 10.0),
)
LIQUIDATION_POLICIES = ("no_rollover", "split_2_on_double", "extract_principal_roll_profit")
LIQUIDATION_MAINTENANCE_RATES = (0.005, 0.008, 0.010)
LIQUIDATION_FEE_RATES = (0.003, 0.005, 0.010)
MARK_ADVERSE_BPS = (0.0, 50.0, 100.0, 200.0)
EXTRA_SHOCK_PCT = (0.0, -3.0, -5.0, -8.0, -10.0)
FUNDING_STRESS_MULTIPLIERS = (1.0, 2.0, 5.0)
FEE_MULTIPLIERS = (1.0, 2.0)
SLIPPAGE_MULTIPLIERS = (1.0, 2.0, 5.0)
SEGMENTS = (
    ("2024", "2024-01-01", "2024-12-31 23:59:59.999"),
    ("2025", "2025-01-01", "2025-12-31 23:59:59.999"),
    ("2026_to_latest", "2026-01-01", None),
)


@dataclass(frozen=True)
class ReviewScenario:
    scenario_id: str
    rollover_policy: str
    leverage: float
    maintenance_margin_rate: float = 0.005
    liquidation_fee_rate: float = 0.003
    mark_adverse_bps: float = 0.0
    extra_shock_pct: float = 0.0
    funding_stress_multiplier: float = 1.0
    fee_multiplier: float = 1.0
    slippage_multiplier: float = 1.0
    window_id: str = "full"


@dataclass
class SleeveGroup:
    count: int
    equity: float
    basis_equity: float


@dataclass
class ReviewResult:
    scenario: ReviewScenario
    equity: pd.Series
    exposure: pd.Series
    metrics: dict[str, Any]
    event_rows: list[dict[str, Any]]


def build_btc_bankroll_rollover_review(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    source_report_path: Path = DEFAULT_SOURCE_REPORT_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    source_csv_path = output_dir / DEFAULT_SOURCE_ATTRIBUTION_CSV_PATH.name
    liquidation_csv_path = output_dir / DEFAULT_LIQUIDATION_CSV_PATH.name
    cost_csv_path = output_dir / DEFAULT_COST_CSV_PATH.name
    segment_csv_path = output_dir / DEFAULT_SEGMENT_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    market = _prepare_market_context(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    blockers = [str(item) for item in market.get("blockers", [])]
    source_report = _read_json(source_report_path)
    if not source_report:
        blockers.append("btc_bankroll_rollover_review_missing_source_bankroll_report")

    direction = _frozen_v3_direction(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    bars_4h = market["bars_4h"].reindex(direction.index)

    source_rows, source_summary = _source_attribution(
        market=market,
        direction=direction,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    liquidation_rows = _liquidation_sensitivity(
        market=market,
        direction=direction,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    cost_rows, cost_summary = _funding_cost_stress(
        market=market,
        direction=direction,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    segment_rows, segment_summary = _segment_and_rolling_start(
        market=market,
        direction=direction,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    decision = _review_decision(liquidation_rows=liquidation_rows, segment_summary=segment_summary)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": decision,
        "scope": "bankroll_rollover_source_attribution_liquidation_cost_segment_review",
        "code_commit": _git_commit(),
        "input": {
            "source_report_path": _portable_path(source_report_path),
            "source_report_status": source_report.get("status") if source_report else None,
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "market_4h_rows": int(len(bars_4h)),
            "market_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "market_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
            "direction_source": "frozen high-yield v3 loss-control direction, generated from completed 1h->4h bars",
        },
        "review_design": {
            "primary_scenario_id": "br_split_2_on_double_lev10p0",
            "core_source_scenarios": [item[0] for item in CORE_SOURCE_SCENARIOS],
            "liquidation_policies": list(LIQUIDATION_POLICIES),
            "liquidation_maintenance_rates": list(LIQUIDATION_MAINTENANCE_RATES),
            "liquidation_fee_rates": list(LIQUIDATION_FEE_RATES),
            "mark_adverse_bps": list(MARK_ADVERSE_BPS),
            "extra_shock_pct": list(EXTRA_SHOCK_PCT),
            "funding_stress_multipliers": list(FUNDING_STRESS_MULTIPLIERS),
            "fee_multipliers": list(FEE_MULTIPLIERS),
            "slippage_multipliers": list(SLIPPAGE_MULTIPLIERS),
            "rolling_start_step_days": 30,
            "excluded_from_review_candidates": {"leverage_100x": "extreme stress reference only, not a review candidate"},
            "liquidation_model": {
                "model": "isolated_linear_perp_4h_high_low_mark_proxy_with_adverse_offsets",
                "threshold_formula": "max(0, 1/leverage - maintenance_margin_rate - liquidation_fee_rate)",
                "adverse_move_formula": "4h high/low adverse move + mark_adverse_bps + abs(extra_shock_pct)",
                "promotion_evidence": False,
            },
        },
        "source_attribution": {"summary": source_summary, "rows": source_rows},
        "liquidation_sensitivity": {"row_count": len(liquidation_rows), "rows": liquidation_rows[:25], "summary": _liquidation_summary(liquidation_rows)},
        "funding_cost_stress": {"summary": cost_summary, "rows": cost_rows},
        "segment_and_rolling_start": {"summary": segment_summary, "rows": segment_rows},
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(decision, liquidation_rows, segment_summary),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "source_attribution_csv": _portable_path(source_csv_path),
            "liquidation_sensitivity_csv": _portable_path(liquidation_csv_path),
            "funding_cost_stress_csv": _portable_path(cost_csv_path),
            "segment_rolling_start_csv": _portable_path(segment_csv_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(source_csv_path, source_rows)
    _write_csv(liquidation_csv_path, liquidation_rows)
    _write_csv(cost_csv_path, cost_rows)
    _write_csv(segment_csv_path, segment_rows)
    _write_text(markdown_path, render_btc_bankroll_rollover_review_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _source_attribution(
    *,
    market: Mapping[str, Any],
    direction: pd.Series,
    initial_capital: float,
    base_cost_bps: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    results: dict[str, ReviewResult] = {}
    for scenario_id, policy, leverage in CORE_SOURCE_SCENARIOS:
        scenario = ReviewScenario(scenario_id=scenario_id, rollover_policy=policy, leverage=leverage)
        result = _simulate_review_bankroll(scenario, market=market, direction=direction, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
        results[scenario_id] = result
        row = _result_row(result)
        row["attribution_bucket"] = _attribution_bucket(policy, leverage)
        rows.append(row)

    one_x = results["br_review_no_rollover_lev1p0"].metrics
    ten_no = results["br_review_no_rollover_lev10p0"].metrics
    ten_split = results["br_review_split_2_on_double_lev10p0"].metrics
    ten_extract = results["br_review_extract_principal_roll_profit_lev10p0"].metrics
    split_increment = float(ten_split["final_equity"]) - float(ten_no["final_equity"])
    split_increment_pct_of_no_rollover = split_increment / max(1e-9, abs(float(ten_no["final_equity"])))
    summary = {
        "unlevered_signal_total_return_pct": one_x["total_return_pct"],
        "leverage_compounding_proxy_10x_no_rollover_total_return_pct": ten_no["total_return_pct"],
        "split_2_total_return_pct": ten_split["total_return_pct"],
        "extract_principal_total_return_pct": ten_extract["total_return_pct"],
        "split_incremental_final_equity_vs_10x_no_rollover": _round(split_increment),
        "split_incremental_pct_of_10x_no_rollover_equity": _round(split_increment_pct_of_no_rollover * 100.0),
        "main_driver": "leverage_compounding_not_split" if abs(split_increment_pct_of_no_rollover) <= 0.01 else "rollover_policy_materially_changes_terminal_equity",
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }
    return rows, summary


def _liquidation_sensitivity(
    *,
    market: Mapping[str, Any],
    direction: pd.Series,
    initial_capital: float,
    base_cost_bps: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for policy in LIQUIDATION_POLICIES:
        for maintenance in LIQUIDATION_MAINTENANCE_RATES:
            for liquidation_fee in LIQUIDATION_FEE_RATES:
                for mark_bps in MARK_ADVERSE_BPS:
                    for shock_pct in EXTRA_SHOCK_PCT:
                        scenario = ReviewScenario(
                            scenario_id=(
                                f"liq10_{policy}_mm{_slug_pct(maintenance)}_lf{_slug_pct(liquidation_fee)}"
                                f"_mark{int(mark_bps)}_shock{_slug_signed_pct(shock_pct)}"
                            ),
                            rollover_policy=policy,
                            leverage=10.0,
                            maintenance_margin_rate=maintenance,
                            liquidation_fee_rate=liquidation_fee,
                            mark_adverse_bps=mark_bps,
                            extra_shock_pct=shock_pct,
                        )
                        result = _simulate_review_bankroll(
                            scenario,
                            market=market,
                            direction=direction,
                            initial_capital=initial_capital,
                            base_cost_bps=base_cost_bps,
                        )
                        row = _result_row(result)
                        row["review_bucket"] = "liquidation_sensitivity"
                        rows.append(row)
    return rows


def _funding_cost_stress(
    *,
    market: Mapping[str, Any],
    direction: pd.Series,
    initial_capital: float,
    base_cost_bps: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    base_results: dict[str, dict[str, Any]] = {}
    for policy in LIQUIDATION_POLICIES:
        base_scenario = ReviewScenario(scenario_id=f"cost10_{policy}_base", rollover_policy=policy, leverage=10.0)
        base_result = _simulate_review_bankroll(base_scenario, market=market, direction=direction, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
        base_row = _result_row(base_result)
        base_row["stress_case"] = "base"
        rows.append(base_row)
        base_results[policy] = base_row
        for funding_multiplier in FUNDING_STRESS_MULTIPLIERS:
            for fee_multiplier in FEE_MULTIPLIERS:
                for slippage_multiplier in SLIPPAGE_MULTIPLIERS:
                    if funding_multiplier == 1.0 and fee_multiplier == 1.0 and slippage_multiplier == 1.0:
                        continue
                    scenario = ReviewScenario(
                        scenario_id=f"cost10_{policy}_fund{_slug_num(funding_multiplier)}_fee{_slug_num(fee_multiplier)}_slip{_slug_num(slippage_multiplier)}",
                        rollover_policy=policy,
                        leverage=10.0,
                        funding_stress_multiplier=funding_multiplier,
                        fee_multiplier=fee_multiplier,
                        slippage_multiplier=slippage_multiplier,
                    )
                    result = _simulate_review_bankroll(
                        scenario,
                        market=market,
                        direction=direction,
                        initial_capital=initial_capital,
                        base_cost_bps=base_cost_bps,
                    )
                    row = _result_row(result)
                    row["stress_case"] = "combined_max" if funding_multiplier == 5.0 and fee_multiplier == 2.0 and slippage_multiplier == 5.0 else "grid"
                    base_final = float(base_row["final_equity"])
                    row["cost_drag_vs_base"] = _round(base_final - float(row["final_equity"]))
                    row["final_equity_decline_pct_vs_base"] = _round((base_final - float(row["final_equity"])) / max(1e-9, abs(base_final)) * 100.0)
                    row["still_positive_return"] = float(row["total_return_pct"]) > 0.0
                    row["additional_liquidations_vs_base"] = int(row["total_liquidation_count"]) - int(base_row["total_liquidation_count"])
                    rows.append(row)

    combined = [row for row in rows if row.get("stress_case") == "combined_max"]
    summary = {
        "row_count": len(rows),
        "base_cost_bps": base_cost_bps,
        "base_taker_fee_bps_assumption": _round(base_cost_bps / 2.0),
        "base_slippage_bps_assumption": _round(base_cost_bps / 2.0),
        "combined_max_positive_count": sum(1 for row in combined if bool(row.get("still_positive_return"))),
        "combined_max_case_count": len(combined),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }
    return rows, summary


def _segment_and_rolling_start(
    *,
    market: Mapping[str, Any],
    direction: pd.Series,
    initial_capital: float,
    base_cost_bps: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment_id, start_text, end_text in SEGMENTS:
        start = pd.Timestamp(start_text, tz="UTC")
        end = pd.Timestamp(end_text, tz="UTC") if end_text else direction.index.max()
        segment_direction = direction[(direction.index >= start) & (direction.index <= end)]
        for scenario in _segment_scenarios(window_id=segment_id):
            if segment_direction.empty:
                rows.append(_skipped_segment_row(scenario=scenario, row_type="segment", reason="empty_segment_window"))
                continue
            result = _simulate_review_bankroll(
                scenario,
                market=market,
                direction=segment_direction,
                initial_capital=initial_capital,
                base_cost_bps=base_cost_bps,
            )
            row = _result_row(result)
            row["row_type"] = "segment"
            row["window_start"] = _ts(segment_direction.index.min())
            row["window_end"] = _ts(segment_direction.index.max())
            rows.append(row)

    start_points = _rolling_start_points(direction.index, step_days=30)
    for start in start_points:
        rolling_direction = direction[direction.index >= start]
        window_id = f"rolling_start_{start.strftime('%Y%m%d')}"
        for scenario in _segment_scenarios(window_id=window_id):
            result = _simulate_review_bankroll(
                scenario,
                market=market,
                direction=rolling_direction,
                initial_capital=initial_capital,
                base_cost_bps=base_cost_bps,
            )
            row = _result_row(result)
            row["row_type"] = "rolling_start"
            row["window_start"] = _ts(rolling_direction.index.min())
            row["window_end"] = _ts(rolling_direction.index.max())
            rows.append(row)

    rolling_main = [row for row in rows if row.get("row_type") == "rolling_start" and row.get("rollover_policy") == "split_2_on_double"]
    final_values = [float(row.get("final_equity", 0.0)) for row in rolling_main]
    all_dead_count = sum(1 for row in rolling_main if bool(row.get("all_sleeves_dead")))
    median_final = float(pd.Series(final_values).median()) if final_values else 0.0
    max_final = max(final_values) if final_values else 0.0
    path_dependence_ratio = max_final / max(1e-9, median_final)
    summary = {
        "segment_ids": [item[0] for item in SEGMENTS],
        "rolling_start_step_days": 30,
        "rolling_start_count": len(start_points),
        "rolling_main_all_dead_count": all_dead_count,
        "rolling_main_max_final_equity": _round(max_final),
        "rolling_main_median_final_equity": _round(median_final),
        "rolling_main_max_to_median_final_equity_ratio": _round(path_dependence_ratio),
        "path_dependent": bool(all_dead_count > 0 or path_dependence_ratio > 20.0),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }
    return rows, summary


def _segment_scenarios(*, window_id: str) -> list[ReviewScenario]:
    return [
        ReviewScenario(scenario_id=f"{window_id}_split_2_lev10", rollover_policy="split_2_on_double", leverage=10.0, window_id=window_id),
        ReviewScenario(scenario_id=f"{window_id}_extract_lev5", rollover_policy="extract_principal_roll_profit", leverage=5.0, window_id=window_id),
    ]


def _simulate_review_bankroll(
    scenario: ReviewScenario,
    *,
    market: Mapping[str, Any],
    direction: pd.Series,
    initial_capital: float,
    base_cost_bps: float,
) -> ReviewResult:
    direction = direction.dropna()
    bars = market["bars_4h"].reindex(direction.index)
    derivatives = market["derivatives_4h"].reindex(direction.index)
    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    close_returns = close.pct_change().fillna(0.0)
    funding = pd.to_numeric(derivatives.get("funding_rate", pd.Series(0.0, index=direction.index)), errors="coerce").fillna(0.0)
    sleeve_initial = float(initial_capital) / float(INITIAL_SLEEVE_COUNT)
    active_groups: list[SleeveGroup] = [SleeveGroup(count=INITIAL_SLEEVE_COUNT, equity=sleeve_initial, basis_equity=sleeve_initial)]
    reserve_cash = 0.0
    previous_side = 0.0
    total_sleeves_created = INITIAL_SLEEVE_COUNT
    rolled_sleeve_count = 0
    dead_sleeve_count = 0
    total_liquidations = 0
    max_same_bar_liquidations = 0
    max_sleeves_observed = INITIAL_SLEEVE_COUNT
    equity_curve: list[float] = []
    exposure_curve: list[float] = []
    event_rows: list[dict[str, Any]] = []
    fee_bps = float(base_cost_bps) / 2.0 * float(scenario.fee_multiplier)
    slippage_bps = float(base_cost_bps) / 2.0 * float(scenario.slippage_multiplier)
    cost_rate = (fee_bps + slippage_bps) / 10_000.0
    liq_threshold = max(0.0, 1.0 / float(scenario.leverage) - float(scenario.maintenance_margin_rate) - float(scenario.liquidation_fee_rate))

    for pos, ts in enumerate(direction.index):
        side = float(direction.iloc[pos])
        liquidations_this_bar = 0
        bar_return = 0.0 if pos == 0 else float(close_returns.iloc[pos])
        turnover_cost = cost_rate if side != previous_side else 0.0
        next_groups: list[SleeveGroup] = []
        for group in active_groups:
            if group.count <= 0 or group.equity <= 0.0:
                continue
            if side == 0.0:
                next_groups.append(group)
                continue
            adverse = _adverse_move(high=high, low=low, close=close, pos=pos, side=side)
            adverse += float(scenario.mark_adverse_bps) / 10_000.0
            adverse += abs(float(scenario.extra_shock_pct)) / 100.0
            if adverse >= liq_threshold:
                liquidations_this_bar += group.count
                total_liquidations += group.count
                dead_sleeve_count += group.count
                event_rows.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "timestamp": _ts(ts),
                        "event_type": "liquidation",
                        "sleeve_count": group.count,
                        "amount": _round(group.count * group.equity),
                        "adverse_move_pct": _round(adverse * 100.0),
                        "liquidation_threshold_pct": _round(liq_threshold * 100.0),
                        "paper_queue_write_allowed": False,
                        "live_unlock_allowed": False,
                    }
                )
                continue
            base_funding_return = -side * float(scenario.leverage) * float(funding.iloc[pos]) * (4.0 / 8.0)
            funding_return = base_funding_return - abs(base_funding_return) * max(0.0, float(scenario.funding_stress_multiplier) - 1.0)
            price_return = side * float(scenario.leverage) * bar_return
            net_return = price_return + funding_return - turnover_cost
            next_equity = group.equity * (1.0 + net_return)
            if next_equity <= 0.0:
                liquidations_this_bar += group.count
                dead_sleeve_count += group.count
                continue
            next_groups.append(SleeveGroup(count=group.count, equity=next_equity, basis_equity=group.basis_equity))

        active_groups = next_groups
        if side != 0.0 and active_groups:
            active_groups, reserve_cash, rolled_delta, created_delta, rollover_events = _apply_group_rollover(
                active_groups,
                scenario=scenario,
                ts=ts,
                reserve_cash=reserve_cash,
            )
            rolled_sleeve_count += rolled_delta
            total_sleeves_created += created_delta
            event_rows.extend(rollover_events)
        active_count = sum(group.count for group in active_groups)
        max_sleeves_observed = max(max_sleeves_observed, active_count)
        max_same_bar_liquidations = max(max_same_bar_liquidations, liquidations_this_bar)
        total_equity = reserve_cash + sum(group.count * max(0.0, group.equity) for group in active_groups)
        active_exposure = sum(abs(side) * scenario.leverage * group.count * group.equity for group in active_groups) / total_equity if total_equity > 0.0 else 0.0
        equity_curve.append(total_equity)
        exposure_curve.append(active_exposure)
        previous_side = side

    equity = pd.Series(equity_curve, index=direction.index, dtype=float)
    exposure = pd.Series(exposure_curve, index=direction.index, dtype=float)
    metrics = _metrics(
        equity=equity,
        exposure=exposure,
        initial_capital=initial_capital,
        reserve_cash=reserve_cash,
        active_sleeve_count=sum(group.count for group in active_groups),
        dead_sleeve_count=dead_sleeve_count,
        rolled_sleeve_count=rolled_sleeve_count,
        total_sleeve_count=total_sleeves_created,
        max_sleeves_observed=max_sleeves_observed,
        total_liquidations=total_liquidations,
        max_same_bar_liquidations=max_same_bar_liquidations,
        liq_threshold=liq_threshold,
    )
    return ReviewResult(scenario=scenario, equity=equity, exposure=exposure, metrics=metrics, event_rows=event_rows[:200])


def _apply_group_rollover(
    active_groups: list[SleeveGroup],
    *,
    scenario: ReviewScenario,
    ts: pd.Timestamp,
    reserve_cash: float,
) -> tuple[list[SleeveGroup], float, int, int, list[dict[str, Any]]]:
    groups: list[SleeveGroup] = []
    events: list[dict[str, Any]] = []
    rolled = 0
    created = 0
    current_active = sum(group.count for group in active_groups)
    for group in active_groups:
        if group.equity < group.basis_equity * ROLL_MULTIPLE:
            groups.append(group)
            continue
        if scenario.rollover_policy == "no_rollover":
            groups.append(SleeveGroup(count=group.count, equity=group.equity, basis_equity=group.equity))
            continue
        if scenario.rollover_policy == "extract_principal_roll_profit":
            extract_each = min(group.basis_equity, group.equity)
            reserve_cash += extract_each * group.count
            groups.append(SleeveGroup(count=group.count, equity=group.equity - extract_each, basis_equity=max(group.equity - extract_each, 1e-9)))
            events.append(_rollover_event(scenario=scenario, ts=ts, event_type="extract_principal", sleeve_count=group.count, amount=extract_each * group.count))
            continue
        split_count = 2 if scenario.rollover_policy == "split_2_on_double" else 5
        if current_active + group.count * (split_count - 1) > MAX_SLEEVE_COUNT:
            groups.append(SleeveGroup(count=group.count, equity=group.equity, basis_equity=group.equity))
            events.append(_rollover_event(scenario=scenario, ts=ts, event_type="rollover_skipped_max_sleeves", sleeve_count=group.count, amount=0.0))
            continue
        new_count = group.count * split_count
        child_equity = group.equity / split_count
        groups.append(SleeveGroup(count=new_count, equity=child_equity, basis_equity=child_equity))
        rolled += group.count
        created += group.count * (split_count - 1)
        current_active += group.count * (split_count - 1)
        events.append(_rollover_event(scenario=scenario, ts=ts, event_type=f"split_{split_count}_on_double", sleeve_count=group.count, amount=group.count * group.equity))
    return groups, reserve_cash, rolled, created, events


def _metrics(
    *,
    equity: pd.Series,
    exposure: pd.Series,
    initial_capital: float,
    reserve_cash: float,
    active_sleeve_count: int,
    dead_sleeve_count: int,
    rolled_sleeve_count: int,
    total_sleeve_count: int,
    max_sleeves_observed: int,
    total_liquidations: int,
    max_same_bar_liquidations: int,
    liq_threshold: float,
) -> dict[str, Any]:
    if equity.empty:
        return {}
    final_equity = float(equity.iloc[-1])
    total_return = final_equity / float(initial_capital) - 1.0
    elapsed_days = max(1.0, float((equity.index.max() - equity.index.min()).total_seconds()) / 86_400.0)
    annual_return = (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0 if total_return > -1.0 else -1.0
    drawdown = equity / equity.cummax() - 1.0
    return {
        "final_equity": _round(final_equity),
        "reserve_cash": _round(reserve_cash),
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "max_drawdown_abs_pct": _round(abs(float(drawdown.min())) * 100.0),
        "active_sleeve_count": int(active_sleeve_count),
        "dead_sleeve_count": int(dead_sleeve_count),
        "rolled_sleeve_count": int(rolled_sleeve_count),
        "total_sleeve_count": int(total_sleeve_count),
        "max_sleeves_observed": int(max_sleeves_observed),
        "total_liquidation_count": int(total_liquidations),
        "max_same_bar_liquidation_count": int(max_same_bar_liquidations),
        "all_sleeves_dead": bool(active_sleeve_count == 0),
        "average_gross_exposure": _round(float(exposure.mean()) if len(exposure) else 0.0),
        "max_gross_exposure": _round(float(exposure.max()) if len(exposure) else 0.0),
        "liquidation_threshold_pct": _round(liq_threshold * 100.0),
        "liquidation_threshold_bps": _round(liq_threshold * 10_000.0),
    }


def _result_row(result: ReviewResult) -> dict[str, Any]:
    s = result.scenario
    return {
        "scenario_id": s.scenario_id,
        "rollover_policy": s.rollover_policy,
        "leverage": s.leverage,
        "maintenance_margin_rate": s.maintenance_margin_rate,
        "liquidation_fee_rate": s.liquidation_fee_rate,
        "mark_adverse_bps": s.mark_adverse_bps,
        "extra_shock_pct": s.extra_shock_pct,
        "funding_stress_multiplier": s.funding_stress_multiplier,
        "fee_multiplier": s.fee_multiplier,
        "slippage_multiplier": s.slippage_multiplier,
        "window_id": s.window_id,
        **result.metrics,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _adverse_move(*, high: pd.Series, low: pd.Series, close: pd.Series, pos: int, side: float) -> float:
    if pos <= 0:
        return 0.0
    prev_close = float(close.iloc[pos - 1])
    if side > 0.0:
        return max(0.0, 1.0 - float(low.iloc[pos]) / prev_close)
    return max(0.0, float(high.iloc[pos]) / prev_close - 1.0)


def _attribution_bucket(policy: str, leverage: float) -> str:
    if leverage == 1.0:
        return "unlevered_signal"
    if policy == "no_rollover":
        return "leverage_plus_compounding"
    if policy == "split_2_on_double":
        return "rollover_split_effect"
    return "principal_extraction_effect"


def _liquidation_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ten_split = [row for row in rows if row.get("rollover_policy") == "split_2_on_double"]
    shock_rows = [row for row in ten_split if float(row.get("extra_shock_pct", 0.0)) < 0.0]
    return {
        "row_count": len(rows),
        "contains_100x_candidate": any(float(row.get("leverage", 0.0)) >= 100.0 for row in rows),
        "split_2_any_shock_all_dead_count": sum(1 for row in shock_rows if bool(row.get("all_sleeves_dead"))),
        "split_2_any_shock_liquidation_count": sum(1 for row in shock_rows if int(row.get("total_liquidation_count", 0)) > 0),
        "max_same_bar_liquidation_count": max((int(row.get("max_same_bar_liquidation_count", 0)) for row in rows), default=0),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _rolling_start_points(index: pd.DatetimeIndex, *, step_days: int) -> list[pd.Timestamp]:
    if len(index) == 0:
        return []
    start = index.min()
    end = index.max() - pd.Timedelta(days=60)
    points: list[pd.Timestamp] = []
    current = start
    while current <= end:
        nearest = index[index >= current]
        if len(nearest) == 0:
            break
        points.append(pd.Timestamp(nearest[0]))
        current += pd.Timedelta(days=step_days)
    return points


def _review_decision(*, liquidation_rows: Sequence[Mapping[str, Any]], segment_summary: Mapping[str, Any]) -> str:
    if bool(segment_summary.get("path_dependent")):
        return "path_dependent_not_forward_observation_ready"
    if any(bool(row.get("all_sleeves_dead")) for row in liquidation_rows):
        return "liquidation_sensitive_not_forward_observation_ready"
    return "bankroll_rollover_review_research_only_no_paper_no_live"


def _warnings(decision: str, liquidation_rows: Sequence[Mapping[str, Any]], segment_summary: Mapping[str, Any]) -> list[str]:
    warnings = ["btc_bankroll_rollover_review_research_only_no_paper_no_live"]
    if decision != "bankroll_rollover_review_research_only_no_paper_no_live":
        warnings.append(decision)
    if any(int(row.get("total_liquidation_count", 0)) > 0 for row in liquidation_rows):
        warnings.append("btc_bankroll_rollover_review_liquidation_sensitivity_observed")
    if bool(segment_summary.get("path_dependent")):
        warnings.append("btc_bankroll_rollover_review_rolling_start_path_dependency")
    return warnings


def _gate() -> dict[str, Any]:
    return {
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Bankroll rollover review is research-only and cannot promote paper/live.",
    }


def _guardrails() -> dict[str, Any]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "hundred_x_review_candidate_allowed": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_bankroll_rollover_review_safety_status_v1",
        "status": "research_only",
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "hundred_x_review_candidate_allowed": False,
        "reason": "Rollover review cannot promote a strategy to paper/live.",
        "blockers": list(report.get("blockers", [])),
    }


def render_btc_bankroll_rollover_review_markdown(report: Mapping[str, Any]) -> str:
    source = report.get("source_attribution", {}).get("summary", {})
    liq = report.get("liquidation_sensitivity", {}).get("summary", {})
    segment = report.get("segment_and_rolling_start", {}).get("summary", {})
    gate = report.get("gate", {})
    lines = [
        "# BTC 分仓滚仓复核包 v1",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 主要收益来源判断：`{source.get('main_driver')}`",
        f"- 10x split 相对 10x 不滚仓的最终权益增量：`{source.get('split_incremental_final_equity_vs_10x_no_rollover')}`",
        f"- 强平敏感性行数：`{liq.get('row_count')}`，含 100x 复核候选：`{liq.get('contains_100x_candidate')}`",
        f"- rolling start 数量：`{segment.get('rolling_start_count')}`，路径依赖：`{segment.get('path_dependent')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 复核结论",
        "",
        "本复核包只用于判断分仓滚仓收益来源和强平/成本敏感性。即使历史收益极高，也不能据此进入 paper 或 live。",
    ]
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _rollover_event(*, scenario: ReviewScenario, ts: pd.Timestamp, event_type: str, sleeve_count: int, amount: float) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "timestamp": _ts(ts),
        "event_type": event_type,
        "sleeve_count": int(sleeve_count),
        "amount": _round(amount),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _skipped_segment_row(*, scenario: ReviewScenario, row_type: str, reason: str) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "rollover_policy": scenario.rollover_policy,
        "leverage": scenario.leverage,
        "window_id": scenario.window_id,
        "row_type": row_type,
        "skipped": True,
        "skip_reason": reason,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _ts(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


def _slug_num(value: float) -> str:
    return str(value).replace(".", "p")


def _slug_pct(value: float) -> str:
    return str(_round(value * 100.0)).replace(".", "p")


def _slug_signed_pct(value: float) -> str:
    prefix = "m" if value < 0 else "p"
    return prefix + str(abs(value)).replace(".", "p")
