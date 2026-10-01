from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.bankroll_rollover_lab import INITIAL_SLEEVE_COUNT, _frozen_v3_direction
from quant_crypto.research.pyramiding_sleeve_lab import (
    ONE_OFF_SPIKE_PCTS,
    ROLE_PRIORITY,
    PyramidSleeve,
    PyramidTemplate,
    _adverse_move,
    _atr,
    _favorable_atr,
    _liquidation_threshold,
    _pullback_visible,
    _shock_slug,
    _total_equity,
    _ts,
)
from quant_crypto.research.simple_trend_rule_lab import (
    BASE_COST_BPS,
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    INITIAL_CAPITAL,
)
from quant_crypto.research.small_account_high_yield_near_miss_review import (
    _git_commit,
    _portable_path,
    _prepare_market_context,
    _round,
)


SCHEMA_VERSION = "btc_high_octane_attack_sleeve_lab_v2"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_high_octane_attack_sleeve_lab/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_high_octane_attack_sleeve_lab_report.json"
DEFAULT_GRID_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_high_octane_attack_sleeve_lab_grid.csv"
DEFAULT_PRELIST_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_high_octane_attack_sleeve_lab_prelist.csv"
DEFAULT_ROLLING_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_high_octane_attack_sleeve_lab_rolling_start.csv"
DEFAULT_WATCHLIST_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_high_octane_attack_sleeve_lab_watchlist.csv"
DEFAULT_EVENT_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_high_octane_attack_sleeve_lab_events.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_high_octane_attack_sleeve_lab_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

ATR_STEP_GRID = (0.35, 0.5, 0.75)
ATTACK_CAP_GRID = (1, 2, 3)
ATTACK_COUNT_GRID = (1, 2, 3)
MAX_TOTAL_EXPOSED_GRID = (7, 8, 10)
CORE_COUNT_GRID = (5, 6)
RESERVE_LEVERAGE_GRID = (3.0, 5.0)
EXTRACT_POLICIES = ("none", "extract_on_double", "extract_on_triple")
WATCHLIST_TIERS = {
    "survive_40pct": {"min_remaining": 40.0, "max_drawdown": 70.0},
    "survive_50pct": {"min_remaining": 50.0, "max_drawdown": 60.0},
    "survive_60pct": {"min_remaining": 60.0, "max_drawdown": 50.0},
}
ROLLING_PRELIST_LIMIT = 60
ROLLING_START_STEP_DAYS = 30
ROLLING_MIN_REMAINING_DAYS = 90
HARD_WIPEOUT_THRESHOLD_PCT_OF_INITIAL = 25.0
MAX_RESEARCH_LEVERAGE = 10.0


@dataclass(frozen=True)
class HighOctaneScenario:
    scenario_id: str
    policy_id: str
    sleeve_templates: tuple[PyramidTemplate, ...]
    max_total_exposed: int
    max_attack_exposed: int
    extract_policy: str
    reserve_requires_pullback: bool
    atr_step: float
    attack_delay_profile: str


@dataclass(frozen=True)
class HighOctaneResult:
    scenario: HighOctaneScenario
    metrics: dict[str, Any]
    event_rows: tuple[dict[str, Any], ...]


def build_btc_high_octane_attack_sleeve_lab(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    grid_csv_path = output_dir / DEFAULT_GRID_CSV_PATH.name
    prelist_csv_path = output_dir / DEFAULT_PRELIST_CSV_PATH.name
    rolling_csv_path = output_dir / DEFAULT_ROLLING_CSV_PATH.name
    watchlist_csv_path = output_dir / DEFAULT_WATCHLIST_CSV_PATH.name
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
    direction = _frozen_v3_direction(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    market = dict(market)
    market["_high_octane_precomputed"] = _precompute_market_series(market=market, direction=direction)
    bars_4h = market["bars_4h"].reindex(direction.index)

    scenarios = _scenario_grid()
    base_results: list[HighOctaneResult] = []
    event_rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        result = _simulate_high_octane(
            scenario,
            market=market,
            direction=direction,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
            collect_events=False,
        )
        base_results.append(result)

    grid_rows = sorted((_result_row(result) for result in base_results), key=_base_rank_key)
    prelist_rows = grid_rows[:ROLLING_PRELIST_LIMIT]
    scenario_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    for row in prelist_rows[:5]:
        replay = _simulate_high_octane(
            scenario_by_id[str(row["scenario_id"])],
            market=market,
            direction=direction,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
            collect_events=True,
        )
        event_rows.extend(replay.event_rows)
    rolling_rows: list[dict[str, Any]] = []
    enriched_rows: list[dict[str, Any]] = []
    for row in prelist_rows:
        scenario = scenario_by_id[str(row["scenario_id"])]
        starts = _rolling_start_times(direction.index)
        scenario_rolling_rows = []
        for start_time in starts:
            rolling_result = _simulate_high_octane(
                scenario,
                market=market,
                direction=direction,
                initial_capital=initial_capital,
                base_cost_bps=base_cost_bps,
                start_time=start_time,
            )
            rolling_row = _rolling_result_row(rolling_result, start_time=start_time, initial_capital=initial_capital)
            scenario_rolling_rows.append(rolling_row)
            rolling_rows.append(rolling_row)
        enriched = dict(row)
        enriched.update(_rolling_summary(scenario_rolling_rows))
        enriched["watchlist_tiers"] = _watchlist_tiers(enriched)
        enriched["watchlist_tier"] = _primary_tier(enriched["watchlist_tiers"])
        enriched["watchlist_decision"] = _watchlist_decision(enriched)
        enriched_rows.append(enriched)

    watchlist_rows = sorted(
        [row for row in enriched_rows if row["watchlist_decision"] == "retain_high_octane_attack_research_watchlist_only"],
        key=_final_rank_key,
    )
    enriched_rows = sorted(enriched_rows, key=_final_rank_key)
    summary = _summary(
        grid_rows=grid_rows,
        prelist_rows=prelist_rows,
        enriched_rows=enriched_rows,
        watchlist_rows=watchlist_rows,
        rolling_rows=rolling_rows,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_high_octane_attack_sleeve_lab_research_only_no_paper_no_live",
        "scope": "small_account_high_octane_attack_sleeve_research_only",
        "code_commit": _git_commit(),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "market_4h_rows": int(len(bars_4h)),
            "market_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "market_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
            "direction_source": "existing frozen Donchian high-yield v3 direction; v2 only tests capital-management overlay",
        },
        "research_design": {
            "objective": "Higher-octane small-account attack sleeve grid; allow partial sleeve death but avoid whole-account spike wipeout.",
            "scenario_count": len(grid_rows),
            "rolling_prelist_limit": ROLLING_PRELIST_LIMIT,
            "atr_step_grid": list(ATR_STEP_GRID),
            "attack_cap_grid": list(ATTACK_CAP_GRID),
            "attack_count_grid": list(ATTACK_COUNT_GRID),
            "max_total_exposed_grid": list(MAX_TOTAL_EXPOSED_GRID),
            "core_leverage": 5.0,
            "core_count_grid": list(CORE_COUNT_GRID),
            "reserve_leverage_grid": list(RESERVE_LEVERAGE_GRID),
            "extract_policy_grid": list(EXTRACT_POLICIES),
            "attack_delay_profiles": sorted(_attack_delay_profiles().keys()),
            "watchlist_tiers": WATCHLIST_TIERS,
            "max_research_leverage": MAX_RESEARCH_LEVERAGE,
            "one_off_spike_pcts": list(ONE_OFF_SPIKE_PCTS),
            "ranking_order": [
                "watchlist_decision",
                "annual_return_pct",
                "total_return_pct",
                "rolling_median_total_return_pct",
                "rolling_full_wipeout_rate",
                "min_remaining_capital_pct_after_10pct_spike",
            ],
            "normal_liquidation_policy": "allowed_but_recorded_and_penalized_in_ranking",
            "funding_model": "research approximation from visible derivatives rows; not live settlement evidence",
        },
        "summary": summary,
        "top_watchlist": watchlist_rows[:20],
        "top_prelist": prelist_rows[:20],
        "grid_rows_sample": grid_rows[:25],
        "rolling_start_sample": rolling_rows[:25],
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(watchlist_rows=watchlist_rows, blockers=blockers),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "grid_csv": _portable_path(grid_csv_path),
            "prelist_csv": _portable_path(prelist_csv_path),
            "rolling_start_csv": _portable_path(rolling_csv_path),
            "watchlist_csv": _portable_path(watchlist_csv_path),
            "events_csv": _portable_path(event_csv_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(grid_csv_path, grid_rows)
    _write_csv(prelist_csv_path, prelist_rows)
    _write_csv(rolling_csv_path, rolling_rows)
    _write_csv(watchlist_csv_path, watchlist_rows)
    _write_csv(event_csv_path, event_rows[:1500])
    _write_text(markdown_path, render_btc_high_octane_attack_sleeve_lab_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _scenario_grid() -> list[HighOctaneScenario]:
    scenarios: list[HighOctaneScenario] = []
    for atr_step in ATR_STEP_GRID:
        for core_count in CORE_COUNT_GRID:
            for reserve_leverage in RESERVE_LEVERAGE_GRID:
                for attack_count in ATTACK_COUNT_GRID:
                    reserve_count = INITIAL_SLEEVE_COUNT - core_count - attack_count
                    if reserve_count < 1:
                        continue
                    for max_total in MAX_TOTAL_EXPOSED_GRID:
                        for attack_cap in ATTACK_CAP_GRID:
                            if attack_cap > attack_count or attack_cap > max_total:
                                continue
                            for profile_id, attack_delays in _attack_delay_profiles().items():
                                for extract_policy in EXTRACT_POLICIES:
                                    templates: list[PyramidTemplate] = []
                                    templates.extend(PyramidTemplate("core", 5.0, i % 3, float(i % 2) * atr_step) for i in range(core_count))
                                    templates.extend(
                                        PyramidTemplate("reserve", reserve_leverage, 4 + (i % 3) * 2, atr_step * (0.75 + (i % 3) * 0.5))
                                        for i in range(reserve_count)
                                    )
                                    templates.extend(PyramidTemplate("attack", 10.0, attack_delays[i], atr_step * (1.0 + i * 0.35)) for i in range(attack_count))
                                    scenario_id = (
                                        f"ho_step{_num_slug(atr_step)}_core5x{core_count}"
                                        f"_reserve{int(reserve_leverage)}x{reserve_count}_attack10x{attack_count}"
                                        f"_cap{attack_cap}_max{max_total}_delay{profile_id}_{extract_policy}"
                                    )
                                    scenarios.append(
                                        HighOctaneScenario(
                                            scenario_id=scenario_id,
                                            policy_id="high_octane_atr_pyramiding_attack_sleeve",
                                            sleeve_templates=tuple(templates),
                                            max_total_exposed=max_total,
                                            max_attack_exposed=attack_cap,
                                            extract_policy=extract_policy,
                                            reserve_requires_pullback=True,
                                            atr_step=atr_step,
                                            attack_delay_profile=profile_id,
                                        )
                                    )
    return scenarios


def _attack_delay_profiles() -> dict[str, tuple[int, int, int]]:
    return {
        "early": (0, 1, 2),
        "balanced": (3, 6, 9),
        "late": (6, 9, 12),
    }


def _simulate_high_octane(
    scenario: HighOctaneScenario,
    *,
    market: Mapping[str, Any],
    direction: pd.Series,
    initial_capital: float,
    base_cost_bps: float,
    start_time: pd.Timestamp | None = None,
    collect_events: bool = False,
) -> HighOctaneResult:
    direction = direction.dropna()
    if start_time is not None:
        start = pd.Timestamp(start_time)
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
        direction = direction.loc[direction.index >= start]
    precomputed = market.get("_high_octane_precomputed")
    if isinstance(precomputed, pd.DataFrame):
        series_frame = precomputed.reindex(direction.index)
        close = series_frame["close"].astype(float)
        high = series_frame["high"].astype(float)
        low = series_frame["low"].astype(float)
        returns = series_frame["returns"].astype(float).fillna(0.0)
        atr = series_frame["atr_20"].astype(float).ffill().fillna(0.0)
        funding = series_frame["funding_rate"].astype(float).fillna(0.0)
    else:
        bars = market["bars_4h"].reindex(direction.index)
        derivatives = market["derivatives_4h"].reindex(direction.index)
        close = bars["close"].astype(float)
        high = bars["high"].astype(float)
        low = bars["low"].astype(float)
        returns = close.pct_change().fillna(0.0)
        atr = _atr(bars, 20).reindex(direction.index).ffill().fillna(0.0)
        funding = pd.to_numeric(derivatives.get("funding_rate", pd.Series(0.0, index=direction.index)), errors="coerce").fillna(0.0)
    timestamps = list(direction.index)
    side_values = direction.astype(float).to_numpy()
    close_values = close.to_numpy()
    high_values = high.to_numpy()
    low_values = low.to_numpy()
    return_values = returns.to_numpy()
    atr_values = atr.to_numpy()
    funding_values = funding.to_numpy()

    templates = list(scenario.sleeve_templates)
    sleeve_count = len(templates)
    sleeve_initial = float(initial_capital) / float(INITIAL_SLEEVE_COUNT)
    roles = [template.role for template in templates]
    leverages = [float(template.leverage) for template in templates]
    entry_delays = [int(template.entry_delay_bars) for template in templates]
    triggers = [float(template.trigger_atr) for template in templates]
    thresholds = [_liquidation_threshold(leverage) for leverage in leverages]
    sorted_indices = sorted(range(sleeve_count), key=lambda idx: (ROLE_PRIORITY[roles[idx]], triggers[idx], entry_delays[idx], idx))
    equity_values = [sleeve_initial for _ in range(sleeve_count)]
    basis_values = [sleeve_initial for _ in range(sleeve_count)]
    reserve_values = [0.0 for _ in range(sleeve_count)]
    alive_values = [True for _ in range(sleeve_count)]
    exposed_side_values = [0.0 for _ in range(sleeve_count)]
    extract_counts = [0 for _ in range(sleeve_count)]
    pyramid_entry_counts = [0 for _ in range(sleeve_count)]

    equity_curve: list[float] = []
    exposed_count_curve: list[int] = []
    attack_count_curve: list[int] = []
    event_rows: list[dict[str, Any]] = []
    previous_signal = 0.0
    signal_age = 0
    campaign_anchor: float | None = None
    normal_liquidation_count = 0
    max_same_bar_normal_liquidations = 0
    funding_cost_amount = 0.0
    turnover_cost_amount = 0.0
    fee_rate = float(base_cost_bps) / 10_000.0
    min_remaining = {shock: 100.0 for shock in ONE_OFF_SPIKE_PCTS}
    max_sleeves_lost = {shock: 0 for shock in ONE_OFF_SPIKE_PCTS}
    max_equity_lost = {shock: 0.0 for shock in ONE_OFF_SPIKE_PCTS}

    for pos, ts in enumerate(timestamps):
        side = float(side_values[pos])
        close_value = float(close_values[pos])
        if side == 0.0:
            signal_age = 0
            campaign_anchor = None
        elif side == previous_signal and campaign_anchor is not None:
            signal_age += 1
        else:
            signal_age = 1
            campaign_anchor = float(close_values[pos - 1]) if pos > 0 else close_value
        favorable_atr = _favorable_atr(close=close_value, anchor=campaign_anchor, side=side, atr=float(atr_values[pos]))
        pullback_visible = _pullback_visible_array(
            returns=return_values,
            high=high_values,
            low=low_values,
            close=close_values,
            pos=pos,
            side=side,
        )
        selected = [False for _ in range(sleeve_count)]
        if side != 0.0:
            selected_count = 0
            selected_attack_count = 0
            for sleeve_idx in sorted_indices:
                if selected_count >= scenario.max_total_exposed:
                    break
                if not alive_values[sleeve_idx]:
                    continue
                if signal_age <= entry_delays[sleeve_idx] or favorable_atr < triggers[sleeve_idx]:
                    continue
                role = roles[sleeve_idx]
                if role == "reserve" and scenario.reserve_requires_pullback and not pullback_visible:
                    continue
                if role == "attack" and selected_attack_count >= scenario.max_attack_exposed:
                    continue
                selected[sleeve_idx] = True
                selected_count += 1
                if role == "attack":
                    selected_attack_count += 1
        adverse = _adverse_move_array(high=high_values, low=low_values, close=close_values, pos=pos, side=side)
        bar_return = 0.0 if pos == 0 else float(return_values[pos])
        normal_liq_this_bar = 0

        for sleeve_idx in range(sleeve_count):
            if not alive_values[sleeve_idx]:
                exposed_side_values[sleeve_idx] = 0.0
                continue
            if not selected[sleeve_idx]:
                exposed_side_values[sleeve_idx] = 0.0
                continue
            if exposed_side_values[sleeve_idx] == 0.0 and triggers[sleeve_idx] > 0.0:
                pyramid_entry_counts[sleeve_idx] += 1
                if collect_events:
                    event_rows.append(
                        _event_from_values(
                            scenario=scenario,
                            ts=ts,
                            event_type="attack_or_pyramid_entry",
                            sleeve_idx=sleeve_idx,
                            role=roles[sleeve_idx],
                            leverage=leverages[sleeve_idx],
                            trigger_atr=triggers[sleeve_idx],
                            amount=equity_values[sleeve_idx],
                            note=f"favorable_atr={_round(favorable_atr)} trigger_atr={triggers[sleeve_idx]}",
                        )
                    )
            turnover_cost = fee_rate if exposed_side_values[sleeve_idx] != side else 0.0
            if adverse >= thresholds[sleeve_idx]:
                if collect_events:
                    event_rows.append(
                        _event_from_values(
                            scenario=scenario,
                            ts=ts,
                            event_type="normal_liquidation",
                            sleeve_idx=sleeve_idx,
                            role=roles[sleeve_idx],
                            leverage=leverages[sleeve_idx],
                            trigger_atr=triggers[sleeve_idx],
                            amount=equity_values[sleeve_idx],
                            note=f"adverse={_round(adverse * 100.0)} threshold={_round(thresholds[sleeve_idx] * 100.0)}",
                        )
                    )
                equity_values[sleeve_idx] = 0.0
                alive_values[sleeve_idx] = False
                exposed_side_values[sleeve_idx] = 0.0
                normal_liquidation_count += 1
                normal_liq_this_bar += 1
                continue
            before_equity = equity_values[sleeve_idx]
            funding_return = -side * leverages[sleeve_idx] * float(funding_values[pos]) * (4.0 / 8.0)
            if funding_return < 0.0:
                funding_cost_amount += before_equity * abs(funding_return)
            turnover_cost_amount += before_equity * turnover_cost
            equity_values[sleeve_idx] = max(0.0, before_equity * (1.0 + side * leverages[sleeve_idx] * bar_return + funding_return - turnover_cost))
            exposed_side_values[sleeve_idx] = side
            if _should_extract_values(equity=equity_values[sleeve_idx], basis=basis_values[sleeve_idx], extract_policy=scenario.extract_policy):
                extracted = min(basis_values[sleeve_idx], equity_values[sleeve_idx])
                equity_values[sleeve_idx] -= extracted
                reserve_values[sleeve_idx] += extracted
                basis_values[sleeve_idx] = max(equity_values[sleeve_idx], 1e-9)
                extract_counts[sleeve_idx] += 1
                if collect_events:
                    event_rows.append(
                        _event_from_values(
                            scenario=scenario,
                            ts=ts,
                            event_type=scenario.extract_policy,
                            sleeve_idx=sleeve_idx,
                            role=roles[sleeve_idx],
                            leverage=leverages[sleeve_idx],
                            trigger_atr=triggers[sleeve_idx],
                            amount=extracted,
                            note="principal protected outside active sleeve",
                        )
                    )

        total_equity = sum(max(0.0, equity_values[idx]) + max(0.0, reserve_values[idx]) for idx in range(sleeve_count))
        exposed_indices = [idx for idx in range(sleeve_count) if alive_values[idx] and exposed_side_values[idx] != 0.0]
        for shock in ONE_OFF_SPIKE_PCTS:
            lost_equity = 0.0
            lost_count = 0
            shock_adverse = adverse + shock / 100.0
            for sleeve_idx in exposed_indices:
                if shock_adverse >= thresholds[sleeve_idx]:
                    lost_equity += equity_values[sleeve_idx]
                    lost_count += 1
            remaining_pct = (total_equity - lost_equity) / max(1e-9, total_equity) * 100.0
            min_remaining[shock] = min(min_remaining[shock], remaining_pct)
            max_sleeves_lost[shock] = max(max_sleeves_lost[shock], lost_count)
            max_equity_lost[shock] = max(max_equity_lost[shock], lost_equity)
        equity_curve.append(total_equity)
        exposed_count_curve.append(len(exposed_indices))
        attack_count_curve.append(sum(1 for idx in exposed_indices if roles[idx] == "attack"))
        max_same_bar_normal_liquidations = max(max_same_bar_normal_liquidations, normal_liq_this_bar)
        previous_signal = side

    equity = pd.Series(equity_curve, index=direction.index, dtype=float)
    drawdown = equity / equity.cummax() - 1.0 if len(equity) else pd.Series(dtype=float)
    final_equity = float(equity_curve[-1]) if equity_curve else 0.0
    total_return = final_equity / float(initial_capital) - 1.0
    elapsed_days = max(1.0, float((direction.index.max() - direction.index.min()).total_seconds()) / 86_400.0) if len(direction) else 1.0
    annual_return = (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0 if total_return > -1.0 else -1.0
    exposed_series = pd.Series(exposed_count_curve, dtype=float)
    attack_series = pd.Series(attack_count_curve, dtype=float)
    reserve_cash = sum(reserve_values)
    metrics: dict[str, Any] = {
        "final_equity": _round(final_equity),
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "max_drawdown_abs_pct": _round(abs(float(drawdown.min())) * 100.0) if len(drawdown) else 0.0,
        "reserve_cash": _round(reserve_cash),
        "reserve_cash_pct_of_initial": _round(reserve_cash / float(initial_capital) * 100.0),
        "alive_sleeve_count": sum(1 for alive in alive_values if alive),
        "dead_sleeve_count": sum(1 for alive in alive_values if not alive),
        "normal_liquidation_count": normal_liquidation_count,
        "max_same_bar_normal_liquidations": max_same_bar_normal_liquidations,
        "average_concurrent_exposed_sleeves": _round(float(exposed_series.mean()) if len(exposed_series) else 0.0),
        "max_concurrent_exposed_sleeves_observed": int(exposed_series.max()) if len(exposed_series) else 0,
        "average_attack_exposed_sleeves": _round(float(attack_series.mean()) if len(attack_series) else 0.0),
        "max_attack_exposed_sleeves_observed": int(attack_series.max()) if len(attack_series) else 0,
        "extract_count": sum(extract_counts),
        "pyramid_entry_count": sum(pyramid_entry_counts),
        "actual_attack_used": bool(attack_series.max() > 0) if len(attack_series) else False,
        "funding_cost_amount": _round(funding_cost_amount),
        "turnover_cost_amount": _round(turnover_cost_amount),
        "hard_wipeout": bool(final_equity <= float(initial_capital) * HARD_WIPEOUT_THRESHOLD_PCT_OF_INITIAL / 100.0),
        "full_wipeout": bool(final_equity <= 1e-9),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
    }
    for shock in ONE_OFF_SPIKE_PCTS:
        slug = _shock_slug(shock)
        metrics[f"min_remaining_capital_pct_after_{slug}_spike"] = _round(min_remaining[shock])
        metrics[f"max_sleeves_lost_single_{slug}_spike"] = int(max_sleeves_lost[shock])
        metrics[f"max_equity_lost_single_{slug}_spike"] = _round(max_equity_lost[shock])
    return HighOctaneResult(scenario=scenario, metrics=metrics, event_rows=tuple(event_rows[:350]))


def _pullback_visible_array(*, returns: Sequence[float], high: Sequence[float], low: Sequence[float], close: Sequence[float], pos: int, side: float) -> bool:
    if pos <= 1 or side == 0.0:
        return False
    previous_return = float(returns[pos - 1])
    previous_adverse = _adverse_move_array(high=high, low=low, close=close, pos=pos - 1, side=side)
    return side * previous_return < 0.0 or previous_adverse >= 0.01


def _adverse_move_array(*, high: Sequence[float], low: Sequence[float], close: Sequence[float], pos: int, side: float) -> float:
    if pos <= 0 or side == 0.0:
        return 0.0
    prev_close = float(close[pos - 1])
    if side > 0.0:
        return max(0.0, 1.0 - float(low[pos]) / prev_close)
    return max(0.0, float(high[pos]) / prev_close - 1.0)


def _precompute_market_series(*, market: Mapping[str, Any], direction: pd.Series) -> pd.DataFrame:
    bars = market["bars_4h"].reindex(direction.index)
    derivatives = market["derivatives_4h"].reindex(direction.index)
    close = bars["close"].astype(float)
    frame = pd.DataFrame(index=direction.index)
    frame["close"] = close
    frame["high"] = bars["high"].astype(float)
    frame["low"] = bars["low"].astype(float)
    frame["returns"] = close.pct_change().fillna(0.0)
    frame["atr_20"] = _atr(bars, 20).reindex(direction.index).ffill().fillna(0.0)
    frame["funding_rate"] = pd.to_numeric(derivatives.get("funding_rate", pd.Series(0.0, index=direction.index)), errors="coerce").fillna(0.0)
    return frame


def _select_sleeves(eligible: Sequence[PyramidSleeve], *, scenario: HighOctaneScenario) -> set[int]:
    selected: list[PyramidSleeve] = []
    attack_count = 0
    for sleeve in sorted(eligible, key=lambda item: (ROLE_PRIORITY[item.role], item.trigger_atr, item.entry_delay_bars, item.sleeve_id)):
        if len(selected) >= scenario.max_total_exposed:
            break
        if sleeve.role == "attack" and attack_count >= scenario.max_attack_exposed:
            continue
        selected.append(sleeve)
        if sleeve.role == "attack":
            attack_count += 1
    return {sleeve.sleeve_id for sleeve in selected}


def _should_extract(sleeve: PyramidSleeve, extract_policy: str) -> bool:
    if extract_policy == "none":
        return False
    if extract_policy == "extract_on_double":
        return sleeve.equity >= sleeve.basis_equity * 2.0
    if extract_policy == "extract_on_triple":
        return sleeve.equity >= sleeve.basis_equity * 3.0
    return False


def _should_extract_values(*, equity: float, basis: float, extract_policy: str) -> bool:
    if extract_policy == "none":
        return False
    if extract_policy == "extract_on_double":
        return equity >= basis * 2.0
    if extract_policy == "extract_on_triple":
        return equity >= basis * 3.0
    return False


def _result_row(result: HighOctaneResult) -> dict[str, Any]:
    scenario = result.scenario
    row = {
        "scenario_id": scenario.scenario_id,
        "policy_id": scenario.policy_id,
        "atr_step": scenario.atr_step,
        "max_total_exposed": scenario.max_total_exposed,
        "max_attack_exposed": scenario.max_attack_exposed,
        "extract_policy": scenario.extract_policy,
        "reserve_requires_pullback": scenario.reserve_requires_pullback,
        "attack_delay_profile": scenario.attack_delay_profile,
        "sleeve_roles": json.dumps([template.role for template in scenario.sleeve_templates], ensure_ascii=False),
        "sleeve_leverages": json.dumps([template.leverage for template in scenario.sleeve_templates], ensure_ascii=False),
        "sleeve_trigger_atr": json.dumps([template.trigger_atr for template in scenario.sleeve_templates], ensure_ascii=False),
        "attack_template_count": sum(1 for template in scenario.sleeve_templates if template.role == "attack"),
        "max_template_leverage": max(template.leverage for template in scenario.sleeve_templates),
        **result.metrics,
    }
    row["base_screen_decision"] = _base_screen_decision(row)
    return row


def _base_screen_decision(row: Mapping[str, Any]) -> str:
    if float(row.get("max_template_leverage", 0.0)) > MAX_RESEARCH_LEVERAGE:
        return "reject_leverage_above_10x"
    if int(row.get("max_attack_exposed_sleeves_observed", 0)) <= 0:
        return "defer_no_actual_10x_attack_exposure"
    if int(row.get("pyramid_entry_count", 0)) <= 0:
        return "defer_no_actual_pyramid_or_attack_entry"
    if float(row.get("total_return_pct", -100.0)) <= 0.0:
        return "defer_non_positive_total_return"
    if float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)) < 40.0:
        return "defer_below_40pct_remaining_after_10pct_spike"
    if float(row.get("max_drawdown_abs_pct", 999.0)) > 70.0:
        return "defer_drawdown_above_70pct"
    return "prelist_eligible_high_octane_attack_research_only"


def _base_rank_key(row: Mapping[str, Any]) -> tuple[int, float, float, float, float, float, str]:
    return (
        0 if row.get("base_screen_decision") == "prelist_eligible_high_octane_attack_research_only" else 1,
        -float(row.get("annual_return_pct", -999.0)),
        -float(row.get("total_return_pct", -999.0)),
        float(row.get("full_wipeout", False)),
        float(row.get("hard_wipeout", False)),
        -float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)),
        str(row.get("scenario_id", "")),
    )


def _final_rank_key(row: Mapping[str, Any]) -> tuple[int, float, float, float, float, float, float, str]:
    return (
        0 if row.get("watchlist_decision") == "retain_high_octane_attack_research_watchlist_only" else 1,
        -float(row.get("annual_return_pct", -999.0)),
        -float(row.get("total_return_pct", -999.0)),
        -float(row.get("rolling_median_total_return_pct", -999.0)),
        float(row.get("rolling_full_wipeout_rate", 1.0)),
        -float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)),
        float(row.get("max_drawdown_abs_pct", 999.0)),
        str(row.get("scenario_id", "")),
    )


def _rolling_result_row(result: HighOctaneResult, *, start_time: pd.Timestamp, initial_capital: float) -> dict[str, Any]:
    row = _result_row(result)
    row["rolling_start_time"] = _ts(start_time)
    row["hard_wipeout_threshold_pct_of_initial"] = HARD_WIPEOUT_THRESHOLD_PCT_OF_INITIAL
    row["hard_wipeout"] = bool(float(row.get("final_equity", 0.0)) <= float(initial_capital) * HARD_WIPEOUT_THRESHOLD_PCT_OF_INITIAL / 100.0)
    row["full_wipeout"] = bool(float(row.get("final_equity", 0.0)) <= 1e-9)
    return row


def _rolling_start_times(index: pd.Index) -> list[pd.Timestamp]:
    if len(index) == 0:
        return []
    start = pd.Timestamp(index.min())
    end = pd.Timestamp(index.max())
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    current = start
    starts: list[pd.Timestamp] = []
    while current <= end - pd.Timedelta(days=ROLLING_MIN_REMAINING_DAYS):
        starts.append(current)
        current += pd.Timedelta(days=ROLLING_START_STEP_DAYS)
    return starts


def _rolling_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    returns = [float(row.get("total_return_pct", 0.0)) for row in rows]
    annuals = [float(row.get("annual_return_pct", 0.0)) for row in rows]
    remaining = [float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0)) for row in rows]
    count = len(rows)
    return {
        "rolling_start_count": count,
        "rolling_median_total_return_pct": _round(median(returns)) if returns else 0.0,
        "rolling_median_annual_return_pct": _round(median(annuals)) if annuals else 0.0,
        "rolling_min_total_return_pct": _round(min(returns)) if returns else 0.0,
        "rolling_positive_rate": _round(sum(1 for value in returns if value > 0.0) / max(1, count)),
        "rolling_normal_liquidation_count": sum(int(row.get("normal_liquidation_count", 0)) for row in rows),
        "rolling_hard_wipeout_rate": _round(sum(1 for row in rows if bool(row.get("hard_wipeout"))) / max(1, count)),
        "rolling_full_wipeout_rate": _round(sum(1 for row in rows if bool(row.get("full_wipeout"))) / max(1, count)),
        "rolling_median_remaining_after_10pct_spike": _round(median(remaining)) if remaining else 0.0,
    }


def _watchlist_tiers(row: Mapping[str, Any]) -> list[str]:
    tiers: list[str] = []
    if not bool(row.get("actual_attack_used")):
        return tiers
    if float(row.get("max_template_leverage", 0.0)) > MAX_RESEARCH_LEVERAGE:
        return tiers
    if float(row.get("total_return_pct", -100.0)) <= 0.0:
        return tiers
    remaining = float(row.get("min_remaining_capital_pct_after_10pct_spike", 0.0))
    drawdown = float(row.get("max_drawdown_abs_pct", 999.0))
    for tier, rule in WATCHLIST_TIERS.items():
        if remaining >= float(rule["min_remaining"]) and drawdown <= float(rule["max_drawdown"]):
            tiers.append(tier)
    return tiers


def _primary_tier(tiers: Sequence[str]) -> str:
    for tier in ("survive_60pct", "survive_50pct", "survive_40pct"):
        if tier in tiers:
            return tier
    return ""


def _watchlist_decision(row: Mapping[str, Any]) -> str:
    if not bool(row.get("actual_attack_used")):
        return "reject_no_actual_10x_attack_exposure"
    if float(row.get("max_template_leverage", 0.0)) > MAX_RESEARCH_LEVERAGE:
        return "reject_leverage_above_10x"
    if float(row.get("total_return_pct", -100.0)) <= 0.0:
        return "reject_non_positive_total_return"
    if not row.get("watchlist_tiers"):
        return "reject_no_40_50_60_survival_tier"
    return "retain_high_octane_attack_research_watchlist_only"


def _summary(
    *,
    grid_rows: Sequence[Mapping[str, Any]],
    prelist_rows: Sequence[Mapping[str, Any]],
    enriched_rows: Sequence[Mapping[str, Any]],
    watchlist_rows: Sequence[Mapping[str, Any]],
    rolling_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    best = dict(watchlist_rows[0]) if watchlist_rows else {}
    tier_counts = {tier: sum(1 for row in watchlist_rows if tier in row.get("watchlist_tiers", [])) for tier in WATCHLIST_TIERS}
    return {
        "scenario_count": len(grid_rows),
        "prelist_count": len(prelist_rows),
        "rolling_start_row_count": len(rolling_rows),
        "watchlist_count": len(watchlist_rows),
        "watchlist_tier_counts": tier_counts,
        "normal_liquidation_grid_count": sum(1 for row in grid_rows if int(row.get("normal_liquidation_count", 0)) > 0),
        "base_actual_attack_grid_count": sum(1 for row in grid_rows if bool(row.get("actual_attack_used"))),
        "best_scenario_id": best.get("scenario_id"),
        "best_watchlist_tier": best.get("watchlist_tier"),
        "best_total_return_pct": best.get("total_return_pct"),
        "best_annual_return_pct": best.get("annual_return_pct"),
        "best_max_drawdown_abs_pct": best.get("max_drawdown_abs_pct"),
        "best_min_remaining_after_10pct_spike": best.get("min_remaining_capital_pct_after_10pct_spike"),
        "best_rolling_median_total_return_pct": best.get("rolling_median_total_return_pct"),
        "best_rolling_full_wipeout_rate": best.get("rolling_full_wipeout_rate"),
        "best_max_attack_exposed_sleeves_observed": best.get("max_attack_exposed_sleeves_observed"),
        "top_enriched_count": len(enriched_rows),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def render_btc_high_octane_attack_sleeve_lab_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    gate = report.get("gate", {})
    lines = [
        "# BTC High-Octane Attack Sleeve Lab v2",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策：`{report.get('decision')}`",
        f"- 场景数：`{summary.get('scenario_count')}`",
        f"- rolling start 行数：`{summary.get('rolling_start_row_count')}`",
        f"- 观察名单数：`{summary.get('watchlist_count')}`",
        f"- 分层数量：`{summary.get('watchlist_tier_counts')}`",
        f"- 最佳场景：`{summary.get('best_scenario_id')}`",
        f"- 最佳年化/总收益/回撤：`{summary.get('best_annual_return_pct')}` / `{summary.get('best_total_return_pct')}` / `{summary.get('best_max_drawdown_abs_pct')}`",
        f"- 最佳 -10% 插针后剩余本金：`{summary.get('best_min_remaining_after_10pct_spike')}`%",
        f"- 最佳 rolling 中位总收益：`{summary.get('best_rolling_median_total_return_pct')}`%",
        f"- 最佳 rolling 全灭率：`{summary.get('best_rolling_full_wipeout_rate')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 口径",
        "",
        "这是小资金激进研究线。它允许部分 sleeve 强平，排名优先看年化、总收益、rolling-start 中位数收益、全灭率和插针后剩余本金；不是 paper/live 证据。",
        "",
        "## Top 10",
        "",
        "| 排名 | 场景 | 层级 | 年化 | 总收益 | 回撤 | -10%剩余 | rolling中位收益 | rolling全灭率 | 强平数 |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for idx, row in enumerate(report.get("top_watchlist", [])[:10], 1):
        lines.append(
            f"| {idx} | `{row.get('scenario_id')}` | `{row.get('watchlist_tier')}` | "
            f"{row.get('annual_return_pct')} | {row.get('total_return_pct')} | {row.get('max_drawdown_abs_pct')} | "
            f"{row.get('min_remaining_capital_pct_after_10pct_spike')} | {row.get('rolling_median_total_return_pct')} | "
            f"{row.get('rolling_full_wipeout_rate')} | {row.get('normal_liquidation_count')} |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "不写 paper 队列，不生成策略骨架，不接 broker/OMS，不解锁 live。强平、funding、mark/index price 均为研究近似。",
        ]
    )
    return "\n".join(lines) + "\n"


def _event(*, scenario: HighOctaneScenario, ts: pd.Timestamp, event_type: str, sleeve: PyramidSleeve, amount: float, note: str) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "event_time": _ts(ts),
        "event_type": event_type,
        "sleeve_id": sleeve.sleeve_id,
        "role": sleeve.role,
        "leverage": sleeve.leverage,
        "trigger_atr": sleeve.trigger_atr,
        "amount": _round(amount),
        "note": note,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _event_from_values(
    *,
    scenario: HighOctaneScenario,
    ts: pd.Timestamp,
    event_type: str,
    sleeve_idx: int,
    role: str,
    leverage: float,
    trigger_atr: float,
    amount: float,
    note: str,
) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "event_time": _ts(ts),
        "event_type": event_type,
        "sleeve_id": sleeve_idx + 1,
        "role": role,
        "leverage": leverage,
        "trigger_atr": trigger_atr,
        "amount": _round(amount),
        "note": note,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _gate() -> dict[str, Any]:
    return {
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "High-octane attack sleeve results are research-only capital-management diagnostics.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }


def _warnings(*, watchlist_rows: Sequence[Mapping[str, Any]], blockers: Sequence[str]) -> list[str]:
    warnings = ["btc_high_octane_attack_sleeve_lab_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_high_octane_attack_sleeve_lab_blocked")
    if not watchlist_rows:
        warnings.append("btc_high_octane_attack_sleeve_lab_no_watchlist_candidate")
    warnings.append("btc_high_octane_attack_sleeve_lab_liquidation_funding_mark_index_are_research_approximations")
    warnings.append("small_account_high_octane_line_accepts_partial_sleeve_death_not_live_evidence")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_high_octane_attack_sleeve_lab_safety_status_v1",
        "status": "research_only",
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "No paper/live promotion is allowed from high-octane attack sleeve artifacts.",
    }


def _num_slug(value: float) -> str:
    return ("%g" % value).replace(".", "p")


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
