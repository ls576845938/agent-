from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.bankroll_attack_refinement_review import DEFAULT_REPORT_PATH as DEFAULT_ATTACK_REFINEMENT_REPORT_PATH
from quant_crypto.research.bankroll_layered_sleeve_scheduler_review import (
    LayeredScenario,
    LayeredSleeve,
    SleeveTemplate,
    _adverse_move,
    _pullback_visible,
    _select_sleeves,
    _total_equity,
    _ts,
)
from quant_crypto.research.bankroll_rollover_lab import INITIAL_SLEEVE_COUNT, _frozen_v3_direction
from quant_crypto.research.simple_trend_rule_lab import BASE_COST_BPS, DEFAULT_DERIVATIVES_ROWS, DEFAULT_MARKET_DB, INITIAL_CAPITAL
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path, _prepare_market_context, _round


SCHEMA_VERSION = "btc_bankroll_attack_top_confirmation_review_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_bankroll_attack_top_confirmation/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_attack_top_confirmation_report.json"
DEFAULT_LIQUIDATION_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_attack_top_confirmation_liquidation_sensitivity.csv"
DEFAULT_FUNDING_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_attack_top_confirmation_funding_cost_stress.csv"
DEFAULT_ROLLING_START_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_attack_top_confirmation_rolling_start.csv"
DEFAULT_EVENT_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_attack_top_confirmation_events.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_bankroll_attack_top_confirmation_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

TOP_SCENARIO_ID = "attack_ref_core5x6_reserve5x2_attack10x2_max8_atkcap1_delaylate_noextract"
MIN_REMAINING_AFTER_10PCT_SPIKE = 80.0
MAX_RESEARCH_LEVERAGE = 10.0


@dataclass(frozen=True)
class StressPolicy:
    policy_id: str
    stress_type: str
    maintenance_margin_rate: float = 0.005
    liquidation_fee_rate: float = 0.003
    mark_price_adverse_offset_bps: float = 0.0
    one_off_adverse_spike_pct: float = 10.0
    funding_adverse_multiplier: float = 1.0
    cost_multiplier: float = 1.0
    start_time: pd.Timestamp | None = None


@dataclass(frozen=True)
class StressResult:
    policy: StressPolicy
    metrics: dict[str, Any]
    event_rows: tuple[dict[str, Any], ...]


def build_btc_bankroll_attack_top_confirmation_review(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    source_attack_refinement_report_path: Path = DEFAULT_ATTACK_REFINEMENT_REPORT_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    liquidation_csv_path = output_dir / DEFAULT_LIQUIDATION_CSV_PATH.name
    funding_csv_path = output_dir / DEFAULT_FUNDING_CSV_PATH.name
    rolling_start_csv_path = output_dir / DEFAULT_ROLLING_START_CSV_PATH.name
    event_csv_path = output_dir / DEFAULT_EVENT_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    market = _prepare_market_context(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    blockers = [str(item) for item in market.get("blockers", [])]
    source_context = _source_context(source_attack_refinement_report_path)
    top_row = source_context.get("top_row", {})
    if not top_row:
        blockers.append("btc_attack_top_confirmation_missing_source_top_row")
    scenario = _scenario_from_source_row(top_row)

    direction = _frozen_v3_direction(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    bars_4h = market["bars_4h"].reindex(direction.index)

    base_result = _simulate_stress(
        scenario,
        market=market,
        direction=direction,
        policy=StressPolicy(policy_id="base_top_current_assumption", stress_type="base"),
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    liquidation_results = [
        _simulate_stress(
            scenario,
            market=market,
            direction=direction,
            policy=policy,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
        for policy in _liquidation_stress_policies()
    ]
    funding_results = [
        _simulate_stress(
            scenario,
            market=market,
            direction=direction,
            policy=policy,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
        for policy in _funding_cost_stress_policies()
    ]
    rolling_start_results = [
        _simulate_stress(
            scenario,
            market=market,
            direction=direction,
            policy=policy,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
        for policy in _rolling_start_policies(direction.index)
    ]

    liquidation_rows = [_result_row(item) for item in liquidation_results]
    funding_rows = [_result_row(item) for item in funding_results]
    rolling_start_rows = [_result_row(item) for item in rolling_start_results]
    base_row = _result_row(base_result)
    summary = _summary(
        base_row=base_row,
        liquidation_rows=liquidation_rows,
        funding_rows=funding_rows,
        rolling_start_rows=rolling_start_rows,
    )
    decision = _forward_observation_decision(summary)
    event_rows = []
    for result in [base_result, *liquidation_results, *funding_results, *rolling_start_results]:
        event_rows.extend(result.event_rows)

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": decision,
        "scope": "top_actual_10x_attack_liquidation_funding_rolling_start_confirmation",
        "code_commit": _git_commit(),
        "input": {
            "source_attack_refinement_report_path": _portable_path(source_attack_refinement_report_path),
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "market_4h_rows": int(len(bars_4h)),
            "market_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "market_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
            "direction_source": "frozen high-yield v3 loss-control direction, completed 1h->4h bars",
        },
        "source_context": {
            "source_schema_version": source_context.get("schema_version"),
            "source_decision": source_context.get("decision"),
            "source_top_scenario_id": source_context.get("top_scenario_id"),
            "source_top_total_return_pct": source_context.get("top_total_return_pct"),
            "source_top_min_remaining_capital_pct_after_10pct_spike": source_context.get("top_min_remaining_capital_pct_after_10pct_spike"),
        },
        "review_design": {
            "top_scenario_id": scenario.scenario_id,
            "objective": "confirm whether the selected actual 10x attack scheme is robust enough for 30/60 day research-only forward observation",
            "max_research_leverage": MAX_RESEARCH_LEVERAGE,
            "minimum_remaining_capital_pct_after_10pct_spike": MIN_REMAINING_AFTER_10PCT_SPIKE,
            "liquidation_sensitivity_grid": {
                "maintenance_margin_rate": [0.005, 0.008, 0.01],
                "liquidation_fee_rate": [0.003, 0.005, 0.01],
                "mark_price_adverse_offset_bps": [0.0, 50.0, 100.0, 200.0],
                "one_off_adverse_spike_pct": [0.0, 3.0, 5.0, 8.0, 10.0, 12.0],
            },
            "funding_cost_stress_grid": {
                "funding_adverse_multiplier": [1.0, 2.0, 5.0],
                "cost_multiplier": [1.0, 2.0, 5.0],
                "funding_model": "research stress treats extra funding multiplier as always adverse to the current side",
            },
            "rolling_start_rule": "rerun the same top scenario every 30 days; include starts with at least 90 days of remaining history",
            "promotion_evidence": False,
        },
        "base_top_result": base_row,
        "summary": summary,
        "forward_observation_decision": {
            "decision": decision,
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "strategy_skeleton_generated": False,
            "reason": _decision_reason(summary, decision),
        },
        "liquidation_sensitivity_sample": liquidation_rows[:25],
        "funding_cost_stress": funding_rows,
        "rolling_start_sample": rolling_start_rows[:25],
        "gate": _gate(decision),
        "guardrails": _guardrails(),
        "warnings": _warnings(summary, decision),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "liquidation_sensitivity_csv": _portable_path(liquidation_csv_path),
            "funding_cost_stress_csv": _portable_path(funding_csv_path),
            "rolling_start_csv": _portable_path(rolling_start_csv_path),
            "events_csv": _portable_path(event_csv_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(liquidation_csv_path, liquidation_rows)
    _write_csv(funding_csv_path, funding_rows)
    _write_csv(rolling_start_csv_path, rolling_start_rows)
    _write_csv(event_csv_path, event_rows[:1000])
    _write_text(markdown_path, render_btc_bankroll_attack_top_confirmation_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _simulate_stress(
    scenario: LayeredScenario,
    *,
    market: Mapping[str, Any],
    direction: pd.Series,
    policy: StressPolicy,
    initial_capital: float,
    base_cost_bps: float,
) -> StressResult:
    direction = direction.dropna()
    if policy.start_time is not None:
        direction = direction.loc[direction.index >= policy.start_time]
    bars = market["bars_4h"].reindex(direction.index)
    derivatives = market["derivatives_4h"].reindex(direction.index)
    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    returns = close.pct_change().fillna(0.0)
    funding = pd.to_numeric(derivatives.get("funding_rate", pd.Series(0.0, index=direction.index)), errors="coerce").fillna(0.0)

    sleeve_initial = float(initial_capital) / float(INITIAL_SLEEVE_COUNT)
    sleeves = [
        LayeredSleeve(
            sleeve_id=i + 1,
            role=template.role,
            leverage=template.leverage,
            entry_delay_bars=template.entry_delay_bars,
            equity=sleeve_initial,
            basis_equity=sleeve_initial,
        )
        for i, template in enumerate(scenario.sleeve_templates)
    ]
    equity_curve: list[float] = []
    exposed_count_curve: list[int] = []
    attack_exposed_curve: list[int] = []
    event_rows: list[dict[str, Any]] = []
    previous_signal = 0.0
    signal_age = 0
    normal_liquidation_count = 0
    max_same_bar_normal_liquidations = 0
    min_spike_remaining = 100.0
    max_spike_sleeves_lost = 0
    max_spike_equity_lost = 0.0
    trading_cost_amount = 0.0
    funding_cost_amount = 0.0
    fee_slippage_rate = float(base_cost_bps) / 10_000.0 * float(policy.cost_multiplier)
    mark_offset = float(policy.mark_price_adverse_offset_bps) / 10_000.0
    spike = float(policy.one_off_adverse_spike_pct) / 100.0

    for pos, ts in enumerate(direction.index):
        side = float(direction.iloc[pos])
        if side == 0.0:
            signal_age = 0
        elif side == previous_signal:
            signal_age += 1
        else:
            signal_age = 1

        pullback_visible = _pullback_visible(returns=returns, high=high, low=low, close=close, pos=pos, side=side)
        eligible = [
            sleeve
            for sleeve in sleeves
            if sleeve.status == "alive"
            and side != 0.0
            and signal_age > sleeve.entry_delay_bars
            and (sleeve.role != "reserve" or not scenario.reserve_requires_pullback or pullback_visible)
        ]
        selected_ids = _select_sleeves(eligible, scenario=scenario)
        normal_liquidations_this_bar = 0
        adverse = _adverse_move(high=high, low=low, close=close, pos=pos, side=side) + mark_offset
        bar_return = 0.0 if pos == 0 else float(returns.iloc[pos])

        for sleeve in sleeves:
            if sleeve.status != "alive":
                sleeve.exposed_side = 0.0
                continue
            should_expose = sleeve.sleeve_id in selected_ids
            turnover_cost = fee_slippage_rate if should_expose and sleeve.exposed_side != side else 0.0
            if not should_expose:
                sleeve.exposed_side = 0.0
                continue
            threshold = _liquidation_threshold(
                sleeve.leverage,
                maintenance_margin_rate=policy.maintenance_margin_rate,
                liquidation_fee_rate=policy.liquidation_fee_rate,
            )
            if adverse >= threshold:
                event_rows.append(
                    _event(
                        scenario=scenario,
                        policy=policy,
                        ts=ts,
                        event_type="normal_liquidation",
                        sleeve=sleeve,
                        amount=sleeve.equity,
                        note=f"adverse={_round(adverse * 100.0)} threshold={_round(threshold * 100.0)}",
                    )
                )
                sleeve.equity = 0.0
                sleeve.status = "liquidated"
                sleeve.exposed_side = 0.0
                sleeve.liquidation_count += 1
                normal_liquidation_count += 1
                normal_liquidations_this_bar += 1
                continue
            before_equity = sleeve.equity
            funding_return = _funding_return(
                side=side,
                leverage=sleeve.leverage,
                funding_rate=float(funding.iloc[pos]),
                adverse_multiplier=policy.funding_adverse_multiplier,
            )
            if funding_return < 0.0:
                funding_cost_amount += before_equity * abs(funding_return)
            if turnover_cost > 0.0:
                trading_cost_amount += before_equity * turnover_cost
            sleeve.equity = max(0.0, sleeve.equity * (1.0 + side * sleeve.leverage * bar_return + funding_return - turnover_cost))
            sleeve.exposed_side = side
            if sleeve.equity <= 0.0:
                sleeve.status = "dead"
                normal_liquidation_count += 1
                normal_liquidations_this_bar += 1
                continue
            if scenario.extract_on_double and sleeve.equity >= sleeve.basis_equity * 2.0:
                extracted = min(sleeve.basis_equity, sleeve.equity)
                sleeve.equity -= extracted
                sleeve.reserve_cash += extracted
                sleeve.basis_equity = max(sleeve.equity, 1e-9)
                sleeve.extract_count += 1
                event_rows.append(_event(scenario=scenario, policy=policy, ts=ts, event_type="extract_principal", sleeve=sleeve, amount=extracted, note="principal protected outside active sleeve"))

        total_equity = _total_equity(sleeves)
        exposed_sleeves = [sleeve for sleeve in sleeves if sleeve.status == "alive" and sleeve.exposed_side != 0.0]
        lost_equity = 0.0
        lost_count = 0
        for sleeve in exposed_sleeves:
            threshold = _liquidation_threshold(
                sleeve.leverage,
                maintenance_margin_rate=policy.maintenance_margin_rate,
                liquidation_fee_rate=policy.liquidation_fee_rate,
            )
            if adverse + spike >= threshold:
                lost_equity += sleeve.equity
                lost_count += 1
        remaining_pct = (total_equity - lost_equity) / max(1e-9, total_equity) * 100.0
        min_spike_remaining = min(min_spike_remaining, remaining_pct)
        max_spike_sleeves_lost = max(max_spike_sleeves_lost, lost_count)
        max_spike_equity_lost = max(max_spike_equity_lost, lost_equity)

        max_same_bar_normal_liquidations = max(max_same_bar_normal_liquidations, normal_liquidations_this_bar)
        equity_curve.append(total_equity)
        exposed_count_curve.append(len(exposed_sleeves))
        attack_exposed_curve.append(sum(1 for sleeve in exposed_sleeves if sleeve.role == "attack"))
        previous_signal = side

    equity = pd.Series(equity_curve, index=direction.index, dtype=float)
    drawdown = equity / equity.cummax() - 1.0 if len(equity) else pd.Series(dtype=float)
    final_equity = float(equity.iloc[-1]) if len(equity) else 0.0
    total_return = final_equity / float(initial_capital) - 1.0
    elapsed_days = max(1.0, float((direction.index.max() - direction.index.min()).total_seconds()) / 86_400.0) if len(direction) else 1.0
    annual_return = (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0 if total_return > -1.0 else -1.0
    exposed_series = pd.Series(exposed_count_curve)
    attack_series = pd.Series(attack_exposed_curve)
    alive_sleeves = [sleeve for sleeve in sleeves if sleeve.status == "alive"]
    reserve_cash = sum(sleeve.reserve_cash for sleeve in sleeves)
    metrics = {
        "scenario_id": scenario.scenario_id,
        "policy_id": policy.policy_id,
        "stress_type": policy.stress_type,
        "start_time": _ts(policy.start_time) if policy.start_time is not None else None,
        "maintenance_margin_rate": policy.maintenance_margin_rate,
        "liquidation_fee_rate": policy.liquidation_fee_rate,
        "mark_price_adverse_offset_bps": policy.mark_price_adverse_offset_bps,
        "one_off_adverse_spike_pct": policy.one_off_adverse_spike_pct,
        "funding_adverse_multiplier": policy.funding_adverse_multiplier,
        "cost_multiplier": policy.cost_multiplier,
        "final_equity": _round(final_equity),
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "max_drawdown_abs_pct": _round(abs(float(drawdown.min())) * 100.0) if len(drawdown) else 0.0,
        "reserve_cash": _round(reserve_cash),
        "reserve_cash_pct_of_initial": _round(reserve_cash / float(initial_capital) * 100.0),
        "alive_sleeve_count": len(alive_sleeves),
        "dead_sleeve_count": len(sleeves) - len(alive_sleeves),
        "normal_liquidation_count": normal_liquidation_count,
        "max_same_bar_normal_liquidations": max_same_bar_normal_liquidations,
        "average_concurrent_exposed_sleeves": _round(float(exposed_series.mean()) if len(exposed_series) else 0.0),
        "max_concurrent_exposed_sleeves_observed": int(exposed_series.max()) if len(exposed_series) else 0,
        "average_attack_exposed_sleeves": _round(float(attack_series.mean()) if len(attack_series) else 0.0),
        "max_attack_exposed_sleeves_observed": int(attack_series.max()) if len(attack_series) else 0,
        "extract_count": sum(sleeve.extract_count for sleeve in sleeves),
        "min_remaining_capital_pct_after_policy_spike": _round(min_spike_remaining),
        "max_sleeves_lost_single_policy_spike": int(max_spike_sleeves_lost),
        "max_equity_lost_single_policy_spike": _round(max_spike_equity_lost),
        "funding_cost_amount": _round(funding_cost_amount),
        "trading_cost_amount": _round(trading_cost_amount),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
    }
    return StressResult(policy=policy, metrics=metrics, event_rows=tuple(event_rows[:200]))


def _liquidation_stress_policies() -> list[StressPolicy]:
    policies: list[StressPolicy] = []
    for maintenance in (0.005, 0.008, 0.01):
        for liquidation_fee in (0.003, 0.005, 0.01):
            for mark_offset_bps in (0.0, 50.0, 100.0, 200.0):
                for spike_pct in (0.0, 3.0, 5.0, 8.0, 10.0, 12.0):
                    policies.append(
                        StressPolicy(
                            policy_id=f"liq_m{int(maintenance*10000)}bp_f{int(liquidation_fee*10000)}bp_mark{int(mark_offset_bps)}bp_spike{_spike_slug(spike_pct)}",
                            stress_type="liquidation_mark_index_spike",
                            maintenance_margin_rate=maintenance,
                            liquidation_fee_rate=liquidation_fee,
                            mark_price_adverse_offset_bps=mark_offset_bps,
                            one_off_adverse_spike_pct=spike_pct,
                        )
                    )
    return policies


def _funding_cost_stress_policies() -> list[StressPolicy]:
    policies: list[StressPolicy] = []
    for funding_multiplier in (1.0, 2.0, 5.0):
        for cost_multiplier in (1.0, 2.0, 5.0):
            policies.append(
                StressPolicy(
                    policy_id=f"funding{_mult_slug(funding_multiplier)}_cost{_mult_slug(cost_multiplier)}",
                    stress_type="funding_cost_stress",
                    funding_adverse_multiplier=funding_multiplier,
                    cost_multiplier=cost_multiplier,
                    one_off_adverse_spike_pct=10.0,
                )
            )
    return policies


def _rolling_start_policies(index: pd.Index) -> list[StressPolicy]:
    if len(index) == 0:
        return []
    start = pd.Timestamp(index.min()).tz_convert("UTC") if pd.Timestamp(index.min()).tzinfo else pd.Timestamp(index.min()).tz_localize("UTC")
    end = pd.Timestamp(index.max()).tz_convert("UTC") if pd.Timestamp(index.max()).tzinfo else pd.Timestamp(index.max()).tz_localize("UTC")
    policies: list[StressPolicy] = []
    current = start
    while current <= end - pd.Timedelta(days=90):
        policies.append(
            StressPolicy(
                policy_id=f"rolling_start_{current.strftime('%Y%m%d')}",
                stress_type="rolling_start",
                start_time=current,
                one_off_adverse_spike_pct=10.0,
            )
        )
        current += pd.Timedelta(days=30)
    return policies


def _summary(
    *,
    base_row: Mapping[str, Any],
    liquidation_rows: Sequence[Mapping[str, Any]],
    funding_rows: Sequence[Mapping[str, Any]],
    rolling_start_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    canonical_liq = [
        row
        for row in liquidation_rows
        if float(row.get("maintenance_margin_rate", 0.0)) <= 0.008
        and float(row.get("liquidation_fee_rate", 0.0)) <= 0.005
        and float(row.get("mark_price_adverse_offset_bps", 0.0)) <= 100.0
        and float(row.get("one_off_adverse_spike_pct", 0.0)) == 10.0
    ]
    severe_liq = [
        row
        for row in liquidation_rows
        if float(row.get("maintenance_margin_rate", 0.0)) >= 0.01
        and float(row.get("liquidation_fee_rate", 0.0)) >= 0.01
        and float(row.get("mark_price_adverse_offset_bps", 0.0)) >= 200.0
        and float(row.get("one_off_adverse_spike_pct", 0.0)) >= 12.0
    ]
    funding_5x_rows = [row for row in funding_rows if float(row.get("funding_adverse_multiplier", 0.0)) == 5.0]
    rolling_positive = [row for row in rolling_start_rows if float(row.get("total_return_pct", -100.0)) > 0.0]
    rolling_survive_80 = [row for row in rolling_start_rows if float(row.get("min_remaining_capital_pct_after_policy_spike", 0.0)) >= MIN_REMAINING_AFTER_10PCT_SPIKE]
    rolling_returns = [float(row.get("total_return_pct", 0.0)) for row in rolling_start_rows]
    positive_returns = [value for value in rolling_returns if value > 0.0]
    median_positive = _median(positive_returns)
    max_positive = max(positive_returns) if positive_returns else 0.0
    return {
        "top_scenario_id": base_row.get("scenario_id"),
        "base_total_return_pct": base_row.get("total_return_pct"),
        "base_annual_return_pct": base_row.get("annual_return_pct"),
        "base_max_drawdown_abs_pct": base_row.get("max_drawdown_abs_pct"),
        "base_normal_liquidation_count": base_row.get("normal_liquidation_count"),
        "base_min_remaining_capital_pct_after_10pct_spike": base_row.get("min_remaining_capital_pct_after_policy_spike"),
        "liquidation_sensitivity_row_count": len(liquidation_rows),
        "liquidation_survive_80_count": _count_survive(liquidation_rows),
        "liquidation_normal_liquidation_row_count": sum(1 for row in liquidation_rows if int(row.get("normal_liquidation_count", 0)) > 0),
        "liquidation_full_wipeout_row_count": sum(1 for row in liquidation_rows if float(row.get("final_equity", 0.0)) <= 1e-9),
        "canonical_10pct_stress_row_count": len(canonical_liq),
        "canonical_10pct_stress_survive_80_count": _count_survive(canonical_liq),
        "canonical_10pct_stress_min_remaining_capital_pct": _min_field(canonical_liq, "min_remaining_capital_pct_after_policy_spike"),
        "canonical_10pct_stress_max_normal_liquidation_count": max((int(row.get("normal_liquidation_count", 0)) for row in canonical_liq), default=0),
        "severe_stress_row_count": len(severe_liq),
        "severe_stress_survive_80_count": _count_survive(severe_liq),
        "severe_stress_min_remaining_capital_pct": _min_field(severe_liq, "min_remaining_capital_pct_after_policy_spike"),
        "funding_cost_stress_row_count": len(funding_rows),
        "funding_5x_positive_row_count": sum(1 for row in funding_5x_rows if float(row.get("total_return_pct", -100.0)) > 0.0),
        "funding_5x_min_total_return_pct": _min_field(funding_5x_rows, "total_return_pct"),
        "funding_cost_worst_total_return_pct": _min_field(funding_rows, "total_return_pct"),
        "funding_cost_worst_annual_return_pct": _min_field(funding_rows, "annual_return_pct"),
        "rolling_start_count": len(rolling_start_rows),
        "rolling_start_positive_count": len(rolling_positive),
        "rolling_start_positive_rate": _round(len(rolling_positive) / max(1, len(rolling_start_rows))),
        "rolling_start_survive_80_count": len(rolling_survive_80),
        "rolling_start_survive_80_rate": _round(len(rolling_survive_80) / max(1, len(rolling_start_rows))),
        "rolling_start_min_total_return_pct": _min_field(rolling_start_rows, "total_return_pct"),
        "rolling_start_median_positive_total_return_pct": _round(median_positive),
        "rolling_start_max_positive_total_return_pct": _round(max_positive),
        "rolling_start_max_to_median_positive_return_ratio": _round(max_positive / max(1e-9, median_positive)) if median_positive > 0.0 else 0.0,
        "rolling_start_normal_liquidation_row_count": sum(1 for row in rolling_start_rows if int(row.get("normal_liquidation_count", 0)) > 0),
        "rolling_start_full_wipeout_row_count": sum(1 for row in rolling_start_rows if float(row.get("final_equity", 0.0)) <= 1e-9),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _forward_observation_decision(summary: Mapping[str, Any]) -> str:
    base_pass = (
        int(summary.get("base_normal_liquidation_count", 999)) == 0
        and float(summary.get("base_min_remaining_capital_pct_after_10pct_spike", 0.0)) >= MIN_REMAINING_AFTER_10PCT_SPIKE
    )
    canonical_pass = int(summary.get("canonical_10pct_stress_row_count", 0)) > 0 and int(summary.get("canonical_10pct_stress_survive_80_count", 0)) == int(summary.get("canonical_10pct_stress_row_count", 0))
    funding_pass = int(summary.get("funding_5x_positive_row_count", 0)) >= 1 and float(summary.get("funding_5x_min_total_return_pct", -100.0)) > 0.0
    rolling_pass = (
        int(summary.get("rolling_start_count", 0)) >= 3
        and int(summary.get("rolling_start_full_wipeout_row_count", 999)) == 0
        and int(summary.get("rolling_start_normal_liquidation_row_count", 999)) == 0
        and float(summary.get("rolling_start_survive_80_rate", 0.0)) >= 0.70
    )
    path_dependency_ok = float(summary.get("rolling_start_max_to_median_positive_return_ratio", 999.0)) <= 100.0
    if base_pass and canonical_pass and funding_pass and rolling_pass and path_dependency_ok:
        return "eligible_for_30_60_day_forward_observation_research_only_no_paper_no_live"
    return "not_forward_observation_ready_due_to_liquidation_funding_or_path_dependency"


def _decision_reason(summary: Mapping[str, Any], decision: str) -> str:
    if decision.startswith("eligible"):
        return "Base, canonical 10pct spike stress, funding 5x stress, and rolling-start survival checks passed; observation only, no paper/live."
    return (
        "At least one confirmation check failed or remains too path-dependent: "
        f"canonical_survive={summary.get('canonical_10pct_stress_survive_80_count')}/{summary.get('canonical_10pct_stress_row_count')}, "
        f"funding5x_min_return={summary.get('funding_5x_min_total_return_pct')}, "
        f"rolling_survive80_rate={summary.get('rolling_start_survive_80_rate')}, "
        f"path_ratio={summary.get('rolling_start_max_to_median_positive_return_ratio')}."
    )


def _result_row(result: StressResult) -> dict[str, Any]:
    return dict(result.metrics)


def _source_context(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    top_rows = report.get("top_attack_watchlist", [])
    top_row = top_rows[0] if isinstance(top_rows, list) and top_rows else {}
    summary = report.get("summary", {})
    if not isinstance(summary, Mapping):
        summary = {}
    return {
        "schema_version": report.get("schema_version"),
        "decision": report.get("decision"),
        "top_row": top_row,
        "top_scenario_id": top_row.get("scenario_id") or summary.get("best_return_watchlist_scenario_id"),
        "top_total_return_pct": top_row.get("total_return_pct") or summary.get("best_return_watchlist_total_return_pct"),
        "top_min_remaining_capital_pct_after_10pct_spike": top_row.get("min_remaining_capital_pct_after_10pct_spike") or summary.get("best_return_watchlist_min_remaining_capital_pct_after_10pct_spike"),
    }


def _scenario_from_source_row(row: Mapping[str, Any]) -> LayeredScenario:
    if not row:
        return _default_top_scenario()
    roles = _loads_list(row.get("sleeve_roles"))
    leverages = [float(item) for item in _loads_list(row.get("sleeve_leverages"))]
    delays = [int(float(item)) for item in _loads_list(row.get("sleeve_entry_delay_bars"))]
    if not roles or len(roles) != len(leverages) or len(roles) != len(delays):
        return _default_top_scenario()
    return LayeredScenario(
        scenario_id=str(row.get("scenario_id") or TOP_SCENARIO_ID),
        policy_id="top_actual_10x_attack_confirmation",
        sleeve_templates=tuple(SleeveTemplate(str(role), float(leverage), int(delay)) for role, leverage, delay in zip(roles, leverages, delays)),
        max_total_exposed=int(row.get("max_total_exposed") or 8),
        max_attack_exposed=int(row.get("max_attack_exposed") or 1),
        extract_on_double=bool(row.get("extract_on_double")),
        reserve_requires_pullback=bool(row.get("reserve_requires_pullback", True)),
    )


def _default_top_scenario() -> LayeredScenario:
    templates = [
        *(SleeveTemplate("core", 5.0, delay) for delay in (0, 1, 2, 0, 1, 2)),
        SleeveTemplate("reserve", 5.0, 6),
        SleeveTemplate("reserve", 5.0, 9),
        SleeveTemplate("attack", 10.0, 6),
        SleeveTemplate("attack", 10.0, 9),
    ]
    return LayeredScenario(
        scenario_id=TOP_SCENARIO_ID,
        policy_id="top_actual_10x_attack_confirmation",
        sleeve_templates=tuple(templates),
        max_total_exposed=8,
        max_attack_exposed=1,
        extract_on_double=False,
        reserve_requires_pullback=True,
    )


def _loads_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        loaded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return loaded if isinstance(loaded, list) else []


def _liquidation_threshold(leverage: float, *, maintenance_margin_rate: float, liquidation_fee_rate: float) -> float:
    return max(0.0, 1.0 / float(leverage) - float(maintenance_margin_rate) - float(liquidation_fee_rate))


def _funding_return(*, side: float, leverage: float, funding_rate: float, adverse_multiplier: float) -> float:
    base = -float(side) * float(leverage) * float(funding_rate) * (4.0 / 8.0)
    extra_adverse = -float(leverage) * abs(float(funding_rate)) * (4.0 / 8.0) * max(0.0, float(adverse_multiplier) - 1.0)
    return base + extra_adverse


def _event(*, scenario: LayeredScenario, policy: StressPolicy, ts: pd.Timestamp, event_type: str, sleeve: LayeredSleeve, amount: float, note: str) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "policy_id": policy.policy_id,
        "stress_type": policy.stress_type,
        "timestamp": _ts(ts),
        "event_type": event_type,
        "sleeve_id": sleeve.sleeve_id,
        "role": sleeve.role,
        "leverage": sleeve.leverage,
        "amount": _round(amount),
        "note": note,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _count_survive(rows: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for row in rows if float(row.get("min_remaining_capital_pct_after_policy_spike", 0.0)) >= MIN_REMAINING_AFTER_10PCT_SPIKE and int(row.get("normal_liquidation_count", 0)) == 0)


def _min_field(rows: Sequence[Mapping[str, Any]], field: str) -> float:
    values = [float(row.get(field, 0.0)) for row in rows]
    return _round(min(values)) if values else 0.0


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _spike_slug(value: float) -> str:
    return str(value).replace(".", "p")


def _mult_slug(value: float) -> str:
    return str(value).replace(".", "p") + "x"


def _gate(decision: str) -> dict[str, Any]:
    return {
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "forward_observation_research_only_allowed": decision.startswith("eligible_for_30_60_day_forward_observation"),
        "reason": "Top attack confirmation is research-only. Forward observation, if allowed, is not paper/live.",
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
        "max_research_leverage": MAX_RESEARCH_LEVERAGE,
    }


def _warnings(summary: Mapping[str, Any], decision: str) -> list[str]:
    warnings = ["btc_attack_top_confirmation_research_only_no_paper_no_live"]
    if not decision.startswith("eligible"):
        warnings.append("btc_attack_top_confirmation_not_forward_observation_ready")
    if int(summary.get("liquidation_normal_liquidation_row_count", 0)) > 0:
        warnings.append("btc_attack_top_confirmation_liquidation_stress_has_failures")
    if int(summary.get("severe_stress_survive_80_count", 0)) < int(summary.get("severe_stress_row_count", 0)):
        warnings.append("btc_attack_top_confirmation_extreme_mark_spike_can_destroy_most_capital")
    if float(summary.get("rolling_start_max_to_median_positive_return_ratio", 0.0)) > 100.0:
        warnings.append("btc_attack_top_confirmation_path_dependent")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    gate = report.get("gate", {})
    return {
        "schema_version": "btc_bankroll_attack_top_confirmation_safety_status_v1",
        "status": "research_only",
        "forward_observation_research_only_allowed": bool(gate.get("forward_observation_research_only_allowed")),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "hundred_x_review_candidate_allowed": False,
        "max_research_leverage": MAX_RESEARCH_LEVERAGE,
        "reason": "Top attack confirmation cannot promote a strategy to paper/live.",
        "blockers": list(report.get("blockers", [])),
    }


def render_btc_bankroll_attack_top_confirmation_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    gate = report.get("gate", {})
    decision = report.get("forward_observation_decision", {})
    lines = [
        "# BTC 10x attack Top 方案确认复核包",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策：`{report.get('decision')}`",
        f"- Top 方案：`{summary.get('top_scenario_id')}`",
        f"- 基准总收益：`{summary.get('base_total_return_pct')}`%",
        f"- 基准年化：`{summary.get('base_annual_return_pct')}`%",
        f"- 基准最大回撤：`{summary.get('base_max_drawdown_abs_pct')}`%",
        f"- 基准 -10% 插针后剩余本金：`{summary.get('base_min_remaining_capital_pct_after_10pct_spike')}`%",
        f"- 强平压力行数：`{summary.get('liquidation_sensitivity_row_count')}`，存活 80%+ 行数：`{summary.get('liquidation_survive_80_count')}`",
        f"- 标准 10% 压力最差剩余本金：`{summary.get('canonical_10pct_stress_min_remaining_capital_pct')}`%",
        f"- funding/cost 压力最差总收益：`{summary.get('funding_cost_worst_total_return_pct')}`%",
        f"- rolling start 数量：`{summary.get('rolling_start_count')}`，80%+ 存活比例：`{summary.get('rolling_start_survive_80_rate')}`",
        f"- rolling start 最大/中位正收益比：`{summary.get('rolling_start_max_to_median_positive_return_ratio')}`",
        f"- 是否允许进入 30/60 天 research-only forward observation：`{gate.get('forward_observation_research_only_allowed')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 结论口径",
        "",
        str(decision.get("reason")),
    ]
    return "\n".join(lines) + "\n"


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
