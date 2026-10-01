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
from quant_crypto.research import pyramiding_sleeve_lab as pyramiding
from quant_crypto.research.bankroll_rollover_lab import INITIAL_SLEEVE_COUNT, _frozen_v3_direction
from quant_crypto.research.pyramiding_sleeve_lab import (
    ONE_OFF_SPIKE_PCTS as DEFENSIVE_SPIKE_PCTS,
    ROLE_PRIORITY,
    PyramidTemplate,
    _atr,
    _favorable_atr,
    _pullback_visible,
    _shock_slug,
)
from quant_crypto.research.simple_trend_rule_lab import (
    BASE_COST_BPS,
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    INITIAL_CAPITAL,
)
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path, _prepare_market_context, _round


SCHEMA_VERSION = "btc_attack_sleeve_risk_stress_review_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_attack_sleeve_risk_stress_review/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_attack_sleeve_risk_stress_review_report.json"
DEFAULT_MATRIX_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_attack_sleeve_risk_stress_review_matrix.csv"
DEFAULT_EVENTS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_attack_sleeve_risk_stress_review_events.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_attack_sleeve_risk_stress_review_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_HIGH_OCTANE_REPORT_PATH = high_octane.DEFAULT_OUTPUT_DIR / "btc_high_octane_attack_sleeve_lab_report.json"
DEFAULT_HIGH_OCTANE_WATCHLIST_PATH = high_octane.DEFAULT_OUTPUT_DIR / "btc_high_octane_attack_sleeve_lab_watchlist.csv"
DEFAULT_PYRAMIDING_ACTUAL_ATTACK_PATH = pyramiding.DEFAULT_OUTPUT_DIR / "btc_pyramiding_sleeve_lab_actual_attack_watchlist.csv"

STRESS_SPIKE_PCTS = (3.0, 5.0, 8.0, 10.0, 12.0)
EVENT_LIMIT = 500


@dataclass(frozen=True)
class SleeveRiskPolicy:
    policy_id: str
    maintenance_margin_rate: float = 0.005
    liquidation_fee_rate: float = 0.003
    mark_adverse_offset_bps: float = 0.0
    funding_adverse_multiplier: float = 1.0
    slippage_bps: float = 4.0
    taker_fee_multiplier: float = 1.0
    max_simultaneous_exposed_sleeves: int = 10
    loss_streak_reduce_after: int = 0
    loss_streak_cooldown_bars: int = 0
    loss_streak_exposure_multiplier: float = 0.5
    force_extract_policy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "maintenance_margin_rate": self.maintenance_margin_rate,
            "liquidation_fee_rate": self.liquidation_fee_rate,
            "mark_adverse_offset_bps": self.mark_adverse_offset_bps,
            "funding_adverse_multiplier": self.funding_adverse_multiplier,
            "slippage_bps": self.slippage_bps,
            "taker_fee_multiplier": self.taker_fee_multiplier,
            "max_simultaneous_exposed_sleeves": self.max_simultaneous_exposed_sleeves,
            "loss_streak_reduce_after": self.loss_streak_reduce_after,
            "loss_streak_cooldown_bars": self.loss_streak_cooldown_bars,
            "loss_streak_exposure_multiplier": self.loss_streak_exposure_multiplier,
            "force_extract_policy": self.force_extract_policy,
        }


@dataclass(frozen=True)
class StressCandidate:
    source_line: str
    scenario_id: str
    templates: tuple[PyramidTemplate, ...]
    max_total_exposed: int
    max_attack_exposed: int
    extract_policy: str
    reserve_requires_pullback: bool
    atr_step: float
    source_rank: int


@dataclass(frozen=True)
class StressResult:
    candidate: StressCandidate
    policy: SleeveRiskPolicy
    metrics: dict[str, Any]
    events: tuple[dict[str, Any], ...]


def build_btc_attack_sleeve_risk_stress_review(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    high_octane_report_path: Path = DEFAULT_HIGH_OCTANE_REPORT_PATH,
    high_octane_watchlist_path: Path = DEFAULT_HIGH_OCTANE_WATCHLIST_PATH,
    pyramiding_actual_attack_path: Path = DEFAULT_PYRAMIDING_ACTUAL_ATTACK_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
    top_n: int = 20,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    matrix_path = output_dir / DEFAULT_MATRIX_CSV_PATH.name
    events_path = output_dir / DEFAULT_EVENTS_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    blockers: list[str] = []
    high_report = _read_json(high_octane_report_path, blockers, "missing_high_octane_report")
    high_rows = _read_csv(high_octane_watchlist_path, blockers, "missing_high_octane_watchlist_csv")
    pyramiding_rows = _read_csv_optional(pyramiding_actual_attack_path)
    candidates = _candidate_specs(high_rows[:top_n], pyramiding_rows[:3])
    if not candidates:
        blockers.append("btc_attack_sleeve_risk_stress_no_candidates")

    market = _prepare_market_context(
        market_db_path=market_db_path,
        derivatives_rows_path=derivatives_rows_path,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    blockers.extend(str(item) for item in market.get("blockers", []))
    direction = _frozen_v3_direction(market, initial_capital=initial_capital, base_cost_bps=base_cost_bps)
    policies = _stress_policies()
    matrix_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    if not blockers:
        for candidate in candidates:
            for policy in policies:
                result = _simulate_strict_sleeve_stress(
                    candidate,
                    policy=policy,
                    market=market,
                    direction=direction,
                    initial_capital=initial_capital,
                    base_cost_bps=base_cost_bps,
                    collect_events=policy.policy_id in {"base_strict_next_bar", "combined_adverse_5x"},
                )
                row = _result_row(result)
                matrix_rows.append(row)
                event_rows.extend(result.events)

    matrix_rows = sorted(matrix_rows, key=_risk_rank_key)
    summary = _summary(matrix_rows=matrix_rows, high_report=high_report, candidate_count=len(candidates), policy_count=len(policies))
    decision = _decision(blockers=blockers, summary=summary)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": decision,
        "scope": "strict_risk_stress_for_high_octane_and_attack_sleeve_research_only",
        "code_commit": _git_commit(),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "high_octane_report_path": _portable_path(high_octane_report_path),
            "high_octane_watchlist_path": _portable_path(high_octane_watchlist_path),
            "pyramiding_actual_attack_path": _portable_path(pyramiding_actual_attack_path),
            "market_4h_rows": int(len(market.get("bars_4h", []))),
            "direction_source": "frozen Donchian high-yield v3 direction; strict stress uses next bar returns",
        },
        "research_design": {
            "candidate_count": len(candidates),
            "policy_count": len(policies),
            "stress_spike_pcts": list(STRESS_SPIKE_PCTS),
            "funding_stress_multipliers": [1.0, 2.0, 5.0],
            "slippage_stress_bps": [4.0, 8.0, 20.0],
            "taker_fee_stress_multipliers": [1.0, 2.0],
            "strict_execution_rule": "decision at completed 4h bar close; PnL and normal liquidation are applied on the next 4h bar; same-bar high/low is not used to grant profit",
            "liquidation_rule": "isolated sleeve proxy; liquidation kills only the active sleeve; reserve/extracted principal remains outside active sleeve",
            "funding_model": "research approximation from visible derivatives rows; funding is separate cashflow and stressed adversely",
            "paper_live_boundary": "Research-only stress review. No paper queue write, no strategy skeleton, no OMS/broker/live unlock.",
        },
        "source_context": {
            "high_octane_best_scenario_id": _mapping(high_report.get("summary")).get("best_scenario_id"),
            "high_octane_best_min_remaining_after_10pct_spike": _mapping(high_report.get("summary")).get("best_min_remaining_after_10pct_spike"),
            "high_octane_same_bar_proxy_source": True,
            "pyramiding_actual_attack_source_rows": len(pyramiding_rows),
        },
        "summary": summary,
        "top_risk_rows": matrix_rows[:25],
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(blockers=blockers, summary=summary),
        "blockers": sorted(set(blockers)),
        "outputs": {
            "json": _portable_path(report_path),
            "matrix_csv": _portable_path(matrix_path),
            "events_csv": _portable_path(events_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(matrix_path, matrix_rows)
    _write_csv(events_path, event_rows[:EVENT_LIMIT])
    _write_text(markdown_path, render_btc_attack_sleeve_risk_stress_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def _stress_policies() -> list[SleeveRiskPolicy]:
    return [
        SleeveRiskPolicy("base_strict_next_bar"),
        SleeveRiskPolicy("funding_2x_adverse", funding_adverse_multiplier=2.0),
        SleeveRiskPolicy("funding_5x_adverse", funding_adverse_multiplier=5.0),
        SleeveRiskPolicy("slippage_2x", slippage_bps=8.0),
        SleeveRiskPolicy("slippage_5x", slippage_bps=20.0),
        SleeveRiskPolicy("taker_fee_2x", taker_fee_multiplier=2.0),
        SleeveRiskPolicy("mark_adverse_100bps", mark_adverse_offset_bps=100.0),
        SleeveRiskPolicy("mark_adverse_200bps", mark_adverse_offset_bps=200.0),
        SleeveRiskPolicy("exposure_cap_7_loss_streak", max_simultaneous_exposed_sleeves=7, loss_streak_reduce_after=2, loss_streak_cooldown_bars=6),
        SleeveRiskPolicy(
            "combined_adverse_5x",
            mark_adverse_offset_bps=200.0,
            funding_adverse_multiplier=5.0,
            slippage_bps=20.0,
            taker_fee_multiplier=2.0,
            max_simultaneous_exposed_sleeves=7,
            loss_streak_reduce_after=2,
            loss_streak_cooldown_bars=6,
        ),
    ]


def _candidate_specs(high_rows: Sequence[Mapping[str, str]], pyramiding_rows: Sequence[Mapping[str, str]]) -> list[StressCandidate]:
    candidates: list[StressCandidate] = []
    high_by_id = {scenario.scenario_id: scenario for scenario in high_octane._scenario_grid()}
    seen: set[str] = set()
    for rank, row in enumerate(high_rows, start=1):
        scenario_id = str(row.get("scenario_id", ""))
        scenario = high_by_id.get(scenario_id)
        if scenario is None or scenario_id in seen:
            continue
        seen.add(scenario_id)
        candidates.append(
            StressCandidate(
                source_line="high_octane_watchlist",
                scenario_id=scenario_id,
                templates=tuple(scenario.sleeve_templates),
                max_total_exposed=int(scenario.max_total_exposed),
                max_attack_exposed=int(scenario.max_attack_exposed),
                extract_policy=str(scenario.extract_policy),
                reserve_requires_pullback=bool(scenario.reserve_requires_pullback),
                atr_step=float(scenario.atr_step),
                source_rank=rank,
            )
        )
    pyramid_by_id = {scenario.scenario_id: scenario for scenario in pyramiding._scenario_grid()}
    for rank, row in enumerate(pyramiding_rows, start=1):
        scenario_id = str(row.get("scenario_id", ""))
        scenario = pyramid_by_id.get(scenario_id)
        if scenario is None or scenario_id in seen:
            continue
        seen.add(scenario_id)
        candidates.append(
            StressCandidate(
                source_line="pyramiding_actual_attack_watchlist",
                scenario_id=scenario_id,
                templates=tuple(scenario.sleeve_templates),
                max_total_exposed=int(scenario.max_total_exposed),
                max_attack_exposed=int(scenario.max_attack_exposed),
                extract_policy="extract_on_double" if scenario.extract_on_double else "none",
                reserve_requires_pullback=bool(scenario.reserve_requires_pullback),
                atr_step=float(scenario.pyramid_step_atr),
                source_rank=rank,
            )
        )
    return candidates


def _simulate_strict_sleeve_stress(
    candidate: StressCandidate,
    *,
    policy: SleeveRiskPolicy,
    market: Mapping[str, Any],
    direction: pd.Series,
    initial_capital: float,
    base_cost_bps: float,
    collect_events: bool,
) -> StressResult:
    direction = direction.dropna()
    bars = market["bars_4h"].reindex(direction.index)
    derivatives = market["derivatives_4h"].reindex(direction.index)
    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    returns = close.pct_change().fillna(0.0)
    atr = _atr(bars, 20).reindex(direction.index).ffill().fillna(0.0)
    funding = pd.to_numeric(derivatives.get("funding_rate", pd.Series(0.0, index=direction.index)), errors="coerce").fillna(0.0)

    templates = list(candidate.templates)
    sleeve_count = len(templates)
    sleeve_initial = float(initial_capital) / float(INITIAL_SLEEVE_COUNT)
    roles = [template.role for template in templates]
    leverages = [float(template.leverage) for template in templates]
    entry_delays = [int(template.entry_delay_bars) for template in templates]
    triggers = [float(template.trigger_atr) for template in templates]
    equity_values = [sleeve_initial for _ in range(sleeve_count)]
    basis_values = [sleeve_initial for _ in range(sleeve_count)]
    reserve_values = [0.0 for _ in range(sleeve_count)]
    alive_values = [True for _ in range(sleeve_count)]
    exposed_side_values = [0.0 for _ in range(sleeve_count)]
    sorted_indices = sorted(range(sleeve_count), key=lambda idx: (ROLE_PRIORITY[roles[idx]], triggers[idx], entry_delays[idx], idx))

    equity_curve: list[float] = []
    exposed_count_curve: list[int] = []
    attack_count_curve: list[int] = []
    event_rows: list[dict[str, Any]] = []
    previous_signal = 0.0
    signal_age = 0
    campaign_anchor: float | None = None
    normal_liquidation_count = 0
    spike_liquidation_max_count = 0
    max_same_bar_normal_liquidations = 0
    funding_cost_amount = 0.0
    fee_slippage_cost_amount = 0.0
    extract_count = 0
    loss_streak = 0
    cooldown_remaining = 0
    min_remaining = {shock: 100.0 for shock in STRESS_SPIKE_PCTS}
    max_sleeves_lost = {shock: 0 for shock in STRESS_SPIKE_PCTS}
    max_equity_lost = {shock: 0.0 for shock in STRESS_SPIKE_PCTS}
    fee_rate = float(base_cost_bps) / 10_000.0 * float(policy.taker_fee_multiplier)
    slippage_rate = float(policy.slippage_bps) / 10_000.0
    last_total_equity = float(initial_capital)

    index = pd.DatetimeIndex(direction.index)
    for pos in range(max(0, len(index) - 1)):
        decision_ts = index[pos]
        execution_ts = index[pos + 1]
        side = float(direction.iloc[pos])
        close_value = float(close.iloc[pos])
        if side == 0.0:
            signal_age = 0
            campaign_anchor = None
        elif side == previous_signal and campaign_anchor is not None:
            signal_age += 1
        else:
            signal_age = 1
            campaign_anchor = float(close.iloc[pos - 1]) if pos > 0 else close_value
        favorable_atr = _favorable_atr(close=close_value, anchor=campaign_anchor, side=side, atr=float(atr.iloc[pos]))
        pullback_visible = _pullback_visible(returns=returns, high=high, low=low, close=close, pos=pos, side=side)
        selected = [False for _ in range(sleeve_count)]
        cap = min(int(candidate.max_total_exposed), int(policy.max_simultaneous_exposed_sleeves))
        if cooldown_remaining > 0:
            cap = max(1, int(cap * float(policy.loss_streak_exposure_multiplier)))
            cooldown_remaining -= 1
        if side != 0.0:
            selected_count = 0
            attack_count = 0
            for sleeve_idx in sorted_indices:
                if selected_count >= cap:
                    break
                if not alive_values[sleeve_idx]:
                    continue
                if signal_age <= entry_delays[sleeve_idx] or favorable_atr < triggers[sleeve_idx]:
                    continue
                role = roles[sleeve_idx]
                if role == "reserve" and candidate.reserve_requires_pullback and not pullback_visible:
                    continue
                if role == "attack" and attack_count >= int(candidate.max_attack_exposed):
                    continue
                selected[sleeve_idx] = True
                selected_count += 1
                if role == "attack":
                    attack_count += 1

        execution_return = float(close.iloc[pos + 1] / close.iloc[pos] - 1.0)
        execution_adverse = _execution_adverse_move(high=float(high.iloc[pos + 1]), low=float(low.iloc[pos + 1]), entry_close=close_value, side=side)
        normal_liq_this_bar = 0
        for sleeve_idx in range(sleeve_count):
            if not alive_values[sleeve_idx]:
                exposed_side_values[sleeve_idx] = 0.0
                continue
            if not selected[sleeve_idx]:
                exposed_side_values[sleeve_idx] = 0.0
                continue
            threshold = _liquidation_threshold(
                leverages[sleeve_idx],
                maintenance_margin_rate=policy.maintenance_margin_rate,
                liquidation_fee_rate=policy.liquidation_fee_rate,
                mark_adverse_offset_bps=policy.mark_adverse_offset_bps,
            )
            if execution_adverse >= threshold:
                if collect_events:
                    event_rows.append(
                        _event_row(
                            candidate=candidate,
                            policy=policy,
                            decision_ts=decision_ts,
                            execution_ts=execution_ts,
                            event_type="normal_liquidation",
                            sleeve_idx=sleeve_idx,
                            role=roles[sleeve_idx],
                            leverage=leverages[sleeve_idx],
                            amount=equity_values[sleeve_idx],
                            note=f"next_bar_adverse={_round(execution_adverse * 100.0)} threshold={_round(threshold * 100.0)}",
                        )
                    )
                equity_values[sleeve_idx] = 0.0
                alive_values[sleeve_idx] = False
                exposed_side_values[sleeve_idx] = 0.0
                normal_liquidation_count += 1
                normal_liq_this_bar += 1
                continue
            before = equity_values[sleeve_idx]
            turnover_cost = fee_rate + slippage_rate if exposed_side_values[sleeve_idx] != side else 0.0
            adverse_funding_return = -leverages[sleeve_idx] * abs(float(funding.iloc[pos + 1])) * float(policy.funding_adverse_multiplier) * (4.0 / 8.0)
            funding_cost_amount += before * abs(adverse_funding_return)
            fee_slippage_cost_amount += before * turnover_cost
            equity_values[sleeve_idx] = max(0.0, before * (1.0 + side * leverages[sleeve_idx] * execution_return + adverse_funding_return - turnover_cost))
            exposed_side_values[sleeve_idx] = side
            extract_policy = policy.force_extract_policy or candidate.extract_policy
            if _should_extract(equity=equity_values[sleeve_idx], basis=basis_values[sleeve_idx], extract_policy=extract_policy):
                extracted = min(basis_values[sleeve_idx], equity_values[sleeve_idx])
                equity_values[sleeve_idx] -= extracted
                reserve_values[sleeve_idx] += extracted
                basis_values[sleeve_idx] = max(equity_values[sleeve_idx], 1e-9)
                extract_count += 1
                if collect_events:
                    event_rows.append(
                        _event_row(
                            candidate=candidate,
                            policy=policy,
                            decision_ts=decision_ts,
                            execution_ts=execution_ts,
                            event_type=extract_policy,
                            sleeve_idx=sleeve_idx,
                            role=roles[sleeve_idx],
                            leverage=leverages[sleeve_idx],
                            amount=extracted,
                            note="principal moved to reserve outside active sleeve",
                        )
                    )
        total_equity = sum(max(0.0, equity_values[idx]) + max(0.0, reserve_values[idx]) for idx in range(sleeve_count))
        exposed_indices = [idx for idx in range(sleeve_count) if alive_values[idx] and exposed_side_values[idx] != 0.0]
        for shock in STRESS_SPIKE_PCTS:
            lost_equity = 0.0
            lost_count = 0
            for sleeve_idx in exposed_indices:
                threshold = _liquidation_threshold(
                    leverages[sleeve_idx],
                    maintenance_margin_rate=policy.maintenance_margin_rate,
                    liquidation_fee_rate=policy.liquidation_fee_rate,
                    mark_adverse_offset_bps=policy.mark_adverse_offset_bps,
                )
                if execution_adverse + shock / 100.0 >= threshold:
                    lost_equity += equity_values[sleeve_idx]
                    lost_count += 1
            remaining_pct = (total_equity - lost_equity) / max(1e-9, total_equity) * 100.0
            min_remaining[shock] = min(min_remaining[shock], remaining_pct)
            max_sleeves_lost[shock] = max(max_sleeves_lost[shock], lost_count)
            max_equity_lost[shock] = max(max_equity_lost[shock], lost_equity)
            spike_liquidation_max_count = max(spike_liquidation_max_count, lost_count)
        equity_curve.append(total_equity)
        exposed_count_curve.append(len(exposed_indices))
        attack_count_curve.append(sum(1 for idx in exposed_indices if roles[idx] == "attack"))
        if total_equity < last_total_equity:
            loss_streak += 1
            if policy.loss_streak_reduce_after and loss_streak >= policy.loss_streak_reduce_after:
                cooldown_remaining = max(cooldown_remaining, int(policy.loss_streak_cooldown_bars))
        else:
            loss_streak = 0
        last_total_equity = total_equity
        max_same_bar_normal_liquidations = max(max_same_bar_normal_liquidations, normal_liq_this_bar)
        previous_signal = side

    equity = pd.Series(equity_curve, index=index[1 : 1 + len(equity_curve)], dtype=float)
    drawdown = equity / equity.cummax() - 1.0 if len(equity) else pd.Series(dtype=float)
    final_equity = float(equity_curve[-1]) if equity_curve else float(initial_capital)
    total_return = final_equity / float(initial_capital) - 1.0
    elapsed_days = max(1.0, float((index[min(len(index) - 1, len(equity_curve))] - index[0]).total_seconds()) / 86_400.0) if len(index) > 1 else 1.0
    annual_return = (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0 if total_return > -1.0 else -1.0
    exposed_series = pd.Series(exposed_count_curve, dtype=float)
    attack_series = pd.Series(attack_count_curve, dtype=float)
    metrics: dict[str, Any] = {
        "final_equity": _round(final_equity),
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "max_drawdown_abs_pct": _round(abs(float(drawdown.min())) * 100.0) if len(drawdown) else 0.0,
        "reserve_cash": _round(sum(reserve_values)),
        "reserve_cash_pct_of_initial": _round(sum(reserve_values) / float(initial_capital) * 100.0),
        "alive_sleeve_count": sum(1 for alive in alive_values if alive),
        "dead_sleeve_count": sum(1 for alive in alive_values if not alive),
        "normal_liquidation_count": normal_liquidation_count,
        "spike_liquidation_max_count": spike_liquidation_max_count,
        "max_same_bar_normal_liquidations": max_same_bar_normal_liquidations,
        "average_concurrent_exposed_sleeves": _round(float(exposed_series.mean()) if len(exposed_series) else 0.0),
        "max_concurrent_exposed_sleeves_observed": int(exposed_series.max()) if len(exposed_series) else 0,
        "average_attack_exposed_sleeves": _round(float(attack_series.mean()) if len(attack_series) else 0.0),
        "max_attack_exposed_sleeves_observed": int(attack_series.max()) if len(attack_series) else 0,
        "extract_count": extract_count,
        "funding_cost_amount": _round(funding_cost_amount),
        "fee_slippage_cost_amount": _round(fee_slippage_cost_amount),
        "hard_wipeout": bool(final_equity <= float(initial_capital) * 0.25),
        "full_wipeout": bool(final_equity <= 1e-9),
        "strict_next_bar_execution": True,
        "same_bar_profit_allowed": False,
        "funding_approximation": True,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }
    for shock in STRESS_SPIKE_PCTS:
        slug = _shock_slug(shock)
        metrics[f"min_remaining_capital_pct_after_{slug}_spike"] = _round(min_remaining[shock])
        metrics[f"max_sleeves_lost_single_{slug}_spike"] = int(max_sleeves_lost[shock])
        metrics[f"max_equity_lost_single_{slug}_spike"] = _round(max_equity_lost[shock])
    return StressResult(candidate=candidate, policy=policy, metrics=metrics, events=tuple(event_rows[:EVENT_LIMIT]))


def _result_row(result: StressResult) -> dict[str, Any]:
    candidate = result.candidate
    policy = result.policy
    row = {
        "source_line": candidate.source_line,
        "source_rank": candidate.source_rank,
        "scenario_id": candidate.scenario_id,
        "policy_id": policy.policy_id,
        "max_total_exposed": candidate.max_total_exposed,
        "max_attack_exposed": candidate.max_attack_exposed,
        "max_policy_exposed": min(candidate.max_total_exposed, policy.max_simultaneous_exposed_sleeves),
        "extract_policy": policy.force_extract_policy or candidate.extract_policy,
        "max_template_leverage": max(float(template.leverage) for template in candidate.templates),
        **policy.to_dict(),
        **result.metrics,
    }
    row["stress_decision"] = _stress_decision(row)
    return row


def _summary(*, matrix_rows: Sequence[Mapping[str, Any]], high_report: Mapping[str, Any], candidate_count: int, policy_count: int) -> dict[str, Any]:
    base_rows = [row for row in matrix_rows if row.get("policy_id") == "base_strict_next_bar"]
    combined_rows = [row for row in matrix_rows if row.get("policy_id") == "combined_adverse_5x"]
    watch_rows = [row for row in matrix_rows if row.get("stress_decision") == "strict_stress_survived_research_only"]
    remaining_10 = [_float(row.get("min_remaining_capital_pct_after_10pct_spike")) for row in matrix_rows]
    summary = _mapping(high_report.get("summary"))
    return {
        "candidate_count": candidate_count,
        "policy_count": policy_count,
        "matrix_row_count": len(matrix_rows),
        "base_strict_row_count": len(base_rows),
        "combined_adverse_row_count": len(combined_rows),
        "strict_survivor_count": len(watch_rows),
        "normal_liquidation_row_count": sum(1 for row in matrix_rows if _int(row.get("normal_liquidation_count")) > 0),
        "full_wipeout_row_count": sum(1 for row in matrix_rows if bool(row.get("full_wipeout"))),
        "hard_wipeout_row_count": sum(1 for row in matrix_rows if bool(row.get("hard_wipeout"))),
        "min_remaining_after_10pct_spike_min": _round(min(remaining_10)) if remaining_10 else 0.0,
        "min_remaining_after_10pct_spike_median": _round(median(remaining_10)) if remaining_10 else 0.0,
        "source_best_min_remaining_after_10pct_spike": summary.get("best_min_remaining_after_10pct_spike"),
        "source_best_scenario_id": summary.get("best_scenario_id"),
        "source_same_bar_proxy_boundary": True,
        "funding_approximation": True,
        "strict_next_bar_execution": True,
        "same_bar_profit_allowed": False,
        "not_forward_observation_ready": True,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _stress_decision(row: Mapping[str, Any]) -> str:
    if _float(row.get("max_template_leverage")) > 10.0:
        return "reject_leverage_above_10x"
    if _int(row.get("normal_liquidation_count")) > 0:
        return "reject_normal_liquidation_under_strict_policy"
    if _float(row.get("min_remaining_capital_pct_after_10pct_spike")) < 40.0:
        return "reject_below_40pct_remaining_after_10pct_spike"
    if bool(row.get("full_wipeout")) or bool(row.get("hard_wipeout")):
        return "reject_wipeout_under_strict_policy"
    return "strict_stress_survived_research_only"


def _decision(*, blockers: Sequence[str], summary: Mapping[str, Any]) -> str:
    if blockers:
        return "blocked_attack_sleeve_risk_stress_inputs_missing_no_paper_no_live"
    if summary.get("not_forward_observation_ready") is True:
        return "not_forward_observation_ready_research_only_no_paper_no_live"
    return "strict_stress_review_complete_research_only_no_paper_no_live"


def _risk_rank_key(row: Mapping[str, Any]) -> tuple[int, float, float, float, str, str]:
    retained = 0 if row.get("stress_decision") == "strict_stress_survived_research_only" else 1
    return (
        retained,
        -_float(row.get("annual_return_pct")),
        _float(row.get("max_drawdown_abs_pct")),
        -_float(row.get("min_remaining_capital_pct_after_10pct_spike")),
        str(row.get("scenario_id", "")),
        str(row.get("policy_id", "")),
    )


def render_btc_attack_sleeve_risk_stress_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    gate = _mapping(report.get("gate"))
    lines = [
        "# BTC 激进 sleeve 风控压力复核 v2",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 候选数 / policy 数 / 压力行数：`{summary.get('candidate_count')}` / `{summary.get('policy_count')}` / `{summary.get('matrix_row_count')}`",
        f"- 严格压力存活行数：`{summary.get('strict_survivor_count')}`",
        f"- 普通强平行数：`{summary.get('normal_liquidation_row_count')}`",
        f"- hard/full wipeout 行数：`{summary.get('hard_wipeout_row_count')}` / `{summary.get('full_wipeout_row_count')}`",
        f"- -10% 插针后剩余本金最小/中位：`{summary.get('min_remaining_after_10pct_spike_min')}` / `{summary.get('min_remaining_after_10pct_spike_median')}`",
        f"- paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- live 解锁：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 关键边界",
        "",
        "- 本复核使用下一根 4H bar 承担收益/亏损；不允许用决策同根 K 线盈利。",
        "- 当前 bar high/low 只能作为已完成历史风险证据；强平和插针按 isolated sleeve 近似处理。",
        "- funding 仍是研究近似，单独记账并做 1x/2x/5x adverse stress。",
        "- 即使严格压力下存活，也只能保留 research-only 观察，不能写 paper 队列。",
        "",
        "## Top 压力行",
        "",
        "| 排名 | 来源 | 场景 | policy | 年化 | 回撤 | -10%剩余 | 强平 | 决策 |",
        "|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for idx, row in enumerate(_list_of_mappings(report.get("top_risk_rows"))[:10], start=1):
        lines.append(
            f"| {idx} | {row.get('source_line')} | `{row.get('scenario_id')}` | `{row.get('policy_id')}` | "
            f"{row.get('annual_return_pct')} | {row.get('max_drawdown_abs_pct')} | "
            f"{row.get('min_remaining_capital_pct_after_10pct_spike')} | {row.get('normal_liquidation_count')} | {row.get('stress_decision')} |"
        )
    lines.extend(["", "本报告只做 research-only 风控复核，不写 paper 队列，不接 broker/OMS/order，不解锁 live。"])
    return "\n".join(lines) + "\n"


def _execution_adverse_move(*, high: float, low: float, entry_close: float, side: float) -> float:
    if side > 0.0:
        return max(0.0, 1.0 - low / max(1e-12, entry_close))
    if side < 0.0:
        return max(0.0, high / max(1e-12, entry_close) - 1.0)
    return 0.0


def _liquidation_threshold(
    leverage: float,
    *,
    maintenance_margin_rate: float,
    liquidation_fee_rate: float,
    mark_adverse_offset_bps: float,
) -> float:
    return max(0.0, 1.0 / float(leverage) - float(maintenance_margin_rate) - float(liquidation_fee_rate) - float(mark_adverse_offset_bps) / 10_000.0)


def _should_extract(*, equity: float, basis: float, extract_policy: str) -> bool:
    if extract_policy == "extract_on_double":
        return equity >= basis * 2.0
    if extract_policy == "extract_on_triple":
        return equity >= basis * 3.0
    return False


def _event_row(
    *,
    candidate: StressCandidate,
    policy: SleeveRiskPolicy,
    decision_ts: pd.Timestamp,
    execution_ts: pd.Timestamp,
    event_type: str,
    sleeve_idx: int,
    role: str,
    leverage: float,
    amount: float,
    note: str,
) -> dict[str, Any]:
    return {
        "source_line": candidate.source_line,
        "scenario_id": candidate.scenario_id,
        "policy_id": policy.policy_id,
        "decision_time": _ts(decision_ts),
        "execution_time": _ts(execution_ts),
        "event_type": event_type,
        "sleeve_id": sleeve_idx + 1,
        "role": role,
        "leverage": leverage,
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
        "reason": "Attack sleeve risk stress review is research-only and cannot promote strategies.",
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
        "strategy_skeleton_generated": False,
    }


def _warnings(*, blockers: Sequence[str], summary: Mapping[str, Any]) -> list[str]:
    warnings = ["btc_attack_sleeve_risk_stress_research_only_no_paper_no_live"]
    if blockers:
        warnings.append("btc_attack_sleeve_risk_stress_blocked")
    if summary.get("source_same_bar_proxy_boundary") is True:
        warnings.append("source_high_octane_same_bar_proxy_boundary_requires_execution_replay")
    if summary.get("funding_approximation") is True:
        warnings.append("funding_is_research_approximation")
    if _int(summary.get("normal_liquidation_row_count")) > 0:
        warnings.append("strict_stress_normal_liquidations_observed")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_attack_sleeve_risk_stress_safety_status_v1",
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
        "reason": "Strict sleeve risk stress output is diagnostic only.",
    }


def _read_json(path: Path, blockers: list[str], blocker_name: str) -> dict[str, Any]:
    if not path.exists():
        blockers.append(blocker_name)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path, blockers: list[str], blocker_name: str) -> list[dict[str, str]]:
    if not path.exists():
        blockers.append(blocker_name)
        return []
    return _read_csv_optional(path)


def _read_csv_optional(path: Path) -> list[dict[str, str]]:
    if not path.exists():
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
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fields})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _ts(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return pd.Timestamp(value).tz_convert("UTC").isoformat()
    except Exception:
        return str(value)

