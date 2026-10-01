from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research import high_octane_attack_sleeve_lab as high_octane
from quant_crypto.research.bankroll_rollover_lab import INITIAL_SLEEVE_COUNT, _frozen_v3_direction
from quant_crypto.research.pyramiding_sleeve_lab import ROLE_PRIORITY, PyramidTemplate
from quant_crypto.research.simple_trend_rule_lab import BASE_COST_BPS, DEFAULT_DERIVATIVES_ROWS, DEFAULT_MARKET_DB, INITIAL_CAPITAL
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path, _prepare_market_context, _round
from quant_crypto.research.ten_u_rollover_rulebook_lab import (
    CONSECUTIVE_LOSS_PAUSE_TRIGGER,
    COOLDOWN_HOURS_AFTER_LOSS,
    GLOBAL_PAUSE_DAYS,
    LEVERAGE_DERISK_MULTIPLIER_AFTER_LOSS,
    PROFIT_EXTRACT_FLOATING_FRACTION,
    PROFIT_EXTRACT_MULTIPLE,
    SPIKE_STRESS_PCTS,
    WEEKLY_PROFIT_SAFE_TRANSFER_FRACTION,
    WEEKLY_PROFIT_STRATEGIC_RESERVE_FRACTION,
)


SCHEMA_VERSION = "btc_high_octane_10u_discipline_overlay_lab_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_high_octane_10u_discipline_overlay_lab/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_high_octane_10u_discipline_overlay_lab_report.json"
DEFAULT_GRID_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_high_octane_10u_discipline_overlay_lab_grid.csv"
DEFAULT_EVENTS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_high_octane_10u_discipline_overlay_lab_events.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_high_octane_10u_discipline_overlay_lab_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"
DEFAULT_HIGH_OCTANE_WATCHLIST_PATH = high_octane.DEFAULT_OUTPUT_DIR / "btc_high_octane_attack_sleeve_lab_watchlist.csv"

TOP_N_DEFAULT = 20
COOLDOWN_BARS_4H = COOLDOWN_HOURS_AFTER_LOSS // 4
GLOBAL_PAUSE_BARS_4H = GLOBAL_PAUSE_DAYS * 24 // 4
MIN_LEVERAGE_SCALE = 0.25
MAX_RESEARCH_LEVERAGE = 10.0


@dataclass(frozen=True)
class OverlayCandidate:
    source_rank: int
    source_row: dict[str, Any]
    scenario: high_octane.HighOctaneScenario


@dataclass(frozen=True)
class OverlayResult:
    candidate: OverlayCandidate
    metrics: dict[str, Any]
    events: tuple[dict[str, Any], ...]


def build_btc_high_octane_10u_discipline_overlay_lab(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    high_octane_watchlist_path: Path = DEFAULT_HIGH_OCTANE_WATCHLIST_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
    top_n: int = TOP_N_DEFAULT,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    grid_path = output_dir / DEFAULT_GRID_CSV_PATH.name
    events_path = output_dir / DEFAULT_EVENTS_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    blockers: list[str] = []
    source_rows = _read_csv(high_octane_watchlist_path, blockers)
    candidates = _candidate_specs(source_rows[: max(1, int(top_n))])
    if not candidates:
        blockers.append("btc_high_octane_10u_overlay_no_source_candidates")
    market = _prepare_market_context(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    blockers.extend(str(item) for item in market.get("blockers", []))
    direction = pd.Series(dtype=float)
    if not blockers:
        direction = _frozen_v3_direction(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)

    results: list[OverlayResult] = []
    event_rows: list[dict[str, Any]] = []
    if not blockers:
        for candidate in candidates:
            result = _simulate_overlay(
                candidate,
                market=market,
                direction=direction,
                initial_capital=initial_capital,
                base_cost_bps=base_cost_bps,
            )
            results.append(result)
            event_rows.extend(result.events)

    grid_rows = sorted((_result_row(result) for result in results), key=_rank_key)
    watchlist_rows = [row for row in grid_rows if row["research_decision"] == "retain_high_octane_10u_overlay_research_watchlist_only"]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_high_octane_10u_discipline_overlay_lab_research_only_no_paper_no_live",
        "scope": "high_octane_attack_sleeve_with_10u_risk_discipline_overlay_research_only",
        "code_commit": _git_commit(),
        "research_question": "Does adding 10U bankroll discipline to the stronger High-Octane Donchian attack sleeve improve survivability without destroying convexity?",
        "economic_hypothesis": "The High-Octane direction and staged attack sleeve may supply trend convexity, while 10U discipline may reduce path-dependence through cooldown, leverage derisk, profit extraction and safe-account transfers.",
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "high_octane_watchlist_path": _portable_path(high_octane_watchlist_path),
            "source_candidate_count": len(candidates),
            "market_4h_rows": int(len(market.get("bars_4h", []))),
            "market_4h_start": _ts(market["bars_4h"].index.min()) if len(market.get("bars_4h", [])) else None,
            "market_4h_end": _ts(market["bars_4h"].index.max()) if len(market.get("bars_4h", [])) else None,
            "direction_source": "existing frozen Donchian high-yield v3 direction; overlay only changes money/risk discipline",
        },
        "research_design": _research_design(candidate_count=len(candidates), top_n=top_n),
        "summary": _summary(grid_rows=grid_rows, watchlist_rows=watchlist_rows),
        "top_watchlist": watchlist_rows[:20],
        "grid_rows_sample": grid_rows[:25],
        "event_sample": event_rows[:300],
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(blockers=blockers, grid_rows=grid_rows),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "grid_csv": _portable_path(grid_path),
            "events_csv": _portable_path(events_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(grid_path, grid_rows)
    _write_csv(events_path, event_rows[:1500])
    _write_text(markdown_path, render_btc_high_octane_10u_discipline_overlay_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _candidate_specs(rows: Sequence[Mapping[str, Any]]) -> list[OverlayCandidate]:
    scenario_by_id = {scenario.scenario_id: scenario for scenario in high_octane._scenario_grid()}
    candidates: list[OverlayCandidate] = []
    seen: set[str] = set()
    for rank, row in enumerate(rows, start=1):
        scenario_id = str(row.get("scenario_id", ""))
        scenario = scenario_by_id.get(scenario_id)
        if scenario is None or scenario_id in seen:
            continue
        seen.add(scenario_id)
        candidates.append(OverlayCandidate(source_rank=rank, source_row=dict(row), scenario=scenario))
    return candidates


def _simulate_overlay(
    candidate: OverlayCandidate,
    *,
    market: Mapping[str, Any],
    direction: pd.Series,
    initial_capital: float,
    base_cost_bps: float,
) -> OverlayResult:
    scenario = candidate.scenario
    direction = direction.dropna()
    bars = market["bars_4h"].reindex(direction.index)
    derivatives = market["derivatives_4h"].reindex(direction.index)
    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    returns = close.pct_change().fillna(0.0)
    atr = high_octane._atr(bars, 20).reindex(direction.index).ffill().fillna(0.0)
    funding = pd.to_numeric(derivatives.get("funding_rate", pd.Series(0.0, index=direction.index)), errors="coerce").fillna(0.0)

    templates = list(scenario.sleeve_templates)
    sleeve_count = len(templates)
    sleeve_initial = float(initial_capital) / float(INITIAL_SLEEVE_COUNT)
    roles = [template.role for template in templates]
    base_leverages = [float(template.leverage) for template in templates]
    entry_delays = [int(template.entry_delay_bars) for template in templates]
    triggers = [float(template.trigger_atr) for template in templates]
    sorted_indices = sorted(range(sleeve_count), key=lambda idx: (ROLE_PRIORITY[roles[idx]], triggers[idx], entry_delays[idx], idx))
    equity_values = [sleeve_initial for _ in range(sleeve_count)]
    basis_values = [sleeve_initial for _ in range(sleeve_count)]
    alive_values = [True for _ in range(sleeve_count)]
    exposed_side_values = [0.0 for _ in range(sleeve_count)]
    safe_cash = 0.0
    strategic_reserve = 0.0
    leverage_scale = 1.0
    cooldown_remaining = 0
    global_pause_remaining = 0
    loss_streak = 0
    previous_signal = 0.0
    signal_age = 0
    campaign_anchor: float | None = None
    last_week_key: tuple[int, int] | None = None
    counts = {
        "normal_liquidation_count": 0,
        "cooldown_count": 0,
        "leverage_derisk_count": 0,
        "global_pause_count": 0,
        "extract_count": 0,
        "weekly_safe_transfer_count": 0,
        "pyramid_entry_count": 0,
        "loss_bar_count": 0,
    }
    min_remaining = {shock: 100.0 for shock in SPIKE_STRESS_PCTS}
    max_sleeves_lost = {shock: 0 for shock in SPIKE_STRESS_PCTS}
    max_same_bar_liquidations = 0
    funding_cost_amount = 0.0
    turnover_cost_amount = 0.0
    equity_curve: list[float] = []
    exposure_curve: list[int] = []
    attack_curve: list[int] = []
    events: list[dict[str, Any]] = []
    fee_rate = float(base_cost_bps) / 10_000.0
    last_total_equity = float(initial_capital)

    for pos, ts in enumerate(direction.index):
        raw_side = float(direction.iloc[pos])
        side = raw_side
        if cooldown_remaining > 0:
            cooldown_remaining -= 1
            side = 0.0
        if global_pause_remaining > 0:
            global_pause_remaining -= 1
            side = 0.0
        close_value = float(close.iloc[pos])
        if side == 0.0:
            signal_age = 0
            campaign_anchor = None
        elif side == previous_signal and campaign_anchor is not None:
            signal_age += 1
        else:
            signal_age = 1
            campaign_anchor = float(close.iloc[pos - 1]) if pos > 0 else close_value
        favorable_atr = high_octane._favorable_atr(close=close_value, anchor=campaign_anchor, side=side, atr=float(atr.iloc[pos]))
        pullback_visible = high_octane._pullback_visible_array(
            returns=returns.to_numpy(),
            high=high.to_numpy(),
            low=low.to_numpy(),
            close=close.to_numpy(),
            pos=pos,
            side=side,
        )
        selected = [False for _ in range(sleeve_count)]
        if side != 0.0:
            selected_count = 0
            selected_attack_count = 0
            for sleeve_idx in sorted_indices:
                if selected_count >= int(scenario.max_total_exposed):
                    break
                if not alive_values[sleeve_idx]:
                    continue
                if signal_age <= entry_delays[sleeve_idx] or favorable_atr < triggers[sleeve_idx]:
                    continue
                role = roles[sleeve_idx]
                if role == "reserve" and scenario.reserve_requires_pullback and not pullback_visible:
                    continue
                if role == "attack" and selected_attack_count >= int(scenario.max_attack_exposed):
                    continue
                selected[sleeve_idx] = True
                selected_count += 1
                if role == "attack":
                    selected_attack_count += 1

        adverse = _adverse_move(high=float(high.iloc[pos]), low=float(low.iloc[pos]), close=close, pos=pos, side=side)
        bar_return = 0.0 if pos == 0 else float(returns.iloc[pos])
        normal_liq_this_bar = 0
        for sleeve_idx in range(sleeve_count):
            if not alive_values[sleeve_idx]:
                exposed_side_values[sleeve_idx] = 0.0
                continue
            if not selected[sleeve_idx]:
                exposed_side_values[sleeve_idx] = 0.0
                continue
            effective_leverage = max(1.0, min(base_leverages[sleeve_idx], base_leverages[sleeve_idx] * leverage_scale))
            if exposed_side_values[sleeve_idx] == 0.0 and triggers[sleeve_idx] > 0.0:
                counts["pyramid_entry_count"] += 1
            if adverse >= _liquidation_threshold(effective_leverage):
                events.append(_event(candidate=candidate, ts=ts, event_type="normal_liquidation", sleeve_idx=sleeve_idx, role=roles[sleeve_idx], leverage=effective_leverage, amount=equity_values[sleeve_idx], note="isolated sleeve killed; safe account retained"))
                equity_values[sleeve_idx] = 0.0
                alive_values[sleeve_idx] = False
                exposed_side_values[sleeve_idx] = 0.0
                counts["normal_liquidation_count"] += 1
                normal_liq_this_bar += 1
                continue
            before = equity_values[sleeve_idx]
            turnover_cost = fee_rate if exposed_side_values[sleeve_idx] != side else 0.0
            funding_return = -side * effective_leverage * float(funding.iloc[pos]) * (4.0 / 8.0)
            if funding_return < 0.0:
                funding_cost_amount += before * abs(funding_return)
            turnover_cost_amount += before * turnover_cost
            equity_values[sleeve_idx] = max(0.0, before * (1.0 + side * effective_leverage * bar_return + funding_return - turnover_cost))
            exposed_side_values[sleeve_idx] = side
            if equity_values[sleeve_idx] >= basis_values[sleeve_idx] * PROFIT_EXTRACT_MULTIPLE:
                floating_profit = max(0.0, equity_values[sleeve_idx] - basis_values[sleeve_idx])
                extracted = floating_profit * PROFIT_EXTRACT_FLOATING_FRACTION
                equity_values[sleeve_idx] -= extracted
                safe_cash += extracted
                basis_values[sleeve_idx] = max(equity_values[sleeve_idx], 1e-9)
                counts["extract_count"] += 1
                events.append(_event(candidate=candidate, ts=ts, event_type="extract_50pct_floating_profit_to_safe_account", sleeve_idx=sleeve_idx, role=roles[sleeve_idx], leverage=effective_leverage, amount=extracted, note="10U profit extraction overlay"))
        max_same_bar_liquidations = max(max_same_bar_liquidations, normal_liq_this_bar)

        if _week_key(ts) != last_week_key:
            safe_delta, reserve_delta, transfer_count = _weekly_transfer_unexposed(
                equity_values=equity_values,
                exposed_side_values=exposed_side_values,
                alive_values=alive_values,
                sleeve_initial=sleeve_initial,
            )
            if transfer_count:
                safe_cash += safe_delta
                strategic_reserve += reserve_delta
                counts["weekly_safe_transfer_count"] += transfer_count
            last_week_key = _week_key(ts)

        total_equity = sum(max(0.0, equity_values[idx]) for idx in range(sleeve_count) if alive_values[idx]) + safe_cash + strategic_reserve
        exposed_indices = [idx for idx in range(sleeve_count) if alive_values[idx] and exposed_side_values[idx] != 0.0]
        for shock in SPIKE_STRESS_PCTS:
            lost_equity = 0.0
            lost_count = 0
            for sleeve_idx in exposed_indices:
                effective_leverage = max(1.0, min(base_leverages[sleeve_idx], base_leverages[sleeve_idx] * leverage_scale))
                if shock / 100.0 >= _liquidation_threshold(effective_leverage):
                    lost_equity += equity_values[sleeve_idx]
                    lost_count += 1
            remaining = (total_equity - lost_equity) / max(1e-9, total_equity) * 100.0
            min_remaining[shock] = min(min_remaining[shock], remaining)
            max_sleeves_lost[shock] = max(max_sleeves_lost[shock], lost_count)
        if exposed_indices and total_equity < last_total_equity:
            loss_streak += 1
            counts["loss_bar_count"] += 1
            cooldown_remaining = max(cooldown_remaining, COOLDOWN_BARS_4H)
            leverage_scale = max(MIN_LEVERAGE_SCALE, leverage_scale * LEVERAGE_DERISK_MULTIPLIER_AFTER_LOSS)
            counts["cooldown_count"] += 1
            counts["leverage_derisk_count"] += 1
            if loss_streak >= CONSECUTIVE_LOSS_PAUSE_TRIGGER:
                global_pause_remaining = max(global_pause_remaining, GLOBAL_PAUSE_BARS_4H)
                counts["global_pause_count"] += 1
                loss_streak = 0
        elif total_equity >= last_total_equity:
            loss_streak = 0
        equity_curve.append(total_equity)
        exposure_curve.append(len(exposed_indices))
        attack_curve.append(sum(1 for idx in exposed_indices if roles[idx] == "attack"))
        last_total_equity = total_equity
        previous_signal = raw_side

    equity = pd.Series(equity_curve, index=direction.index[: len(equity_curve)], dtype=float)
    drawdown = equity / equity.cummax() - 1.0 if len(equity) else pd.Series(dtype=float)
    final_equity = float(equity_curve[-1]) if equity_curve else float(initial_capital)
    total_return = final_equity / float(initial_capital) - 1.0
    elapsed_days = max(1.0, float((direction.index.max() - direction.index.min()).total_seconds()) / 86_400.0) if len(direction) else 1.0
    annual_return = (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0 if total_return > -1.0 else -1.0
    exposure_series = pd.Series(exposure_curve, dtype=float)
    attack_series = pd.Series(attack_curve, dtype=float)
    metrics: dict[str, Any] = {
        "final_equity": _round(final_equity),
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "max_drawdown_abs_pct": _round(abs(float(drawdown.min())) * 100.0) if len(drawdown) else 0.0,
        "safe_cash": _round(safe_cash),
        "strategic_reserve": _round(strategic_reserve),
        "safe_plus_reserve_pct_of_initial": _round((safe_cash + strategic_reserve) / float(initial_capital) * 100.0),
        "alive_sleeve_count": sum(1 for alive in alive_values if alive),
        "dead_sleeve_count": sum(1 for alive in alive_values if not alive),
        "average_concurrent_exposed_sleeves": _round(float(exposure_series.mean()) if len(exposure_series) else 0.0),
        "max_concurrent_exposed_sleeves_observed": int(exposure_series.max()) if len(exposure_series) else 0,
        "average_attack_exposed_sleeves": _round(float(attack_series.mean()) if len(attack_series) else 0.0),
        "max_attack_exposed_sleeves_observed": int(attack_series.max()) if len(attack_series) else 0,
        "max_same_bar_normal_liquidations": max_same_bar_liquidations,
        "final_leverage_scale": _round(leverage_scale),
        "funding_cost_amount": _round(funding_cost_amount),
        "turnover_cost_amount": _round(turnover_cost_amount),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
    }
    metrics.update({key: int(value) for key, value in counts.items()})
    for shock in SPIKE_STRESS_PCTS:
        slug = _shock_slug(shock)
        metrics[f"min_remaining_capital_pct_after_{slug}_spike"] = _round(min_remaining[shock])
        metrics[f"max_sleeves_lost_single_{slug}_spike"] = int(max_sleeves_lost.get(shock, 0))
    return OverlayResult(candidate=candidate, metrics=metrics, events=tuple(events[:500]))


def _weekly_transfer_unexposed(
    *,
    equity_values: list[float],
    exposed_side_values: Sequence[float],
    alive_values: Sequence[bool],
    sleeve_initial: float,
) -> tuple[float, float, int]:
    safe_delta = 0.0
    reserve_delta = 0.0
    count = 0
    for idx, equity in enumerate(equity_values):
        if not alive_values[idx] or exposed_side_values[idx] != 0.0:
            continue
        profit = equity - sleeve_initial
        if profit <= 0.0:
            continue
        safe_delta += profit * WEEKLY_PROFIT_SAFE_TRANSFER_FRACTION
        reserve_delta += profit * WEEKLY_PROFIT_STRATEGIC_RESERVE_FRACTION
        equity_values[idx] = sleeve_initial
        count += 1
    return safe_delta, reserve_delta, count


def _result_row(result: OverlayResult) -> dict[str, Any]:
    candidate = result.candidate
    row = {
        "source_rank": candidate.source_rank,
        "scenario_id": candidate.scenario.scenario_id,
        "source_annual_return_pct": _float(candidate.source_row.get("annual_return_pct")),
        "source_total_return_pct": _float(candidate.source_row.get("total_return_pct")),
        "source_max_drawdown_abs_pct": _float(candidate.source_row.get("max_drawdown_abs_pct")),
        "source_min_remaining_after_10pct_spike": _float(candidate.source_row.get("min_remaining_capital_pct_after_10pct_spike")),
        "overlay": "10u_discipline_cooldown_derisk_pause_extract_safe_account",
        "max_template_leverage": max(float(template.leverage) for template in candidate.scenario.sleeve_templates),
        **result.metrics,
    }
    row["annual_return_delta_vs_source_pct"] = _round(float(row["annual_return_pct"]) - float(row["source_annual_return_pct"]))
    row["drawdown_delta_vs_source_pct"] = _round(float(row["max_drawdown_abs_pct"]) - float(row["source_max_drawdown_abs_pct"]))
    row["research_decision"] = _research_decision(row)
    return row


def _research_decision(row: Mapping[str, Any]) -> str:
    if _float(row.get("max_template_leverage")) > MAX_RESEARCH_LEVERAGE:
        return "reject_leverage_above_10x"
    if _float(row.get("total_return_pct")) <= 0.0:
        return "reject_non_positive_overlay_return"
    if _int(row.get("normal_liquidation_count")) > 0:
        return "reject_overlay_normal_liquidation_observed"
    if _float(row.get("min_remaining_capital_pct_after_10pct_spike")) < 40.0:
        return "reject_overlay_below_40pct_remaining_after_10pct_spike"
    return "retain_high_octane_10u_overlay_research_watchlist_only"


def _rank_key(row: Mapping[str, Any]) -> tuple[int, float, float, float, str]:
    retained = 0 if row.get("research_decision") == "retain_high_octane_10u_overlay_research_watchlist_only" else 1
    return (
        retained,
        -_float(row.get("annual_return_pct")),
        _float(row.get("max_drawdown_abs_pct")),
        -_float(row.get("min_remaining_capital_pct_after_10pct_spike")),
        str(row.get("scenario_id", "")),
    )


def _research_design(*, candidate_count: int, top_n: int) -> dict[str, Any]:
    return {
        "source_line": "btc_high_octane_attack_sleeve_lab latest watchlist",
        "top_n_requested": int(top_n),
        "candidate_count": candidate_count,
        "overlay_disciplines": [
            "10 isolated sleeve accounts",
            "48h cooldown after losing exposed bar",
            "20pct leverage derisk after loss",
            "3 consecutive losses trigger 7d global pause",
            "extract 50pct floating profit to safe account after 3x sleeve equity",
            "weekly 60pct safe account / 40pct strategic reserve transfer from unexposed sleeve profits",
            "spike remaining capital diagnostics",
        ],
        "cooldown_bars_4h": COOLDOWN_BARS_4H,
        "global_pause_bars_4h": GLOBAL_PAUSE_BARS_4H,
        "min_leverage_scale": MIN_LEVERAGE_SCALE,
        "max_research_leverage": MAX_RESEARCH_LEVERAGE,
        "same_bar_profit_allowed": False,
        "paper_live_boundary": "research-only artifact; no strategy skeleton, paper queue write, broker, OMS, order, or live unlock",
    }


def _summary(*, grid_rows: Sequence[Mapping[str, Any]], watchlist_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    best = grid_rows[0] if grid_rows else {}
    deltas = [_float(row.get("annual_return_delta_vs_source_pct")) for row in grid_rows]
    return {
        "candidate_count": len(grid_rows),
        "watchlist_count": len(watchlist_rows),
        "best_scenario_id": best.get("scenario_id"),
        "best_research_decision": best.get("research_decision"),
        "best_annual_return_pct": best.get("annual_return_pct"),
        "best_total_return_pct": best.get("total_return_pct"),
        "best_max_drawdown_abs_pct": best.get("max_drawdown_abs_pct"),
        "best_min_remaining_after_10pct_spike": best.get("min_remaining_capital_pct_after_10pct_spike"),
        "best_safe_plus_reserve_pct_of_initial": best.get("safe_plus_reserve_pct_of_initial"),
        "median_annual_return_delta_vs_source_pct": _round(median(deltas)) if deltas else 0.0,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _warnings(*, blockers: Sequence[str], grid_rows: Sequence[Mapping[str, Any]]) -> list[str]:
    warnings = ["btc_high_octane_10u_discipline_overlay_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_high_octane_10u_overlay_blocked_or_degraded_inputs")
    if any(_int(row.get("normal_liquidation_count")) > 0 for row in grid_rows):
        warnings.append("overlay_normal_liquidations_observed")
    if any(_float(row.get("annual_return_delta_vs_source_pct")) < 0.0 for row in grid_rows):
        warnings.append("10u_discipline_reduces_some_high_octane_returns")
    return warnings


def render_btc_high_octane_10u_discipline_overlay_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    gate = _mapping(report.get("gate"))
    lines = [
        "# BTC High-Octane + 10U 风控纪律嫁接实验室",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 候选数：`{summary.get('candidate_count')}`，watchlist：`{summary.get('watchlist_count')}`",
        f"- 最佳场景：`{summary.get('best_scenario_id')}`",
        f"- 最佳年化 / 总收益 / 回撤：`{summary.get('best_annual_return_pct')}` / `{summary.get('best_total_return_pct')}` / `{summary.get('best_max_drawdown_abs_pct')}`",
        f"- -10% 插针后最低剩余本金：`{summary.get('best_min_remaining_after_10pct_spike')}`%",
        f"- 安全账户+战略储备占初始本金：`{summary.get('best_safe_plus_reserve_pct_of_initial')}`%",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 嫁接的 10U 纪律",
        "",
        "- 10 个 sleeve 资金隔离。",
        "- 亏损后 48 小时冷却，后续杠杆降低 20%。",
        "- 连续三次亏损触发 7 天全局暂停。",
        "- sleeve 达到 3x 后提取 50% 浮盈到安全账户。",
        "- 每周从未暴露 sleeve 的超额利润中按 60/40 转入安全账户/战略储备。",
        "- 持续输出插针后剩余本金。",
        "",
        "| 排名 | 场景 | 年化 | 对原始年化差 | 回撤 | -10%剩余 | 冷却 | 降杠杆 | 全局暂停 | 结论 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for idx, row in enumerate(_list_of_mappings(report.get("top_watchlist"))[:10], start=1):
        lines.append(
            f"| {idx} | `{row.get('scenario_id')}` | {row.get('annual_return_pct')} | {row.get('annual_return_delta_vs_source_pct')} | "
            f"{row.get('max_drawdown_abs_pct')} | {row.get('min_remaining_capital_pct_after_10pct_spike')} | "
            f"{row.get('cooldown_count')} | {row.get('leverage_derisk_count')} | {row.get('global_pause_count')} | `{row.get('research_decision')}` |"
        )
    if not report.get("top_watchlist"):
        lines.append("| - | 无 | - | - | - | - | - | - | - | 无普通 watchlist |")
    lines.extend(["", "本实验只做 research-only，不写 paper 队列，不生成策略骨架，不接 broker/OMS/order，不解锁 live。"])
    return "\n".join(lines) + "\n"


def _read_csv(path: Path, blockers: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        blockers.append(f"missing_high_octane_watchlist:{_portable_path(path)}")
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _adverse_move(*, high: float, low: float, close: pd.Series, pos: int, side: float) -> float:
    if pos <= 0 or side == 0.0:
        return 0.0
    previous = float(close.iloc[pos - 1])
    if side > 0.0:
        return max(0.0, 1.0 - low / max(1e-12, previous))
    return max(0.0, high / max(1e-12, previous) - 1.0)


def _liquidation_threshold(leverage: float) -> float:
    return max(0.0, 1.0 / float(leverage) - 0.005 - 0.003)


def _event(
    *,
    candidate: OverlayCandidate,
    ts: pd.Timestamp,
    event_type: str,
    sleeve_idx: int,
    role: str,
    leverage: float,
    amount: float,
    note: str,
) -> dict[str, Any]:
    return {
        "scenario_id": candidate.scenario.scenario_id,
        "timestamp": _ts(ts),
        "event_type": event_type,
        "sleeve_id": sleeve_idx + 1,
        "role": role,
        "leverage": _round(leverage),
        "amount": _round(amount),
        "note": note,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _week_key(ts: pd.Timestamp) -> tuple[int, int]:
    iso = ts.isocalendar()
    return int(iso.year), int(iso.week)


def _shock_slug(value: float) -> str:
    return f"{int(round(value))}pct" if abs(value - round(value)) < 1e-9 else str(value).replace(".", "p") + "pct"


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "High-Octane + 10U discipline overlay is research-only and cannot promote strategies.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_high_octane_10u_discipline_overlay_safety_status_v1",
        "status": "research_only",
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
        "strategy_skeleton_generated": False,
        "reason": "Overlay output is diagnostic research only.",
        "blockers": list(report.get("blockers", [])),
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [row for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _float(value: Any) -> float:
    try:
        if value in {"", None}:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        if value in {"", None}:
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _ts(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


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
